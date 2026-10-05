"""
strategy.py
===========
Estrategia "Sentiment Momentum" (solo largos):
las noticias son el CATALIZADOR y el análisis técnico la CONFIRMACIÓN.

ENTRADA — deben cumplirse todas:
  1. Score de Trading >= ENTRY_SCORE con al menos MIN_ARTICLES noticias.
  2. Hay una noticia fresca (< NEWS_FRESHNESS_MINUTES) y es posterior al
     catalizador de la última entrada (no se opera dos veces la misma noticia).
  3. El sentimiento general del mercado no está en "risk-off".
  4. EMA rápida > EMA lenta            -> tendencia alcista de corto plazo.
  5. Precio > VWAP                     -> los compradores dominan.
  6. RSI dentro de [RSI_ENTRY_MIN, RSI_ENTRY_MAX] -> momentum sin sobrecompra.
  7. Volumen >= media * MIN_VOLUME_RATIO -> el movimiento tiene participación.

SALIDA anticipada (además del SL / TP / trailing del gestor de riesgo):
  - El Score de Trading cae a EXIT_SCORE o menos (las noticias se giran).
  - Tendencia rota: EMA rápida < EMA lenta Y precio < VWAP.

Por qué solo largos: vender en corto exige margen (acciones) o derivados
(cripto) y tiene pérdida teórica ilimitada; no encaja con un enfoque
conservador. El sentimiento negativo se usa como veto y como señal de salida.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd

from config import StrategySettings, timeframe_to_minutes
from indicators import add_indicators
from sentiment import SentimentResult

logger = logging.getLogger("strategy")

_REQUIRED = ("close", "ema_fast", "ema_slow", "rsi", "atr", "vwap")


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    action: Action
    symbol: str
    reason: str
    price: float | None = None
    atr: float | None = None
    checks: dict[str, bool] = field(default_factory=dict)


class SentimentMomentumStrategy:
    def __init__(self, cfg: StrategySettings):
        self.cfg = cfg
        self.timeframe = pd.Timedelta(minutes=timeframe_to_minutes(cfg.timeframe))

    @property
    def min_bars(self) -> int:
        """Velas necesarias para que todos los indicadores estén 'calientes'."""
        c = self.cfg
        return max(c.ema_slow * 2, c.rsi_period * 2, c.atr_period * 2,
                   c.vwap_window, c.volume_window + 1) + 1

    # --- filtros de sentimiento (no requieren llamadas a la API) -------------
    def sentiment_gate(self, sentiment: SentimentResult, market: SentimentResult | None,
                       now: datetime, last_catalyst: datetime | None = None) -> tuple[bool, str]:
        c = self.cfg
        if sentiment.n_articles < c.min_articles:
            return False, f"pocas noticias ({sentiment.n_articles}/{c.min_articles})"
        if sentiment.trading_score < c.entry_score:
            return False, f"score {sentiment.trading_score:+.0f} < {c.entry_score:+.0f}"
        latest = sentiment.latest_published
        if latest is None or now - latest > timedelta(minutes=c.news_freshness_minutes):
            return False, f"ninguna noticia en los últimos {c.news_freshness_minutes} min"
        if last_catalyst is not None and latest <= last_catalyst:
            return False, "catalizador ya operado (no hay noticias nuevas desde la última entrada)"
        if market is not None and market.n_articles and market.trading_score <= c.market_risk_off_score:
            return False, f"mercado en risk-off (score mercado {market.trading_score:+.0f})"
        return True, "ok"

    # --- datos técnicos --------------------------------------------------------
    def prepare(self, bars: pd.DataFrame | None, now: datetime) -> pd.DataFrame | None:
        """
        Calcula indicadores SOLO sobre velas cerradas: usar la vela en curso
        haría que la señal "parpadee" (repainting) y falsearía cualquier backtest.
        Devuelve None si faltan datos o si están desactualizados (feed caído).
        """
        if bars is None or bars.empty:
            return None
        now_ts = pd.Timestamp(now)
        closed = bars[bars.index + self.timeframe <= now_ts]
        if len(closed) < self.min_bars:
            return None
        last_close_time = closed.index[-1] + self.timeframe
        if now_ts - last_close_time > self.timeframe * 3:
            return None
        c = self.cfg
        df = add_indicators(closed, ema_fast=c.ema_fast, ema_slow=c.ema_slow,
                            rsi_period=c.rsi_period, atr_period=c.atr_period,
                            vwap_window=c.vwap_window, volume_window=c.volume_window)
        if df[list(_REQUIRED)].iloc[-1].isna().any():
            return None
        return df

    def _technical_checks(self, last: pd.Series) -> dict[str, bool]:
        c = self.cfg
        vol_ok = c.min_volume_ratio <= 0 or (pd.notna(last["vol_ratio"])
                                             and last["vol_ratio"] >= c.min_volume_ratio)
        return {
            f"EMA{c.ema_fast}>EMA{c.ema_slow}": bool(last["ema_fast"] > last["ema_slow"]),
            "precio>VWAP": bool(last["close"] > last["vwap"]),
            f"RSI∈[{c.rsi_entry_min:.0f},{c.rsi_entry_max:.0f}]":
                bool(c.rsi_entry_min <= last["rsi"] <= c.rsi_entry_max),
            f"volumen≥{c.min_volume_ratio:g}x": bool(vol_ok),
        }

    @staticmethod
    def _describe(last: pd.Series) -> str:
        vol = f"{last['vol_ratio']:.1f}x" if pd.notna(last["vol_ratio"]) else "n/d"
        return (f"close={last['close']:.6g} EMAf={last['ema_fast']:.6g} EMAs={last['ema_slow']:.6g} "
                f"VWAP={last['vwap']:.6g} RSI={last['rsi']:.0f} vol={vol}")

    # --- señales ---------------------------------------------------------------
    def evaluate_entry(self, symbol: str, bars: pd.DataFrame | None, sentiment: SentimentResult,
                       market: SentimentResult | None, now: datetime,
                       last_catalyst: datetime | None = None) -> Signal:
        ok, why = self.sentiment_gate(sentiment, market, now, last_catalyst)
        if not ok:
            return Signal(Action.HOLD, symbol, why)
        df = self.prepare(bars, now)
        if df is None:
            return Signal(Action.HOLD, symbol, "velas insuficientes o desactualizadas")
        last = df.iloc[-1]
        checks = self._technical_checks(last)
        technical = self._describe(last)
        if all(checks.values()):
            return Signal(Action.BUY, symbol, f"{sentiment.describe()} | {technical}",
                          price=float(last["close"]), atr=float(last["atr"]), checks=checks)
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        return Signal(Action.HOLD, symbol,
                      f"{sentiment.describe()} pero el técnico no confirma ({failed}) | {technical}",
                      price=float(last["close"]), atr=float(last["atr"]), checks=checks)

    def evaluate_exit(self, symbol: str, bars: pd.DataFrame | None, sentiment: SentimentResult,
                      now: datetime) -> Signal:
        if sentiment.n_articles and sentiment.trading_score <= self.cfg.exit_score:
            return Signal(Action.SELL, symbol, f"sentimiento girado a negativo: {sentiment.describe()}")
        df = self.prepare(bars, now)
        if df is not None:
            last = df.iloc[-1]
            if last["ema_fast"] < last["ema_slow"] and last["close"] < last["vwap"]:
                return Signal(Action.SELL, symbol, f"tendencia rota | {self._describe(last)}",
                              price=float(last["close"]))
        return Signal(Action.HOLD, symbol, "mantener")
