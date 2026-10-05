"""
config.py
=========
Configuración central del bot: flag de modo pruebas, carga de variables de
entorno (.env), parámetros de estrategia y de gestión de riesgo.

Convención: todos los porcentajes se expresan como FRACCIÓN (0.01 = 1 %).
Cualquier parámetro puede sobrescribirse desde el archivo .env con el mismo
nombre en MAYÚSCULAS (ver .env.example).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# =============================================================================
#  MODO PRUEBAS (PAPER TRADING) — FLAG GLOBAL
# -----------------------------------------------------------------------------
#  True  -> NUNCA se envía una orden real. Las compras/ventas se simulan con
#           precios reales de mercado (aplicando comisiones y slippage) y se
#           registran en logs/paper_trades.log y logs/paper_trades.csv.
#  False -> Se envían órdenes al broker. Por seguridad hace falta ADEMÁS:
#           LIVE_TRADING_CONFIRMATION=ACEPTO_EL_RIESGO en el .env, y mientras
#           ALPACA_PAPER / CRYPTO_SANDBOX sigan en true, las órdenes van a los
#           entornos de pruebas del broker (Alpaca Paper / Binance Testnet).
# =============================================================================
PAPER_TRADING = True

LIVE_CONFIRMATION_PHRASE = "ACEPTO_EL_RIESGO"

# Límite DURO de tamaño de posición (5 % del saldo). El .env puede bajarlo,
# nunca subirlo: el gestor de riesgo lo vuelve a aplicar por si acaso.
HARD_MAX_POSITION_PCT = 0.05

BASE_DIR = Path(__file__).resolve().parent

STOCKS = "stocks"
CRYPTO = "crypto"
MACRO = "macro"  # Categoría de noticias generales (afecta a ambos mercados)


class ConfigError(ValueError):
    """Valor inválido en la configuración (.env)."""


# Temporalidades soportadas por los tres proveedores de velas
TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def timeframe_to_minutes(timeframe: str) -> int:
    try:
        return TIMEFRAME_MINUTES[timeframe]
    except KeyError as exc:
        raise ConfigError(
            f"BAR_TIMEFRAME={timeframe!r} no soportado. Usa uno de: {', '.join(TIMEFRAME_MINUTES)}"
        ) from exc


# -----------------------------------------------------------------------------
# Lectura tipada de variables de entorno
# -----------------------------------------------------------------------------
def _raw(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def env_str(name: str, default: str = "") -> str:
    value = _raw(name)
    return default if value is None else value


def env_bool(name: str, default: bool) -> bool:
    value = _raw(name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name}={value!r} no es un booleano válido (usa true/false)")


def env_float(name: str, default: float, min_value: float | None = None,
              max_value: float | None = None) -> float:
    value = _raw(name)
    try:
        result = default if value is None else float(value)
    except ValueError as exc:
        raise ConfigError(f"{name}={value!r} no es un número válido") from exc
    if min_value is not None and result < min_value:
        raise ConfigError(f"{name}={result} debe ser >= {min_value}")
    if max_value is not None and result > max_value:
        raise ConfigError(f"{name}={result} debe ser <= {max_value}")
    return result


def env_int(name: str, default: int, min_value: int | None = None,
            max_value: int | None = None) -> int:
    return int(env_float(name, default, min_value, max_value))


def env_list(name: str, default: list[str]) -> list[str]:
    value = _raw(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


# -----------------------------------------------------------------------------
# Universo de activos y palabras clave para asociar noticias a cada símbolo
# -----------------------------------------------------------------------------
# Las palabras clave se buscan sin distinguir mayúsculas y respetando límites
# de palabra ("sol" no casa con "solution"). Los tickers (AAPL, BTC...) se
# buscan en MAYÚSCULAS o como cashtag ($AAPL). Amplía este diccionario si
# añades símbolos nuevos a la watchlist.
DEFAULT_KEYWORDS: dict[str, list[str]] = {
    # Acciones
    "AAPL": ["apple", "iphone", "tim cook"],
    "MSFT": ["microsoft", "azure", "satya nadella"],
    "NVDA": ["nvidia", "jensen huang"],
    "TSLA": ["tesla", "cybertruck"],
    "AMZN": ["amazon", "aws"],
    "GOOGL": ["google", "alphabet"],
    "GOOG": ["google", "alphabet"],
    "META": ["meta platforms", "facebook", "instagram", "zuckerberg"],
    "AMD": ["advanced micro devices"],
    "NFLX": ["netflix"],
    "SPY": ["s&p 500", "wall street"],
    "QQQ": ["nasdaq 100", "nasdaq"],
    # Cripto (clave = activo base)
    "BTC": ["bitcoin"],
    "ETH": ["ethereum", "ether"],
    "SOL": ["solana"],
    "XRP": ["ripple"],
    "ADA": ["cardano"],
    "DOGE": ["dogecoin"],
    "BNB": ["binance coin"],
    "AVAX": ["avalanche"],
    "LINK": ["chainlink"],
    "DOT": ["polkadot"],
}

# Feeds RSS por defecto: (url, categoría). Categorías: stocks | crypto | macro.
# Para acciones se añaden además automáticamente los feeds de Yahoo Finance
# por ticker. Puedes sustituir la lista con RSS_FEEDS en el .env.
DEFAULT_RSS_FEEDS: list[tuple[str, str]] = [
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", MACRO),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html", STOCKS),
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories", MACRO),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", CRYPTO),
    ("https://cointelegraph.com/rss", CRYPTO),
    ("https://decrypt.co/feed", CRYPTO),
]


@dataclass(frozen=True)
class Instrument:
    """Activo de la watchlist."""

    symbol: str                       # "AAPL" o "BTC/USDT" (formato ccxt)
    asset_class: str                  # STOCKS | CRYPTO
    keywords: tuple[str, ...] = ()    # nombres a buscar en titulares
    tickers: tuple[str, ...] = ()     # tickers que usan los proveedores

    @property
    def base(self) -> str:
        """Activo base: 'BTC' para 'BTC/USDT', el propio ticker en acciones."""
        return self.symbol.split("/")[0].upper()

    @property
    def quote_currency(self) -> str:
        return self.symbol.split("/")[1].upper() if "/" in self.symbol else "USD"


def build_instruments(stock_symbols: list[str], crypto_symbols: list[str]) -> list[Instrument]:
    instruments: list[Instrument] = []
    for raw in stock_symbols:
        symbol = raw.upper()
        instruments.append(Instrument(
            symbol=symbol,
            asset_class=STOCKS,
            keywords=tuple(DEFAULT_KEYWORDS.get(symbol, [])),
            tickers=(symbol,),
        ))
    for raw in crypto_symbols:
        symbol = raw.upper()
        if "/" not in symbol:
            raise ConfigError(f"Símbolo cripto {raw!r} inválido: usa el formato BASE/QUOTE (ej. BTC/USDT)")
        base = symbol.split("/")[0]
        instruments.append(Instrument(
            symbol=symbol,
            asset_class=CRYPTO,
            keywords=tuple(DEFAULT_KEYWORDS.get(base, [])),
            # Cada proveedor etiqueta las cripto de forma distinta:
            # Alpaca -> BTCUSD, Alpha Vantage -> CRYPTO:BTC, Yahoo -> BTC-USD
            tickers=(base, f"{base}USD", f"{base}USDT", f"CRYPTO:{base}", f"{base}-USD"),
        ))
    return instruments


def _parse_rss_feeds(raw: str | None) -> list[tuple[str, str]]:
    """RSS_FEEDS=url|categoria,url|categoria (categoría opcional, por defecto macro)."""
    if not raw:
        return list(DEFAULT_RSS_FEEDS)
    feeds = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        url, _, category = item.partition("|")
        category = (category or MACRO).strip().lower()
        if category not in {STOCKS, CRYPTO, MACRO}:
            raise ConfigError(f"Categoría RSS inválida {category!r} en {item!r}")
        feeds.append((url.strip(), category))
    return feeds


# -----------------------------------------------------------------------------
# Bloques de configuración
# -----------------------------------------------------------------------------
@dataclass
class BrokerSettings:
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True          # True = endpoint paper-api de Alpaca
    alpaca_data_feed: str = "iex"      # iex (gratis) | sip (suscripción)
    alpaca_fractional: bool = True     # permite fracciones de acción
    crypto_exchange: str = "binance"   # binance | kraken
    crypto_api_key: str = ""
    crypto_api_secret: str = ""
    crypto_sandbox: bool = True        # True = Binance Testnet (solo modo real)


@dataclass
class NewsSettings:
    providers: list[str] = field(default_factory=lambda: ["rss", "alpaca", "newsapi", "alphavantage"])
    newsapi_key: str = ""
    alphavantage_key: str = ""
    rss_feeds: list[tuple[str, str]] = field(default_factory=lambda: list(DEFAULT_RSS_FEEDS))
    yahoo_ticker_feeds: bool = True
    # Frecuencia de consulta por proveedor (respetando los límites gratuitos:
    # NewsAPI 100 req/día, Alpha Vantage 25 req/día)
    rss_poll_seconds: int = 180
    alpaca_poll_seconds: int = 120
    newsapi_poll_seconds: int = 900
    alphavantage_poll_seconds: int = 3600
    lookback_minutes: int = 240        # ventana de noticias consideradas
    half_life_minutes: float = 60.0    # vida media del peso de una noticia
    http_timeout: float = 10.0


@dataclass
class StrategySettings:
    timeframe: str = "5m"
    bars_lookback: int = 150
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_entry_min: float = 50.0        # momentum alcista...
    rsi_entry_max: float = 70.0        # ...pero sin sobrecompra
    atr_period: int = 14
    vwap_window: int = 48
    volume_window: int = 20
    min_volume_ratio: float = 1.0
    entry_score: float = 25.0          # Score de Trading mínimo para comprar
    exit_score: float = -20.0          # Score que fuerza la salida
    min_articles: int = 2              # noticias mínimas para confiar
    full_confidence_articles: float = 3.0
    news_freshness_minutes: int = 90   # exige al menos una noticia reciente
    market_risk_off_score: float = -30.0


@dataclass
class RiskSettings:
    max_position_pct: float = 0.05         # máx. 5 % del saldo por operación
    max_risk_per_trade_pct: float = 0.01   # máx. 1 % del capital en riesgo
    stop_loss_pct: float = 0.01            # stop máximo: 1 % desde la entrada
    min_stop_pct: float = 0.005            # stop mínimo (evita saltar por ruido)
    atr_stop_multiplier: float = 2.0       # stop dinámico = 2 x ATR
    take_profit_rr: float = 1.5            # TP = 1.5 x distancia del stop
    trailing_activation_r: float = 1.0     # activa trailing con +1R de beneficio
    trailing_distance_r: float = 0.75      # el trailing persigue a 0.75R
    max_open_positions: int = 3
    max_total_exposure_pct: float = 0.15
    max_daily_loss_pct: float = 0.02       # kill switch diario
    max_trades_per_day: int = 20
    max_consecutive_losses: int = 3
    pause_after_losses_minutes: int = 60
    symbol_cooldown_minutes: int = 15
    max_holding_minutes: int = 180
    max_spread_pct: float = 0.002
    fee_pct_stocks: float = 0.0
    fee_pct_crypto: float = 0.001
    slippage_pct: float = 0.0005
    min_edge_cost_multiple: float = 2.0    # TP >= 2 x costes de ida y vuelta
    flatten_minutes_before_close: int = 10
    no_entries_minutes_before_close: int = 30
    pdt_protection: bool = True
    kill_switch_flatten: bool = True
    daily_reset_tz: str = "UTC"

    def fee_pct(self, asset_class: str) -> float:
        return self.fee_pct_crypto if asset_class == CRYPTO else self.fee_pct_stocks


@dataclass
class PaperSettings:
    initial_cash_stocks: float = 10_000.0
    initial_cash_crypto: float = 10_000.0


@dataclass
class Settings:
    paper_trading: bool = PAPER_TRADING
    live_confirmation: str = ""
    loop_interval_seconds: int = 30
    heartbeat_every_cycles: int = 10
    log_level: str = "INFO"
    instruments: list[Instrument] = field(default_factory=list)
    broker: BrokerSettings = field(default_factory=BrokerSettings)
    news: NewsSettings = field(default_factory=NewsSettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    paper: PaperSettings = field(default_factory=PaperSettings)
    log_dir: Path = BASE_DIR / "logs"
    state_dir: Path = BASE_DIR / "state"

    @property
    def stock_instruments(self) -> list[Instrument]:
        return [i for i in self.instruments if i.asset_class == STOCKS]

    @property
    def crypto_instruments(self) -> list[Instrument]:
        return [i for i in self.instruments if i.asset_class == CRYPTO]


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Carga el .env y construye la configuración validada."""
    load_dotenv(env_file or BASE_DIR / ".env", override=False)

    broker = BrokerSettings(
        alpaca_api_key=env_str("ALPACA_API_KEY"),
        alpaca_secret_key=env_str("ALPACA_SECRET_KEY"),
        alpaca_paper=env_bool("ALPACA_PAPER", True),
        alpaca_data_feed=env_str("ALPACA_DATA_FEED", "iex").lower(),
        alpaca_fractional=env_bool("ALPACA_FRACTIONAL", True),
        crypto_exchange=env_str("CRYPTO_EXCHANGE", "binance").lower(),
        crypto_api_key=env_str("CRYPTO_API_KEY"),
        crypto_api_secret=env_str("CRYPTO_API_SECRET"),
        crypto_sandbox=env_bool("CRYPTO_SANDBOX", True),
    )
    if broker.crypto_exchange not in {"binance", "kraken"}:
        raise ConfigError("CRYPTO_EXCHANGE debe ser 'binance' o 'kraken'")

    news = NewsSettings(
        providers=[p.lower() for p in env_list("NEWS_PROVIDERS", ["rss", "alpaca", "newsapi", "alphavantage"])],
        newsapi_key=env_str("NEWSAPI_KEY"),
        alphavantage_key=env_str("ALPHAVANTAGE_KEY"),
        rss_feeds=_parse_rss_feeds(_raw("RSS_FEEDS")),
        yahoo_ticker_feeds=env_bool("YAHOO_TICKER_FEEDS", True),
        rss_poll_seconds=env_int("RSS_POLL_SECONDS", 180, 30),
        alpaca_poll_seconds=env_int("ALPACA_NEWS_POLL_SECONDS", 120, 30),
        newsapi_poll_seconds=env_int("NEWSAPI_POLL_SECONDS", 900, 60),
        alphavantage_poll_seconds=env_int("ALPHAVANTAGE_POLL_SECONDS", 3600, 60),
        lookback_minutes=env_int("NEWS_LOOKBACK_MINUTES", 240, 15),
        half_life_minutes=env_float("SENTIMENT_HALF_LIFE_MINUTES", 60.0, 1.0),
        http_timeout=env_float("HTTP_TIMEOUT_SECONDS", 10.0, 1.0, 60.0),
    )

    strategy = StrategySettings(
        timeframe=env_str("BAR_TIMEFRAME", "5m"),
        bars_lookback=env_int("BARS_LOOKBACK", 150, 50, 1000),
        ema_fast=env_int("EMA_FAST", 9, 2),
        ema_slow=env_int("EMA_SLOW", 21, 3),
        rsi_period=env_int("RSI_PERIOD", 14, 2),
        rsi_entry_min=env_float("RSI_ENTRY_MIN", 50.0, 0, 100),
        rsi_entry_max=env_float("RSI_ENTRY_MAX", 70.0, 0, 100),
        atr_period=env_int("ATR_PERIOD", 14, 2),
        vwap_window=env_int("VWAP_WINDOW", 48, 5),
        volume_window=env_int("VOLUME_WINDOW", 20, 5),
        min_volume_ratio=env_float("MIN_VOLUME_RATIO", 1.0, 0.0),
        entry_score=env_float("ENTRY_SCORE", 25.0, 0, 100),
        exit_score=env_float("EXIT_SCORE", -20.0, -100, 0),
        min_articles=env_int("MIN_ARTICLES", 2, 1),
        full_confidence_articles=env_float("FULL_CONFIDENCE_ARTICLES", 3.0, 1.0),
        news_freshness_minutes=env_int("NEWS_FRESHNESS_MINUTES", 90, 5),
        market_risk_off_score=env_float("MARKET_RISK_OFF_SCORE", -30.0, -100, 0),
    )
    timeframe_to_minutes(strategy.timeframe)  # valida la temporalidad
    if strategy.ema_fast >= strategy.ema_slow:
        raise ConfigError("EMA_FAST debe ser menor que EMA_SLOW")
    if strategy.rsi_entry_min >= strategy.rsi_entry_max:
        raise ConfigError("RSI_ENTRY_MIN debe ser menor que RSI_ENTRY_MAX")
    # Velas necesarias para que los indicadores estén "calientes" (ver strategy.min_bars)
    needed = max(2 * strategy.ema_slow, 2 * strategy.rsi_period, 2 * strategy.atr_period,
                 strategy.vwap_window, strategy.volume_window + 1) + 1
    if strategy.bars_lookback < needed:
        raise ConfigError(f"BARS_LOOKBACK={strategy.bars_lookback} es insuficiente: "
                          f"los indicadores configurados necesitan al menos {needed} velas")

    risk = RiskSettings(
        max_position_pct=env_float("MAX_POSITION_PCT", 0.05, 0.001, 1.0),
        max_risk_per_trade_pct=env_float("MAX_RISK_PER_TRADE_PCT", 0.01, 0.0005, 0.05),
        stop_loss_pct=env_float("STOP_LOSS_PCT", 0.01, 0.001, 0.10),
        min_stop_pct=env_float("MIN_STOP_PCT", 0.005, 0.0005, 0.10),
        atr_stop_multiplier=env_float("ATR_STOP_MULTIPLIER", 2.0, 0.1, 10),
        take_profit_rr=env_float("TAKE_PROFIT_RR", 1.5, 0.0, 10),
        trailing_activation_r=env_float("TRAILING_ACTIVATION_R", 1.0, 0.0, 10),
        trailing_distance_r=env_float("TRAILING_DISTANCE_R", 0.75, 0.05, 10),
        max_open_positions=env_int("MAX_OPEN_POSITIONS", 3, 1, 50),
        max_total_exposure_pct=env_float("MAX_TOTAL_EXPOSURE_PCT", 0.15, 0.001, 1.0),
        max_daily_loss_pct=env_float("MAX_DAILY_LOSS_PCT", 0.02, 0.001, 0.5),
        max_trades_per_day=env_int("MAX_TRADES_PER_DAY", 20, 1),
        max_consecutive_losses=env_int("MAX_CONSECUTIVE_LOSSES", 3, 1),
        pause_after_losses_minutes=env_int("PAUSE_AFTER_LOSSES_MINUTES", 60, 0),
        symbol_cooldown_minutes=env_int("SYMBOL_COOLDOWN_MINUTES", 15, 0),
        max_holding_minutes=env_int("MAX_HOLDING_MINUTES", 180, 1),
        max_spread_pct=env_float("MAX_SPREAD_PCT", 0.002, 0.0, 0.05),
        fee_pct_stocks=env_float("FEE_PCT_STOCKS", 0.0, 0.0, 0.01),
        fee_pct_crypto=env_float("FEE_PCT_CRYPTO", 0.001, 0.0, 0.01),
        slippage_pct=env_float("SLIPPAGE_PCT", 0.0005, 0.0, 0.01),
        min_edge_cost_multiple=env_float("MIN_EDGE_COST_MULTIPLE", 2.0, 0.0, 20),
        flatten_minutes_before_close=env_int("FLATTEN_MINUTES_BEFORE_CLOSE", 10, 0, 120),
        no_entries_minutes_before_close=env_int("NO_ENTRIES_MINUTES_BEFORE_CLOSE", 30, 0, 240),
        pdt_protection=env_bool("PDT_PROTECTION", True),
        kill_switch_flatten=env_bool("KILL_SWITCH_FLATTEN", True),
        daily_reset_tz=env_str("DAILY_RESET_TZ", "UTC"),
    )
    if risk.max_position_pct > HARD_MAX_POSITION_PCT:
        raise ConfigError(
            f"MAX_POSITION_PCT={risk.max_position_pct} supera el límite duro del "
            f"{HARD_MAX_POSITION_PCT:.0%} por operación"
        )
    if risk.min_stop_pct > risk.stop_loss_pct:
        raise ConfigError("MIN_STOP_PCT no puede ser mayor que STOP_LOSS_PCT")

    paper = PaperSettings(
        initial_cash_stocks=env_float("PAPER_INITIAL_CASH_STOCKS", 10_000.0, 1.0),
        initial_cash_crypto=env_float("PAPER_INITIAL_CASH_CRYPTO", 10_000.0, 1.0),
    )

    instruments = build_instruments(
        env_list("STOCK_SYMBOLS", ["AAPL", "MSFT", "NVDA", "TSLA"]),
        env_list("CRYPTO_SYMBOLS", ["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
    )
    if not instruments:
        raise ConfigError("La watchlist está vacía: define STOCK_SYMBOLS y/o CRYPTO_SYMBOLS")

    log_level = env_str("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigError("LOG_LEVEL debe ser DEBUG, INFO, WARNING o ERROR")

    return Settings(
        paper_trading=PAPER_TRADING,
        live_confirmation=env_str("LIVE_TRADING_CONFIRMATION"),
        loop_interval_seconds=env_int("LOOP_INTERVAL_SECONDS", 30, 5, 3600),
        heartbeat_every_cycles=env_int("HEARTBEAT_EVERY_CYCLES", 10, 1),
        log_level=log_level,
        instruments=instruments,
        broker=broker,
        news=news,
        strategy=strategy,
        risk=risk,
        paper=paper,
        log_dir=Path(env_str("LOG_DIR", str(BASE_DIR / "logs"))),
        state_dir=Path(env_str("STATE_DIR", str(BASE_DIR / "state"))),
    )
