"""Voice session setup.

The browser holds the microphone and streams to Azure Speech directly with a short-lived
token minted here, so audio never transits our servers and the subscription key never
reaches the client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.db import get_db
from app.core.security import Principal, current_principal, load_tenant_or_404
from app.services.azure_speech import VOICES, issue_token
from sqlalchemy.orm import Session

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/token")
async def token(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    if not tenant.voice_enabled:
        return {"mode": "disabled",
                "reason": "Voice is switched off for this workspace in Settings."}
    payload = await issue_token()
    payload["tenant_locale"] = _locale_for(tenant.country)
    return payload


@router.get("/config")
def config(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    return {
        "enabled": tenant.voice_enabled,
        "provider": "azure-speech" if settings.speech_enabled else "browser",
        "locales": sorted(VOICES.keys()),
        "voices": VOICES,
        "default_locale": _locale_for(tenant.country),
        "default_voice": settings.azure_speech_voice,
        "wake_phrase": "Hey ShopperMind",
        "sample_questions": [
            "Why did sales fall this month?",
            "Which stores need attention?",
            "What are customers complaining about?",
            "What should we promote this weekend?",
            "What happens if we raise the combo price by twenty rupees?",
        ],
    }


def _locale_for(country: str) -> str:
    return {"IN": "en-IN", "AE": "ar-AE", "GB": "en-GB", "US": "en-US"}.get(
        country.upper(), "en-IN"
    )
