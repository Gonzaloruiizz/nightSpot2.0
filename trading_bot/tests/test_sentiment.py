from datetime import timedelta

import pytest

from sentiment import NEGATIVE, NEUTRAL, POSITIVE, SentimentAnalyzer
from tests.conftest import NOW, article


@pytest.fixture(scope="module")
def analyzer():
    return SentimentAnalyzer(half_life_minutes=60, full_confidence_articles=3)


@pytest.mark.parametrize("headline, expected", [
    ("Bitcoin surges to record high as ETF inflows jump", POSITIVE),
    ("Nvidia beats estimates, raises outlook", POSITIVE),
    ("Analyst upgrades AMD to outperform", POSITIVE),
    ("Apple shares plunge after earnings miss", NEGATIVE),
    ("Crypto exchange hacked, $200 million stolen", NEGATIVE),
    ("Tesla recalls 100,000 vehicles over safety issue", NEGATIVE),
    ("Microsoft to report earnings on Tuesday", NEUTRAL),
])
def test_finance_headlines(analyzer, headline, expected):
    assert analyzer.label(analyzer.score_text(headline)) == expected


def test_empty_aggregate_is_neutral(analyzer):
    result = analyzer.aggregate("BTC/USDT", [], NOW)
    assert result.trading_score == 0
    assert result.label == NEUTRAL
    assert result.n_articles == 0


def test_fresh_consistent_news_gives_high_score(analyzer):
    news = [(article("Bitcoin surges to record high", 5), 1.0),
            (article("Bitcoin rally extends as ETF inflows soar", 10), 1.0),
            (article("Analysts turn bullish on bitcoin", 15), 1.0)]
    result = analyzer.aggregate("BTC/USDT", news, NOW)
    assert result.trading_score > 40
    assert result.label == POSITIVE
    assert result.latest_published == NOW - timedelta(minutes=5)
    assert len(result.top_headlines) == 3


def test_time_decay_favours_recent_news(analyzer):
    news = [(article("Bitcoin surges to record high", 300), 1.0),   # hace 5 h
            (article("Bitcoin plunges after exchange hack", 2), 1.0)]
    assert analyzer.aggregate("BTC/USDT", news, NOW).score < 0


def test_disagreement_and_few_articles_reduce_confidence(analyzer):
    consistent = [(article(f"Bitcoin surges again {i}", 5), 1.0) for i in range(3)]
    mixed = [(article("Bitcoin surges", 5), 1.0), (article("Bitcoin plunges", 5), 1.0),
             (article("Bitcoin soars", 5), 1.0)]
    single = [(article("Bitcoin surges", 5), 1.0)]
    c = analyzer.aggregate("X", consistent, NOW).confidence
    assert analyzer.aggregate("X", mixed, NOW).confidence < c
    assert analyzer.aggregate("X", single, NOW).confidence < c


def test_relevance_weights_and_cache(analyzer):
    a = article("Bitcoin surges", 5)
    analyzer.aggregate("X", [(a, 0.5)], NOW)
    assert a.sentiment is not None  # se calcula una sola vez por noticia
    cached = a.sentiment
    a.title = "Bitcoin plunges"
    assert analyzer.score_article(a) == cached
