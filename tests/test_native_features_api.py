"""Focused evidence for native feature selection after dataset confirmation."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app
from komus_risk.application.feature_selection import FeatureSelectionService
from komus_risk.contracts import FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.registries import FeatureRegistry


def _prepared_client() -> TestClient:
    client = TestClient(create_app())
    uploaded = client.post(
        "/api/v1/dataset/upload",
        files={"file": ("customer.csv", b"client_id,target,alternate_target,score\na,0,1,0.2\nb,1,0,0.9\nc,0,1,0.1\nd,1,0,0.8\n", "text/csv")},
    )
    assert uploaded.status_code == 200
    assert client.patch("/api/v1/dataset/preparation/draft", json={"positive_class": 1}).status_code == 200
    assert client.post("/api/v1/dataset/preparation/review").status_code == 200
    assert client.post("/api/v1/dataset/preparation/confirm", json={"population_policy_acknowledged": True}).status_code == 200
    return client


def test_feature_selection_is_initialized_from_allowed_registry_rows_and_survives_algorithm() -> None:
    client = _prepared_client()

    features = client.get("/api/v1/features")
    assert features.status_code == 200, features.text
    payload = features.json()
    assert payload["selected_feature_ids"] == [row["feature_id"] for row in payload["features"]]
    assert payload["selected_count"] == payload["available_count"] == len(payload["features"])
    assert "client_id" not in {row["column_name"] for row in payload["features"]}
    assert {group["group_id"] for group in payload["groups"]} == {row["group_id"] for row in payload["features"]}

    cleared = client.patch("/api/v1/features/selection", json={"selected_feature_ids": []})
    assert cleared.status_code == 200
    assert cleared.json()["selected_feature_ids"] == []
    assert cleared.json()["selected_count"] == 0
    denied = client.post("/api/v1/features/continue")
    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "FEATURE_SELECTION_REQUIRED"

    selected_all = client.patch("/api/v1/features/selection", json={"selected_feature_ids": [row["feature_id"] for row in payload["features"]]})
    assert selected_all.status_code == 200
    assert selected_all.json()["selected_count"] == selected_all.json()["available_count"]

    selected = payload["selected_feature_ids"][:1]
    assert client.patch("/api/v1/features/selection", json={"selected_feature_ids": selected}).status_code == 200
    continued = client.post("/api/v1/features/continue")
    assert continued.status_code == 200
    assert continued.json()["current_step"] == 2
    assert continued.json()["resume_route"] == "#/analysis/algorithm"
    assert client.get("/api/v1/features").json()["selected_feature_ids"] == selected


def test_feature_selection_rejects_duplicates_and_non_selectable_context_rows() -> None:
    client = _prepared_client()
    payload = client.get("/api/v1/features").json()
    feature_id = payload["features"][0]["feature_id"]

    duplicate = client.patch("/api/v1/features/selection", json={"selected_feature_ids": [feature_id, feature_id]})
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["code"] == "DUPLICATE_FEATURE_ID"

    forbidden = client.patch("/api/v1/features/selection", json={"selected_feature_ids": ["not-a-feature"]})
    assert forbidden.status_code == 422
    assert forbidden.json()["detail"]["code"] == "UNKNOWN_FEATURE_ID"


def test_changed_selection_after_algorithm_invalidates_completion_and_resume_route() -> None:
    client = _prepared_client()
    features = client.get("/api/v1/features").json()
    selected = features["selected_feature_ids"][:1]

    assert client.patch("/api/v1/features/selection", json={"selected_feature_ids": selected}).status_code == 200
    continued = client.post("/api/v1/features/continue")
    assert continued.status_code == 200
    assert continued.json()["current_step"] == 2
    assert continued.json()["resume_route"] == "#/analysis/algorithm"

    cleared = client.patch("/api/v1/features/selection", json={"selected_feature_ids": []})
    assert cleared.status_code == 200
    session = client.get("/api/v1/session")
    assert session.status_code == 200
    assert session.json()["resume_route"] == "#/analysis/features"

    denied = client.post("/api/v1/features/continue")
    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "FEATURE_SELECTION_REQUIRED"

    changed = client.patch("/api/v1/features/selection", json={"selected_feature_ids": selected})
    assert changed.status_code == 200
    session = client.get("/api/v1/session")
    assert session.status_code == 200
    assert session.json()["current_step"] == 1
    assert session.json()["resume_route"] == "#/analysis/features"
    recontinued = client.post("/api/v1/features/continue")
    assert recontinued.status_code == 200
    assert recontinued.json()["current_step"] == 2
    assert recontinued.json()["resume_route"] == "#/analysis/algorithm"

    changed_again = client.patch("/api/v1/features/selection", json={"selected_feature_ids": []})
    assert changed_again.status_code == 200
    session = client.get("/api/v1/session")
    assert session.status_code == 200
    assert session.json()["current_step"] == 1
    assert session.json()["resume_route"] == "#/analysis/features"


def test_selection_service_never_exposes_non_model_allowed_statuses() -> None:
    statuses = list(FeatureUsageStatus)
    specs = [FeatureSpec(f"id-{status.value}", status.value, status.value, "Description", "group", "string", "unknown", "test", status, "blocked" if status is FeatureUsageStatus.BLOCKED else None, None, None, index) for index, status in enumerate(statuses)]
    registry = FeatureRegistry("registry", specs, [FeatureGroup("group", "Группа", "Тестовая группа", 0, "test", tuple(item.feature_id for item in specs))])
    context = SimpleNamespace(feature_registry=registry)

    service = FeatureSelectionService()
    assert service.initial_selection(context) == ("id-model_allowed",)
