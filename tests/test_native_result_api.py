"""Focused tests for the current-session native Result read boundary."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app
from komus_risk.application.native_session import NativeSessionStore, QualityTrainingStatus


def _completed_session(store: NativeSessionStore, session_id: str, artifact_id: str) -> None:
    session = store._sessions[session_id]
    session.analysis_active = True
    session.data_substep = "PREPARED"
    session.prepared_context_id = "prepared-context"
    session.features_completed = True
    session.selected_feature_ids = ("feature",)
    session.algorithm_completed = True
    session.selected_model_id = "model"
    session.quality_completed = True
    session.quality_training_status = QualityTrainingStatus.COMPLETED
    session.quality_training_artifact_id = artifact_id


class _ResultService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float | None]] = []
        self.summary_value = SimpleNamespace(
            artifact_id="artifact-exact", result_id="result-exact", model_id="catboost",
            model_version="4.1", object_count=120, feature_count=7, folds=5,
            evaluation_level="OOF", runtime_seconds=12.5, gini=0.42, roc_auc=0.71,
            pr_auc=0.38, fold_metrics=({"fold": 1, "roc_auc": 0.7},),
            limitations=("Random folds do not establish temporal stability.",),
        )
        self.threshold_value = SimpleNamespace(
            artifact_id="artifact-exact", threshold=0.5, tp=10, tn=80, fp=20, fn=10,
            precision=1 / 3, recall=0.5, f1=0.4, above_threshold_count=30,
            above_threshold_share=0.25,
        )

    def summary(self, artifact_id: str):
        self.calls.append(("summary", artifact_id, None))
        return self.summary_value

    def threshold(self, artifact_id: str, threshold: float):
        self.calls.append(("threshold", artifact_id, threshold))
        return self.threshold_value


def _client(result_service: _ResultService):
    store = NativeSessionStore()
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(session_store=store, oof_result_service=result_service, prepared_context_authority=authority))
    assert client.get("/api/v1/session").status_code == 200
    session_id = client.cookies.get("axion_session")
    assert session_id
    return client, store, session_id


def test_result_is_not_ready_before_current_training_completion() -> None:
    service = _ResultService()
    client, _store, _session_id = _client(service)

    response = client.get("/api/v1/result")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "RESULT_NOT_READY",
        "message": "Результат полного обучения ещё не готов.",
    }
    assert service.calls == []


def test_result_uses_exact_current_artifact_and_returns_service_values() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result")

    assert response.status_code == 200, response.text
    assert service.calls == [
        ("summary", "artifact-exact", None),
        ("threshold", "artifact-exact", 0.5),
    ]
    payload = response.json()
    assert payload["summary"]["artifact_id"] == "artifact-exact"
    assert payload["summary"]["result_id"] == "result-exact"
    assert payload["summary"]["gini"] == 0.42
    assert payload["summary"]["fold_metrics"] == [{"fold": 1, "roc_auc": 0.7}]
    assert payload["threshold"]["f1"] == 0.4
    assert payload["threshold"]["above_threshold_share"] == 0.25
    assert "filesystem" not in response.text.lower()


def test_result_service_error_is_safe_and_does_not_leak_exception_text() -> None:
    class BrokenService(_ResultService):
        def summary(self, artifact_id: str):
            self.calls.append(("summary", artifact_id, None))
            raise RuntimeError("private path and traceback details")

    service = BrokenService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "RESULT_READ_ERROR",
        "message": "Не удалось прочитать сохранённый результат.",
    }
    assert "private path" not in response.text


def test_session_resume_tracks_completed_artifact_and_quality_invalidation() -> None:
    store = NativeSessionStore()
    session_id, _snapshot = store.get_or_create(None)
    session = store._sessions[session_id]
    session.analysis_active = True
    session.data_substep = "PREPARED"
    session.prepared_context_id = "prepared-context"
    session.features_completed = True
    session.selected_feature_ids = ("feature",)
    session.algorithm_completed = True
    session.selected_model_id = "model"
    assert store.snapshot(session_id).resume_route == "#/analysis/quality"

    _completed_session(store, session_id, "artifact-exact")
    assert store.snapshot(session_id).resume_route == "#/analysis/result"
    assert store.current_result_artifact_id(session_id) == "artifact-exact"

    store.set_quality_settings(session_id, seed=42, folds=5)
    assert store.snapshot(session_id).resume_route == "#/analysis/quality"
    assert store.current_result_artifact_id(session_id) is None
