"""Registration, isolation and the authenticated surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client(_schema) -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def account(client: TestClient) -> dict:
    res = client.post("/api/v1/auth/register", json={
        "company_name": "API Test Foods", "vertical": "qsr",
        "full_name": "Test Owner", "email": "owner@apitest.example",
        "password": "TestPassw0rd!", "seed_demo_data": False,
    })
    assert res.status_code == 201, res.text
    return res.json()


def auth(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['access_token']}"}


def test_health(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"


def test_registration_creates_an_isolated_workspace(account: dict):
    assert account["tenant"]["slug"] == "api-test-foods"
    assert account["user"]["role"] == "owner"
    assert account["tenant"]["currency"] == "INR"


def test_weak_password_is_rejected(client: TestClient):
    res = client.post("/api/v1/auth/register", json={
        "company_name": "Weak Co", "full_name": "X", "email": "weak@example.com",
        "password": "passwordpassword", "seed_demo_data": False,
    })
    assert res.status_code == 422


def test_unauthenticated_requests_are_refused(client: TestClient):
    assert client.get("/api/v1/intelligence/pulse").status_code == 401


def test_module_catalogue_is_complete(client: TestClient, account: dict):
    body = client.get("/api/v1/intelligence/modules", headers=auth(account)).json()
    assert len(body["modules"]) == 14
    assert len(body["segments"]) == 7
    assert len(body["stack"]) == 6
    # Every one of the doc's five questions is covered by at least one module.
    assert len(body["by_question"]) == 5


def test_empty_workspace_reports_missing_sources_rather_than_zeroes(
    client: TestClient, account: dict
):
    body = client.get("/api/v1/ingest/status", headers=auth(account)).json()
    assert body["ready"] is False
    assert "Transactions (POS)" in body["missing_required"]
    assert any(b["module_key"] == "basket_analysis" for b in body["modules_blocked"])


def test_copilot_declines_to_invent_numbers(client: TestClient, account: dict):
    """With no data connected, the answer must say so — not estimate."""
    res = client.post("/api/v1/copilot/ask", headers=auth(account), json={
        "question": "Why did sales fall this month?", "period_days": 30,
    })
    assert res.status_code == 200
    answer = res.json()["answer"].lower()
    assert any(phrase in answer for phrase in
               ("not connected", "no orders", "nothing crossed", "not enough", "data sources"))


def test_ingest_then_analyse(client: TestClient, account: dict):
    headers = auth(account)
    client.post("/api/v1/ingest/stores", headers=headers, json=[
        {"code": "S1", "name": "Test Store", "city": "Bengaluru"},
    ])
    client.post("/api/v1/ingest/products", headers=headers, json=[
        {"sku": "P1", "name": "Test Burger", "category": "Burgers", "price": 180, "cost": 70},
        {"sku": "P2", "name": "Test Fries", "category": "Sides", "price": 90, "cost": 25},
    ])
    orders = [
        {
            "external_id": f"O{i}", "store_code": "S1", "customer_external_id": f"C{i % 12}",
            "placed_at": "2026-09-10T12:30:00Z", "channel": "dine-in",
            "gross_amount": 270, "discount_amount": 0,
            "items": [
                {"sku": "P1", "quantity": 1, "unit_price": 180},
                {"sku": "P2", "quantity": 1, "unit_price": 90},
            ],
        }
        for i in range(40)
    ]
    res = client.post("/api/v1/ingest/orders", headers=headers, json=orders)
    assert res.json()["created"] == 40

    # The same batch again must not double-count revenue.
    again = client.post("/api/v1/ingest/orders", headers=headers, json=orders)
    assert again.json()["created"] == 0
    assert again.json()["skipped_duplicates"] == 40

    result = client.get(
        "/api/v1/intelligence/modules/purchase_behavior?period_days=90", headers=headers
    ).json()
    assert result["headline_metrics"]["orders"] == 40


def test_analysis_period_is_bounded(client: TestClient, account: dict):
    """An unbounded period would let one request scan a tenant's whole history."""
    res = client.get(
        "/api/v1/intelligence/modules/purchase_behavior?period_days=3650",
        headers=auth(account),
    )
    assert res.status_code == 422


def test_camera_ingest_requires_a_key(client: TestClient):
    res = client.post("/api/v1/cameras/events", json=[])
    assert res.status_code == 401
