"""Voice: short-lived Speech tokens for the browser, plus server-side TTS.

The browser talks to Azure Speech directly using a ten-minute token minted here, so the
subscription key never reaches the client. When Speech is not configured the front-end
falls back to the Web Speech API, which is why the token endpoint returns a mode rather
than an error.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# Voices chosen for the launch markets. The tenant picks one in Settings.
VOICES = {
    "en-IN": ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural"],
    "hi-IN": ["hi-IN-SwaraNeural", "hi-IN-MadhurNeural"],
    "ta-IN": ["ta-IN-PallaviNeural", "ta-IN-ValluvarNeural"],
    "te-IN": ["te-IN-ShrutiNeural", "te-IN-MohanNeural"],
    "mr-IN": ["mr-IN-AarohiNeural", "mr-IN-ManoharNeural"],
    "bn-IN": ["bn-IN-TanishaaNeural", "bn-IN-BashkarNeural"],
    "en-US": ["en-US-JennyNeural", "en-US-GuyNeural"],
    "ar-AE": ["ar-AE-FatimaNeural", "ar-AE-HamdanNeural"],
}

# Phrases the recogniser is biased towards. Retail and QSR vocabulary is exactly what
# generic speech models get wrong, so this list matters more than it looks.
PHRASE_HINTS = [
    "ShopperMind", "basket", "footfall", "attach rate", "cross-sell", "upsell", "daypart",
    "same-store sales", "churn", "lapsed", "win-back", "next best offer", "combo",
    "average order value", "conversion", "dwell time", "queue length", "shrinkage",
    "like-for-like", "SKU", "planogram", "quick service restaurant",
]


async def issue_token() -> dict:
    """Mint a ten-minute Speech token for the browser SDK."""
    if not settings.speech_enabled:
        return {
            "mode": "browser",
            "reason": "Azure Speech is not configured; the client should use the Web Speech API.",
            "region": settings.azure_speech_region,
            "voice": settings.azure_speech_voice,
            "phrase_hints": PHRASE_HINTS,
        }

    url = (
        f"https://{settings.azure_speech_region}.api.cognitive.microsoft.com"
        "/sts/v1.0/issueToken"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url, headers={"Ocp-Apim-Subscription-Key": settings.azure_speech_key}
            )
            resp.raise_for_status()
            token = resp.text
    except Exception:
        log.warning("Speech token request failed; client will fall back", exc_info=True)
        return {"mode": "browser", "reason": "Token request failed", "phrase_hints": PHRASE_HINTS}

    return {
        "mode": "azure",
        "token": token,
        "region": settings.azure_speech_region,
        "voice": settings.azure_speech_voice,
        "expires_in": 540,
        "phrase_hints": PHRASE_HINTS,
        "voices": VOICES,
    }


def build_ssml(text: str, voice: str | None = None, locale: str = "en-IN") -> str:
    """Speech output that reads like an analyst, not a screen reader.

    Numbers get a short pause before them so a spoken metric lands, and the whole thing is
    slowed very slightly — spoken analysis is harder to follow than spoken prose.
    """
    import html

    voice = voice or settings.azure_speech_voice
    safe = html.escape(text)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{locale}">'
        f'<voice name="{voice}">'
        f'<mstts:express-as style="narration-professional">'
        f'<prosody rate="-4%">{safe}</prosody>'
        f"</mstts:express-as></voice></speak>"
    )


async def synthesize(text: str, voice: str | None = None, locale: str = "en-IN") -> bytes | None:
    """Server-side TTS. Returns MP3 bytes, or None when Speech is not configured."""
    if not settings.speech_enabled:
        return None
    url = (
        f"https://{settings.azure_speech_region}.tts.speech.microsoft.com"
        "/cognitiveservices/v1"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        "User-Agent": "ShopperMind",
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url, headers=headers, content=build_ssml(text, voice, locale).encode("utf-8")
            )
            resp.raise_for_status()
            return resp.content
    except Exception:
        log.warning("Speech synthesis failed", exc_info=True)
        return None


def spoken_form(text: str, currency: str = "INR") -> str:
    """Rewrite an on-screen answer for the ear.

    Screen text and spoken text are not the same register: '₹4,32,000' and '8.4%' read
    fine but are awkward to hear, and a spoken answer has to be shorter because the
    listener cannot skim.
    """
    import re

    symbol = {"INR": "rupees", "USD": "dollars", "AED": "dirhams", "GBP": "pounds"}.get(
        currency, ""
    )

    def money(match: re.Match) -> str:
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            return match.group(0)
        if value >= 1e7:
            return f"{value / 1e7:.1f} crore {symbol}"
        if value >= 1e5:
            return f"{value / 1e5:.1f} lakh {symbol}"
        if value >= 1000:
            return f"{value / 1000:.1f} thousand {symbol}"
        return f"{value:.0f} {symbol}"

    text = re.sub(r"[₹$£]\s?([\d,]+(?:\.\d+)?)", money, text)
    text = re.sub(r"(\d+(?:\.\d+)?)%", r"\1 percent", text)
    text = text.replace("→", " leads to ")
    text = re.sub(r"\s+", " ", text).strip()
    # Keep a spoken answer to roughly three sentences; the screen holds the rest.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:3])
