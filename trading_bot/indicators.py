"""
indicators.py
=============
Indicadores técnicos implementados con pandas puro (sin TA-Lib), para no
depender de librerías con compilación nativa difícil de instalar en un VPS.

Todas las funciones reciben un DataFrame OHLCV con columnas
open, high, low, close, volume e índice temporal ascendente.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Media móvil exponencial."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI con el suavizado de Wilder (equivalente a una EMA con alpha = 1/period),
    que es el que usan TradingView y la mayoría de plataformas.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # Sin pérdidas en la ventana -> RSI = 100; sin movimiento -> 50
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return out.where(avg_gain.notna())


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (Wilder). Mide la volatilidad "normal" de una vela y se
    usa para colocar el stop dinámico fuera del ruido del mercado.
    """
    prev_close = df["close"].shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rolling_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    """
    VWAP móvil (precio medio ponderado por volumen de las últimas `window`
    velas). Se usa uno móvil en vez del de sesión para tratar igual acciones
    y cripto (que no tienen apertura/cierre diario).
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (typical * df["volume"]).rolling(window, min_periods=window).sum()
    vol = df["volume"].rolling(window, min_periods=window).sum()
    vwap = pv / vol.replace(0.0, np.nan)
    # Sin volumen (feed sin datos de volumen) -> media simple del precio típico
    return vwap.fillna(typical.rolling(window, min_periods=window).mean())


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Volumen de la vela / media de las `window` velas ANTERIORES."""
    baseline = volume.shift(1).rolling(window, min_periods=window).mean()
    return volume / baseline.replace(0.0, np.nan)


def add_indicators(df: pd.DataFrame, *, ema_fast: int, ema_slow: int, rsi_period: int,
                   atr_period: int, vwap_window: int, volume_window: int) -> pd.DataFrame:
    """Devuelve una COPIA del DataFrame con todas las columnas de indicadores."""
    out = df.copy()
    out["ema_fast"] = ema(out["close"], ema_fast)
    out["ema_slow"] = ema(out["close"], ema_slow)
    out["rsi"] = rsi(out["close"], rsi_period)
    out["atr"] = atr(out, atr_period)
    out["vwap"] = rolling_vwap(out, vwap_window)
    out["vol_ratio"] = volume_ratio(out["volume"], volume_window)
    return out
