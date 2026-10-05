"""Utilidades compartidas por los tests: datos sintéticos y brokers falsos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from api_handler import AccountInfo, BaseBroker, BrokerError, OrderResult, Quote
from config import CRYPTO, RiskSettings, StrategySettings
from news_handler import NewsArticle, NewsProvider

NOW = datetime(2026, 10, 5, 14, 2, 30, tzinfo=timezone.utc)


def make_bars(n: int = 120, *, end: datetime = NOW, start_price: float = 100.0, up: float = 1.0,
              down: float = 0.6, timeframe_min: int = 5, volume: float = 1_000.0,
              include_open_bar: bool = True) -> pd.DataFrame:
    """
    Velas en zigzag: sube `up`, baja `down`, alternando. Con up > down es una
    tendencia alcista con RSI ~ 100*up/(up+down) (62.5 por defecto), lo que
    permite probar la estrategia sin aleatoriedad.
    """
    tf = pd.Timedelta(minutes=timeframe_min)
    current_bar = pd.Timestamp(end).floor(tf)
    count = n if include_open_bar else n - 1
    last_open = current_bar if include_open_bar else current_bar - tf
    index = pd.date_range(end=last_open, periods=count, freq=tf, tz="UTC")
    closes, price = [], start_price
    for i in range(count):
        price += up if i % 2 == 0 else -down
        closes.append(price)
    close = pd.Series(closes, index=index)
    open_ = close.shift(1).fillna(start_price)
    df = pd.DataFrame({
        "open": open_,
        "high": pd.concat([open_, close], axis=1).max(axis=1) + 0.2,
        "low": pd.concat([open_, close], axis=1).min(axis=1) - 0.2,
        "close": close,
        "volume": volume,
    })
    return df


class FakeDataBroker(BaseBroker):
    """Broker de datos controlable. Enviarle una orden es un fallo del test."""

    name = "fake"

    def __init__(self, asset_class: str = CRYPTO, bars: pd.DataFrame | None = None,
                 price: float = 100.0, spread: float = 0.02):
        super().__init__(asset_class)
        self.bars = bars if bars is not None else make_bars()
        self.price = price
        self.spread = spread
        self.market_open = True
        self.close_in_minutes: float | None = None
        self.fail_quotes = False

    def get_bars(self, symbol, timeframe, limit):
        return self.bars.tail(limit)

    def get_quote(self, symbol):
        if self.fail_quotes:
            raise BrokerError("red caída (simulada)")
        half = self.spread / 2
        return Quote(symbol, self.price - half, self.price + half, self.price)

    def get_account(self):
        return AccountInfo(equity=0.0, cash=0.0)

    def get_positions(self):
        return {}

    def submit_market_order(self, symbol, side, qty, client_order_id=None) -> OrderResult:
        raise AssertionError("¡El broker REAL nunca debe recibir órdenes en modo paper!")

    def normalize_qty(self, symbol, qty):
        return float(int(qty * 1e6) / 1e6)

    def min_order_notional(self, symbol):
        return 5.0

    def is_market_open(self):
        return self.market_open

    def minutes_to_close(self):
        return self.close_in_minutes


class StaticNewsProvider(NewsProvider):
    name = "static"

    def __init__(self, articles: list[NewsArticle] | None = None, fail: bool = False,
                 poll_seconds: int = 60):
        super().__init__(session=None, timeout=1, poll_seconds=poll_seconds)
        self.articles = articles or []
        self.fail = fail
        self.calls = 0

    def fetch(self, since):
        self.calls += 1
        if self.fail:
            raise RuntimeError("proveedor caído (simulado)")
        return [a for a in self.articles if a.published_at >= since]


def article(title: str, minutes_ago: float = 5, *, now: datetime = NOW, provider: str = "static",
            summary: str = "", tickers: frozenset[str] = frozenset(), category: str = "") -> NewsArticle:
    return NewsArticle(title=title, summary=summary, published_at=now - timedelta(minutes=minutes_ago),
                       provider=provider, tickers=tickers, category=category)


@pytest.fixture
def risk_cfg() -> RiskSettings:
    return RiskSettings()


@pytest.fixture
def strategy_cfg() -> StrategySettings:
    return StrategySettings()
