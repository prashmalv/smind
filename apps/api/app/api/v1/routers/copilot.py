"""Ask ShopperMind — the conversational surface, text and voice."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copilot.orchestrator import answer
from app.core.db import get_db
from app.core.security import Principal, current_principal, load_tenant_or_404
from app.intelligence.base import AnalysisContext
from app.models.intelligence import Conversation, Message

router = APIRouter(prefix="/copilot", tags=["copilot"])


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: str | None = None
    period_days: int = Field(default=30, ge=1, le=365)
    store_ids: list[str] | None = None
    is_voice: bool = False
    speak: bool = Field(
        default=False,
        description="Return an audio URL alongside the text. Requires Azure Speech.",
    )


@router.post("/ask")
async def ask(
    payload: AskRequest,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    tenant = load_tenant_or_404(db, principal.tenant_id)
    ctx = AnalysisContext(
        db=db, tenant_id=tenant.id, period_days=payload.period_days,
        period_end=datetime.now(UTC), store_ids=payload.store_ids,
        currency=tenant.currency, vertical=tenant.vertical,
    )

    conversation = _get_or_create_conversation(
        db, principal, payload.conversation_id, payload.question,
        "voice" if payload.is_voice else "text",
    )
    history = _history(db, conversation.id)

    result = await answer(
        payload.question, ctx, tenant.name, history=history, is_voice=payload.is_voice
    )

    db.add(Message(
        tenant_id=tenant.id, conversation_id=conversation.id, role="user",
        content=payload.question, was_voice=payload.is_voice,
    ))
    db.add(Message(
        tenant_id=tenant.id, conversation_id=conversation.id, role="assistant",
        content=result.text, modules_used=",".join(result.modules_used),
        evidence=json.dumps(result.evidence, default=str)[:60000],
        latency_ms=result.latency_ms, was_voice=payload.is_voice,
    ))
    db.commit()

    body = {
        "conversation_id": conversation.id,
        "answer": result.text,
        "modules_used": result.modules_used,
        "findings": result.findings,
        "charts": result.charts,
        "followups": result.followups,
        "evidence": result.evidence,
        "latency_ms": result.latency_ms,
        "engine": result.engine,
    }

    if payload.speak:
        from app.services.azure_speech import spoken_form

        # The client POSTs this to /copilot/speak for audio, or hands it to the browser's
        # own speech synthesis when Azure Speech is not configured.
        body["spoken_text"] = spoken_form(result.text, tenant.currency)

    return body


@router.post("/speak")
async def speak(
    text: str = Body(..., embed=True),
    voice: str | None = Body(None, embed=True),
    locale: str = Body("en-IN", embed=True),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Server-side text to speech. Returns MP3, or 503 when Speech is not configured —
    the client then falls back to the browser's own speech synthesis."""
    from app.services.azure_speech import spoken_form, synthesize

    tenant = load_tenant_or_404(db, principal.tenant_id)
    audio = await synthesize(spoken_form(text, tenant.currency), voice, locale)
    if audio is None:
        raise HTTPException(
            status_code=503,
            detail="Azure Speech is not configured. Use the browser speech synthesis fallback.",
        )
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/conversations")
def list_conversations(
    limit: int = Query(30, le=100),
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == principal.tenant_id,
               Conversation.user_id == principal.user_id,
               Conversation.is_archived.is_(False))
        .order_by(Conversation.updated_at.desc()).limit(limit)
    ).all()
    return [
        {"id": c.id, "title": c.title, "modality": c.modality,
         "updated_at": c.updated_at.isoformat()}
        for c in rows
    ]


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    ).all()
    return {
        "id": conv.id, "title": conv.title, "modality": conv.modality,
        "messages": [
            {
                "id": m.id, "role": m.role, "content": m.content,
                "modules_used": [x for x in m.modules_used.split(",") if x],
                "evidence": json.loads(m.evidence or "{}"),
                "latency_ms": m.latency_ms, "was_voice": m.was_voice,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
def archive_conversation(
    conversation_id: str,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.is_archived = True
    db.commit()


def _get_or_create_conversation(
    db: Session, principal: Principal, conversation_id: str | None,
    first_question: str, modality: str,
) -> Conversation:
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv
    title = first_question.strip()
    conv = Conversation(
        tenant_id=principal.tenant_id, user_id=principal.user_id,
        title=(title[:80] + "…") if len(title) > 80 else title, modality=modality,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _history(db: Session, conversation_id: str) -> list[dict]:
    msgs = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id,
                              Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at.desc()).limit(6)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(msgs)]
