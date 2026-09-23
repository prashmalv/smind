"""Registration, login, invitations. This is the front door of the SaaS."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    Principal,
    create_access_token,
    current_principal,
    hash_password,
    require_admin,
    verify_password,
)
from app.models.base import utcnow
from app.models.tenant import Tenant, User
from app.schemas.auth import (
    AuthResponse,
    InviteRequest,
    LoginRequest,
    RegisterRequest,
    TenantOut,
    UserOut,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

RESERVED_SLUGS = {"admin", "api", "www", "app", "shoppermind", "support", "status", "docs"}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug or "workspace"


def _unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    if base in RESERVED_SLUGS:
        base = f"{base}-co"
    slug, n = base, 1
    while db.scalar(select(func.count()).select_from(Tenant).where(Tenant.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


def _auth_response(user: User, tenant: Tenant) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(
            user_id=user.id, tenant_id=tenant.id, role=user.role, email=user.email
        ),
        expires_in_minutes=settings.access_token_ttl_minutes,
        user=UserOut(id=user.id, email=user.email, full_name=user.full_name,
                     role=user.role, job_title=user.job_title),
        tenant=TenantOut(
            id=tenant.id, name=tenant.name, slug=tenant.slug, vertical=tenant.vertical,
            currency=tenant.currency, country=tenant.country, timezone=tenant.timezone,
            plan=tenant.plan, camera_enabled=tenant.camera_enabled,
            voice_enabled=tenant.voice_enabled,
        ),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """Create a workspace and its owner.

    Anyone can sign up — that is the point of the platform. What they get is an isolated
    tenant, seeded with demo data so the product is explorable before their POS is wired in.
    """
    from datetime import timedelta

    tenant = Tenant(
        name=payload.company_name.strip(),
        slug=_unique_slug(db, payload.company_name),
        vertical=payload.vertical,
        country=payload.country.upper(),
        currency=payload.currency.upper(),
        timezone=payload.timezone,
        plan="trial",
        trial_ends_at=utcnow() + timedelta(days=30),
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="owner",
        job_title=payload.job_title,
        last_login_at=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(tenant)
    db.refresh(user)

    if payload.seed_demo_data:
        from app.seed.demo import seed_tenant

        try:
            seed_tenant(db, tenant)
        except Exception:
            # A seeding failure must not cost the user their account.
            log.exception("Demo seeding failed for tenant %s", tenant.id)
            db.rollback()

    return _auth_response(user, tenant)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = payload.email.lower()
    stmt = select(User, Tenant).join(Tenant, Tenant.id == User.tenant_id).where(
        User.email == email, User.is_active.is_(True), Tenant.is_active.is_(True)
    )
    if payload.tenant_slug:
        stmt = stmt.where(Tenant.slug == payload.tenant_slug)
    rows = db.execute(stmt).all()

    if not rows:
        raise HTTPException(status_code=401, detail="Email or password is incorrect")

    if len(rows) > 1:
        # The same person can belong to several workspaces; make them name one.
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This email belongs to more than one workspace. Include tenant_slug.",
                "workspaces": [{"slug": t.slug, "name": t.name} for _, t in rows],
            },
        )

    user, tenant = rows[0]
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")

    user.last_login_at = utcnow()
    db.commit()
    return _auth_response(user, tenant)


@router.get("/me", response_model=AuthResponse)
def me(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = db.get(User, principal.user_id)
    tenant = db.get(Tenant, principal.tenant_id)
    if user is None or tenant is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return _auth_response(user, tenant)


@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def invite(
    payload: InviteRequest,
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    """Add a teammate to this workspace. Admin and above only."""
    from app.core.security import ROLE_RANK

    if ROLE_RANK.get(payload.role, 0) > ROLE_RANK.get(principal.role, 0):
        raise HTTPException(status_code=403, detail="You cannot grant a role above your own")

    tenant = db.get(Tenant, principal.tenant_id)
    seats = db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == principal.tenant_id)
    ) or 0
    if tenant and seats >= tenant.limits["seats"]:
        raise HTTPException(
            status_code=402,
            detail=f"The {tenant.plan} plan includes {tenant.limits['seats']} seats. Upgrade to add more.",
        )

    exists = db.scalar(
        select(User).where(User.tenant_id == principal.tenant_id,
                           User.email == payload.email.lower())
    )
    if exists:
        raise HTTPException(status_code=409, detail="That email is already in this workspace")

    user = User(
        tenant_id=principal.tenant_id, email=payload.email.lower(),
        full_name=payload.full_name, password_hash=hash_password(payload.password),
        role=payload.role, job_title=payload.job_title,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, email=user.email, full_name=user.full_name,
                   role=user.role, job_title=user.job_title)


@router.get("/users", response_model=list[UserOut])
def list_users(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    users = db.scalars(
        select(User).where(User.tenant_id == principal.tenant_id).order_by(User.created_at)
    ).all()
    return [UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role,
                    job_title=u.job_title) for u in users]
