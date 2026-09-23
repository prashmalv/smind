"""Sentiment, key-phrase and PII handling for incoming text.

Azure AI Language when configured; a lexicon classifier otherwise. Every piece of feedback
is enriched once at ingest, so the reading modules never call a model per request.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# A small, explicitly QSR/retail-tuned lexicon. It exists so the platform produces honest
# sentiment on a laptop; Azure AI Language replaces it the moment a key is present.
_POSITIVE = {
    "good", "great", "excellent", "love", "loved", "amazing", "delicious", "fresh", "fast",
    "friendly", "clean", "best", "perfect", "tasty", "quick", "polite", "value", "worth",
    "recommend", "favourite", "favorite", "helpful", "consistent", "generous",
}
_NEGATIVE = {
    "bad", "poor", "terrible", "worst", "cold", "late", "delay", "delayed", "slow", "rude",
    "dirty", "stale", "expensive", "overpriced", "small", "wrong", "missing", "soggy",
    "waited", "waiting", "queue", "disappointed", "awful", "bland", "burnt", "refund",
}
_NEGATORS = {"not", "never", "no", "isn't", "wasn't", "didn't", "don't", "won't"}

# Theme lexicon — the vocabulary the voice-of-customer module groups by.
_THEMES: dict[str, tuple[str, ...]] = {
    # "waiting" deliberately belongs to queue-and-wait, not here: it also appears in
    # "no waiting at all", which would tag a compliment as a delivery complaint.
    "delivery delay": ("arrived late", "delivery was late", "delay", "delayed",
                       "slow delivery", "took long", "not delivered", "delivery time"),
    "food temperature": ("cold", "lukewarm", "not hot", "warm food", "temperature"),
    "portion size": ("portion", "small", "tiny", "quantity", "less quantity", "size"),
    "pricing": ("expensive", "overpriced", "costly", "price", "value for money", "pricey"),
    "staff behaviour": ("rude", "polite", "friendly", "staff", "service", "attitude", "helpful"),
    "cleanliness": ("dirty", "clean", "hygiene", "unclean", "messy", "spotless"),
    "order accuracy": ("wrong", "missing", "incorrect", "not what i ordered", "mixed up"),
    "queue and wait": ("queue", "line", "waited", "waiting", "wait time", "crowded",
                       "slow counter"),
    "taste": ("tasty", "bland", "delicious", "flavour", "flavor", "taste", "spicy", "salty"),
    "packaging": ("packaging", "spilled", "leaked", "packed", "container"),
    "app experience": ("app", "website", "checkout", "payment failed", "crash", "login"),
    "availability": ("out of stock", "unavailable", "sold out", "not available", "finished"),
}

_PII_PATTERNS = (
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\b(?:\+?91[\s-]?)?[6-9]\d{9}\b"), "[phone]"),
    (re.compile(r"\b\d{12}\b"), "[id]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[card]"),
)


def redact_pii(text: str) -> str:
    """Strip direct identifiers before text is stored or sent to any model."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _local_sentiment(text: str) -> tuple[str, float]:
    words = re.findall(r"[a-z']+", text.lower())
    score = 0
    for i, w in enumerate(words):
        weight = -1 if i and words[i - 1] in _NEGATORS else 1
        if w in _POSITIVE:
            score += weight
        elif w in _NEGATIVE:
            score -= weight
    if score > 0:
        return "positive", min(0.5 + score * 0.12, 1.0)
    if score < 0:
        return "negative", max(0.5 + score * 0.12, 0.0)
    return "neutral", 0.5


def _local_themes(text: str) -> list[str]:
    low = text.lower()
    return [theme for theme, cues in _THEMES.items() if any(c in low for c in cues)]


async def _azure_sentiment(documents: list[str], language: str = "en") -> list[dict]:
    url = f"{settings.azure_language_endpoint.rstrip('/')}/language/:analyze-text?api-version=2023-04-01"
    body = {
        "kind": "SentimentAnalysis",
        "parameters": {"modelVersion": "latest", "opinionMining": True},
        "analysisInput": {
            "documents": [
                {"id": str(i), "language": language, "text": t[:5000]}
                for i, t in enumerate(documents)
            ]
        },
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url, json=body, headers={"Ocp-Apim-Subscription-Key": settings.azure_language_key}
        )
        resp.raise_for_status()
        return resp.json()["results"]["documents"]


async def enrich(text: str, language: str = "en") -> dict:
    """One utterance in, enrichment out. Safe to call on every ingested row."""
    clean = redact_pii(text.strip())

    if settings.language_enabled:
        try:
            docs = await _azure_sentiment([clean], language)
            doc = docs[0]
            scores = doc["confidenceScores"]
            sentiment = doc["sentiment"]
            score = {
                "positive": scores["positive"],
                "negative": 1 - scores["negative"],
                "neutral": 0.5,
                "mixed": 0.5,
            }.get(sentiment, 0.5)
            return {
                "body": clean,
                "sentiment": "neutral" if sentiment == "mixed" else sentiment,
                "sentiment_score": round(float(score), 3),
                "themes": ",".join(_local_themes(clean)),
                "provider": "azure-ai-language",
            }
        except Exception:
            log.warning("Azure AI Language call failed; falling back to local classifier",
                        exc_info=True)

    sentiment, score = _local_sentiment(clean)
    return {
        "body": clean,
        "sentiment": sentiment,
        "sentiment_score": round(score, 3),
        "themes": ",".join(_local_themes(clean)),
        "provider": "local",
    }


def enrich_sync(text: str) -> dict:
    """Synchronous path used by the seeder, which runs outside the event loop."""
    clean = redact_pii(text.strip())
    sentiment, score = _local_sentiment(clean)
    return {
        "body": clean,
        "sentiment": sentiment,
        "sentiment_score": round(score, 3),
        "themes": ",".join(_local_themes(clean)),
        "provider": "local",
    }


THEME_KEYS = tuple(_THEMES.keys())
