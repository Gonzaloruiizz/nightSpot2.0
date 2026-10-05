#!/usr/bin/env python3
"""
bot.py
======
Orquestador del bot de trading por sentimiento.

Cada ciclo (LOOP_INTERVAL_SECONDS, 30 s por defecto):
  1. Lee el capital de cada cuenta y gestiona el cambio de jornada.
  2. (Modo real) Reconcilia las posiciones del bot con las del broker.
  3. Gestiona las posiciones abiertas: stop-loss, trailing, take-profit,
     tiempo máximo, cierre de mercado y señales de salida. Va ANTES que las
     noticias para que una fuente lenta nunca retrase una salida.
  4. Actualiza noticias (cada proveedor con su propia frecuencia).
  5. Comprueba el kill switch diario.
  6. Busca entradas: primero filtra por sentimiento (sin coste de API) y solo
     entonces descarga velas para la confirmación técnica.

Uso:
    python bot.py              # bucle continuo (Ctrl+C para parar)
    python bot.py --once       # un único ciclo (pruebas)
    python bot.py --report     # estadísticas del diario de operaciones
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from api_handler import BUY, SELL, AccountInfo, BaseBroker, BrokerError, build_brokers, new_client_order_id
from config import CRYPTO, STOCKS, ConfigError, Instrument, Settings, load_settings
from news_handler import NewsAggregator
from risk_manager import ExitReason, Position, RiskManager, TradePlan
from sentiment import SentimentAnalyzer, SentimentResult
from strategy import Action, SentimentMomentumStrategy
from utils import TradeJournal, fmt_money, fmt_price, setup_logging, utc_now

logger = logging.getLogger("bot")


class TradingBot:
    MAX_ERROR_BACKOFF_SECONDS = 300

    def __init__(self, settings: Settings, brokers: dict[str, BaseBroker], news: NewsAggregator,
                 analyzer: SentimentAnalyzer, strategy: SentimentMomentumStrategy,
                 risk: RiskManager, journal: TradeJournal):
        self.settings = settings
        self.brokers = brokers
        self.news = news
        self.analyzer = analyzer
        self.strategy = strategy
        self.risk = risk
        self.journal = journal
        self.paper = settings.paper_trading
        self.instruments = [i for i in settings.instruments if i.asset_class in brokers]
        self._stop = threading.Event()
        self._timeframe = strategy.timeframe
        self._bars_cache: dict[str, tuple[pd.Timestamp, pd.DataFrame]] = {}
        self._accounts: dict[str, AccountInfo] = {}
        self._market_sentiment: dict[str, SentimentResult] = {}
        self._warned_unmanaged: set[str] = set()
        self._cycle = 0

    # =========================================================================
    # Bucle principal
    # =========================================================================
    def run_forever(self) -> None:
        consecutive_errors = 0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.run_cycle()
                consecutive_errors = 0
            except Exception:  # noqa: BLE001 - el bucle nunca debe morir
                consecutive_errors += 1
                logger.exception("Error inesperado en el ciclo (%d seguidos)", consecutive_errors)
            interval = self.settings.loop_interval_seconds
            if consecutive_errors:
                # Si algo falla de forma persistente, se espacian los ciclos
                interval = min(self.MAX_ERROR_BACKOFF_SECONDS, interval * 2 ** min(consecutive_errors, 6))
            self._stop.wait(max(1.0, interval - (time.monotonic() - started)))
        self.shutdown()

    def stop(self, *_args: object) -> None:
        if not self._stop.is_set():
            logger.info("Parada solicitada: se termina el ciclo actual y se guarda el estado...")
        self._stop.set()

    def shutdown(self) -> None:
        self.risk.save()
        logger.info("Bot detenido. Posiciones abiertas: %d%s", len(self.risk.positions),
                    " (se retomarán al reiniciar)" if self.risk.positions else "")

    def run_cycle(self, now: datetime | None = None) -> None:
        now = now or utc_now()
        self._cycle += 1
        self._refresh_accounts()
        total_equity = (sum(a.equity for a in self._accounts.values())
                        if len(self._accounts) == len(self.brokers) else None)
        self.risk.roll_day_if_needed(now, total_equity)
        if not self.paper:
            self._reconcile_positions()
        # Risk-first: los stops se revisan ANTES de descargar noticias, para que
        # un feed lento nunca retrase una salida.
        self._manage_open_positions(now)
        self._refresh_news(now)
        self._update_market_sentiment(now)
        if self.risk.check_daily_loss():
            self._handle_kill_switch(now)
        else:
            self._scan_for_entries(now)
        self.risk.save()
        if self._cycle == 1 or self._cycle % self.settings.heartbeat_every_cycles == 0:
            self._heartbeat()

    # =========================================================================
    # Datos
    # =========================================================================
    def _refresh_news(self, now: datetime) -> None:
        try:
            added = self.news.refresh(now)
            if added:
                logger.info("%d noticias nuevas (%d en la ventana de análisis)", added, len(self.news))
        except Exception:  # noqa: BLE001
            logger.exception("Error actualizando noticias")

    def _refresh_accounts(self) -> None:
        for asset_class, broker in self.brokers.items():
            try:
                self._accounts[asset_class] = broker.get_account()
            except BrokerError as exc:
                logger.warning("No se pudo leer la cuenta %s: %s", broker.name, exc)
                self._accounts.pop(asset_class, None)

    def _symbol_sentiment(self, symbol: str, now: datetime) -> SentimentResult:
        return self.analyzer.aggregate(symbol, self.news.articles_for(symbol), now)

    def _update_market_sentiment(self, now: datetime) -> None:
        for asset_class in self.brokers:
            self._market_sentiment[asset_class] = self.analyzer.aggregate(
                f"MERCADO_{asset_class.upper()}", self.news.market_articles(asset_class), now)

    def _get_bars(self, broker: BaseBroker, symbol: str, now: datetime) -> pd.DataFrame:
        """Velas con caché: solo se descargan de nuevo cuando cierra una vela."""
        current_bar = pd.Timestamp(now).floor(self._timeframe)
        cached = self._bars_cache.get(symbol)
        if cached and cached[0] == current_bar:
            return cached[1]
        s = self.settings.strategy
        bars = broker.get_bars(symbol, s.timeframe, s.bars_lookback)
        # Solo se cachea si ya incluye la última vela cerrada (las APIs tardan
        # unos segundos en publicarla); si no, se reintenta en el próximo ciclo.
        if not bars.empty and bars.index[-1] >= current_bar - self._timeframe:
            self._bars_cache[symbol] = (current_bar, bars)
        return bars

    # =========================================================================
    # Gestión de posiciones abiertas
    # =========================================================================
    def _manage_open_positions(self, now: datetime) -> None:
        for position in list(self.risk.positions.values()):
            try:
                self._manage_position(position, now)
            except BrokerError as exc:
                logger.warning("%s: no se pudo gestionar la posición: %s", position.symbol, exc)
            except Exception:  # noqa: BLE001
                logger.exception("%s: error gestionando la posición", position.symbol)

    def _manage_position(self, position: Position, now: datetime) -> None:
        broker = self.brokers.get(position.asset_class)
        if broker is None:
            logger.warning("%s: no hay broker activo para %s", position.symbol, position.asset_class)
            return
        if position.asset_class == STOCKS and not broker.is_market_open():
            return  # fuera de horario una orden a mercado no se ejecuta

        price = broker.get_quote(position.symbol).sell_price
        reason = self.risk.update_and_check_exit(position, price, now)
        detail = ""
        if reason is None and position.asset_class == STOCKS:
            minutes_left = broker.minutes_to_close()
            if minutes_left is not None and minutes_left <= self.settings.risk.flatten_minutes_before_close:
                reason, detail = ExitReason.MARKET_CLOSE, f"{minutes_left:.0f} min para el cierre"
        if reason is None:
            sentiment = self._symbol_sentiment(position.symbol, now)
            bars = self._get_bars(broker, position.symbol, now)
            signal = self.strategy.evaluate_exit(position.symbol, bars, sentiment, now)
            if signal.action == Action.SELL:
                reason, detail = ExitReason.SIGNAL, signal.reason
        if reason is not None:
            self._close_position(position, reason, now, detail)

    def _close_position(self, position: Position, reason: ExitReason, now: datetime,
                        detail: str = "") -> bool:
        broker = self.brokers.get(position.asset_class)
        if broker is None:
            return False
        qty = position.qty
        if not self.paper and position.asset_class == CRYPTO:
            # Nunca vender más de lo que hay libre (las comisiones en especie restan)
            try:
                qty = min(qty, broker.get_positions().get(position.symbol, 0.0))
            except BrokerError as exc:
                logger.warning("%s: no se pudo comprobar el saldo antes de vender: %s", position.symbol, exc)
        qty = broker.normalize_qty(position.symbol, qty)
        if qty <= 0:
            self.risk.drop_position(position.symbol, "cantidad residual inferior al mínimo negociable")
            return False

        logger.info("%s: cerrando posición — %s%s", position.symbol, reason.value,
                    f" ({detail})" if detail else "")
        try:
            result = broker.submit_market_order(position.symbol, SELL, qty,
                                                client_order_id=new_client_order_id())
        except BrokerError as exc:
            logger.error("%s: NO se pudo cerrar (%s). Se reintentará en el próximo ciclo.",
                         position.symbol, exc)
            return False
        if result.filled_qty <= 0:
            logger.error("%s: la orden de venta no se ejecutó (estado %s)", position.symbol, result.status)
            return False
        trade = self.risk.register_close(position.symbol, result.avg_price, result.filled_qty,
                                         result.fee, reason, now)
        if trade is not None:
            self.journal.log_close(trade.to_row())
        return True

    def _handle_kill_switch(self, now: datetime) -> None:
        if not (self.settings.risk.kill_switch_flatten and self.risk.positions):
            return
        for position in list(self.risk.positions.values()):
            broker = self.brokers.get(position.asset_class)
            if broker is None or (position.asset_class == STOCKS and not broker.is_market_open()):
                continue
            try:
                self._close_position(position, ExitReason.KILL_SWITCH, now, "pérdida diaria máxima")
            except Exception:  # noqa: BLE001
                logger.exception("%s: error cerrando por kill switch", position.symbol)

    def _reconcile_positions(self) -> None:
        """Modo real: sincroniza el estado del bot con las posiciones del broker."""
        for asset_class, broker in self.brokers.items():
            try:
                held = broker.get_positions()
            except BrokerError as exc:
                logger.warning("No se pudo reconciliar %s: %s", broker.name, exc)
                continue
            for position in [p for p in self.risk.positions.values() if p.asset_class == asset_class]:
                actual = held.get(position.symbol, 0.0)
                if actual <= 0:
                    self.risk.drop_position(position.symbol, "ya no existe en el broker (¿cierre manual?)")
                elif actual < position.qty * 0.99:
                    logger.warning("%s: el broker tiene %.8g y el bot esperaba %.8g; se ajusta",
                                   position.symbol, actual, position.qty)
                    position.qty = actual
            if asset_class == STOCKS:  # en cripto el saldo puede ser inversión propia del usuario
                for symbol, qty in held.items():
                    if qty > 0 and symbol not in self.risk.positions and symbol not in self._warned_unmanaged:
                        logger.warning("Posición %s (%.8g) en %s no la gestiona el bot: no se tocará",
                                       symbol, qty, broker.name)
                        self._warned_unmanaged.add(symbol)

    # =========================================================================
    # Búsqueda de entradas
    # =========================================================================
    def _scan_for_entries(self, now: datetime) -> None:
        blocked = self.risk.entries_blocked(now)
        if blocked:
            logger.debug("Entradas bloqueadas: %s", blocked)
            return
        for instrument in self.instruments:
            if self._stop.is_set() or self.risk.entries_blocked(now):
                break
            try:
                self._evaluate_entry(instrument, now)
            except BrokerError as exc:
                logger.warning("%s: error de broker evaluando entrada: %s", instrument.symbol, exc)
            except Exception:  # noqa: BLE001
                logger.exception("%s: error evaluando entrada", instrument.symbol)

    def _evaluate_entry(self, instrument: Instrument, now: datetime) -> None:
        symbol, asset_class = instrument.symbol, instrument.asset_class
        broker = self.brokers[asset_class]
        account = self._accounts.get(asset_class)
        if account is None or account.trading_blocked:
            return
        ok, why = self.risk.can_open(symbol, asset_class, now, account.equity, account.daytrade_count)
        if not ok:
            logger.debug("%s: sin entrada — %s", symbol, why)
            return

        # 1) Filtro de sentimiento: barato, sin llamadas a la API del broker
        sentiment = self._symbol_sentiment(symbol, now)
        market = self._market_sentiment.get(asset_class)
        last_catalyst = self.risk.last_catalyst.get(symbol)
        ok, why = self.strategy.sentiment_gate(sentiment, market, now, last_catalyst)
        if not ok:
            logger.debug("%s: sin entrada — %s", symbol, why)
            return

        # 2) Horario: acciones solo en sesión regular y lejos del cierre
        if asset_class == STOCKS:
            if not broker.is_market_open():
                logger.debug("%s: mercado cerrado", symbol)
                return
            minutes_left = broker.minutes_to_close()
            if minutes_left is not None and minutes_left <= self.settings.risk.no_entries_minutes_before_close:
                logger.debug("%s: demasiado cerca del cierre (%.0f min)", symbol, minutes_left)
                return

        # 3) Confirmación técnica
        bars = self._get_bars(broker, symbol, now)
        signal = self.strategy.evaluate_entry(symbol, bars, sentiment, market, now, last_catalyst)
        if signal.action != Action.BUY:
            logger.info("%s: candidato descartado — %s", symbol, signal.reason)
            return

        # 4) Riesgo: spread, tamaño, stops
        quote = broker.get_quote(symbol)
        ok, why = self.risk.check_spread(quote.bid, quote.ask)
        if not ok:
            logger.info("%s: señal de compra descartada — %s", symbol, why)
            return
        plan, why = self.risk.build_trade_plan(
            symbol=symbol, asset_class=asset_class, price=quote.buy_price, atr=signal.atr,
            equity=account.equity, cash=account.cash,
            normalize_qty=lambda q: broker.normalize_qty(symbol, q),
            min_notional=broker.min_order_notional(symbol),
        )
        if plan is None:
            logger.info("%s: señal de compra descartada por riesgo — %s", symbol, why)
            return
        logger.info("%s: SEÑAL DE COMPRA — %s", symbol, signal.reason)
        self._open_position(broker, plan, signal.reason, sentiment, now)

    def _open_position(self, broker: BaseBroker, plan: TradePlan, reason: str,
                       sentiment: SentimentResult, now: datetime) -> None:
        pre_qty = None
        if not self.paper:
            with contextlib.suppress(BrokerError):
                pre_qty = broker.get_positions().get(plan.symbol, 0.0)
        try:
            result = broker.submit_market_order(plan.symbol, BUY, plan.qty,
                                                client_order_id=new_client_order_id())
        except BrokerError as exc:
            logger.error("%s: la orden de compra falló: %s", plan.symbol, exc)
            self._recover_unconfirmed_buy(broker, plan, pre_qty, sentiment, now)
            return
        if result.filled_qty <= 0:
            logger.warning("%s: compra no ejecutada (estado %s)", plan.symbol, result.status)
            return
        position = self.risk.register_open(plan, result.filled_qty, result.avg_price, result.fee,
                                           now, catalyst_at=sentiment.latest_published)
        self.journal.log_open(
            symbol=position.symbol, qty=position.qty, price=position.entry_price,
            stop=position.stop_price, take_profit=position.take_profit_price,
            notional=position.qty * position.entry_price, fee=result.fee,
            reason=f"{reason} | riesgo≈{fmt_money(plan.risk_amount)} ({plan.limited_by})",
        )
        try:  # el efectivo cambió: refrescar antes de dimensionar la siguiente
            self._accounts[plan.asset_class] = broker.get_account()
        except BrokerError:
            self._accounts.pop(plan.asset_class, None)

    def _recover_unconfirmed_buy(self, broker: BaseBroker, plan: TradePlan, pre_qty: float | None,
                                 sentiment: SentimentResult, now: datetime) -> None:
        """
        Si la respuesta de la orden se perdió (timeout) pero el broker sí la
        ejecutó, la posición quedaría sin stop. Se compara el saldo antes y
        después y, si ha aumentado, se adopta la posición con sus stops.
        """
        if pre_qty is None:
            return
        try:
            post_qty = broker.get_positions().get(plan.symbol, 0.0)
        except BrokerError as exc:
            logger.critical("%s: estado de la orden DESCONOCIDO y no se puede verificar (%s). "
                            "Revisa el broker manualmente.", plan.symbol, exc)
            return
        bought = post_qty - pre_qty
        if bought > 0:
            logger.critical("%s: la orden SÍ se ejecutó pese al error (%.8g unidades). "
                            "Se adopta la posición con stop-loss.", plan.symbol, bought)
            self.risk.register_open(plan, bought, plan.entry_price, 0.0, now,
                                    catalyst_at=sentiment.latest_published)

    # =========================================================================
    # Informe periódico
    # =========================================================================
    def _heartbeat(self) -> None:
        mode = "PAPER (simulado)" if self.paper else "REAL"
        logger.info("── Estado [%s] noticias=%d | PnL día=%+.2f | operaciones hoy=%d | posiciones=%d%s",
                    mode, len(self.news), self.risk.daily_pnl(), self.risk.trades_today,
                    len(self.risk.positions), " | KILL SWITCH" if self.risk.kill_switch else "")
        for asset_class, account in self._accounts.items():
            logger.info("   Cuenta %-6s capital=%s efectivo=%s %s", asset_class,
                        fmt_money(account.equity), fmt_money(account.cash), account.currency)
        for asset_class, market in self._market_sentiment.items():
            logger.info("   Mercado %-6s %s", asset_class, market.describe())
        for p in self.risk.positions.values():
            logger.info("   %-9s qty=%.8g entrada=%s último=%s SL=%s TP=%s PnL=%+.2f (%+.2fR)%s",
                        p.symbol, p.qty, fmt_price(p.entry_price), fmt_price(p.mark()),
                        fmt_price(p.stop_price),
                        fmt_price(p.take_profit_price) if p.take_profit_price else "—",
                        p.unrealized_pnl(), p.r_multiple(), " [trailing]" if p.trailing_active else "")


# =============================================================================
# Informe de resultados
# =============================================================================
def print_report(csv_path: Path) -> int:
    if not csv_path.exists():
        print(f"Aún no hay operaciones cerradas en {csv_path}")
        return 0
    df = pd.read_csv(csv_path)
    if df.empty:
        print("El diario de operaciones está vacío")
        return 0
    wins, losses = df[df["net_pnl"] > 0], df[df["net_pnl"] <= 0]
    gross_loss = abs(losses["net_pnl"].sum())
    equity = df["net_pnl"].cumsum()
    print(f"\n=== Informe de operaciones ({csv_path.name}) ===")
    print(f"Operaciones           : {len(df)}")
    print(f"Tasa de acierto       : {len(wins) / len(df):.1%}")
    print(f"PnL neto total        : {df['net_pnl'].sum():+.2f}")
    print(f"Comisiones pagadas    : {df['fees'].sum():.2f}")
    print(f"Ganancia media        : {wins['net_pnl'].mean() if len(wins) else 0:+.2f}")
    print(f"Pérdida media         : {losses['net_pnl'].mean() if len(losses) else 0:+.2f}")
    print(f"Profit factor         : {wins['net_pnl'].sum() / gross_loss if gross_loss else float('inf'):.2f}")
    print(f"Esperanza por trade   : {df['net_pnl'].mean():+.2f} ({df['r_multiple'].mean():+.2f}R)")
    print(f"Máximo drawdown       : {(equity - equity.cummax()).min():.2f}")
    print(f"Duración media        : {df['holding_minutes'].mean():.0f} min")
    print("\nPor símbolo:")
    print(df.groupby("symbol")["net_pnl"].agg(["count", "sum", "mean"]).round(2).to_string())
    print("\nPor motivo de salida:")
    print(df.groupby("exit_reason")["net_pnl"].agg(["count", "sum", "mean"]).round(2).to_string())
    return 0


# =============================================================================
# Arranque
# =============================================================================
def _log_banner(settings: Settings) -> None:
    r, s = settings.risk, settings.strategy
    if settings.paper_trading:
        logger.info("=" * 78)
        logger.info(" MODO PAPER TRADING — órdenes SIMULADAS, ningún dinero real en juego")
        logger.info("=" * 78)
    else:
        logger.warning("=" * 78)
        logger.warning(" MODO REAL — se enviarán órdenes al broker")
        logger.warning("   Alpaca: %s | Cripto (%s): %s",
                       "PAPER (sin dinero real)" if settings.broker.alpaca_paper else "CUENTA REAL",
                       settings.broker.crypto_exchange,
                       "SANDBOX/TESTNET" if settings.broker.crypto_sandbox else "CUENTA REAL")
        logger.warning("=" * 78)
    logger.info("Watchlist: %s", ", ".join(i.symbol for i in settings.instruments))
    logger.info("Riesgo: máx %.1f%% del capital por operación (riesgo %.1f%%) | stop ATR x%.1f en "
                "[%.2f%%, %.2f%%] | TP %.1fR | trailing desde +%.2fR a %.2fR | pérdida diaria máx %.1f%%",
                100 * r.max_position_pct, 100 * r.max_risk_per_trade_pct, r.atr_stop_multiplier,
                100 * r.min_stop_pct, 100 * r.stop_loss_pct, r.take_profit_rr,
                r.trailing_activation_r, r.trailing_distance_r, 100 * r.max_daily_loss_pct)
    logger.info("Estrategia: velas %s | entrada con Score >= %+.0f | salida con Score <= %+.0f",
                s.timeframe, s.entry_score, s.exit_score)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bot de trading por sentimiento + técnico")
    parser.add_argument("--once", action="store_true", help="ejecuta un único ciclo y termina")
    parser.add_argument("--report", action="store_true", help="muestra estadísticas del diario")
    parser.add_argument("--env-file", default=None, help="ruta alternativa al archivo .env")
    parser.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.env_file)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2

    mode = "paper" if settings.paper_trading else "live"
    if args.report:
        return print_report(settings.log_dir / f"{mode}_trades.csv")

    trades_log = setup_logging(settings.log_dir, args.log_level or settings.log_level,
                               settings.paper_trading)

    # Doble cerrojo para operar con órdenes reales
    if not settings.paper_trading and settings.live_confirmation != config.LIVE_CONFIRMATION_PHRASE:
        logger.critical("PAPER_TRADING=False pero falta LIVE_TRADING_CONFIRMATION=%s en el .env. "
                        "Abortando por seguridad.", config.LIVE_CONFIRMATION_PHRASE)
        return 3

    _log_banner(settings)
    brokers = build_brokers(settings)
    if not brokers:
        logger.critical("Ningún mercado disponible: revisa las claves API y la watchlist del .env")
        return 4

    active = [i for i in settings.instruments if i.asset_class in brokers]
    news = NewsAggregator(settings.news, active,
                          alpaca_keys=(settings.broker.alpaca_api_key, settings.broker.alpaca_secret_key))
    bot = TradingBot(
        settings=settings,
        brokers=brokers,
        news=news,
        analyzer=SentimentAnalyzer(settings.news.half_life_minutes,
                                   settings.strategy.full_confidence_articles),
        strategy=SentimentMomentumStrategy(settings.strategy),
        risk=RiskManager(settings.risk, settings.state_dir / f"risk_state_{mode}.json"),
        journal=TradeJournal(settings.log_dir, settings.paper_trading),
    )
    logger.info("Diario de operaciones: %s", trades_log)

    signal.signal(signal.SIGINT, bot.stop)
    signal.signal(signal.SIGTERM, bot.stop)  # systemd / docker stop

    if args.once:
        bot.run_cycle()
        bot.shutdown()
    else:
        bot.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
