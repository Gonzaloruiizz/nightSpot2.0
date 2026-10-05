"""
news_handler.py
===============
Ingesta de noticias financieras desde varios proveedores y asociación de
cada noticia a los símbolos de la watchlist.

Proveedores soportados (se activan solos si tienen credenciales):
  - rss           Feeds RSS públicos (CNBC, MarketWatch, CoinDesk, Cointelegraph,
                  Decrypt y Yahoo Finance por ticker). No requiere clave.
  - alpaca        Alpaca News API (Benzinga, tiempo real). Usa las claves de Alpaca.
  - newsapi       NewsAPI.org (el plan gratuito tiene retardo y 100 req/día).
  - alphavantage  Alpha Vantage NEWS_SENTIMENT (plan gratuito: 25 req/día).

Cada proveedor se consulta con su propia frecuencia y, si falla, se aplica
un backoff exponencial SOLO a ese proveedor: la caída de una fuente nunca
detiene el bot.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import logging
import re
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests

from config import CRYPTO, MACRO, STOCKS, Instrument, NewsSettings
from utils import call_with_retry, utc_now

logger = logging.getLogger("news")

USER_AGENT = "Mozilla/5.0 (compatible; SentimentTradingBot/1.0)"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Relevancia de una noticia para un símbolo según dónde aparece
RELEVANCE_TITLE = 1.0       # nombrado en el titular
RELEVANCE_TAGGED = 0.6      # el proveedor lo etiqueta, pero no está en el titular
RELEVANCE_SUMMARY = 0.5     # solo aparece en el resumen


class NewsProviderError(Exception):
    """Error permanente o de cuota de un proveedor de noticias."""


class TransientNewsError(Exception):
    """Error de red/servidor que merece reintento."""


@dataclass
class NewsArticle:
    title: str
    published_at: datetime
    provider: str
    source: str = ""
    summary: str = ""
    url: str = ""
    category: str = ""                         # stocks | crypto | macro | "" (desconocida)
    tickers: frozenset[str] = frozenset()      # tickers etiquetados por el proveedor
    # --- Calculados al ingerir ---
    matches: dict[str, float] = field(default_factory=dict)  # símbolo -> relevancia
    asset_classes: frozenset[str] = frozenset()
    sentiment: float | None = None             # compound VADER (caché)

    @property
    def uid(self) -> str:
        """Identificador para deduplicar: el mismo titular en dos fuentes cuenta una vez."""
        return hashlib.sha1(_normalize_title(self.title).encode()).hexdigest()


# -----------------------------------------------------------------------------
# Utilidades de texto
# -----------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SECRET_RE = re.compile(r"(apikey|apiKey|api_key|token|key)=([^&\s'\"]+)")


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def clean_text(text: str | None) -> str:
    """Quita HTML y espacios sobrantes (los resúmenes RSS suelen traer HTML)."""
    if not text:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def redact(message: str) -> str:
    """Oculta claves API que puedan aparecer en mensajes de error (URLs con ?apikey=)."""
    return _SECRET_RE.sub(r"\1=***", message)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# -----------------------------------------------------------------------------
# Asociación noticia -> símbolo
# -----------------------------------------------------------------------------
class SymbolMatcher:
    """
    Decide a qué instrumentos se refiere una noticia:
      - nombres/palabras clave: sin distinguir mayúsculas y con límites de palabra
      - tickers en el texto: en MAYÚSCULAS (BTC, NVDA) o como cashtag ($AAPL).
        Los tickers de 1-2 letras solo se aceptan como cashtag para evitar
        falsos positivos ("A new...", "IT sector").
      - tickers estructurados que devuelven Alpaca / Alpha Vantage / Yahoo.
    """

    def __init__(self, instruments: list[Instrument]):
        self._entries: list[tuple[Instrument, re.Pattern | None, re.Pattern, frozenset[str]]] = []
        for inst in instruments:
            keyword_re = None
            if inst.keywords:
                alternatives = "|".join(re.escape(k) for k in inst.keywords)
                keyword_re = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)
            ticker = re.escape(inst.base)
            if len(inst.base) >= 3:
                ticker_re = re.compile(rf"(?<![\w$])\$?{ticker}(?!\w)")
            else:
                ticker_re = re.compile(rf"\${ticker}(?!\w)")
            provider_tickers = frozenset(t.upper() for t in inst.tickers)
            self._entries.append((inst, keyword_re, ticker_re, provider_tickers))

    @staticmethod
    def _mentions(text: str, keyword_re: re.Pattern | None, ticker_re: re.Pattern) -> bool:
        if not text:
            return False
        return bool((keyword_re and keyword_re.search(text)) or ticker_re.search(text))

    def match(self, article: NewsArticle) -> dict[str, float]:
        result: dict[str, float] = {}
        for inst, keyword_re, ticker_re, provider_tickers in self._entries:
            relevance = 0.0
            if self._mentions(article.title, keyword_re, ticker_re):
                relevance = RELEVANCE_TITLE
            elif article.tickers & provider_tickers:
                relevance = RELEVANCE_TAGGED
            elif self._mentions(article.summary, keyword_re, ticker_re):
                relevance = RELEVANCE_SUMMARY
            if relevance > 0:
                result[inst.symbol] = relevance
        return result


# -----------------------------------------------------------------------------
# Proveedores
# -----------------------------------------------------------------------------
def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, TransientNewsError)


class NewsProvider(ABC):
    name = "base"

    def __init__(self, session: requests.Session, timeout: float, poll_seconds: int):
        self.session = session
        self.timeout = timeout
        self.poll_seconds = poll_seconds

    @abstractmethod
    def fetch(self, since: datetime) -> list[NewsArticle]:
        """Devuelve las noticias publicadas desde `since`."""

    def _http_get(self, url: str, params: dict | None = None, headers: dict | None = None) -> requests.Response:
        """GET con reintentos en errores transitorios y mensajes sin claves API."""
        def do_request() -> requests.Response:
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                raise TransientNewsError(redact(f"{type(exc).__name__}: {exc}")) from None
            if response.status_code == 429 or response.status_code >= 500:
                raise TransientNewsError(f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise NewsProviderError(f"HTTP {response.status_code}: {redact(response.text[:200])}")
            return response

        return call_with_retry(do_request, is_transient=_is_transient, attempts=2,
                               base_delay=2.0, description=f"Noticias {self.name}")

    def _get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        response = self._http_get(url, params, headers)
        try:
            return response.json()
        except ValueError as exc:
            raise NewsProviderError(f"respuesta no JSON de {self.name}") from exc


class RSSProvider(NewsProvider):
    name = "rss"
    MAX_WORKERS = 8

    def __init__(self, feeds: list[tuple[str, str, frozenset[str]]], **kwargs):
        super().__init__(**kwargs)
        self.feeds = feeds  # (url, categoría, tickers asociados al feed)
        self._feed_failures: dict[str, int] = {}

    @staticmethod
    def _entry_datetime(entry: Any) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed:
            return None  # sin fecha no podemos saber si es reciente: se descarta
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)

    def _download(self, url: str) -> bytes | None:
        try:
            content = self._http_get(url).content
        except Exception as exc:  # noqa: BLE001 - un feed caído no afecta al resto
            count = self._feed_failures[url] = self._feed_failures.get(url, 0) + 1
            if count == 1 or count % 20 == 0:  # no inundar el log con un feed roto
                logger.warning("Feed RSS %s no disponible (%d fallos): %s",
                               urlparse(url).netloc, count, exc)
            return None
        self._feed_failures[url] = 0
        return content

    def fetch(self, since: datetime) -> list[NewsArticle]:
        # Descargas en paralelo: con 10+ feeds, hacerlo en serie podría tardar
        # minutos si varios servidores responden lento.
        with ThreadPoolExecutor(max_workers=min(self.MAX_WORKERS, max(1, len(self.feeds)))) as pool:
            contents = list(pool.map(self._download, [url for url, _, _ in self.feeds]))

        articles: list[NewsArticle] = []
        failures = 0
        for (url, category, tickers), content in zip(self.feeds, contents, strict=True):
            if content is None:
                failures += 1
                continue
            parsed = feedparser.parse(content)
            if parsed.bozo and not parsed.entries:
                logger.debug("Feed RSS %s mal formado: %s", url, parsed.get("bozo_exception"))
                continue
            source = clean_text(parsed.feed.get("title")) or urlparse(url).netloc
            for entry in parsed.entries:
                published = self._entry_datetime(entry)
                title = clean_text(entry.get("title"))
                if not title or published is None or published < since:
                    continue
                articles.append(NewsArticle(
                    title=title,
                    summary=clean_text(entry.get("summary"))[:600],
                    url=entry.get("link", ""),
                    published_at=published,
                    provider=self.name,
                    source=source,
                    category=category,
                    tickers=tickers,
                ))
        if self.feeds and failures == len(self.feeds):
            raise NewsProviderError("todos los feeds RSS han fallado")
        return articles


class NewsAPIProvider(NewsProvider):
    """NewsAPI.org /v2/everything. Ojo: el plan gratuito (Developer) tiene retardo."""

    name = "newsapi"
    URL = "https://newsapi.org/v2/everything"
    MAX_QUERY_LEN = 500

    def __init__(self, api_key: str, instruments: list[Instrument], **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.query = self._build_query(instruments)

    @classmethod
    def _build_query(cls, instruments: list[Instrument]) -> str:
        terms: list[str] = []
        for inst in instruments:
            for term in (*inst.keywords, inst.base if len(inst.base) >= 3 else None):
                if term and term not in terms:
                    terms.append(term)
        query = ""
        for term in terms:
            piece = f'"{term}"' if " " in term else term
            candidate = f"{query} OR {piece}" if query else piece
            if len(candidate) > cls.MAX_QUERY_LEN:
                break
            query = candidate
        return query

    def fetch(self, since: datetime) -> list[NewsArticle]:
        data = self._get_json(self.URL, params={
            "q": self.query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 100,
            "from": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, headers={"X-Api-Key": self.api_key})
        if data.get("status") != "ok":
            raise NewsProviderError(f"{data.get('code')}: {data.get('message')}")
        articles = []
        for item in data.get("articles", []):
            title = clean_text(item.get("title"))
            published = _parse_iso(item.get("publishedAt"))
            if not title or title == "[Removed]" or published is None:
                continue
            articles.append(NewsArticle(
                title=title,
                summary=clean_text(item.get("description"))[:600],
                url=item.get("url") or "",
                published_at=published,
                provider=self.name,
                source=(item.get("source") or {}).get("name", ""),
            ))
        return articles


class AlphaVantageProvider(NewsProvider):
    """Alpha Vantage NEWS_SENTIMENT. Se piden las últimas noticias del mercado
    (sin filtrar por tickers, porque el filtro de AV exige que la noticia
    mencione TODOS los tickers a la vez) y se filtra localmente."""

    name = "alphavantage"
    URL = "https://www.alphavantage.co/query"
    MIN_TICKER_RELEVANCE = 0.25

    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def fetch(self, since: datetime) -> list[NewsArticle]:
        data = self._get_json(self.URL, params={
            "function": "NEWS_SENTIMENT",
            "sort": "LATEST",
            "limit": 200,
            "time_from": since.strftime("%Y%m%dT%H%M"),
            "apikey": self.api_key,
        })
        if "feed" not in data:
            # AV devuelve HTTP 200 con un mensaje cuando se agota la cuota
            message = data.get("Information") or data.get("Note") or data.get("Error Message") or data
            raise NewsProviderError(redact(str(message))[:200])
        articles = []
        for item in data["feed"]:
            title = clean_text(item.get("title"))
            try:
                # AV no indica zona horaria; se asume UTC (si fuese posterior a
                # "ahora", el agregador la recorta para no inflar la frescura)
                published = datetime.strptime(item.get("time_published", ""), "%Y%m%dT%H%M%S")
            except ValueError:
                continue
            tickers = set()
            for ts in item.get("ticker_sentiment") or []:
                try:
                    if float(ts.get("relevance_score", 0)) >= self.MIN_TICKER_RELEVANCE:
                        tickers.add(str(ts.get("ticker", "")).upper())
                except (TypeError, ValueError):
                    continue
            if not title:
                continue
            articles.append(NewsArticle(
                title=title,
                summary=clean_text(item.get("summary"))[:600],
                url=item.get("url") or "",
                published_at=published.replace(tzinfo=timezone.utc),
                provider=self.name,
                source=item.get("source") or "",
                tickers=frozenset(tickers),
            ))
        return articles


class AlpacaNewsProvider(NewsProvider):
    """Alpaca News API (Benzinga). Incluye acciones y cripto (BTCUSD...)."""

    name = "alpaca"
    URL = "https://data.alpaca.markets/v1beta1/news"

    def __init__(self, api_key: str, secret_key: str, instruments: list[Instrument], **kwargs):
        super().__init__(**kwargs)
        self.headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
        symbols = []
        for inst in instruments:
            symbols.append(inst.symbol if inst.asset_class == STOCKS else f"{inst.base}USD")
        self.symbols = ",".join(dict.fromkeys(symbols))

    def fetch(self, since: datetime) -> list[NewsArticle]:
        data = self._get_json(self.URL, params={
            "symbols": self.symbols,
            "start": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 50,
            "sort": "desc",
            "include_content": "false",
        }, headers=self.headers)
        articles = []
        for item in data.get("news", []):
            title = clean_text(item.get("headline"))
            published = _parse_iso(item.get("created_at"))
            if not title or published is None:
                continue
            articles.append(NewsArticle(
                title=title,
                summary=clean_text(item.get("summary"))[:600],
                url=item.get("url") or "",
                published_at=published,
                provider=self.name,
                source=item.get("source") or "alpaca",
                tickers=frozenset(str(s).upper() for s in item.get("symbols") or []),
            ))
        return articles


# -----------------------------------------------------------------------------
# Agregador
# -----------------------------------------------------------------------------
class NewsAggregator:
    """Mantiene una ventana deslizante de noticias deduplicadas y etiquetadas."""

    MAX_BACKOFF_SECONDS = 2 * 3600

    def __init__(self, settings: NewsSettings, instruments: list[Instrument],
                 alpaca_keys: tuple[str, str] | None = None,
                 session: requests.Session | None = None,
                 providers: list[NewsProvider] | None = None):
        self.settings = settings
        self.instruments = {i.symbol: i for i in instruments}
        self.matcher = SymbolMatcher(instruments)
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.providers = providers if providers is not None else self._build_providers(alpaca_keys)
        self._articles: dict[str, NewsArticle] = {}
        self._next_poll: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}

    def _build_providers(self, alpaca_keys: tuple[str, str] | None) -> list[NewsProvider]:
        s = self.settings
        common = {"session": self.session, "timeout": s.http_timeout}
        instruments = list(self.instruments.values())
        providers: list[NewsProvider] = []
        for name in s.providers:
            if name == "rss":
                feeds = [(url, cat, frozenset()) for url, cat in s.rss_feeds]
                if s.yahoo_ticker_feeds:
                    for inst in instruments:
                        if inst.asset_class == STOCKS:
                            feeds.append((
                                f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={inst.symbol}"
                                f"&region=US&lang=en-US", STOCKS, frozenset({inst.symbol})))
                providers.append(RSSProvider(feeds, poll_seconds=s.rss_poll_seconds, **common))
            elif name == "newsapi":
                if not s.newsapi_key:
                    logger.info("NewsAPI desactivado (falta NEWSAPI_KEY)")
                    continue
                providers.append(NewsAPIProvider(s.newsapi_key, instruments,
                                                 poll_seconds=s.newsapi_poll_seconds, **common))
            elif name == "alphavantage":
                if not s.alphavantage_key:
                    logger.info("Alpha Vantage desactivado (falta ALPHAVANTAGE_KEY)")
                    continue
                providers.append(AlphaVantageProvider(s.alphavantage_key,
                                                      poll_seconds=s.alphavantage_poll_seconds, **common))
            elif name == "alpaca":
                if not alpaca_keys or not all(alpaca_keys):
                    logger.info("Alpaca News desactivado (faltan ALPACA_API_KEY / ALPACA_SECRET_KEY)")
                    continue
                providers.append(AlpacaNewsProvider(*alpaca_keys, instruments,
                                                    poll_seconds=s.alpaca_poll_seconds, **common))
            else:
                logger.warning("Proveedor de noticias desconocido: %r (se ignora)", name)
        if not providers:
            logger.warning("No hay proveedores de noticias activos: el bot no abrirá operaciones")
        return providers

    # --- ciclo de actualización ---------------------------------------------
    def refresh(self, now: datetime | None = None) -> int:
        """Consulta los proveedores que toque. Devuelve cuántas noticias nuevas entraron."""
        now = now or utc_now()
        since = now - timedelta(minutes=self.settings.lookback_minutes)
        added = 0
        for provider in self.providers:
            if now < self._next_poll.get(provider.name, _EPOCH):
                continue
            try:
                fetched = provider.fetch(since)
            except Exception as exc:  # noqa: BLE001 - aislar fallos por proveedor
                failures = self._failures[provider.name] = self._failures.get(provider.name, 0) + 1
                backoff = min(provider.poll_seconds * 2 ** failures,
                              max(self.MAX_BACKOFF_SECONDS, provider.poll_seconds))
                self._next_poll[provider.name] = now + timedelta(seconds=backoff)
                logger.warning("Noticias %s falló (%d seguidos): %s — próximo intento en %d min",
                               provider.name, failures, redact(str(exc)), backoff // 60)
                continue
            self._failures[provider.name] = 0
            self._next_poll[provider.name] = now + timedelta(seconds=provider.poll_seconds)
            new = sum(self._ingest(article, now) for article in fetched)
            added += new
            logger.debug("Noticias %s: %d recibidas, %d nuevas", provider.name, len(fetched), new)
        self._prune(now)
        return added

    def _ingest(self, article: NewsArticle, now: datetime) -> int:
        if article.published_at > now + timedelta(minutes=5):
            article.published_at = now  # fechas futuras (zona horaria mal declarada)
        uid = article.uid
        existing = self._articles.get(uid)
        if existing is not None:
            # Otra fuente puede aportar tickers estructurados que la primera no tenía
            if article.tickers - existing.tickers:
                existing.tickers = existing.tickers | article.tickers
                existing.matches = self.matcher.match(existing)
                existing.asset_classes = self._asset_classes(existing)
            return 0
        article.matches = self.matcher.match(article)
        article.asset_classes = self._asset_classes(article)
        self._articles[uid] = article
        return 1

    def _asset_classes(self, article: NewsArticle) -> frozenset[str]:
        classes = set()
        if article.category in (STOCKS, CRYPTO):
            classes.add(article.category)
        elif article.category == MACRO:
            classes.update((STOCKS, CRYPTO))
        for symbol in article.matches:
            classes.add(self.instruments[symbol].asset_class)
        return frozenset(classes)

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.settings.lookback_minutes)
        for uid in [u for u, a in self._articles.items() if a.published_at < cutoff]:
            del self._articles[uid]

    # --- consultas ------------------------------------------------------------
    def articles_for(self, symbol: str) -> list[tuple[NewsArticle, float]]:
        """Noticias del símbolo con su relevancia (0-1)."""
        return [(a, a.matches[symbol]) for a in self._articles.values() if symbol in a.matches]

    def market_articles(self, asset_class: str) -> list[tuple[NewsArticle, float]]:
        """Noticias que afectan a todo un mercado (para detectar 'risk-off')."""
        return [(a, 1.0) for a in self._articles.values() if asset_class in a.asset_classes]

    def __len__(self) -> int:
        return len(self._articles)
