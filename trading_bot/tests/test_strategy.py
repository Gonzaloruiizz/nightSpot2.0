from dataclasses import replace
from datetime import timedelta

import pytest

from sentiment import SentimentResult
from strategy import Action, SentimentMomentumStrategy
from tests.conftest import NOW, make_bars


def bullish(score=45.0, n=3, minutes_ago=5) -> SentimentResult:
    return SentimentResult(symbol="X", score=0.6, trading_score=score, label="Positivo", n_articles=n,
                           confidence=0.8, latest_published=NOW - timedelta(minutes=minutes_ago))


@pytest.fixture
def strategy(strategy_cfg):
    return SentimentMomentumStrategy(strategy_cfg)


def test_buy_when_sentiment_and_technicals_agree(strategy):
    signal = strategy.evaluate_entry("X", make_bars(), bullish(), None, NOW)
    assert signal.action == Action.BUY, signal.reason
    assert signal.atr and signal.atr > 0
    assert all(signal.checks.values())


@pytest.mark.parametrize("sentiment, fragment", [
    (bullish(score=10), "score"),
    (bullish(n=1), "pocas noticias"),
    (bullish(minutes_ago=200), "ninguna noticia"),
])
def test_sentiment_gate_blocks(strategy, sentiment, fragment):
    signal = strategy.evaluate_entry("X", make_bars(), sentiment, None, NOW)
    assert signal.action == Action.HOLD and fragment in signal.reason


def test_same_catalyst_is_not_traded_twice(strategy):
    s = bullish()
    signal = strategy.evaluate_entry("X", make_bars(), s, None, NOW, last_catalyst=s.latest_published)
    assert signal.action == Action.HOLD and "catalizador" in signal.reason


def test_market_risk_off_vetoes_entries(strategy):
    market = SentimentResult(symbol="M", trading_score=-50, n_articles=10)
    signal = strategy.evaluate_entry("X", make_bars(), bullish(), market, NOW)
    assert signal.action == Action.HOLD and "risk-off" in signal.reason


def test_downtrend_is_not_confirmed(strategy):
    bars = make_bars(up=0.6, down=1.0)
    signal = strategy.evaluate_entry("X", bars, bullish(), None, NOW)
    assert signal.action == Action.HOLD and "técnico no confirma" in signal.reason


def test_overbought_is_not_bought(strategy):
    bars = make_bars(up=1.0, down=0.05)  # RSI ~ 95
    signal = strategy.evaluate_entry("X", bars, bullish(), None, NOW)
    assert signal.action == Action.HOLD and "RSI" in signal.reason


def test_in_progress_bar_is_ignored(strategy):
    """La vela en curso no debe influir: cambiarla no altera la señal."""
    bars = make_bars(include_open_bar=True)
    base = strategy.prepare(bars, NOW)
    bars.iloc[-1, bars.columns.get_loc("close")] = 1.0  # vela en curso absurda
    again = strategy.prepare(bars, NOW)
    assert again["close"].iloc[-1] == base["close"].iloc[-1]
    assert again.index[-1] < bars.index[-1]


def test_stale_or_short_data_returns_hold(strategy):
    stale = make_bars(end=NOW - timedelta(hours=2))
    assert strategy.evaluate_entry("X", stale, bullish(), None, NOW).action == Action.HOLD
    assert strategy.prepare(make_bars(20), NOW) is None


def test_volume_filter(strategy_cfg):
    strategy = SentimentMomentumStrategy(replace(strategy_cfg, min_volume_ratio=1.5))
    signal = strategy.evaluate_entry("X", make_bars(), bullish(), None, NOW)
    assert signal.action == Action.HOLD and "volumen" in signal.reason


def test_exit_on_negative_sentiment(strategy):
    negative = SentimentResult(symbol="X", trading_score=-35, n_articles=3)
    assert strategy.evaluate_exit("X", make_bars(), negative, NOW).action == Action.SELL


def test_exit_on_broken_trend(strategy):
    neutral = SentimentResult(symbol="X")
    assert strategy.evaluate_exit("X", make_bars(up=0.6, down=1.0), neutral, NOW).action == Action.SELL
    assert strategy.evaluate_exit("X", make_bars(), neutral, NOW).action == Action.HOLD
