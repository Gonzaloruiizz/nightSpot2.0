"""
api_handler.py
==============
Capa de conexión con los brokers. El resto del bot solo conoce la interfaz
`BaseBroker`, así que cambiar de broker no afecta a la estrategia ni al riesgo.

  - AlpacaBroker  -> acciones USA (alpaca-py). Endpoint paper o real.
  - CCXTBroker    -> cripto spot en Binance o Kraken (ccxt).
  - PaperBroker   -> SIMULADOR: usa precios reales de otro broker pero nunca
                     envía órdenes; aplica comisiones y slippage, lleva un
                     saldo virtual persistente y registra todo en el .log.

Política de errores:
  - Lecturas (velas, cotizaciones, saldo): reintentos con backoff exponencial
    SOLO ante errores transitorios (red, timeouts, 429, 5xx).
  - Órdenes: NUNCA se reintentan automáticamente (una orden con respuesta
    perdida podría haberse ejecutado y se duplicaría). El bot reconcilia el
    estado consultando las posiciones reales.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd

from config import CRYPTO, STOCKS, Settings, timeframe_to_minutes
from utils import (
    TRADE_LOGGER_NAME,
    atomic_write_json,
    call_with_retry,
    floor_to_decimals,
    fmt_money,
    fmt_price,
    read_json,
    utc_now,
)

T = TypeVar("T")
logger = logging.getLogger("api")

BUY = "buy"
SELL = "sell"
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class BrokerError(Exception):
    """Cualquier fallo del broker (red, credenciales, datos, orden)."""


class OrderRejected(BrokerError):
    """El broker rechazó la orden (cantidad, símbolo, mercado cerrado...)."""


class InsufficientFunds(OrderRejected):
    """Saldo insuficiente para la orden."""


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: datetime | None = None

    @property
    def buy_price(self) -> float:
        """Precio realista de compra a mercado (se compra al ask)."""
        return self.ask if self.ask > 0 else self.last

    @property
    def sell_price(self) -> float:
        """Precio realista de venta a mercado (se vende al bid)."""
        return self.bid if self.bid > 0 else self.last


@dataclass
class AccountInfo:
    equity: float          # valor total de la cuenta
    cash: float            # efectivo disponible (sin apalancamiento)
    currency: str = "USD"
    daytrade_count: int | None = None
    trading_blocked: bool = False


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    requested_qty: float
    filled_qty: float      # cantidad NETA recibida (descontando comisiones en especie)
    avg_price: float
    fee: float = 0.0       # comisión en divisa de cotización
    status: str = "filled"


def new_client_order_id() -> str:
    """ID propio de la orden: permite localizarla aunque se pierda la respuesta."""
    return f"sbot-{uuid.uuid4().hex[:20]}"


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV_COLUMNS, index=pd.DatetimeIndex([], tz="UTC"), dtype=float)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


class BaseBroker(ABC):
    name = "base"

    def __init__(self, asset_class: str):
        self.asset_class = asset_class

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Velas OHLCV (índice UTC ascendente). Puede incluir la vela en curso."""

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """Mejor bid/ask y último precio."""

    @abstractmethod
    def get_account(self) -> AccountInfo:
        """Capital y efectivo de la cuenta."""

    @abstractmethod
    def get_positions(self) -> dict[str, float]:
        """Cantidades disponibles por símbolo."""

    @abstractmethod
    def submit_market_order(self, symbol: str, side: str, qty: float,
                            client_order_id: str | None = None) -> OrderResult:
        """Envía una orden a mercado y espera su ejecución."""

    def normalize_qty(self, symbol: str, qty: float) -> float:
        """Redondea HACIA ABAJO la cantidad a lo que acepta el mercado."""
        return floor_to_decimals(qty, 6)

    def min_order_notional(self, symbol: str) -> float:
        return 1.0

    def is_market_open(self) -> bool:
        return True

    def minutes_to_close(self) -> float | None:
        return None


# =============================================================================
# Alpaca (acciones)
# =============================================================================
class AlpacaBroker(BaseBroker):
    name = "alpaca"
    FILL_TIMEOUT_SECONDS = 15
    CLOCK_TTL_SECONDS = 60
    _TERMINAL = {"filled", "canceled", "expired", "rejected", "done_for_day"}

    def __init__(self, api_key: str, secret_key: str, *, paper_endpoint: bool = True,
                 data_feed: str = "iex", allow_fractional: bool = True, read_only: bool = False):
        super().__init__(STOCKS)
        if not api_key or not secret_key:
            raise BrokerError("faltan ALPACA_API_KEY / ALPACA_SECRET_KEY en el .env")
        try:
            from alpaca.data.enums import DataFeed
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise BrokerError("falta la librería alpaca-py (pip install -r requirements.txt)") from exc
        try:
            self.feed = DataFeed(data_feed)
        except ValueError as exc:
            raise BrokerError(f"ALPACA_DATA_FEED={data_feed!r} no válido (usa iex o sip)") from exc
        self.trading = TradingClient(api_key, secret_key, paper=paper_endpoint)
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self.paper_endpoint = paper_endpoint
        self.allow_fractional = allow_fractional
        self.read_only = read_only
        self._clock: Any = None
        self._clock_fetched = 0.0
        self._fractionable: dict[str, bool] = {}

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        import requests
        from alpaca.common.exceptions import APIError
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(exc, APIError):
            try:
                return exc.status_code in (429, 500, 502, 503, 504)
            except Exception:  # noqa: BLE001 - APIError sin respuesta HTTP
                return False
        return False

    def _call(self, fn: Callable[[], T], description: str) -> T:
        try:
            return call_with_retry(fn, is_transient=self._is_transient,
                                   description=f"Alpaca {description}")
        except Exception as exc:  # noqa: BLE001 - todo se traduce a BrokerError
            raise BrokerError(f"Alpaca {description}: {exc}") from exc

    # --- datos -----------------------------------------------------------------
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        from alpaca.common.enums import Sort
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        minutes = timeframe_to_minutes(timeframe)
        tf = (TimeFrame(minutes // 60, TimeFrameUnit.Hour) if minutes >= 60
              else TimeFrame(minutes, TimeFrameUnit.Minute))
        # Ventana amplia para cubrir noches, fines de semana y festivos; con
        # orden descendente + limit se obtienen exactamente las últimas velas.
        start = utc_now() - timedelta(minutes=minutes * limit * 4) - timedelta(days=4)
        request = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start,
                                   limit=limit, sort=Sort.DESC, feed=self.feed)
        barset = self._call(lambda: self.data.get_stock_bars(request), f"velas {symbol}")
        df = barset.df
        if df.empty:
            return _empty_bars()
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        df = df[OHLCV_COLUMNS].astype(float).sort_index()
        index = pd.DatetimeIndex(df.index)
        df.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
        return df.tail(limit)

    def get_quote(self, symbol: str) -> Quote:
        from alpaca.data.requests import StockSnapshotRequest

        request = StockSnapshotRequest(symbol_or_symbols=symbol, feed=self.feed)
        snapshots = self._call(lambda: self.data.get_stock_snapshot(request), f"cotización {symbol}")
        snap = snapshots.get(symbol) if isinstance(snapshots, dict) else snapshots
        if snap is None:
            raise BrokerError(f"Alpaca no devolvió cotización para {symbol}")
        quote, trade = snap.latest_quote, snap.latest_trade
        bid = float(quote.bid_price or 0) if quote else 0.0
        ask = float(quote.ask_price or 0) if quote else 0.0
        last = float(trade.price or 0) if trade else 0.0
        if last <= 0 and bid > 0 and ask > 0:
            last = (bid + ask) / 2
        if last <= 0:
            raise BrokerError(f"sin precio válido para {symbol}")
        return Quote(symbol, bid, ask, last, getattr(trade, "timestamp", None))

    # --- cuenta ------------------------------------------------------------------
    def get_account(self) -> AccountInfo:
        acct = self._call(self.trading.get_account, "cuenta")
        return AccountInfo(
            equity=float(acct.equity or 0),
            cash=float(acct.cash or 0),
            currency=acct.currency or "USD",
            daytrade_count=int(acct.daytrade_count or 0),
            trading_blocked=bool(acct.trading_blocked or acct.account_blocked),
        )

    def get_positions(self) -> dict[str, float]:
        positions = self._call(self.trading.get_all_positions, "posiciones")
        return {p.symbol: float(p.qty_available if p.qty_available is not None else p.qty)
                for p in positions}

    # --- órdenes -------------------------------------------------------------------
    def submit_market_order(self, symbol: str, side: str, qty: float,
                            client_order_id: str | None = None) -> OrderResult:
        if self.read_only:
            raise BrokerError("broker en modo SOLO LECTURA (PAPER_TRADING): orden real bloqueada")
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == BUY else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,  # obligatorio para fracciones; muere al cierre
            client_order_id=client_order_id or new_client_order_id(),
        )
        try:
            order = self.trading.submit_order(request)  # SIN reintentos (evita duplicados)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"orden {side} {qty} {symbol} no confirmada por Alpaca: {exc}") from exc
        order = self._wait_for_fill(order)
        return OrderResult(
            order_id=str(order.id),
            symbol=symbol,
            side=side,
            requested_qty=qty,
            filled_qty=float(order.filled_qty or 0),
            avg_price=float(order.filled_avg_price or 0),
            fee=0.0,  # Alpaca no cobra comisión en acciones
            status=_enum_value(order.status),
        )

    def _wait_for_fill(self, order: Any) -> Any:
        deadline = time.monotonic() + self.FILL_TIMEOUT_SECONDS
        while _enum_value(order.status) not in self._TERMINAL and time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                order = self.trading.get_order_by_id(order.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo consultar la orden %s: %s", order.id, exc)
        if _enum_value(order.status) not in self._TERMINAL:
            # Una orden "colgada" se cancela para que el estado sea conocido
            logger.warning("Orden %s sin completar tras %ss: se cancela el resto",
                           order.id, self.FILL_TIMEOUT_SECONDS)
            try:
                self.trading.cancel_order_by_id(order.id)
                time.sleep(1)
                order = self.trading.get_order_by_id(order.id)
            except Exception as exc:  # noqa: BLE001
                logger.error("No se pudo cancelar/consultar la orden %s: %s", order.id, exc)
        return order

    def normalize_qty(self, symbol: str, qty: float) -> float:
        if self.allow_fractional and self._is_fractionable(symbol):
            return floor_to_decimals(qty, 4)
        return float(math.floor(qty))

    def _is_fractionable(self, symbol: str) -> bool:
        # Si la consulta falla se propaga el BrokerError en vez de suponer "no
        # fraccionable": redondear 4.9975 a 4 al vender dejaría 0.9975 acciones
        # huérfanas sin stop. El bot reintentará en el siguiente ciclo.
        if symbol not in self._fractionable:
            asset = self._call(lambda: self.trading.get_asset(symbol), f"activo {symbol}")
            self._fractionable[symbol] = bool(asset.fractionable)
        return self._fractionable[symbol]

    # --- horario de mercado ------------------------------------------------------
    def _get_clock(self) -> Any:
        if self._clock is None or time.monotonic() - self._clock_fetched > self.CLOCK_TTL_SECONDS:
            self._clock = self._call(self.trading.get_clock, "reloj de mercado")
            self._clock_fetched = time.monotonic()
        return self._clock

    def is_market_open(self) -> bool:
        try:
            return bool(self._get_clock().is_open)
        except BrokerError as exc:
            logger.warning("No se pudo consultar el horario de mercado: %s", exc)
            return False  # ante la duda, mercado cerrado

    def minutes_to_close(self) -> float | None:
        try:
            clock = self._get_clock()
        except BrokerError:
            return None
        if not clock.is_open or clock.next_close is None:
            return None
        next_close = clock.next_close
        if next_close.tzinfo is None:
            next_close = next_close.replace(tzinfo=timezone.utc)
        return (next_close - utc_now()).total_seconds() / 60.0


# =============================================================================
# Binance / Kraken (cripto spot vía ccxt)
# =============================================================================
class CCXTBroker(BaseBroker):
    FILL_TIMEOUT_SECONDS = 15
    _TERMINAL = {"closed", "canceled", "rejected", "expired"}

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "", *,
                 sandbox: bool = False, read_only: bool = False, symbols: list[str] | tuple = ()):
        super().__init__(CRYPTO)
        try:
            import ccxt
        except ImportError as exc:
            raise BrokerError("falta la librería ccxt (pip install -r requirements.txt)") from exc
        if not hasattr(ccxt, exchange_id):
            raise BrokerError(f"exchange {exchange_id!r} no soportado por ccxt")
        self._ccxt = ccxt
        self.name = exchange_id
        self.symbols = list(symbols)
        quotes = Counter(s.split("/")[1] for s in self.symbols if "/" in s)
        if len(quotes) > 1:
            raise BrokerError(f"todos los pares cripto deben cotizar en la misma divisa, hay: {dict(quotes)}")
        self.quote_currency = next(iter(quotes), "USDT")

        options: dict[str, Any] = {"enableRateLimit": True, "timeout": 15_000,
                                   "options": {"defaultType": "spot"}}
        self.has_credentials = bool(api_key and secret)
        if self.has_credentials:
            options.update(apiKey=api_key, secret=secret)
        self.exchange = getattr(ccxt, exchange_id)(options)
        if sandbox:
            try:
                self.exchange.set_sandbox_mode(True)
            except Exception as exc:  # noqa: BLE001 - Kraken spot no tiene sandbox
                raise BrokerError(
                    f"{exchange_id} no ofrece entorno sandbox para spot ({exc}). "
                    "Usa PAPER_TRADING=True para simular, o CRYPTO_SANDBOX=false SOLO si "
                    "quieres operar con dinero real") from exc
        self.read_only = read_only or not self.has_credentials
        self._markets_loaded = False

    def _is_transient(self, exc: BaseException) -> bool:
        return isinstance(exc, self._ccxt.NetworkError)

    def _call(self, fn: Callable[[], T], description: str) -> T:
        try:
            return call_with_retry(fn, is_transient=self._is_transient,
                                   description=f"{self.name} {description}")
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"{self.name} {description}: {exc}") from exc

    def _market(self, symbol: str) -> dict:
        if not self._markets_loaded:
            self._call(self.exchange.load_markets, "carga de mercados")
            self._markets_loaded = True
        try:
            return self.exchange.market(symbol)
        except Exception as exc:  # noqa: BLE001 - BadSymbol
            raise BrokerError(f"el par {symbol} no existe en {self.name}") from exc

    # --- datos -----------------------------------------------------------------
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        self._market(symbol)
        rows = self._call(lambda: self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1),
                          f"velas {symbol}")
        if not rows:
            return _empty_bars()
        df = pd.DataFrame(rows, columns=["timestamp", *OHLCV_COLUMNS])
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True))
        return df.astype(float).sort_index().tail(limit + 1)

    def get_quote(self, symbol: str) -> Quote:
        self._market(symbol)
        ticker = self._call(lambda: self.exchange.fetch_ticker(symbol), f"ticker {symbol}")
        bid = float(ticker.get("bid") or 0)
        ask = float(ticker.get("ask") or 0)
        last = float(ticker.get("last") or ticker.get("close") or 0)
        if last <= 0 and bid > 0 and ask > 0:
            last = (bid + ask) / 2
        if last <= 0:
            raise BrokerError(f"sin precio válido para {symbol}")
        ts = ticker.get("timestamp")
        return Quote(symbol, bid, ask, last,
                     datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else None)

    # --- cuenta ------------------------------------------------------------------
    def _balance(self) -> dict:
        if not self.has_credentials:
            raise BrokerError("sin claves API no se puede consultar el saldo")
        return self._call(self.exchange.fetch_balance, "saldo")

    def get_account(self) -> AccountInfo:
        """
        Capital = saldo en divisa de cotización + valor de los activos de la
        watchlist. Se recomienda una SUBCUENTA dedicada al bot para que el
        cálculo no incluya inversiones a largo plazo.
        """
        balance = self._balance()
        total, free = balance.get("total") or {}, balance.get("free") or {}
        equity = float(total.get(self.quote_currency) or 0)
        for symbol in self.symbols:
            amount = float(total.get(symbol.split("/")[0]) or 0)
            if amount > 0:
                try:
                    equity += amount * self.get_quote(symbol).sell_price
                except BrokerError as exc:
                    logger.warning("No se pudo valorar %s: %s", symbol, exc)
        return AccountInfo(equity=equity, cash=float(free.get(self.quote_currency) or 0),
                           currency=self.quote_currency)

    def get_positions(self) -> dict[str, float]:
        free = self._balance().get("free") or {}
        return {s: float(free.get(s.split("/")[0]) or 0) for s in self.symbols
                if float(free.get(s.split("/")[0]) or 0) > 0}

    # --- órdenes -------------------------------------------------------------------
    def submit_market_order(self, symbol: str, side: str, qty: float,
                            client_order_id: str | None = None) -> OrderResult:
        if self.read_only:
            raise BrokerError("broker en modo SOLO LECTURA: orden real bloqueada")
        market = self._market(symbol)
        amount = self.normalize_qty(symbol, qty)
        if amount <= 0:
            raise OrderRejected(f"cantidad {qty} por debajo del mínimo de {symbol}")
        params = {"newClientOrderId": client_order_id} if self.name == "binance" and client_order_id else {}
        try:
            order = self.exchange.create_order(symbol, "market", side, amount, None, params)
        except self._ccxt.InsufficientFunds as exc:
            raise InsufficientFunds(str(exc)) from exc
        except self._ccxt.InvalidOrder as exc:
            raise OrderRejected(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - SIN reintentos (evita duplicados)
            raise BrokerError(f"orden {side} {amount} {symbol} no confirmada: {exc}") from exc
        order = self._wait_for_fill(symbol, order)

        filled = float(order.get("filled") or 0)
        avg = float(order.get("average") or 0)
        if avg <= 0 and filled > 0 and order.get("cost"):
            avg = float(order["cost"]) / filled
        base, quote = symbol.split("/")
        fee_quote, fee_base = 0.0, 0.0
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        for fee in fees:
            if not fee or fee.get("cost") is None:
                continue
            cost, currency = float(fee["cost"]), fee.get("currency")
            if currency == base:
                fee_base += cost  # la comisión se cobra en el activo comprado
                fee_quote += cost * avg
            elif currency == quote:
                fee_quote += cost
            else:  # p. ej. BNB: se estima con la comisión taker del mercado
                fee_quote += filled * avg * float(market.get("taker") or 0.001)
        return OrderResult(
            order_id=str(order.get("id")),
            symbol=symbol,
            side=side,
            requested_qty=qty,
            filled_qty=max(0.0, filled - fee_base) if side == BUY else filled,
            avg_price=avg,
            fee=fee_quote,
            status=str(order.get("status")),
        )

    def _wait_for_fill(self, symbol: str, order: dict) -> dict:
        deadline = time.monotonic() + self.FILL_TIMEOUT_SECONDS
        while order.get("status") not in self._TERMINAL and time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                order = self.exchange.fetch_order(order["id"], symbol)
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo consultar la orden %s: %s", order.get("id"), exc)
        if order.get("status") not in self._TERMINAL:
            logger.warning("Orden %s sin completar: se cancela el resto", order.get("id"))
            try:
                self.exchange.cancel_order(order["id"], symbol)
                order = self.exchange.fetch_order(order["id"], symbol)
            except Exception as exc:  # noqa: BLE001
                logger.error("No se pudo cancelar/consultar la orden %s: %s", order.get("id"), exc)
        return order

    def normalize_qty(self, symbol: str, qty: float) -> float:
        market = self._market(symbol)
        try:
            amount = float(self.exchange.amount_to_precision(symbol, qty))  # trunca, no redondea
        except Exception:  # noqa: BLE001 - ccxt lanza si el resultado es 0
            return 0.0
        min_amount = ((market.get("limits") or {}).get("amount") or {}).get("min") or 0
        return amount if amount >= min_amount else 0.0

    def min_order_notional(self, symbol: str) -> float:
        market = self._market(symbol)
        cost_min = ((market.get("limits") or {}).get("cost") or {}).get("min")
        return float(cost_min) if cost_min else 5.0


# =============================================================================
# Simulador (PAPER_TRADING = True)
# =============================================================================
class PaperBroker(BaseBroker):
    """
    Broker simulado. Toma velas y cotizaciones REALES del broker de datos, pero
    las órdenes solo modifican un saldo virtual:
      - compra al ASK + slippage, venta al BID - slippage
      - comisión porcentual sobre el nominal
      - saldo y posiciones persistidos en state/paper_<mercado>.json
    Cada orden simulada se escribe en logs/paper_trades.log.
    """

    def __init__(self, data_broker: BaseBroker, *, initial_cash: float, fee_pct: float,
                 slippage_pct: float, state_path: Path | None = None, currency: str = "USD"):
        super().__init__(data_broker.asset_class)
        self.data = data_broker
        self.name = f"paper-{data_broker.name}"
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.state_path = state_path
        self.currency = currency
        self.trade_log = logging.getLogger(TRADE_LOGGER_NAME)
        state = read_json(state_path, None) if state_path else None
        if state:
            self.initial_cash = float(state.get("initial_cash", initial_cash))
            self.cash = float(state["cash"])
            self.holdings = {k: float(v) for k, v in state.get("holdings", {}).items()}
            self.avg_cost = {k: float(v) for k, v in state.get("avg_cost", {}).items()}
            self.fees_paid = float(state.get("fees_paid", 0.0))
            self.order_seq = int(state.get("order_seq", 0))
            logger.info("Cuenta simulada %s restaurada: efectivo %s %s, %d posiciones",
                        self.name, fmt_money(self.cash), currency, len(self.holdings))
        else:
            self.initial_cash = initial_cash
            self.cash = initial_cash
            self.holdings: dict[str, float] = {}
            self.avg_cost: dict[str, float] = {}
            self.fees_paid = 0.0
            self.order_seq = 0

    # Datos de mercado: se delegan en el broker real
    def get_bars(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        return self.data.get_bars(symbol, timeframe, limit)

    def get_quote(self, symbol: str) -> Quote:
        return self.data.get_quote(symbol)

    def normalize_qty(self, symbol: str, qty: float) -> float:
        return self.data.normalize_qty(symbol, qty)

    def min_order_notional(self, symbol: str) -> float:
        return self.data.min_order_notional(symbol)

    def is_market_open(self) -> bool:
        return self.data.is_market_open()

    def minutes_to_close(self) -> float | None:
        return self.data.minutes_to_close()

    # Cuenta virtual
    def get_account(self) -> AccountInfo:
        equity = self.cash
        for symbol, qty in self.holdings.items():
            try:
                price = self.data.get_quote(symbol).sell_price
            except BrokerError as exc:
                price = self.avg_cost.get(symbol, 0.0)
                logger.warning("Sin precio para valorar %s (%s): se usa el coste medio", symbol, exc)
            equity += qty * price
        return AccountInfo(equity=equity, cash=self.cash, currency=self.currency)

    def get_positions(self) -> dict[str, float]:
        return {s: q for s, q in self.holdings.items() if q > 0}

    def submit_market_order(self, symbol: str, side: str, qty: float,
                            client_order_id: str | None = None) -> OrderResult:
        if qty <= 0:
            raise OrderRejected("la cantidad debe ser positiva")
        quote = self.data.get_quote(symbol)
        if side == BUY:
            price = quote.buy_price * (1 + self.slippage_pct)
            notional = qty * price
            fee = notional * self.fee_pct
            if notional + fee > self.cash + 1e-9:
                raise InsufficientFunds(f"efectivo simulado insuficiente: {self.cash:.2f} < {notional + fee:.2f}")
            held = self.holdings.get(symbol, 0.0)
            self.avg_cost[symbol] = (held * self.avg_cost.get(symbol, 0.0) + notional) / (held + qty)
            self.holdings[symbol] = held + qty
            self.cash -= notional + fee
        else:
            held = self.holdings.get(symbol, 0.0)
            if held <= 0:
                raise OrderRejected(f"no hay posición simulada en {symbol}")
            qty = min(qty, held)
            price = quote.sell_price * (1 - self.slippage_pct)
            notional = qty * price
            fee = notional * self.fee_pct
            self.cash += notional - fee
            remaining = held - qty
            if remaining <= 1e-12:
                self.holdings.pop(symbol, None)
                self.avg_cost.pop(symbol, None)
            else:
                self.holdings[symbol] = remaining
        self.fees_paid += fee
        self.order_seq += 1
        order_id = client_order_id or f"paper-{self.order_seq}"
        self.trade_log.info(
            "[PAPER] ORDEN SIMULADA %-4s %-9s qty=%s @ %s (bid=%s ask=%s, slippage %.2f%%) "
            "comisión=%s | efectivo=%s %s",
            side.upper(), symbol, f"{qty:.8g}", fmt_price(price), fmt_price(quote.bid),
            fmt_price(quote.ask), 100 * self.slippage_pct, fmt_money(fee), fmt_money(self.cash),
            self.currency,
        )
        self._save()
        return OrderResult(order_id, symbol, side, qty, qty, price, fee, "filled")

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            atomic_write_json(self.state_path, {
                "initial_cash": self.initial_cash,
                "cash": self.cash,
                "holdings": self.holdings,
                "avg_cost": self.avg_cost,
                "fees_paid": self.fees_paid,
                "order_seq": self.order_seq,
                "updated_at": utc_now().isoformat(),
            })
        except OSError as exc:
            logger.error("No se pudo guardar la cuenta simulada: %s", exc)


# =============================================================================
# Fábrica
# =============================================================================
def build_brokers(settings: Settings) -> dict[str, BaseBroker]:
    """
    Crea un broker por mercado activo. Si un mercado no se puede inicializar
    (faltan claves, exchange no válido...) se desactiva con un error en el
    log y el bot continúa con el resto.
    """
    brokers: dict[str, BaseBroker] = {}
    paper = settings.paper_trading
    b = settings.broker

    if settings.stock_instruments:
        try:
            alpaca = AlpacaBroker(
                b.alpaca_api_key, b.alpaca_secret_key,
                paper_endpoint=b.alpaca_paper,
                data_feed=b.alpaca_data_feed,
                allow_fractional=b.alpaca_fractional,
                read_only=paper,  # en simulación el cliente real no puede enviar órdenes
            )
            brokers[STOCKS] = PaperBroker(
                alpaca,
                initial_cash=settings.paper.initial_cash_stocks,
                fee_pct=settings.risk.fee_pct_stocks,
                slippage_pct=settings.risk.slippage_pct,
                state_path=settings.state_dir / "paper_stocks.json",
                currency="USD",
            ) if paper else alpaca
        except BrokerError as exc:
            logger.error("ACCIONES DESACTIVADAS: %s", exc)

    if settings.crypto_instruments:
        symbols = [i.symbol for i in settings.crypto_instruments]
        try:
            if paper:
                # Simulación: datos PÚBLICOS de producción y NINGUNA clave API,
                # así que es técnicamente imposible enviar una orden real.
                data = CCXTBroker(b.crypto_exchange, sandbox=False, read_only=True, symbols=symbols)
                brokers[CRYPTO] = PaperBroker(
                    data,
                    initial_cash=settings.paper.initial_cash_crypto,
                    fee_pct=settings.risk.fee_pct_crypto,
                    slippage_pct=settings.risk.slippage_pct,
                    state_path=settings.state_dir / "paper_crypto.json",
                    currency=data.quote_currency,
                )
            else:
                if not (b.crypto_api_key and b.crypto_api_secret):
                    raise BrokerError("faltan CRYPTO_API_KEY / CRYPTO_API_SECRET en el .env")
                brokers[CRYPTO] = CCXTBroker(b.crypto_exchange, b.crypto_api_key, b.crypto_api_secret,
                                             sandbox=b.crypto_sandbox, read_only=False, symbols=symbols)
        except BrokerError as exc:
            logger.error("CRIPTO DESACTIVADA: %s", exc)

    return brokers
