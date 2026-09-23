"""Password hashing, JWT issue/verify, and the tenant-aware request principal."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)

# Role hierarchy. A role satisfies any requirement at or below its rank.
ROLE_RANK = {"viewer": 10, "analyst": 20, "manager": 30, "admin": 40, "owner": 50}


def _prehash(raw: str) -> bytes:
    """bcrypt silently truncates past 72 bytes, which turns a long passphrase into a
    weaker secret than the user believes they chose. Hashing to a fixed-length digest
    first removes the limit instead of hiding it."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_prehash(raw), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(raw), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: str, tenant_id: str, role: str, email: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.api_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.api_secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. `tenant_id` scopes every downstream query."""

    user_id: str
    tenant_id: str
    role: str
    email: str

    def require(self, minimum: str) -> None:
        if ROLE_RANK.get(self.role, 0) < ROLE_RANK.get(minimum, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum} role or above",
            )


def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing"
        )
    claims = decode_token(creds.credentials)
    return Principal(
        user_id=claims["sub"],
        tenant_id=claims["tid"],
        role=claims.get("role", "viewer"),
        email=claims.get("email", ""),
    )


def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
    principal.require("admin")
    return principal


def require_manager(principal: Principal = Depends(current_principal)) -> Principal:
    principal.require("manager")
    return principal


# Convenience alias so routers read as `db: Session = Depends(db_session)`
db_session = get_db


def load_tenant_or_404(db: Session, tenant_id: str):
    from app.models.tenant import Tenant

    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=404, detail="Tenant not found or suspended")
    return tenant
