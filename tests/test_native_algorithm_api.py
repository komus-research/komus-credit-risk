"""Focused contract tests for the native Algorithm boundary."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app


def _algorithm_client() -> TestClient:
    client = TestClient(create_app())
    upload = client.post("/api/v1/dataset/upload", files={"file": ("customers.csv", b"id,target,score\na,0,0.1\nb,1,0.9\nc,0,0.2\nd,1,0.8\n", "text/csv")})
    assert upload.status_code == 200
    assert client.patch("/api/v1/dataset/preparation/draft", json={"positive_class": 1}).status_code == 200
    assert client.post("/api/v1/dataset/preparation/review").status_code == 200
    assert client.post("/api/v1/dataset/preparation/confirm", json={"population_policy_acknowledged": True}).status_code == 200
    assert client.post("/api/v1/features/continue").status_code == 200
    return client


def test_algorithm_catalog_is_explicit_and_selection_is_never_automatic() -> None:
    client = _algorithm_client()
    payload = client.get("/api/v1/algorithm")
    assert payload.status_code == 200, payload.text
    body = payload.json()
    assert body["selected_model_id"] is None
    assert body["configuration_mode"] == "RECOMMENDED"
    assert body["user_overrides"] == {}
    assert body["models"]
    assert {"model_id", "parameter_schema", "state"}.issubset(body["models"][0])
    assert client.patch("/api/v1/algorithm/model", json={"model_id": "not-registered"}).status_code == 422


def test_algorithm_configuration_hide_restore_and_quality_transition() -> None:
    client = _algorithm_client()
    state = client.get("/api/v1/algorithm").json()
    available = next(model for model in state["models"] if model["state"] == "AVAILABLE")
    model_id = available["model_id"]
    selected = client.patch("/api/v1/algorithm/model", json={"model_id": model_id})
    assert selected.status_code == 200
    parameters = [p for p in available["parameter_schema"]["parameters"] if p["editable"]]
    if parameters:
        parameter = parameters[0]
        value = parameter["recommended_value"]
        override = not value if isinstance(value, bool) else value + 1
        configured = client.patch("/api/v1/algorithm/configuration", json={"configuration_mode": "ADVANCED", "user_overrides": {parameter["parameter_path"]: override}})
        assert configured.status_code == 200
        assert configured.json()["configuration_mode"] == "ADVANCED"
        same = client.patch("/api/v1/algorithm/model", json={"model_id": model_id})
        assert same.json()["configuration_mode"] == "ADVANCED"
        another = next(model for model in state["models"] if model["state"] == "AVAILABLE" and model["model_id"] != model_id)
        switched = client.patch("/api/v1/algorithm/model", json={"model_id": another["model_id"]})
        assert switched.json()["configuration_mode"] == "RECOMMENDED"
        assert switched.json()["user_overrides"] == {}
        assert client.patch("/api/v1/algorithm/model", json={"model_id": model_id}).status_code == 200
    hidden = client.post(f"/api/v1/algorithm/models/{model_id}/hide")
    assert hidden.status_code == 200
    assert hidden.json()["selected_model_id"] is None
    restored = client.post(f"/api/v1/algorithm/models/{model_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["selected_model_id"] is None
    assert client.patch("/api/v1/algorithm/model", json={"model_id": model_id}).status_code == 200
    continued = client.post("/api/v1/algorithm/continue")
    assert continued.status_code == 200
    assert continued.json()["current_step"] == 3
    assert continued.json()["resume_route"] == "#/analysis/quality"

    # A repeated model selection and canonical configuration patch are no-ops.
    assert client.patch("/api/v1/algorithm/model", json={"model_id": model_id}).status_code == 200
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/quality"
    before = client.get("/api/v1/algorithm").json()
    same_config = client.patch("/api/v1/algorithm/configuration", json={
        "configuration_mode": before["configuration_mode"],
        "user_overrides": before["user_overrides"],
    })
    assert same_config.status_code == 200
    assert client.get("/api/v1/session").json()["current_step"] == 3
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/quality"

    other_id = next(model["model_id"] for model in state["models"] if model["state"] == "AVAILABLE" and model["model_id"] != model_id)
    assert client.post(f"/api/v1/algorithm/models/{other_id}/hide").json()["selected_model_id"] == model_id
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/quality"
    assert client.post(f"/api/v1/algorithm/models/{other_id}/restore").json()["selected_model_id"] == model_id
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/quality"

    # A real configuration or model change invalidates the completed step.
    changed_config = client.patch("/api/v1/algorithm/configuration", json={"configuration_mode": "ADVANCED", "user_overrides": {}})
    assert changed_config.status_code == 200
    assert client.get("/api/v1/session").json()["current_step"] == 2
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/algorithm"
    assert client.post("/api/v1/algorithm/continue").status_code == 200
    another = next(model["model_id"] for model in state["models"] if model["state"] == "AVAILABLE" and model["model_id"] != model_id)
    changed_model = client.patch("/api/v1/algorithm/model", json={"model_id": another})
    assert changed_model.status_code == 200
    assert changed_model.json()["configuration_mode"] == "RECOMMENDED"
    assert changed_model.json()["user_overrides"] == {}
    assert client.get("/api/v1/session").json()["current_step"] == 2
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/algorithm"
    assert client.post("/api/v1/algorithm/continue").status_code == 200
    assert client.post(f"/api/v1/algorithm/models/{another}/hide").status_code == 200
    final = client.get("/api/v1/algorithm").json()
    assert final["selected_model_id"] is None
    assert final["configuration_mode"] == "RECOMMENDED"
    assert final["user_overrides"] == {}
    assert client.get("/api/v1/session").json()["resume_route"] == "#/analysis/algorithm"
