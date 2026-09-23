"""Test fixtures: an isolated SQLite database per test session, seeded once."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest

# Must be set before app.core.config is imported anywhere.
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["API_SECRET_KEY"] = "test-only-key"

from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401  — registers the tables
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.seed.demo import seed_tenant  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Generator[None, None, None]:
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    os.close(_db_fd)
    os.unlink(_db_path)


@pytest.fixture(scope="session")
def seeded_tenant(_schema) -> Tenant:
    """One seeded QSR workspace, shared across the suite.

    Seeding is the slow part, so it happens once. Tests must not mutate it — anything
    that writes gets its own tenant.
    """
    db: Session = SessionLocal()
    tenant = Tenant(name="Test QSR", slug="test-qsr", vertical="qsr", currency="INR")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    seed_tenant(db, tenant, days=45)
    db.close()
    return tenant


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
