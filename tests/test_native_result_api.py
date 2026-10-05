"""Focused tests for the current-session native Result read boundary."""

from __future__ import annotations

from pathlib import Path
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app
from app.native_runtime import create_native_experiment_runtime
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
        self.sweep_calls: list[str] = []
        self.object_calls: list[tuple[object, ...]] = []
        self.detail_calls: list[tuple[str, str, float]] = []
        self.summary_value = SimpleNamespace(
            artifact_id="artifact-exact", result_id="result-exact", model_id="catboost",
            model_version="4.1", object_count=120, feature_count=7, folds=5,
            evaluation_level="OOF", runtime_seconds=12.5, gini=0.42, roc_auc=0.71,
            pr_auc=0.38, fold_metrics=({"fold": 1, "roc_auc": 0.7},),
            limitations=("Random folds do not establish temporal stability.",),
            capture=SimpleNamespace(
                total_positive_events=20,
                points=(
                    SimpleNamespace(object_share=0.0, event_share=0.0),
                    SimpleNamespace(object_share=0.15, event_share=0.6),
                    SimpleNamespace(object_share=1.0, event_share=1.0),
                ),
                marker=SimpleNamespace(object_share=0.15, event_share=0.6),
            ),
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

    def threshold_sweep(self, artifact_id: str):
        self.sweep_calls.append(artifact_id)
        return tuple(
            SimpleNamespace(**{**vars(self.threshold_value), "threshold": index / 50})
            for index in range(51)
        )

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


class _ArtifactStore:
    def __init__(self) -> None:
        self.loads: list[str] = []
        self.artifact = SimpleNamespace(
            dataset_contract=SimpleNamespace(dataset_name="Trusted dataset"),
            config=SimpleNamespace(folds=4),
        )

    def load(self, artifact_id: str):
        self.loads.append(artifact_id)
        return self.artifact


class _GlobalExplanationService:
    def __init__(self, *, error: Exception | None = None, on_call=None, state: str = "READY") -> None:
        self.calls: list[str] = []
        self.heavy_calls: list[str] = []
        self.start_calls: list[str] = []
        self.worker_starts = 0
        self.retry_calls: list[str] = []
        self.state = state
        self.error = error
        self.on_call = on_call
        self.evidence = SimpleNamespace(
            artifact_id="untrusted-other-artifact",
            model_id="catboost",
            model_version="4.1",
            row_count=120,
            feature_count=3,
            output_space="raw_margin",
            evidence_hash="global-hash",
            provider_id="private-provider",
            provider_version="private-version",
            explanation_method_id="private-method",
            explanation_method_version="private-method-version",
            background_policy_id="private-background",
            feature_binding_hash="private-binding-hash",
            fold_model_binding_ids=("private-fold-binding",),
            features=(
                SimpleNamespace(feature_id="feature-1", column_name="column_1", mean_abs_shap=0.6, rank=1),
                SimpleNamespace(feature_id="feature-2", column_name="column_2", mean_abs_shap=0.3, rank=2),
                SimpleNamespace(feature_id="feature-3", column_name="column_3", mean_abs_shap=0.1, rank=3),
            ),
        )

    def global_oof(self, artifact_id: str):
        self.heavy_calls.append(artifact_id)
        return self.global_oof_ready_result(artifact_id)

    def global_oof_ready_result(self, artifact_id: str):
        self.calls.append(artifact_id)
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
        if self.state != "READY":
            raise OOFExplanationError("GLOBAL_OOF_RESULT_NOT_READY")
        return self.evidence

    def _snapshot(self, artifact_id: str):
        status = self.state
        stage = "READY" if status == "READY" else "FAILED" if status == "FAILED" else "PROCESSING_FOLD" if status == "RUNNING" else "VALIDATING"
        return SimpleNamespace(
            artifact_id=artifact_id, derivation_key="safe-test-key", status=status,
            stage=stage, stage_label="Обработка части" if status == "RUNNING" else "Готово" if status == "READY" else "Не запущено",
            current_fold=1 if status == "RUNNING" else None, total_folds=4,
            processed_rows=25 if status == "RUNNING" else 0, total_rows=120,
            started_at="2026-10-04T10:00:00Z" if status == "RUNNING" else None,
            updated_at="2026-10-04T10:00:00Z", elapsed_seconds=2.0,
            safe_error_code="GLOBAL_OOF_EXPLANATION_FAILED" if status == "FAILED" else None,
        )

    def start_global_oof(self, artifact_id: str):
        self.start_calls.append(artifact_id)
        if self.on_call is not None:
            self.on_call()
        if self.state == "NOT_STARTED":
            self.worker_starts += 1
            self.state = "RUNNING"
        return self._snapshot(artifact_id)

    def global_oof_status(self, artifact_id: str):
        if self.on_call is not None:
            self.on_call()
        return self._snapshot(artifact_id)

    def retry_global_oof(self, artifact_id: str):
        if self.state != "FAILED":
            raise ValueError("GLOBAL_OOF_RETRY_NOT_AVAILABLE")
        self.retry_calls.append(artifact_id)
        self.state = "RUNNING"
        return self._snapshot(artifact_id)


class _IntegrationWorkflowService:
    def __init__(self, *, state: str = "AVAILABLE", reason_code: str = "RESULT_INTERPRETER_READY", error: Exception | None = None, fail_at: str | None = None, on_interpret=None) -> None:
        self.state = state
        self.reason_code = reason_code
        self.error = error
        self.fail_at = fail_at
        self.on_interpret = on_interpret
        self.capability_calls: list[object] = []
        self.prepare_calls: list[tuple[object, str]] = []
        self.interpret_calls: list[object] = []
        self.global_capability_calls: list[bool] = []
        self.global_prepare_calls: list[tuple[object, object, object, str]] = []
        self.global_interpret_calls: list[object] = []
        self.request = object()
        self.global_request = object()
        self.outcome = SimpleNamespace(
            response=SimpleNamespace(
                text="Trusted interpretation",
                created_at="2026-10-02T10:00:00Z",
                response_hash="response-hash",
                request_hash="private-request-hash",
                prompt_id="private-prompt",
                prompt_version="private-version",
                prompt_hash="private-prompt-hash",
                interpreter_id="private-interpreter",
                interpreter_model="private-model",
            ),
            dispatch_receipt=SimpleNamespace(payload={"secret": "private-provider-payload"}),
        )

    def capabilities(self, *, local_explanation_evidence):
        self.capability_calls.append(local_explanation_evidence)
        return {"result_interpretation": SimpleNamespace(state=self.state, reason_code=self.reason_code)}

    def prepare_interpretation(self, *, evidence, recipient_role):
        self.prepare_calls.append((evidence, recipient_role))
        if self.fail_at == "prepare":
            raise self.error or RuntimeError("private prepare details")
        return self.request

    def interpret(self, *, request):
        self.interpret_calls.append(request)
        if self.on_interpret is not None:
            self.on_interpret()
        if self.fail_at == "interpret":
            raise self.error or RuntimeError("private provider details")
        return self.outcome

    def global_result_interpretation_capability(self, *, global_evidence_ready: bool):
        self.global_capability_calls.append(global_evidence_ready)
        return SimpleNamespace(state=self.state, reason_code=self.reason_code)

    def prepare_global_interpretation(self, *, summary, threshold, global_explanation, recipient_role):
        self.global_prepare_calls.append((summary, threshold, global_explanation, recipient_role))
        if self.fail_at == "prepare_global":
            raise self.error or RuntimeError("private global prepare details")
        return self.global_request

    def interpret_global(self, *, request):
        self.global_interpret_calls.append(request)
        if self.on_interpret is not None:
            self.on_interpret()
        if self.fail_at == "interpret_global":
            raise self.error or RuntimeError("private global provider details")
        return self.outcome


def _client(
    result_service: _ResultService,
    explanation_service: _ExplanationService | _GlobalExplanationService | None = None,
    artifact_store: _ArtifactStore | None = None,
    integration_workflow_service: _IntegrationWorkflowService | None = None,
):
    store = NativeSessionStore()
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(
        session_store=store,
        oof_result_service=result_service,
        oof_explanation_service=explanation_service,
        experiment_artifact_store=artifact_store,
        prepared_context_authority=authority,
        integration_workflow_service=integration_workflow_service,
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
    assert payload["capture"] == {
        "total_positive_events": 20,
        "points": [
            {"object_share": 0.0, "event_share": 0.0},
            {"object_share": 0.15, "event_share": 0.6},
            {"object_share": 1.0, "event_share": 1.0},
        ],
        "marker": {"object_share": 0.15, "event_share": 0.6},
    }
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


def test_threshold_preview_recomputes_without_saving_session_value() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")
    assert store.current_result_threshold(session_id) == 0.5

    response = client.get("/api/v1/result/threshold", params={"threshold": 0.37})

    assert response.status_code == 200, response.text
    assert service.calls == [("threshold", "artifact-exact", 0.37)]
    assert response.json()["threshold"] == 0.37
    assert store.current_result_threshold(session_id) == 0.5


def test_threshold_sweep_returns_bounded_curve_without_saving_session_value() -> None:
    service = _ResultService()
    client, store, session_id = _client(service)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/threshold/sweep")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert service.sweep_calls == ["artifact-exact"]
    assert len(payload) == 51
    assert payload[0]["threshold"] == 0.0
    assert payload[25]["threshold"] == 0.5
    assert payload[-1]["threshold"] == 1.0
    assert store.current_result_threshold(session_id) == 0.5


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


def test_interpretation_is_not_ready_without_current_result() -> None:
    explanation = _ExplanationService()
    workflow = _IntegrationWorkflowService()
    client, _store, _session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/lawyer"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert explanation.local_calls == []
    assert workflow.capability_calls == []


def test_interpretation_rejects_invalid_role_before_trusted_services() -> None:
    explanation = _ExplanationService()
    workflow = _IntegrationWorkflowService()
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/administrator"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_INTERPRETER_ROLE"
    assert explanation.local_calls == []
    assert workflow.capability_calls == []


def test_interpretation_uses_trusted_binding_role_and_safe_response_projection() -> None:
    explanation = _ExplanationService()
    workflow = _IntegrationWorkflowService()
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/sales_manager"
    )

    assert response.status_code == 200, response.text
    assert explanation.local_calls == [("artifact-exact", "object-opaque-123")]
    assert workflow.capability_calls == [explanation.evidence]
    assert workflow.prepare_calls == [(explanation.evidence, "sales_manager")]
    assert workflow.interpret_calls == [workflow.request]
    assert response.json() == {
        "artifact_id": "artifact-exact",
        "object_id": "object-opaque-123",
        "role": "sales_manager",
        "text": "Trusted interpretation",
        "created_at": "2026-10-02T10:00:00Z",
        "response_hash": "response-hash",
    }
    for private_value in (
        "private-request-hash", "private-prompt", "private-prompt-hash",
        "private-interpreter", "private-model", "private-provider-payload",
    ):
        assert private_value not in response.text




def test_global_interpretation_is_not_ready_without_current_result() -> None:
    explanation = _GlobalExplanationService()
    workflow = _IntegrationWorkflowService()
    client, _store, _session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )

    response = client.post("/api/v1/result/interpretations/lawyer")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert explanation.calls == []
    assert workflow.global_capability_calls == []


def test_global_interpretation_uses_aggregate_result_and_safe_response_projection() -> None:
    result = _ResultService()
    explanation = _GlobalExplanationService()
    workflow = _IntegrationWorkflowService()
    client, store, session_id = _client(
        result, explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post("/api/v1/result/interpretations/credit_controller")

    assert response.status_code == 200, response.text
    assert explanation.calls == ["artifact-exact"]
    assert workflow.global_capability_calls == [True]
    assert len(workflow.global_prepare_calls) == 1
    summary_arg, threshold_arg, explanation_arg, role_arg = workflow.global_prepare_calls[0]
    assert summary_arg is result.summary_value
    assert threshold_arg.threshold == 0.5
    assert explanation_arg is explanation.evidence
    assert role_arg == "credit_controller"
    assert workflow.global_interpret_calls == [workflow.global_request]
    assert response.json() == {
        "artifact_id": "artifact-exact",
        "role": "credit_controller",
        "text": "Trusted interpretation",
        "created_at": "2026-10-02T10:00:00Z",
        "response_hash": "response-hash",
    }
    assert "private-request-hash" not in response.text
    assert "private-provider-payload" not in response.text


def test_global_interpretation_capability_blocks_provider() -> None:
    explanation = _GlobalExplanationService()
    workflow = _IntegrationWorkflowService(
        state="DISABLED", reason_code="EXTERNAL_DATA_POLICY_DISABLED"
    )
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post("/api/v1/result/interpretations/sales_manager")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXTERNAL_DATA_POLICY_DISABLED"
    assert workflow.global_prepare_calls == []
    assert workflow.global_interpret_calls == []


def test_global_interpretation_discards_response_when_threshold_changes() -> None:
    explanation = _GlobalExplanationService()
    store = NativeSessionStore()
    session_id, _snapshot = store.get_or_create(None)
    _completed_session(store, session_id, "artifact-exact")
    workflow = _IntegrationWorkflowService(
        on_interpret=lambda: store.set_current_result_threshold(
            session_id, "artifact-exact", 0.61
        )
    )
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(
        session_store=store,
        oof_result_service=_ResultService(),
        oof_explanation_service=explanation,
        prepared_context_authority=authority,
        integration_workflow_service=workflow,
    ))
    client.cookies.set("axion_session", session_id)

    response = client.post("/api/v1/result/interpretations/lawyer")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_CHANGED"
    assert "Trusted interpretation" not in response.text


def test_app_uses_native_runtime_workflow_when_not_injected(monkeypatch) -> None:
    workflow = _IntegrationWorkflowService()
    native_runtime = replace(
        create_native_experiment_runtime(),
        integration_workflow_service=workflow,
    )
    monkeypatch.setattr(
        "app.api.main.create_native_experiment_runtime",
        lambda: native_runtime,
    )
    explanation = _ExplanationService()
    store = NativeSessionStore()
    session_id, _snapshot = store.get_or_create(None)
    _completed_session(store, session_id, "artifact-exact")
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(
        session_store=store,
        oof_result_service=_ResultService(),
        oof_explanation_service=explanation,
        prepared_context_authority=authority,
    ))
    client.cookies.set("axion_session", session_id)

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/lawyer"
    )

    assert response.status_code == 200, response.text
    assert workflow.capability_calls == [explanation.evidence]
    assert workflow.prepare_calls == [(explanation.evidence, "lawyer")]
    assert workflow.interpret_calls == [workflow.request]


def test_interpretation_capability_blocks_prepare_and_interpret() -> None:
    explanation = _ExplanationService()
    workflow = _IntegrationWorkflowService(state="DISABLED", reason_code="EXTERNAL_DATA_POLICY_DISABLED")
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/credit_controller"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXTERNAL_DATA_POLICY_DISABLED"
    assert workflow.prepare_calls == []
    assert workflow.interpret_calls == []


def test_interpretation_object_not_found_is_safe() -> None:
    explanation = _ExplanationService(error=OOFExplanationError("OBJECT_NOT_FOUND"))
    workflow = _IntegrationWorkflowService()
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post(
        "/api/v1/result/objects/object-missing/interpretations/lawyer"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "OBJECT_NOT_FOUND"
    assert workflow.capability_calls == []


@pytest.mark.parametrize("fail_at", ["prepare", "interpret"])
def test_interpretation_failure_does_not_leak_exception_details(fail_at: str) -> None:
    explanation = _ExplanationService()
    workflow = _IntegrationWorkflowService(
        fail_at=fail_at, error=RuntimeError("private provider path and API key")
    )
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/information_security"
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "RESULT_INTERPRETER_ERROR"
    assert "private provider path" not in response.text
    assert "API key" not in response.text


def test_interpretation_discards_response_when_current_artifact_changes() -> None:
    explanation = _ExplanationService()
    store = NativeSessionStore()
    session_id, _snapshot = store.get_or_create(None)
    _completed_session(store, session_id, "artifact-exact")
    workflow = _IntegrationWorkflowService(
        on_interpret=lambda: store.set_quality_settings(session_id, seed=42, folds=5)
    )
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(
        session_store=store,
        oof_result_service=_ResultService(),
        oof_explanation_service=explanation,
        prepared_context_authority=authority,
        integration_workflow_service=workflow,
    ))
    client.cookies.set("axion_session", session_id)

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/lawyer"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_CHANGED"
    assert "Trusted interpretation" not in response.text


def test_interpretation_capability_unavailable_preserves_reason_code() -> None:
    explanation = _ExplanationService()
    workflow = _IntegrationWorkflowService(state="MISCONFIGURED", reason_code="RESULT_INTERPRETER_PROMPTS_INVALID")
    client, store, session_id = _client(
        _ResultService(), explanation, integration_workflow_service=workflow
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.post(
        "/api/v1/result/objects/object-opaque-123/interpretations/information_security"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_INTERPRETER_PROMPTS_INVALID"
    assert workflow.prepare_calls == []
    assert workflow.interpret_calls == []


def test_global_explanation_is_not_ready_without_current_result() -> None:
    explanation = _GlobalExplanationService()
    artifact_store = _ArtifactStore()
    client, _store, _session_id = _client(
        _ResultService(), explanation, artifact_store
    )

    response = client.get("/api/v1/result/explanation/global")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_NOT_READY"
    assert explanation.calls == []
    assert artifact_store.loads == []


def test_global_explanation_not_ready_is_read_only_and_does_not_compute() -> None:
    explanation = _GlobalExplanationService(state="NOT_STARTED")
    artifact_store = _ArtifactStore()
    client, store, session_id = _client(_ResultService(), explanation, artifact_store)
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/explanation/global")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "GLOBAL_OOF_RESULT_NOT_READY",
        "message": "Расчёт влияния признаков ещё не готов.",
    }
    assert explanation.heavy_calls == []


def test_global_run_starts_once_and_status_is_read_only() -> None:
    explanation = _GlobalExplanationService(state="NOT_STARTED")
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    first = client.post("/api/v1/result/explanation/global/run")
    joined = client.post("/api/v1/result/explanation/global/run", json={"retry": False})
    status = client.get("/api/v1/result/explanation/global/status")

    assert first.status_code == joined.status_code == status.status_code == 200
    assert first.json()["status"] == joined.json()["status"] == status.json()["status"] == "RUNNING"
    assert explanation.worker_starts == 1
    assert explanation.heavy_calls == []
    assert explanation.calls == []


def test_global_operation_failure_message_is_safe_and_retry_starts_one_attempt() -> None:
    explanation = _GlobalExplanationService(state="FAILED")
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    failed = client.post("/api/v1/result/explanation/global/run", json={"retry": False})
    retried = client.post("/api/v1/result/explanation/global/run", json={"retry": True})

    assert failed.status_code == retried.status_code == 200
    assert failed.json()["status"] == "FAILED"
    assert failed.json()["message"] == "Не удалось рассчитать влияние признаков. Сам результат модели остаётся доступен."
    assert retried.json()["status"] == "RUNNING"
    assert explanation.retry_calls == ["artifact-exact"]
    assert "private" not in failed.text


def test_global_run_rejects_browser_artifact_authority() -> None:
    explanation = _GlobalExplanationService(state="NOT_STARTED")
    client, store, session_id = _client(_ResultService(), explanation)
    _completed_session(store, session_id, "artifact-exact")

    response = client.post("/api/v1/result/explanation/global/run", json={"retry": False, "artifact_id": "other"})

    assert response.status_code == 422
    assert explanation.start_calls == []


def test_global_run_fails_if_current_artifact_changes_during_request() -> None:
    store = NativeSessionStore()
    explanation = _GlobalExplanationService(state="NOT_STARTED", on_call=lambda: store.set_quality_settings(session_id, seed=42, folds=5))
    client = TestClient(create_app(
        session_store=store, oof_result_service=_ResultService(), oof_explanation_service=explanation,
        prepared_context_authority=SimpleNamespace(resolve=lambda _context_id: object()),
    ))
    client.get("/api/v1/session")
    session_id = client.cookies.get("axion_session")
    assert session_id
    _completed_session(store, session_id, "artifact-exact")

    response = client.post("/api/v1/result/explanation/global/run")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_CHANGED"


def test_global_status_fails_if_current_artifact_changes_during_request() -> None:
    store = NativeSessionStore()
    explanation = _GlobalExplanationService(state="RUNNING", on_call=lambda: store.set_quality_settings(session_id, seed=42, folds=5))
    client = TestClient(create_app(
        session_store=store, oof_result_service=_ResultService(), oof_explanation_service=explanation,
        prepared_context_authority=SimpleNamespace(resolve=lambda _context_id: object()),
    ))
    client.get("/api/v1/session")
    session_id = client.cookies.get("axion_session")
    assert session_id
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/explanation/global/status")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESULT_CHANGED"


def test_global_explanation_projects_complete_safe_ranked_dto_from_trusted_artifact() -> None:
    explanation = _GlobalExplanationService()
    artifact_store = _ArtifactStore()
    client, store, session_id = _client(
        _ResultService(), explanation, artifact_store
    )
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/explanation/global")

    assert response.status_code == 200, response.text
    assert explanation.calls == ["artifact-exact"]
    assert artifact_store.loads == ["artifact-exact"]
    payload = response.json()
    assert set(payload) == {
        "artifact_id", "model_id", "model_version", "dataset_name", "row_count",
        "feature_count", "folds", "output_space", "evidence_hash", "features",
    }
    assert payload == {
        "artifact_id": "artifact-exact",
        "model_id": "catboost",
        "model_version": "4.1",
        "dataset_name": "Trusted dataset",
        "row_count": 120,
        "feature_count": 3,
        "folds": 4,
        "output_space": "raw_margin",
        "evidence_hash": "global-hash",
        "features": [
            {"feature_id": "feature-1", "column_name": "column_1", "mean_abs_shap": 0.6, "rank": 1},
            {"feature_id": "feature-2", "column_name": "column_2", "mean_abs_shap": 0.3, "rank": 2},
            {"feature_id": "feature-3", "column_name": "column_3", "mean_abs_shap": 0.1, "rank": 3},
        ],
    }
    assert "threshold" not in payload
    for internal_name in (
        "provider_id", "provider_version", "explanation_method_id",
        "explanation_method_version", "background_policy_id", "feature_binding_hash",
        "fold_model_binding_ids", "fold_model_paths", "background_hashes", "provenance",
    ):
        assert internal_name not in response.text


def test_global_explanation_error_mappings_are_safe() -> None:
    cases = [
        ("GLOBAL_OOF_EXPLANATION_UNSUPPORTED", "Для этой модели глобальное OOF-объяснение недоступно."),
        ("OOF_RESULT_EVIDENCE_INCOMPLETE", "Не удалось безопасно построить глобальное объяснение сохранённого OOF-результата. Сам результат остаётся доступен."),
        ("FOLD_MODEL_UNAVAILABLE", "Не удалось безопасно построить глобальное объяснение сохранённого OOF-результата. Сам результат остаётся доступен."),
        ("PROVENANCE_MISMATCH", "Не удалось безопасно построить глобальное объяснение сохранённого OOF-результата. Сам результат остаётся доступен."),
        ("OOF_PREDICTION_MISMATCH", "Не удалось безопасно построить глобальное объяснение сохранённого OOF-результата. Сам результат остаётся доступен."),
        ("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE", "Не удалось безопасно построить глобальное объяснение сохранённого OOF-результата. Сам результат остаётся доступен."),
    ]
    for code, message in cases:
        explanation = _GlobalExplanationService(error=OOFExplanationError(code))
        client, store, session_id = _client(_ResultService(), explanation, _ArtifactStore())
        _completed_session(store, session_id, "artifact-exact")

        response = client.get("/api/v1/result/explanation/global")

        assert response.status_code == 409
        assert response.json()["detail"] == {"code": code, "message": message}


def test_global_explanation_unexpected_error_does_not_leak_details() -> None:
    explanation = _GlobalExplanationService(error=RuntimeError("private provider path"))
    client, store, session_id = _client(_ResultService(), explanation, _ArtifactStore())
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/explanation/global")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "GLOBAL_OOF_EXPLANATION_FAILED"
    assert response.json()["detail"]["message"]
    assert "private provider path" not in response.text


def test_global_explanation_discards_result_when_current_artifact_changes_during_call() -> None:
    store = NativeSessionStore()
    session_id, _snapshot = store.get_or_create(None)
    _completed_session(store, session_id, "artifact-exact")

    def invalidate() -> None:
        store.set_quality_settings(session_id, seed=42, folds=5)

    explanation = _GlobalExplanationService(on_call=invalidate)
    artifact_store = _ArtifactStore()
    authority = SimpleNamespace(resolve=lambda _context_id: object())
    client = TestClient(create_app(
        session_store=store,
        oof_result_service=_ResultService(),
        oof_explanation_service=explanation,
        experiment_artifact_store=artifact_store,
        prepared_context_authority=authority,
    ))
    client.cookies.set("axion_session", session_id)

    response = client.get("/api/v1/result/explanation/global")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "RESULT_CHANGED",
        "message": "Текущий результат изменился. Откройте влияние признаков заново.",
    }


def test_global_explanation_is_independent_of_diagnostic_threshold() -> None:
    explanation = _GlobalExplanationService()
    client, store, session_id = _client(_ResultService(), explanation, _ArtifactStore())
    _completed_session(store, session_id, "artifact-exact")

    threshold_response = client.patch("/api/v1/result/threshold", json={"threshold": 0.8})
    response = client.get("/api/v1/result/explanation/global")

    assert threshold_response.status_code == 200
    assert response.status_code == 200
    assert explanation.calls == ["artifact-exact"]
    assert "threshold" not in response.json()


def test_global_explanation_rejects_unordered_features_without_resorting() -> None:
    explanation = _GlobalExplanationService()
    explanation.evidence.features = tuple(reversed(explanation.evidence.features))
    client, store, session_id = _client(_ResultService(), explanation, _ArtifactStore())
    _completed_session(store, session_id, "artifact-exact")

    response = client.get("/api/v1/result/explanation/global")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE"
