"""
sentiment.py
============
Análisis de sentimiento de titulares con VADER + léxico financiero, y
cálculo del "Score de Trading" agregado por símbolo.

Por qué VADER: es ligero (sin GPU ni descargas), rápido y está diseñado para
textos cortos como titulares. Su debilidad es que es un léxico generalista:
"Bitcoin surges to record high" puntúa 0 porque no conoce "surges". Por eso
se amplía con vocabulario financiero y se neutralizan palabras que en
finanzas no tienen carga emocional ("shares", "interest", "credit"...).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from news_handler import NewsArticle

POSITIVE = "Positivo"
NEGATIVE = "Negativo"
NEUTRAL = "Neutral"

# Escala de VADER: -4 (muy negativo) a +4 (muy positivo)
FINANCE_LEXICON: dict[str, float] = {
    # --- Alcista ---
    "beat": 1.8, "beats": 1.8, "surge": 2.5, "surges": 2.5, "surged": 2.5, "surging": 2.5,
    "soar": 2.7, "soars": 2.7, "soared": 2.7, "soaring": 2.7, "skyrocket": 3.0, "skyrockets": 3.0,
    "rally": 2.0, "rallies": 2.0, "rallied": 2.0, "jump": 1.5, "jumps": 1.5, "jumped": 1.5,
    "climb": 1.3, "climbs": 1.3, "rises": 1.0, "rise": 1.0, "gains": 1.8, "rebound": 1.5,
    "rebounds": 1.5, "recovers": 1.3, "recovery": 1.3, "upgrade": 2.0, "upgrades": 2.0,
    "upgraded": 2.0, "outperform": 2.0, "outperforms": 2.0, "overweight": 1.2,
    "bullish": 2.5, "bull": 1.2, "breakout": 1.5, "highs": 1.2, "record": 0.8,
    "approved": 2.0, "approves": 2.0, "approval": 2.0, "partnership": 1.5, "acquire": 0.8,
    "buyback": 1.5, "dividend": 1.0, "profitable": 2.0, "inflows": 1.8, "adoption": 1.5,
    "expands": 1.0, "expansion": 1.0, "launches": 0.8, "wins": 1.8, "boosts": 1.5,
    "raises": 0.8, "tops": 1.3, "exceeds": 1.8, "strong": 1.5, "optimism": 2.0,
    # --- Bajista ---
    "miss": -2.0, "misses": -2.0, "missed": -2.0, "plunge": -2.8, "plunges": -2.8,
    "plunged": -2.8, "plummet": -3.0, "plummets": -3.0, "plummeted": -3.0,
    "tumble": -2.3, "tumbles": -2.3, "tumbled": -2.3, "slump": -2.2, "slumps": -2.2,
    "slide": -1.5, "slides": -1.5, "slid": -1.5, "sinks": -2.0, "sink": -2.0,
    "falls": -1.5, "fall": -1.5, "fell": -1.5, "drops": -1.5, "dropped": -1.5,
    "tank": -2.5, "tanks": -2.5, "tanked": -2.5, "crash": -3.0, "crashes": -3.0,
    "selloff": -2.5, "sell-off": -2.5, "downgrade": -2.0, "downgrades": -2.0,
    "downgraded": -2.0, "underperform": -2.0, "underweight": -1.2, "bearish": -2.5,
    "bear": -1.2, "lows": -1.2, "lawsuit": -2.0, "sues": -1.8, "sued": -2.0,
    "probe": -1.8, "investigation": -1.8, "subpoena": -2.0, "fined": -2.2,
    "penalty": -1.8, "bankruptcy": -3.5, "bankrupt": -3.5, "insolvency": -3.2,
    "default": -1.5, "hack": -2.8, "hacked": -3.0, "exploit": -2.5, "exploited": -2.8,
    "breach": -2.5, "outage": -2.0, "delisting": -2.8, "delist": -2.8, "delisted": -2.8,
    "liquidation": -2.0, "liquidations": -2.0, "outflows": -1.8, "layoffs": -2.0,
    "recall": -1.5, "recalls": -2.0, "recalled": -2.0, "halt": -2.0, "halts": -2.0, "halted": -2.0, "warns": -1.8,
    "recession": -2.5, "hike": -1.0, "hikes": -1.0, "tariffs": -1.2, "sanctions": -1.5, "weak": -1.8,
    "slowdown": -1.8, "volatile": -0.8, "turmoil": -2.5, "fears": -1.8,
}

# Palabras con valencia en VADER que en finanzas son neutras o ambiguas
NEUTRALIZED_WORDS = (
    "share", "shares", "interest", "credit", "trust", "united", "demand",
    "cut", "cuts", "free", "top", "safety",
)


@dataclass
class SentimentResult:
    """Sentimiento agregado de un símbolo (o del mercado)."""

    symbol: str
    score: float = 0.0             # media ponderada del compound VADER, [-1, 1]
    trading_score: float = 0.0     # Score de Trading, [-100, 100]
    label: str = NEUTRAL
    n_articles: int = 0
    confidence: float = 0.0        # [0, 1]
    latest_published: datetime | None = None
    top_headlines: list[tuple[float, str]] = field(default_factory=list)

    def describe(self) -> str:
        return (f"sentimiento={self.trading_score:+.0f} ({self.label}, {self.n_articles} noticias, "
                f"confianza {self.confidence:.0%})")


class SentimentAnalyzer:
    """
    Puntúa titulares y los agrega en un Score de Trading:

        peso_i      = relevancia_i * 0.5 ** (antigüedad_min / vida_media)
        score       = Σ peso_i * compound_i / Σ peso_i                ∈ [-1, 1]
        confianza   = min(1, Σ peso_i / N_completo) * (1 - 0.5 * dispersión)
        trading     = 100 * score * confianza                          ∈ [-100, 100]

    - El decaimiento exponencial hace que una noticia de hace 2 h pese 1/4
      que una recién publicada (con vida media de 60 min).
    - La confianza baja si hay pocas noticias o si se contradicen entre sí.
    """

    def __init__(self, half_life_minutes: float = 60.0, full_confidence_articles: float = 3.0,
                 neutral_band: float = 0.05, title_weight: float = 0.75):
        self.half_life = half_life_minutes
        self.full_confidence = full_confidence_articles
        self.neutral_band = neutral_band
        self.title_weight = title_weight
        self._vader = SentimentIntensityAnalyzer()
        for word in NEUTRALIZED_WORDS:
            self._vader.lexicon.pop(word, None)
        self._vader.lexicon.update(FINANCE_LEXICON)

    # --- texto individual ----------------------------------------------------
    def score_text(self, title: str, summary: str = "") -> float:
        """Compound en [-1, 1]. El titular pesa más que el resumen."""
        title_score = self._vader.polarity_scores(title)["compound"] if title else 0.0
        if not summary:
            return title_score
        summary_score = self._vader.polarity_scores(summary)["compound"]
        return self.title_weight * title_score + (1 - self.title_weight) * summary_score

    def label(self, value: float) -> str:
        if value >= self.neutral_band:
            return POSITIVE
        if value <= -self.neutral_band:
            return NEGATIVE
        return NEUTRAL

    def score_article(self, article: NewsArticle) -> float:
        if article.sentiment is None:  # se calcula una sola vez por noticia
            article.sentiment = self.score_text(article.title, article.summary)
        return article.sentiment

    # --- agregado --------------------------------------------------------------
    def aggregate(self, symbol: str, weighted_articles: list[tuple[NewsArticle, float]],
                  now: datetime) -> SentimentResult:
        total_weight = 0.0
        weighted_sum = 0.0
        scored: list[tuple[float, float, NewsArticle]] = []
        latest: datetime | None = None
        for article, relevance in weighted_articles:
            age_min = max(0.0, (now - article.published_at).total_seconds() / 60.0)
            weight = relevance * 0.5 ** (age_min / self.half_life)
            if weight <= 0:
                continue
            value = self.score_article(article)
            scored.append((weight, value, article))
            total_weight += weight
            weighted_sum += weight * value
            if latest is None or article.published_at > latest:
                latest = article.published_at

        if total_weight == 0:
            return SentimentResult(symbol=symbol)

        score = weighted_sum / total_weight
        variance = sum(w * (v - score) ** 2 for w, v, _ in scored) / total_weight
        dispersion = min(1.0, math.sqrt(variance))
        confidence = min(1.0, total_weight / self.full_confidence) * (1.0 - 0.5 * dispersion)
        trading_score = max(-100.0, min(100.0, 100.0 * score * confidence))
        top = sorted(scored, key=lambda item: item[0], reverse=True)[:3]
        return SentimentResult(
            symbol=symbol,
            score=round(score, 4),
            trading_score=round(trading_score, 2),
            label=self.label(score),
            n_articles=len(scored),
            confidence=round(confidence, 3),
            latest_published=latest,
            top_headlines=[(round(v, 2), a.title) for _, v, a in top],
        )
