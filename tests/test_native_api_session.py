"""HTTP boundary tests for the native AXION session foundation."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import SESSION_COOKIE_NAME, create_app
from komus_risk.application.native_session import NativeSessionStore


def test_health_and_session_cookie_reuse() -> None:
    client = TestClient(create_app())

    health = client.get("/api/v1/health")
    first_session = client.get("/api/v1/session")
    cookie = client.cookies.get(SESSION_COOKIE_NAME)
    second_session = client.get("/api/v1/session")

    assert health.json() == {"status": "ok"}
    assert first_session.json() == second_session.json()
    assert cookie is not None
    assert len(cookie) >= 32
    assert SESSION_COOKIE_NAME in first_session.headers["set-cookie"]
    assert "HttpOnly" in first_session.headers["set-cookie"]


def test_new_analysis_contract_requires_confirmation_then_resets() -> None:
    store = NativeSessionStore()
    client = TestClient(create_app(session_store=store))
    client.get("/api/v1/session")
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id is not None
    store.mark_meaningful_temporary_work(session_id)

    confirmation = client.post("/api/v1/analysis/new", json={})
    confirmed = client.post("/api/v1/analysis/new", json={"confirm_reset": True})

    assert confirmation.json() == {
        "status": "CONFIRMATION_REQUIRED",
        "current_step": 0,
        "analysis_active": True,
        "data_substep": "FILE",
        "has_meaningful_temporary_work": True,
        "resume_route": "#/analysis/data/file",
    }
    assert confirmed.json() == {
        "status": "STARTED",
        "current_step": 0,
        "analysis_active": True,
        "data_substep": "FILE",
        "has_meaningful_temporary_work": False,
        "resume_route": "#/analysis/data/file",
    }


def test_new_analysis_rejects_unknown_http_fields() -> None:
    client = TestClient(create_app())

    response = client.post("/api/v1/analysis/new", json={"unknown": True})

    assert response.status_code == 422
