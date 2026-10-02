"""Focused tests for the current-session native Result read boundary."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app
from komus_risk.application.oof_result import OOFResultError
from komus_risk.application.oof_explanation import OOFExplanationError
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
        self.object_calls: list[tuple[object, ...]] = []
        self.detail_calls: list[tuple[str, str, float]] = []
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
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise OOFResultError("INVALID_THRESHOLD")
        return SimpleNamespace(**{**vars(self.threshold_value), "threshold": float(threshold)})

    def objects(self, artifact_id: str, threshold: float, offset: int, limit: int, **query):
        self.object_calls.append((artifact_id, threshold, offset, limit, query))
        if query["sort"] == "INVALID":
            raise OOFResultError("INVALID_QUERY")
        return SimpleNamespace(
            artifact_id=artifact_id,
            threshold=threshold,
            total_count=120,
            filtered_count=2,
            offset=offset,
            limit=limit,
            returned_count=2,
            items=(
                SimpleNamespace(object_id="object-1", identifier_display="Клиент 1", y_true=1, score=0.81, predicted_positive=True, outcome="TP"),
                SimpleNamespace(object_id="object-2", identifier_display="Клиент 2", y_true=0, score=0.23, predicted_positive=False, outcome="TN"),
            ),
        )

    def object_detail(self, artifact_id: str, object_id: str, threshold: float):
        self.detail_calls.append((artifact_id, object_id, threshold))
        return SimpleNamespace(
            artifact_id=artifact_id,
            object_id=object_id,
            identifier_display="Клиент Detail",
            y_true=1,
            score=0.37,
            threshold=threshold,
            predicted_positive=False,
            outcome="FN",
            fold_number=3,
        )


class _ExplanationService:
    def __init__(self, *, feature_count: int = 7, error: Exception | None = None) -> None:
        self.local_calls: list[tuple[str, str]] = []
        self.error = error
        self.features = [
            SimpleNamespace(
                feature_id=f"feature-{rank}",
                column_name=f"column_{rank}",
                display_name_ru=f"Признак {rank}",
                description_ru=f"Описание {rank}",
                raw_value=rank + 0.25,
                shap_value=(-0.1 if rank == 6 else 0.5 if rank == 7 else rank / 10),
                abs_rank=rank,
                direction="decreases_output" if rank == 1 else "increases_output" if rank == 2 else "neutral",
            )
            for rank in range(1, feature_count + 1)
        ]
        self.evidence = SimpleNamespace(
            evidence_version="local_explanation_v2",
            object_id="object-opaque-123",
            evidence_hash="hash-exact",
            prediction_probability=0.731,
            base_value=-0.12,
            explained_output_value=1.002,
            output_space="raw_margin",
            explanation_method_id="catboost_native_shap",
            explanation_method_version="1.2.3",
            provider_id="trusted_provider",
            provider_version="provider-4",
            features=self.features,
            dataset_id="private-dataset",
            dataset_fingerprint="private-fingerprint",
            model_binding_id="private-binding",
            source_kind="private-source-kind",
            provenance={"secret": "private-provenance"},
        )

    def local(self, artifact_id: str, object_id: str):
        self.local_calls.append((artifact_id, object_id))
        if self.error is not None:
            raise self.error
        return self.evidence


def _client(result_service: _ResultService, explanation_service: _ExplanationService | None = None):
    store = NativeSessionStore()
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(
        session_store=store,
        oof_result_service=result_service,
        oof_explanation_service=explanation_service,
        prepared_context_authority=authority,
    ))
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


def test_threshold_patch_is_not_ready_before_current_training_completion() -> None:
    service = _ResultService()
    client, _store, _session_id = _client(service)

    response = client.patch("/api/v1/result/threshold", json={"threshold": 0.65})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert service.calls == []


def test_objects_is_not_ready_before_current_training_completion() -> None:
    service = _ResultService()
    client, _store, _session_id = _client(service)

    response = client.get("/api/v1/result/objects")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "RESULT_NOT_READY",
        "message": "Результат полного обучения ещё не готов.",
    }
    assert service.object_calls == []


def test_object_detail_is_not_ready_before_current_training_completion() -> None:
    service = _ResultService()
    client, _store, _session_id = _client(service)

    response = client.get("/api/v1/result/objects/object-opaque-123")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "RESULT_NOT_READY",
        "message": "Результат полного обучения ещё не готов.",
    }
    assert service.detail_calls == []


def test_object_detail_uses_current_artifact_and_threshold_and_returns_exact_service_values() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")
    assert store.set_current_result_threshold(session_id, "artifact-exact", 0.65)

    response = client.get("/api/v1/result/objects/object-opaque-123")

    assert response.status_code == 200, response.text
    assert service.detail_calls == [("artifact-exact", "object-opaque-123", 0.65)]
    assert response.json() == {
        "artifact_id": "artifact-exact",
        "object_id": "object-opaque-123",
        "identifier_display": "Клиент Detail",
        "y_true": 1,
        "score": 0.37,
        "threshold": 0.65,
        "predicted_positive": False,
        "outcome": "FN",
        "fold_number": 3,
    }


def test_object_detail_not_found_is_mapped_to_404() -> None:
    class MissingObjectService(_ResultService):
        def object_detail(self, artifact_id: str, object_id: str, threshold: float):
            self.detail_calls.append((artifact_id, object_id, threshold))
            raise OOFResultError("OBJECT_NOT_FOUND")

    service = MissingObjectService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "OBJECT_NOT_FOUND",
        "message": "Объект не найден в текущем OOF-результате.",
    }
    assert service.detail_calls == [("artifact-exact", "object-missing", 0.5)]


def test_object_detail_unexpected_error_is_safe() -> None:
    class BrokenService(_ResultService):
        def object_detail(self, *args, **kwargs):
            raise RuntimeError("private artifact path")

    service = BrokenService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-opaque-123")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "RESULT_READ_ERROR",
        "message": "Не удалось прочитать сохранённый результат.",
    }
    assert "private artifact path" not in response.text


def test_object_detail_uses_new_current_threshold_after_threshold_change() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    assert client.patch("/api/v1/result/threshold", json={"threshold": 0.7}).status_code == 200
    response = client.get("/api/v1/result/objects/object-opaque-123")

    assert response.status_code == 200
    assert service.detail_calls == [("artifact-exact", "object-opaque-123", 0.7)]


def test_object_detail_is_not_ready_after_quality_invalidation() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")
    store.set_quality_settings(session_id, seed=42, folds=5)

    response = client.get("/api/v1/result/objects/object-opaque-123")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert service.detail_calls == []


def test_objects_use_current_artifact_threshold_and_exact_query() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")
    assert store.set_current_result_threshold(session_id, "artifact-exact", 0.65)

    response = client.get(
        "/api/v1/result/objects",
        params=[
            ("offset", "120000"), ("limit", "50"), ("search", " Клиент "),
            ("target", "POSITIVE"), ("outcomes", "FP"), ("outcomes", "FN"),
            ("min_score", "0.2"), ("max_score", "0.8"),
            ("sort", "DISTANCE_TO_THRESHOLD_ASC"),
        ],
    )

    assert response.status_code == 200, response.text
    assert service.object_calls == [(
        "artifact-exact", 0.65, 120000, 50,
        {"search": " Клиент ", "target": "POSITIVE", "outcomes": ["FP", "FN"], "min_score": 0.2, "max_score": 0.8, "sort": "DISTANCE_TO_THRESHOLD_ASC"},
    )]
    assert response.json() == {
        "artifact_id": "artifact-exact", "threshold": 0.65,
        "total_count": 120, "filtered_count": 2, "offset": 120000, "limit": 50,
        "returned_count": 2,
        "items": [
            {"object_id": "object-1", "identifier_display": "Клиент 1", "y_true": 1, "score": 0.81, "predicted_positive": True, "outcome": "TP"},
            {"object_id": "object-2", "identifier_display": "Клиент 2", "y_true": 0, "score": 0.23, "predicted_positive": False, "outcome": "TN"},
        ],
    }


def test_objects_invalid_query_is_safe() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects", params={"sort": "INVALID"})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "INVALID_QUERY",
        "message": "Параметры списка объектов некорректны.",
    }


def test_objects_use_new_current_threshold_after_threshold_change() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    assert client.patch("/api/v1/result/threshold", json={"threshold": 0.7}).status_code == 200
    response = client.get("/api/v1/result/objects")

    assert response.status_code == 200
    assert service.object_calls == [(
        "artifact-exact", 0.7, 0, 50,
        {"search": None, "target": "ANY", "outcomes": None, "min_score": None, "max_score": None, "sort": "SCORE_DESC"},
    )]


def test_objects_are_not_ready_after_quality_invalidation() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")
    store.set_quality_settings(session_id, seed=42, folds=5)

    response = client.get("/api/v1/result/objects")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert service.object_calls == []


def test_objects_unexpected_error_is_safe() -> None:
    class BrokenService(_ResultService):
        def objects(self, *args, **kwargs):
            raise RuntimeError("private artifact path")

    service = BrokenService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "RESULT_READ_ERROR",
        "message": "Не удалось прочитать сохранённый результат.",
    }
    assert "private artifact path" not in response.text


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


def test_threshold_patch_saves_session_value_and_next_get_uses_it() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.patch("/api/v1/result/threshold", json={"threshold": 0.65})

    assert response.status_code == 200, response.text
    assert service.calls == [("threshold", "artifact-exact", 0.65)]
    assert response.json() == {
        "threshold": 0.65, "tp": 10, "tn": 80, "fp": 20, "fn": 10,
        "precision": 1 / 3, "recall": 0.5, "f1": 0.4,
        "above_threshold_count": 30, "above_threshold_share": 0.25,
    }
    assert store.current_result_threshold(session_id) == 0.65

    service.calls.clear()
    overview = client.get("/api/v1/result")

    assert overview.status_code == 200
    assert service.calls == [
        ("summary", "artifact-exact", None),
        ("threshold", "artifact-exact", 0.65),
    ]
    assert overview.json()["threshold"]["threshold"] == 0.65


def test_invalid_threshold_does_not_change_current_session_value() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.patch("/api/v1/result/threshold", json={"threshold": 1.5})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "INVALID_THRESHOLD",
        "message": "Порог должен быть числом от 0 до 1.",
    }
    assert store.current_result_threshold(session_id) == 0.5


def test_threshold_patch_service_error_is_safe_and_does_not_change_session() -> None:
    class BrokenService(_ResultService):
        def threshold(self, artifact_id: str, threshold: float):
            self.calls.append(("threshold", artifact_id, threshold))
            raise RuntimeError("private path and traceback details")

    service = BrokenService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.patch("/api/v1/result/threshold", json={"threshold": 0.65})

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "RESULT_READ_ERROR",
        "message": "Не удалось прочитать сохранённый результат.",
    }
    assert "private path" not in response.text
    assert store.current_result_threshold(session_id) == 0.5


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
    assert store.current_result_threshold(session_id) == 0.5
    assert store.set_current_result_threshold(session_id, "artifact-exact", 0.7)
    assert store.current_result_threshold(session_id) == 0.7

    store.set_quality_settings(session_id, seed=42, folds=5)
    assert store.snapshot(session_id).resume_route == "#/analysis/quality"
    assert store.current_result_artifact_id(session_id) is None
    assert store.current_result_threshold(session_id) is None
    assert store._sessions[session_id].result_threshold == 0.5


def test_explanation_is_not_ready_without_current_result() -> None:
    explanation = _ExplanationService()
    client, _store, _session_id = _client(_ResultService(), explanation)

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "RESULT_NOT_READY",
        "message": "Результат полного обучения ещё не готов.",
    }
    assert explanation.local_calls == []


def test_explanation_uses_exact_current_artifact_and_public_projection() -> None:
    explanation = _ExplanationService()
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 200, response.text
    assert explanation.local_calls == [("artifact-exact", "object-opaque-123")]
    payload = response.json()
    assert set(payload) == {
        "evidence_version", "artifact_id", "object_id", "evidence_hash",
        "prediction_probability", "base_value", "explained_output_value", "output_space",
        "explanation_method_id", "explanation_method_version", "explanation_provider_id",
        "explanation_provider_version", "features", "remainder",
    }
    assert payload == {
        "evidence_version": "local_explanation_v2",
        "artifact_id": "artifact-exact",
        "object_id": "object-opaque-123",
        "evidence_hash": "hash-exact",
        "prediction_probability": 0.731,
        "base_value": -0.12,
        "explained_output_value": 1.002,
        "output_space": "raw_margin",
        "explanation_method_id": "catboost_native_shap",
        "explanation_method_version": "1.2.3",
        "explanation_provider_id": "trusted_provider",
        "explanation_provider_version": "provider-4",
        "features": [
            {
                "feature_id": f"feature-{rank}",
                "column_name": f"column_{rank}",
                "display_name_ru": f"Признак {rank}",
                "description_ru": f"Описание {rank}",
                "raw_value": rank + 0.25,
                "shap_value": -0.1 if rank == 6 else 0.5 if rank == 7 else rank / 10,
                "abs_rank": rank,
                "direction": "decreases_output" if rank == 1 else "increases_output" if rank == 2 else "neutral",
            }
            for rank in range(1, 8)
        ],
        "remainder": {"feature_count": 2, "shap_value": 0.4, "direction": "increases_output"},
    }
    for internal_name in (
        "dataset_id", "dataset_fingerprint", "model_binding_id", "source_kind", "provenance",
    ):
        assert internal_name not in payload
    assert "threshold" not in payload


def test_explanation_remainder_is_null_for_five_or_fewer_features() -> None:
    explanation = _ExplanationService(feature_count=5)
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 200
    assert response.json()["remainder"] is None


def test_explanation_is_threshold_independent() -> None:
    explanation = _ExplanationService()
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    threshold_response = client.patch("/api/v1/result/threshold", json={"threshold": 0.8})
    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert threshold_response.status_code == 200
    assert response.status_code == 200
    assert explanation.local_calls == [("artifact-exact", "object-opaque-123")]
    assert "threshold" not in response.json()


def test_explanation_is_not_ready_after_quality_invalidation() -> None:
    explanation = _ExplanationService()
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")
    store.set_quality_settings(session_id, seed=42, folds=5)

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert explanation.local_calls == []


def test_explanation_object_not_found_is_safe() -> None:
    explanation = _ExplanationService(error=OOFExplanationError("OBJECT_NOT_FOUND"))
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-missing/explanation")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "OBJECT_NOT_FOUND",
        "message": "Объект не найден в текущем OOF-результате.",
    }


def test_explanation_unsupported_is_safe() -> None:
    code = "LOCAL_OOF_EXPLANATION_UNSUPPORTED"
    explanation = _ExplanationService(error=OOFExplanationError(code))
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": code,
        "message": "Для этой модели локальное объяснение недоступно.",
    }


@pytest.mark.parametrize("code", [
    "OOF_RESULT_EVIDENCE_INCOMPLETE",
    "FOLD_MODEL_UNAVAILABLE",
    "PROVENANCE_MISMATCH",
    "OOF_PREDICTION_MISMATCH",
])
def test_explanation_integrity_errors_are_safe(code: str) -> None:
    explanation = _ExplanationService(error=OOFExplanationError(code))
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": code,
        "message": "Не удалось безопасно построить объяснение для сохранённой OOF-оценки. Сам результат объекта остаётся доступен.",
    }


def test_explanation_unexpected_error_does_not_leak_exception_text() -> None:
    explanation = _ExplanationService(error=RuntimeError("private fold model path"))
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/objects/object-opaque-123/explanation")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "LOCAL_EXPLANATION_ERROR",
        "message": "Не удалось построить объяснение. Сам результат объекта остаётся доступен.",
    }
    assert "private fold model path" not in response.text
