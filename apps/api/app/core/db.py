"""Database session and declarative base.

Tenant isolation is enforced in the repository layer: every query against a tenant-scoped
table goes through `tenant_query()`, which injects the `tenant_id` filter. Postgres RLS is
layered on top in cloud deployments (see docs/03-data-model.md).
"""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Select, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_connect_args: dict[str, Any] = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def tenant_query(model: Any, tenant_id: str) -> Select:
    """Build a SELECT already narrowed to one tenant. Use this, never a bare select()."""
    if not hasattr(model, "tenant_id"):
        raise ValueError(f"{model.__name__} is not tenant-scoped")
    return select(model).where(model.tenant_id == tenant_id)
