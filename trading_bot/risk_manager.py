"""
risk_manager.py
===============
Gestión de riesgo (Risk-First): decide SI se puede operar, CUÁNTO comprar y
CUÁNDO salir. Ninguna orden de compra se envía sin pasar por aquí.

Reglas principales (todas configurables en .env, ver config.py):

  Tamaño de posición
    qty = min( riesgo_max / pérdida_por_unidad,     # 1 % del capital en riesgo
               5 % del capital / precio,            # límite duro por operación
               exposición_restante / precio,        # 15 % total por cuenta
               efectivo_disponible / precio )       # nunca apalancamiento

  Stop-loss dinámico
    distancia = clamp(ATR * 2, 0.5 % precio, 1 % precio)
    -> se adapta a la volatilidad pero nunca pierde más de un 1 % por operación.

  Take-profit
    TP = entrada + 1.5 * distancia_stop (1.5R), y solo se opera si el TP cubre
    al menos 2 veces los costes de ida y vuelta (comisiones + slippage).

  Trailing stop
    Cuando el precio avanza +1R, el stop sube a (máximo - 0.75R) y sigue al
    precio: la operación ya no puede acabar en pérdida (salvo gaps).

  Cortafuegos de cartera
    - kill switch: pérdida diaria >= 2 % -> cierra todo y no opera hasta mañana
    - pausa de 60 min tras 3 pérdidas consecutivas
    - máximo de posiciones simultáneas y de operaciones por día
    - cooldown por símbolo tras cerrar
    - stop temporal: cierre forzado tras MAX_HOLDING_MINUTES
    - protección PDT (cuentas USA < 25.000 $: máx. 3 day trades / 5 días)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import HARD_MAX_POSITION_PCT, STOCKS, RiskSettings
from utils import atomic_write_json, fmt_money, fmt_price, read_json

logger = logging.getLogger("risk")

NY_TZ = ZoneInfo("America/New_York")
PDT_EQUITY_THRESHOLD = 25_000.0
PDT_MAX_DAY_TRADES = 3
DUST_FRACTION = 0.01  # restos < 1 % de la posición se consideran cerrados


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_STOP = "TIEMPO_MAXIMO"
    SIGNAL = "SEÑAL_SALIDA"
    MARKET_CLOSE = "CIERRE_MERCADO"
    KILL_SWITCH = "KILL_SWITCH"


@dataclass
class TradePlan:
    symbol: str
    asset_class: str
    qty: float
    entry_price: float
    stop_price: float
    take_profit_price: float | None
    stop_distance: float      # 1R expresado en precio
    notional: float
    risk_amount: float        # pérdida estimada si salta el stop (con costes)
    limited_by: str = ""


@dataclass
class Position:
    symbol: str
    asset_class: str
    qty: float
    entry_price: float
    stop_price: float
    take_profit_price: float | None
    initial_stop_distance: float
    highest_price: float
    opened_at: datetime
    entry_fees: float = 0.0
    trailing_active: bool = False
    last_price: float | None = None
    catalyst_at: datetime | None = None

    def mark(self, price: float | None = None) -> float:
        return price if price is not None else (self.last_price or self.entry_price)

    def unrealized_pnl(self, price: float | None = None) -> float:
        return (self.mark(price) - self.entry_price) * self.qty

    def market_value(self, price: float | None = None) -> float:
        return self.mark(price) * self.qty

    def r_multiple(self, price: float | None = None) -> float:
        if self.initial_stop_distance <= 0:
            return 0.0
        return (self.mark(price) - self.entry_price) / self.initial_stop_distance

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("opened_at", "catalyst_at"):
            data[key] = data[key].isoformat() if data[key] else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Position:
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        for key in ("opened_at", "catalyst_at"):
            if clean.get(key):
                clean[key] = datetime.fromisoformat(clean[key])
        return cls(**clean)


@dataclass
class ClosedTrade:
    symbol: str
    asset_class: str
    qty: float
    entry_price: float
    exit_price: float
    opened_at: datetime
    closed_at: datetime
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    exit_reason: str

    def to_row(self) -> dict[str, Any]:
        notional = self.entry_price * self.qty
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "notional": round(notional, 2),
            "gross_pnl": round(self.gross_pnl, 4),
            "fees": round(self.fees, 4),
            "net_pnl": round(self.net_pnl, 4),
            "return_pct": round(100 * self.net_pnl / notional, 4) if notional else 0.0,
            "r_multiple": round(self.r_multiple, 3),
            "exit_reason": self.exit_reason,
            "holding_minutes": round((self.closed_at - self.opened_at).total_seconds() / 60, 1),
        }


class RiskManager:
    def __init__(self, cfg: RiskSettings, state_path: Path | None = None):
        self.cfg = cfg
        self.state_path = state_path
        self.tz = ZoneInfo(cfg.daily_reset_tz)
        self.positions: dict[str, Position] = {}
        self.day: str | None = None
        self.day_start_equity: float | None = None
        self.realized_pnl_today = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self.paused_until: datetime | None = None
        self.kill_switch = False
        self.cooldowns: dict[str, datetime] = {}
        self.last_catalyst: dict[str, datetime] = {}
        self.day_trades: list[str] = []  # fechas (NY) de day trades en acciones
        self.load()

    # =========================================================================
    # Jornada y cortafuegos de cartera
    # =========================================================================
    def roll_day_if_needed(self, now: datetime, total_equity: float | None) -> bool:
        """Reinicia los contadores diarios al cambiar de día (zona DAILY_RESET_TZ)."""
        day = now.astimezone(self.tz).date().isoformat()
        if day == self.day:
            if self.day_start_equity is None and total_equity:
                self.day_start_equity = total_equity
            return False
        if self.day is not None:
            logger.info("Fin de jornada %s: PnL realizado %+.2f en %d operaciones",
                        self.day, self.realized_pnl_today, self.trades_today)
        self.day = day
        self.day_start_equity = total_equity or None
        self.realized_pnl_today = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self.paused_until = None
        self.kill_switch = False
        cutoff = (now.astimezone(NY_TZ).date() - timedelta(days=14)).isoformat()
        self.day_trades = [d for d in self.day_trades if d >= cutoff]
        logger.info("Nueva jornada %s — capital de referencia: %s", day,
                    fmt_money(total_equity) if total_equity else "pendiente")
        self.save()
        return True

    def daily_pnl(self) -> float:
        """PnL del día = realizado + no realizado de las posiciones abiertas."""
        return self.realized_pnl_today + sum(p.unrealized_pnl() for p in self.positions.values())

    def check_daily_loss(self) -> bool:
        """Activa el kill switch si la pérdida diaria supera MAX_DAILY_LOSS_PCT."""
        if self.kill_switch:
            return True
        if not self.day_start_equity:
            return False
        limit = -self.cfg.max_daily_loss_pct * self.day_start_equity
        pnl = self.daily_pnl()
        if pnl <= limit:
            self.kill_switch = True
            logger.critical("KILL SWITCH: pérdida diaria %.2f supera el límite %.2f (%.1f%% de %s). "
                            "No se abrirán más operaciones hoy.", pnl, limit,
                            100 * self.cfg.max_daily_loss_pct, fmt_money(self.day_start_equity))
            self.save()
            return True
        return False

    def _recent_day_trades(self, now: datetime) -> int:
        """Day trades en los últimos 5 días hábiles (regla PDT de FINRA)."""
        window: set[str] = set()
        day: date = now.astimezone(NY_TZ).date()
        while len(window) < 5:
            if day.weekday() < 5:
                window.add(day.isoformat())
            day -= timedelta(days=1)
        return sum(1 for d in self.day_trades if d in window)

    def entries_blocked(self, now: datetime) -> str | None:
        """Motivo global (no por símbolo) que impide abrir posiciones, o None."""
        if self.kill_switch:
            return "kill switch diario activo"
        if self.paused_until and now < self.paused_until:
            return f"pausa tras pérdidas consecutivas hasta {self.paused_until:%H:%M} UTC"
        if len(self.positions) >= self.cfg.max_open_positions:
            return f"máximo de posiciones abiertas ({self.cfg.max_open_positions})"
        if self.trades_today >= self.cfg.max_trades_per_day:
            return f"máximo de operaciones diarias ({self.cfg.max_trades_per_day})"
        return None

    def can_open(self, symbol: str, asset_class: str, now: datetime, equity: float,
                 broker_daytrade_count: int | None = None) -> tuple[bool, str]:
        blocked = self.entries_blocked(now)
        if blocked:
            return False, blocked
        if symbol in self.positions:
            return False, "ya hay una posición abierta"
        cooldown = self.cooldowns.get(symbol)
        if cooldown and now < cooldown:
            return False, f"cooldown hasta {cooldown:%H:%M} UTC"
        if asset_class == STOCKS and self.cfg.pdt_protection and equity < PDT_EQUITY_THRESHOLD:
            count = max(self._recent_day_trades(now), broker_daytrade_count or 0)
            if count >= PDT_MAX_DAY_TRADES:
                return False, f"protección PDT ({count} day trades en 5 días con capital < 25.000 $)"
        return True, "ok"

    def check_spread(self, bid: float, ask: float) -> tuple[bool, str]:
        """Evita entrar con horquillas anchas: en scalping el spread es un coste directo."""
        if bid <= 0 or ask <= 0 or ask < bid:
            return True, "sin datos de horquilla"
        spread = (ask - bid) / ((ask + bid) / 2)
        if spread > self.cfg.max_spread_pct:
            return False, f"spread {spread:.3%} > máximo {self.cfg.max_spread_pct:.3%}"
        return True, f"spread {spread:.3%}"

    # =========================================================================
    # Dimensionamiento
    # =========================================================================
    def stop_distance(self, price: float, atr: float | None) -> float:
        """Stop dinámico por ATR, acotado entre MIN_STOP_PCT y STOP_LOSS_PCT."""
        max_distance = price * self.cfg.stop_loss_pct
        min_distance = price * self.cfg.min_stop_pct
        raw = atr * self.cfg.atr_stop_multiplier if atr and atr > 0 else max_distance
        return min(max(raw, min_distance), max_distance)

    def exposure(self, asset_class: str | None = None) -> float:
        return sum(p.market_value() for p in self.positions.values()
                   if asset_class is None or p.asset_class == asset_class)

    def build_trade_plan(self, *, symbol: str, asset_class: str, price: float, atr: float | None,
                         equity: float, cash: float, normalize_qty: Callable[[float], float],
                         min_notional: float) -> tuple[TradePlan | None, str]:
        cfg = self.cfg
        if price <= 0 or equity <= 0:
            return None, "precio o capital no válidos"

        one_way_cost = cfg.fee_pct(asset_class) + cfg.slippage_pct
        distance = self.stop_distance(price, atr)
        tp_distance = distance * cfg.take_profit_rr if cfg.take_profit_rr > 0 else None

        # Filtro de costes: un TP que apenas cubre comisiones es una pérdida esperada
        if tp_distance is not None and cfg.min_edge_cost_multiple > 0:
            round_trip = 2 * one_way_cost
            required = cfg.min_edge_cost_multiple * round_trip
            if tp_distance / price + 1e-12 < required:
                return None, (f"TP {tp_distance / price:.2%} no cubre {cfg.min_edge_cost_multiple:g}x "
                              f"los costes de ida y vuelta ({round_trip:.2%})")

        # Pérdida por unidad si salta el stop, incluyendo comisiones y slippage
        loss_per_unit = distance + price * 2 * one_way_cost
        # Los topes se calculan con el precio de ejecución esperado (con
        # slippage) para que el deslizamiento no los rebase
        exec_price = price * (1 + cfg.slippage_pct)
        max_position_pct = min(cfg.max_position_pct, HARD_MAX_POSITION_PCT)
        candidates = {
            "riesgo 1R": equity * cfg.max_risk_per_trade_pct / loss_per_unit,
            f"tope {max_position_pct:.0%} por operación": equity * max_position_pct / exec_price,
            "exposición total": max(0.0, equity * cfg.max_total_exposure_pct
                                    - self.exposure(asset_class)) / exec_price,
            "efectivo disponible": max(0.0, cash * 0.99) / (price * (1 + one_way_cost)),
        }
        limited_by = min(candidates, key=candidates.get)
        qty = normalize_qty(candidates[limited_by])
        if qty <= 0:
            return None, f"cantidad 0 tras redondear (limitada por {limited_by})"
        notional = qty * price
        if notional < min_notional:
            return None, f"nominal {notional:.2f} < mínimo del broker {min_notional:.2f} (limitado por {limited_by})"

        return TradePlan(
            symbol=symbol,
            asset_class=asset_class,
            qty=qty,
            entry_price=price,
            stop_price=price - distance,
            take_profit_price=price + tp_distance if tp_distance else None,
            stop_distance=distance,
            notional=notional,
            risk_amount=qty * loss_per_unit,
            limited_by=limited_by,
        ), f"tamaño limitado por {limited_by}"

    # =========================================================================
    # Ciclo de vida de las posiciones
    # =========================================================================
    def register_open(self, plan: TradePlan, filled_qty: float, fill_price: float, fee: float,
                      now: datetime, catalyst_at: datetime | None = None) -> Position:
        # Los niveles se recalculan sobre el precio REAL de ejecución (slippage)
        distance = plan.stop_distance
        tp = fill_price + distance * self.cfg.take_profit_rr if self.cfg.take_profit_rr > 0 else None
        position = Position(
            symbol=plan.symbol,
            asset_class=plan.asset_class,
            qty=filled_qty,
            entry_price=fill_price,
            stop_price=fill_price - distance,
            take_profit_price=tp,
            initial_stop_distance=distance,
            highest_price=fill_price,
            opened_at=now,
            entry_fees=fee,
            last_price=fill_price,
            catalyst_at=catalyst_at,
        )
        self.positions[plan.symbol] = position
        self.trades_today += 1
        if catalyst_at:
            self.last_catalyst[plan.symbol] = catalyst_at
        self.save()
        return position

    def update_and_check_exit(self, position: Position, price: float, now: datetime) -> ExitReason | None:
        """Actualiza máximo y trailing stop con el último precio y devuelve el motivo de salida."""
        cfg = self.cfg
        position.last_price = price
        if price > position.highest_price:
            position.highest_price = price

        r = position.initial_stop_distance
        progress = position.highest_price - position.entry_price
        # Pequeña tolerancia para que 100.6 - 100.0 = 0.59999... cuente como +1R
        if r > 0 and progress >= cfg.trailing_activation_r * r - 1e-9 * position.entry_price:
            candidate = position.highest_price - cfg.trailing_distance_r * r
            if candidate > position.stop_price:  # el stop solo sube, nunca baja
                if not position.trailing_active:
                    logger.info("%s: trailing stop activado (+%.2fR) — stop %s -> %s", position.symbol,
                                position.r_multiple(), fmt_price(position.stop_price), fmt_price(candidate))
                position.trailing_active = True
                position.stop_price = candidate

        if price <= position.stop_price:
            return ExitReason.TRAILING_STOP if position.trailing_active else ExitReason.STOP_LOSS
        if position.take_profit_price is not None and price >= position.take_profit_price:
            return ExitReason.TAKE_PROFIT
        if now - position.opened_at >= timedelta(minutes=cfg.max_holding_minutes):
            return ExitReason.TIME_STOP
        return None

    def register_close(self, symbol: str, exit_price: float, qty: float, fee: float,
                       reason: ExitReason | str, now: datetime) -> ClosedTrade | None:
        position = self.positions.get(symbol)
        if position is None:
            return None
        qty = min(qty, position.qty)
        fraction = qty / position.qty if position.qty else 1.0
        entry_fees = position.entry_fees * fraction
        gross = (exit_price - position.entry_price) * qty
        fees = entry_fees + fee
        net = gross - fees
        risk_amount = position.initial_stop_distance * qty
        trade = ClosedTrade(
            symbol=symbol,
            asset_class=position.asset_class,
            qty=qty,
            entry_price=position.entry_price,
            exit_price=exit_price,
            opened_at=position.opened_at,
            closed_at=now,
            gross_pnl=gross,
            fees=fees,
            net_pnl=net,
            r_multiple=net / risk_amount if risk_amount > 0 else 0.0,
            exit_reason=reason.value if isinstance(reason, ExitReason) else str(reason),
        )

        remaining = position.qty - qty
        fully_closed = remaining <= position.qty * DUST_FRACTION
        if fully_closed:
            del self.positions[symbol]
            if position.asset_class == STOCKS:
                opened_day = position.opened_at.astimezone(NY_TZ).date()
                if opened_day == now.astimezone(NY_TZ).date():
                    self.day_trades.append(opened_day.isoformat())
        else:
            position.qty = remaining
            position.entry_fees -= entry_fees
            logger.warning("%s: cierre parcial, quedan %.8g unidades", symbol, remaining)

        self.realized_pnl_today += net
        self.cooldowns[symbol] = now + timedelta(minutes=self.cfg.symbol_cooldown_minutes)
        if net < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.cfg.max_consecutive_losses:
                self.paused_until = now + timedelta(minutes=self.cfg.pause_after_losses_minutes)
                logger.warning("%d pérdidas consecutivas: nuevas entradas en pausa hasta %s UTC",
                               self.consecutive_losses, f"{self.paused_until:%H:%M}")
                self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0
        self.save()
        return trade

    def drop_position(self, symbol: str, reason: str) -> None:
        """Deja de seguir una posición sin registrar PnL (cerrada fuera del bot o restos)."""
        if self.positions.pop(symbol, None) is not None:
            logger.warning("%s: posición eliminada del seguimiento — %s", symbol, reason)
            self.save()

    # =========================================================================
    # Persistencia (para sobrevivir a reinicios sin perder stops ni contadores)
    # =========================================================================
    def save(self) -> None:
        if self.state_path is None:
            return
        state = {
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "realized_pnl_today": self.realized_pnl_today,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "paused_until": self.paused_until.isoformat() if self.paused_until else None,
            "kill_switch": self.kill_switch,
            "cooldowns": {s: t.isoformat() for s, t in self.cooldowns.items()},
            "last_catalyst": {s: t.isoformat() for s, t in self.last_catalyst.items()},
            "day_trades": self.day_trades,
        }
        try:
            atomic_write_json(self.state_path, state)
        except OSError as exc:
            logger.error("No se pudo guardar el estado de riesgo: %s", exc)

    def load(self) -> None:
        if self.state_path is None:
            return
        state = read_json(self.state_path, None)
        if not state:
            return
        try:
            self.positions = {s: Position.from_dict(p) for s, p in state.get("positions", {}).items()}
            self.day = state.get("day")
            self.day_start_equity = state.get("day_start_equity")
            self.realized_pnl_today = float(state.get("realized_pnl_today", 0.0))
            self.trades_today = int(state.get("trades_today", 0))
            self.consecutive_losses = int(state.get("consecutive_losses", 0))
            paused = state.get("paused_until")
            self.paused_until = datetime.fromisoformat(paused) if paused else None
            self.kill_switch = bool(state.get("kill_switch", False))
            self.cooldowns = {s: datetime.fromisoformat(t) for s, t in state.get("cooldowns", {}).items()}
            self.last_catalyst = {s: datetime.fromisoformat(t)
                                  for s, t in state.get("last_catalyst", {}).items()}
            self.day_trades = list(state.get("day_trades", []))
        except (TypeError, ValueError, KeyError) as exc:
            logger.error("Estado de riesgo inválido (%s): se arranca con estado limpio", exc)
            path = self.state_path
            self.__init__(self.cfg, None)
            self.state_path = path
            return
        if self.positions:
            logger.info("Estado restaurado: %d posiciones abiertas (%s)",
                        len(self.positions), ", ".join(self.positions))
