from datetime import timedelta
from email.utils import format_datetime

import pytest

from config import CRYPTO, STOCKS, NewsSettings, build_instruments
from news_handler import (
    AlphaVantageProvider,
    NewsAggregator,
    NewsAPIProvider,
    NewsProviderError,
    RSSProvider,
    SymbolMatcher,
    clean_text,
    redact,
)
from tests.conftest import NOW, StaticNewsProvider, article

INSTRUMENTS = build_instruments(["AAPL", "AMD", "T"], ["BTC/USDT", "SOL/USDT"])


class FakeResponse:
    def __init__(self, status=200, content=b"", payload=None):
        self.status_code = status
        self.content = content
        self.text = content.decode() if content else ""
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


# --- Asociación noticia -> símbolo ------------------------------------------------
@pytest.mark.parametrize("title, expected", [
    ("Solana surges after ETF approval", {"SOL/USDT"}),
    ("A new solution for payments", set()),              # 'sol' dentro de otra palabra
    ("AMD beats estimates", {"AMD"}),
    ("Investors amd traders react", set()),              # ticker en minúsculas: no
    ("Apple unveils new iPhone", {"AAPL"}),
    ("$T shares slide after guidance", {"T"}),           # ticker de 1 letra: solo cashtag
    ("T-Mobile and A new deal", set()),
    ("BTC and ETH rally", {"BTC/USDT"}),
])
def test_symbol_matching(title, expected):
    assert set(SymbolMatcher(INSTRUMENTS).match(article(title))) == expected


def test_relevance_levels():
    matcher = SymbolMatcher(INSTRUMENTS)
    assert matcher.match(article("Apple soars"))["AAPL"] == 1.0
    assert matcher.match(article("Tech wrap", tickers=frozenset({"AAPL"})))["AAPL"] == 0.6
    assert matcher.match(article("Tech wrap", summary="Apple and others"))["AAPL"] == 0.5
    assert matcher.match(article("Crypto wrap", tickers=frozenset({"CRYPTO:BTC"})))["BTC/USDT"] == 0.6


# --- Proveedores ---------------------------------------------------------------------
def rss_bytes(items):
    entries = "".join(
        f"<item><title>{t}</title><link>https://x/{i}</link>"
        + (f"<pubDate>{format_datetime(d)}</pubDate>" if d else "")
        + "<description>&lt;p&gt;Resumen &lt;b&gt;HTML&lt;/b&gt;&lt;/p&gt;</description></item>"
        for i, (t, d) in enumerate(items))
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>Feed</title>{entries}</channel></rss>".encode()


def test_rss_provider_parses_and_filters():
    content = rss_bytes([("Bitcoin surges", NOW - timedelta(minutes=5)),
                         ("Old news", NOW - timedelta(days=2)),
                         ("Undated news", None)])
    provider = RSSProvider([("https://feed", CRYPTO, frozenset())], session=FakeSession(FakeResponse(content=content)),
                           timeout=1, poll_seconds=60)
    articles = provider.fetch(NOW - timedelta(hours=4))
    assert [a.title for a in articles] == ["Bitcoin surges"]
    assert articles[0].summary == "Resumen HTML"
    assert articles[0].category == CRYPTO
    assert articles[0].published_at == NOW - timedelta(minutes=5)


def test_rss_all_feeds_down_raises():
    provider = RSSProvider([("https://feed", CRYPTO, frozenset())], session=FakeSession(FakeResponse(status=503)),
                           timeout=1, poll_seconds=60)
    with pytest.raises(NewsProviderError):
        provider.fetch(NOW)


def test_alpha_vantage_quota_message_raises():
    session = FakeSession(FakeResponse(payload={"Information": "rate limit apikey=SECRETO"}))
    provider = AlphaVantageProvider("SECRETO", session=session, timeout=1, poll_seconds=60)
    with pytest.raises(NewsProviderError) as err:
        provider.fetch(NOW)
    assert "SECRETO" not in str(err.value)


def test_alpha_vantage_parses_tickers():
    payload = {"feed": [{"title": "Apple beats", "time_published": "20261005T140000", "summary": "",
                         "ticker_sentiment": [{"ticker": "AAPL", "relevance_score": "0.9"},
                                              {"ticker": "MSFT", "relevance_score": "0.05"}]}]}
    provider = AlphaVantageProvider("k", session=FakeSession(FakeResponse(payload=payload)), timeout=1,
                                    poll_seconds=60)
    [a] = provider.fetch(NOW - timedelta(hours=1))
    assert a.tickers == frozenset({"AAPL"})


def test_newsapi_query_is_bounded():
    query = NewsAPIProvider._build_query(build_instruments(["AAPL"] * 1, ["BTC/USDT"]) * 50)
    assert 0 < len(query) <= NewsAPIProvider.MAX_QUERY_LEN
    assert '"tim cook"' in query


def test_text_helpers():
    assert clean_text("<p>Hola&nbsp;<b>mundo</b></p>") == "Hola mundo"
    assert redact("https://x/query?function=N&apikey=ABC123&x=1") == "https://x/query?function=N&apikey=***&x=1"


# --- Agregador ---------------------------------------------------------------------
def make_aggregator(*providers):
    return NewsAggregator(NewsSettings(lookback_minutes=240), INSTRUMENTS, providers=list(providers))


def test_aggregator_dedups_and_merges_tickers():
    a = StaticNewsProvider([article("Market wrap: stocks mixed", 5)])
    b = StaticNewsProvider([article("Market wrap: stocks mixed!", 6, tickers=frozenset({"AAPL"}))])
    b.name = "other"
    agg = make_aggregator(a, b)
    assert agg.refresh(NOW) == 1
    assert len(agg) == 1
    assert [x.title for x, _ in agg.articles_for("AAPL")] == ["Market wrap: stocks mixed"]


def test_aggregator_isolates_failing_provider_with_backoff():
    ok = StaticNewsProvider([article("Bitcoin surges", 5)], poll_seconds=60)
    broken = StaticNewsProvider(fail=True, poll_seconds=60)
    broken.name = "broken"
    agg = make_aggregator(ok, broken)
    assert agg.refresh(NOW) == 1
    agg.refresh(NOW + timedelta(seconds=90))       # 'ok' vuelve a consultarse; 'broken' en backoff
    assert ok.calls == 2 and broken.calls == 1
    agg.refresh(NOW + timedelta(seconds=121))      # backoff de 2 x 60 s cumplido
    assert broken.calls == 2


def test_aggregator_prunes_old_and_clamps_future():
    p = StaticNewsProvider([article("Bitcoin surges", 5), article("Apple soars", -60)])
    agg = make_aggregator(p)
    agg.refresh(NOW)
    future = [a for a, _ in agg.articles_for("AAPL")][0]
    assert future.published_at == NOW
    agg.refresh(NOW + timedelta(hours=5))
    assert len(agg) == 0


def test_market_articles_by_asset_class():
    p = StaticNewsProvider([article("Fed hikes rates", 5, category="macro"),
                            article("Solana soars", 5),
                            article("Apple soars", 5)])
    agg = make_aggregator(p)
    agg.refresh(NOW)
    crypto = {a.title for a, _ in agg.market_articles(CRYPTO)}
    stocks = {a.title for a, _ in agg.market_articles(STOCKS)}
    assert crypto == {"Fed hikes rates", "Solana soars"}
    assert stocks == {"Fed hikes rates", "Apple soars"}
