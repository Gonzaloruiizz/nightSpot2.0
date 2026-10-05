import numpy as np
import pandas as pd
import pytest

from indicators import atr, ema, rolling_vwap, rsi, volume_ratio
from tests.conftest import make_bars


def test_rsi_extremes_and_flat():
    up = pd.Series(np.arange(1, 60, dtype=float))
    down = up[::-1].reset_index(drop=True)
    flat = pd.Series([10.0] * 60)
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    assert rsi(down).iloc[-1] == pytest.approx(0.0)
    assert rsi(flat).iloc[-1] == pytest.approx(50.0)


def test_rsi_is_bounded_and_warms_up():
    rng = np.random.default_rng(7)
    series = pd.Series(100 + rng.normal(0, 1, 500).cumsum())
    values = rsi(series, 14)
    assert values.iloc[:13].isna().all()
    assert values.dropna().between(0, 100).all()


def test_rsi_zigzag_stays_in_momentum_zone():
    bars = make_bars(200, up=1.0, down=0.6)
    # RS medio = 1.0 / 0.6 -> RSI en torno a 62.5 (oscila según acabe en subida o bajada)
    assert 55 < rsi(bars["close"]).iloc[-1] < 68


def test_atr_constant_range():
    idx = pd.date_range("2026-01-01", periods=50, freq="5min", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx)
    assert atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_ema_trend_and_vwap():
    bars = make_bars(120)
    assert ema(bars["close"], 9).iloc[-1] > ema(bars["close"], 21).iloc[-1]
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    # Con volumen constante el VWAP es la media simple del precio típico
    assert rolling_vwap(bars, 20).iloc[-1] == pytest.approx(typical.tail(20).mean())


def test_vwap_without_volume_falls_back_to_mean():
    bars = make_bars(60, volume=0.0)
    assert not np.isnan(rolling_vwap(bars, 20).iloc[-1])


def test_volume_ratio_uses_previous_bars():
    volume = pd.Series([100.0] * 25 + [200.0])
    assert volume_ratio(volume, 20).iloc[-1] == pytest.approx(2.0)
