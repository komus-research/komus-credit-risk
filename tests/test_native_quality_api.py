"""Focused evidence for native Quality V1A's fail-closed preflight boundary."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import create_app
from app.native_runtime import create_native_experiment_runtime
from komus_risk.application import NativeQualityService
from komus_risk.application.native_session import NativeSessionStore, QualityPlanStatus, QualityPreflightStatus
from komus_risk.contracts import DatasetContract, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.model_platform import SmokeStatus
from komus_risk.preparation import PreparedDatasetContext
from komus_risk.registries import FeatureRegistry
import numpy as np
import pandas as pd


def _quality_client(rows: int = 40) -> TestClient:
    client = TestClient(create_app())
    body = b"id,target,score\n" + b"".join(
        f"id-{index},{index % 2},{index / (rows * 2):.3f}\n".encode()
        for index in range(rows)
    )
    assert client.post("/api/v1/dataset/upload", files={"file": ("customers.csv", body, "text/csv")}).status_code == 200
    assert client.patch("/api/v1/dataset/preparation/draft", json={"positive_class": 1}).status_code == 200
    assert client.post("/api/v1/dataset/preparation/review").status_code == 200
    assert client.post("/api/v1/dataset/preparation/confirm", json={"population_policy_acknowledged": True}).status_code == 200
    assert client.post("/api/v1/features/continue").status_code == 200
    assert client.patch("/api/v1/algorithm/model", json={"model_id": "catboost"}).status_code == 200
    assert client.post("/api/v1/algorithm/continue").status_code == 200
    return client


def test_quality_is_closed_until_algorithm_is_completed() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/quality")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ALGORITHM_CONTINUE_REQUIRED"


def test_quality_uses_protocol_defaults_and_passes_matching_technical_smoke() -> None:
    client = _quality_client()
    initial = client.get("/api/v1/quality")
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["settings"] == {"folds": payload["supported_protocol"]["default_folds"], "seed": payload["supported_protocol"]["default_seed"]}
    assert payload["summary"]["dataset_name"] == "customers.csv"
    assert payload["summary"]["population_size"] == 40
    assert payload["summary"]["selected_feature_count"] == 1

    checked = client.post("/api/v1/quality/preflight")
    assert checked.status_code == 200, checked.text
    result = checked.json()
    assert result["plan"]["status"] == "VALID"
    assert result["preflight"]["status"] == "PASS"
    assert result["preflight"]["identity"]
    assert result["can_start_training"] is True


def test_quality_settings_and_algorithm_change_invalidate_readiness_without_fake_pass() -> None:
    client = _quality_client()
    assert client.post("/api/v1/quality/preflight").json()["preflight"]["status"] == "PASS"

    initial_settings = client.get("/api/v1/quality").json()["settings"]
    same = client.patch("/api/v1/quality/settings", json=initial_settings)
    assert same.status_code == 200
    assert same.json()["preflight"]["status"] == "PASS"

    changed_seed = client.patch("/api/v1/quality/settings", json={"seed": initial_settings["seed"] + 1})
    assert changed_seed.status_code == 200
    assert changed_seed.json()["preflight"]["status"] == "IDLE"
    assert changed_seed.json()["can_start_training"] is False

    invalid_folds = client.patch("/api/v1/quality/settings", json={"folds": 1})
    assert invalid_folds.status_code == 422
    assert invalid_folds.json()["detail"]["code"] == "INVALID_FOLDS"

    assert client.patch("/api/v1/algorithm/configuration", json={"configuration_mode": "ADVANCED", "user_overrides": {}}).status_code == 200
    assert client.get("/api/v1/quality").status_code == 409


def test_smoke_failure_is_safe_and_never_authorizes_training() -> None:
    client = _quality_client(rows=4)
    response = client.post("/api/v1/quality/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["status"] == "VALID"
    assert payload["preflight"]["status"] == "FAIL"
    assert payload["can_start_training"] is False
    assert "Traceback" not in (payload["preflight"]["message"] or "")


def test_invalid_plan_never_starts_smoke() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    session = store._sessions[session_id]
    session.data_substep = "PREPARED"
    session.prepared_context_id = "trusted"
    session.selected_feature_ids = ("feature",)
    session.features_completed = True
    session.selected_model_id = "model"
    session.algorithm_completed = True
    context = SimpleNamespace(
        loaded_dataset=SimpleNamespace(contract=SimpleNamespace(dataset_name="Набор")),
        feature_registry=SimpleNamespace(),
        population=SimpleNamespace(row_positions=(0, 1)),
    )

    class Planning:
        def list_models(self):
            return (SimpleNamespace(model_id="model", display_name_ru="Модель"),)

        def build_plan(self, *_args, **_kwargs):
            return SimpleNamespace(is_valid=False)

    class Application:
        def run_configuration_smoke(self, **_kwargs):
            raise AssertionError("smoke must not run for an invalid plan")

    quality = NativeQualityService(
        session_store=store,
        planning_service=Planning(),
        application_service=Application(),
        prepared_context_authority=SimpleNamespace(resolve=lambda _context_id: context),
        supported_protocol=SimpleNamespace(protocol_id="p", protocol_version="1", evaluation_level="oof", minimum_folds=2, default_folds=2, default_seed=7),
    )

    result = quality.preflight(session_id)
    assert result["plan"]["status"] == "INVALID"
    assert result["preflight"]["status"] == "FAIL"
    assert result["can_start_training"] is False


def _direct_quality(application, *, plan_valid: bool = True):
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    session = store._sessions[session_id]
    session.data_substep = "PREPARED"
    session.prepared_context_id = "trusted"
    session.selected_feature_ids = ("feature",)
    session.features_completed = True
    session.selected_model_id = "model"
    session.algorithm_completed = True
    context = SimpleNamespace(
        loaded_dataset=SimpleNamespace(contract=SimpleNamespace(dataset_name="Набор")),
        feature_registry=SimpleNamespace(),
        population=SimpleNamespace(row_positions=(0, 1)),
    )

    class Planning:
        def list_models(self):
            return (SimpleNamespace(model_id="model", display_name_ru="Модель"),)

        def build_plan(self, *_args, **_kwargs):
            return SimpleNamespace(is_valid=plan_valid)

    service = NativeQualityService(
        session_store=store,
        planning_service=Planning(),
        application_service=application,
        prepared_context_authority=SimpleNamespace(resolve=lambda _context_id: context),
        supported_protocol=SimpleNamespace(protocol_id="p", protocol_version="1", evaluation_level="oof", minimum_folds=2, default_folds=3, default_seed=42),
    )
    return store, session_id, service


def test_stale_smoke_pass_after_seed_change_cannot_authorize_current_settings() -> None:
    started, release = Event(), Event()

    class BlockingSmoke:
        def run_configuration_smoke(self, *, request, **_kwargs):
            assert request.seed == 42
            started.set()
            assert release.wait(10)
            return SimpleNamespace(status=SmokeStatus.PASS, smoke_identity="identity-seed-42", failure_code=None)

    store, session_id, quality = _direct_quality(BlockingSmoke())
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(quality.preflight, session_id)
        assert started.wait(10)
        store.set_quality_settings(session_id, seed=99, folds=3)
        release.set()
        result = pending.result(timeout=10)

    assert result["settings"] == {"seed": 99, "folds": 3}
    assert result["preflight"]["status"] == "IDLE"
    assert result["preflight"]["identity"] is None
    assert result["can_start_training"] is False


def test_older_superseded_preflight_cannot_overwrite_newer_completion() -> None:
    first_started, release_first = Event(), Event()

    class SupersedingSmoke:
        calls = 0

        def run_configuration_smoke(self, **_kwargs):
            self.calls += 1
            call = self.calls
            if call == 1:
                first_started.set()
                assert release_first.wait(10)
            return SimpleNamespace(status=SmokeStatus.PASS, smoke_identity=f"identity-{call}", failure_code=None)

    app = SupersedingSmoke()
    _store, session_id, quality = _direct_quality(app)
    with ThreadPoolExecutor(max_workers=2) as executor:
        older = executor.submit(quality.preflight, session_id)
        assert first_started.wait(10)
        newer = executor.submit(quality.preflight, session_id)
        newest_state = newer.result(timeout=10)
        assert newest_state["preflight"]["identity"] == "identity-2"
        release_first.set()
        older.result(timeout=10)

    final = quality.state(session_id)
    assert final["preflight"]["status"] == "PASS"
    assert final["preflight"]["identity"] == "identity-2"
    assert final["can_start_training"] is True


def test_retry_after_fail_starts_fresh_preflight_and_can_pass() -> None:
    class FailsOnce:
        calls = 0

        def run_configuration_smoke(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                status=SmokeStatus.FAIL if self.calls == 1 else SmokeStatus.PASS,
                smoke_identity=f"identity-{self.calls}",
                failure_code="SMOKE_RUNTIME_FAILURE" if self.calls == 1 else None,
            )

    store, session_id, quality = _direct_quality(FailsOnce())
    first = quality.preflight(session_id)
    token_after_fail = store._sessions[session_id].quality_preflight_operation_token
    assert first["preflight"]["status"] == "FAIL"
    assert first["can_start_training"] is False

    second = quality.preflight(session_id)
    token_after_retry = store._sessions[session_id].quality_preflight_operation_token
    assert token_after_retry != token_after_fail
    assert second["preflight"]["status"] == "PASS"
    assert second["preflight"]["identity"] == "identity-2"
    assert second["can_start_training"] is True


def test_same_canonical_settings_preserve_pass_and_operation_token() -> None:
    class PassingSmoke:
        def run_configuration_smoke(self, **_kwargs):
            return SimpleNamespace(status=SmokeStatus.PASS, smoke_identity="stable-identity", failure_code=None)

    store, session_id, quality = _direct_quality(PassingSmoke())
    passed = quality.preflight(session_id)
    token = store._sessions[session_id].quality_preflight_operation_token

    quality.update_settings(session_id, seed=42, folds=3)
    unchanged = quality.state(session_id)

    assert unchanged["preflight"]["status"] == "PASS"
    assert unchanged["preflight"]["identity"] == passed["preflight"]["identity"] == "stable-identity"
    assert store._sessions[session_id].quality_preflight_operation_token == token


def test_full_training_requires_pass_and_uses_exact_trusted_configuration() -> None:
    class TrainingApplication:
        calls = []

        def run_configuration_smoke(self, **_kwargs):
            return SimpleNamespace(status=SmokeStatus.PASS, smoke_identity="smoke-current", failure_code=None)

        def run_experiment(self, **kwargs):
            self.calls.append(kwargs)
            kwargs["progress_listener"](SimpleNamespace(stage="fold_started", fold_number=2, folds_total=3))
            return SimpleNamespace(artifact_id="artifact-exact")

    app = TrainingApplication()
    store, session_id, quality = _direct_quality(app)
    with pytest.raises(ValueError, match="PREFLIGHT_REQUIRED"):
        quality.train(session_id)
    assert not app.calls

    ready = quality.preflight(session_id)
    assert ready["can_start_training"] is True
    published = []

    def run_with_progress(**kwargs):
        app.calls.append(kwargs)
        kwargs["progress_listener"](SimpleNamespace(stage="fold_started", fold_number=2, folds_total=3))
        published.append(quality.state(session_id)["training"])
        return SimpleNamespace(artifact_id="artifact-exact")

    app.run_experiment = run_with_progress
    completed = quality.train(session_id)
    call = app.calls[0]
    assert call["request"].selected_feature_ids == ("feature",)
    assert call["request"].model_id == "model"
    assert call["request"].seed == 42
    assert call["request"].folds == 3
    assert call["prepared_context_id"] == "trusted"
    assert published[0]["stage"] == "fold_started"
    assert published[0]["fold_number"] == 2
    assert published[0]["folds_total"] == 3
    assert completed["training"]["status"] == "COMPLETED"
    assert completed["training"]["artifact_id"] == "artifact-exact"
    assert completed["can_start_training"] is False


def test_duplicate_training_start_is_rejected_and_failure_allows_retry() -> None:
    started, release = Event(), Event()

    class TrainingApplication:
        calls = 0

        def run_configuration_smoke(self, **_kwargs):
            return SimpleNamespace(status=SmokeStatus.PASS, smoke_identity="smoke-current", failure_code=None)

        def run_experiment(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                started.set()
                assert release.wait(10)
                raise RuntimeError("secret traceback must not escape")
            return SimpleNamespace(artifact_id="artifact-retry")

    app = TrainingApplication()
    _store, session_id, quality = _direct_quality(app)
    quality.preflight(session_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(quality.train, session_id)
        assert started.wait(10)
        with pytest.raises(ValueError, match="TRAINING_ALREADY_RUNNING"):
            quality.train(session_id)
        release.set()
        failed = pending.result(timeout=10)

    assert failed["training"]["status"] == "FAIL"
    assert failed["training"]["artifact_id"] is None
    assert failed["training"]["failure_code"] == "TRAINING_FAILED"
    assert "secret traceback" not in failed["training"]["message"]
    assert failed["can_start_training"] is True
    retried = quality.train(session_id)
    assert retried["training"]["status"] == "COMPLETED"
    assert retried["training"]["artifact_id"] == "artifact-retry"


def test_stale_training_completion_cannot_publish_artifact_after_settings_change() -> None:
    started, release = Event(), Event()

    class TrainingApplication:
        def run_configuration_smoke(self, **_kwargs):
            return SimpleNamespace(status=SmokeStatus.PASS, smoke_identity="smoke-current", failure_code=None)

        def run_experiment(self, **_kwargs):
            started.set()
            assert release.wait(10)
            return SimpleNamespace(artifact_id="persisted-but-stale")

    store, session_id, quality = _direct_quality(TrainingApplication())
    quality.preflight(session_id)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(quality.train, session_id)
        assert started.wait(10)
        store.set_quality_settings(session_id, seed=43, folds=3)
        release.set()
        pending.result(timeout=10)

    current = quality.state(session_id)
    assert current["training"]["status"] == "IDLE"
    assert current["training"]["artifact_id"] is None
    assert current["preflight"]["status"] == "IDLE"
    assert current["can_start_training"] is False


def test_native_quality_smoke_samples_only_trusted_working_population() -> None:
    runtime = create_native_experiment_runtime()
    registry = FeatureRegistry(
        "native-quality-test-registry",
        (FeatureSpec("feature", "score", "Оценка", "Числовой показатель", "group", "float", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 0),),
        (FeatureGroup("group", "Группа", "Тестовая группа", 0, "test", ("feature",)),),
    )
    rows = 50
    frame = pd.DataFrame({"id": [f"id-{i}" for i in range(rows)], "target": [i % 2 for i in range(rows)], "score": np.linspace(0.0, 1.0, rows)})
    contract = DatasetContract("locked-dataset", "1", "Защищённый набор", "test", "fingerprint", rows, 3, "target", 1, "id", registry.registry_id, registry.registry_hash, "validated", True)
    dataset = LoadedDataset(frame, contract, Path("locked.csv"), "csv", "source-hash")
    working = EvaluationPopulation(tuple(range(40)), "working-population", "working-fingerprint", "working")
    context = runtime.prepared_context_authority.register(PreparedDatasetContext("locked-context", "Защищённый набор", dataset, registry, working))

    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    session = store._sessions[session_id]
    session.data_substep = "PREPARED"
    session.prepared_context_id = context.context_id
    session.selected_feature_ids = ("feature",)
    session.features_completed = True
    session.selected_model_id = "catboost"
    session.algorithm_completed = True
    quality = NativeQualityService(
        session_store=store,
        planning_service=runtime.planning_service,
        application_service=runtime.application_service,
        prepared_context_authority=runtime.prepared_context_authority,
        supported_protocol=runtime.supported_protocol,
    )

    result = quality.preflight(session_id)
    assert result["preflight"]["status"] == "PASS"
    evidence = runtime.application_service._smoke_evidence[result["preflight"]["identity"]]
    assert set(evidence.sampled_row_positions).issubset(set(working.row_positions))
    assert not set(evidence.sampled_row_positions).intersection(range(40, 50))
    assert result["can_start_training"] is True


def test_native_runtime_services_share_canonical_artifact_store() -> None:
    runtime = create_native_experiment_runtime()

    expected_root = Path(__file__).resolve().parents[1] / ".axion-artifacts"
    assert runtime.artifact_store.root == expected_root
    assert runtime.artifact_store.root.name == ".axion-artifacts"
    assert runtime.artifact_store.root.name != ".streamlit-artifacts"
    assert runtime.application_service.artifact_store is runtime.artifact_store
    assert runtime.oof_result_service.artifact_store is runtime.artifact_store
    assert runtime.oof_explanation_service.artifact_store is runtime.artifact_store
    assert runtime.analysis_history_service.artifact_store is runtime.artifact_store

    workflow = runtime.integration_workflow_service
    final_training = workflow.final_model_training_service
    assert final_training.experiment_artifact_store is runtime.artifact_store
    assert final_training.model_version_store is workflow.model_version_store
    assert workflow.model_version_store.root == expected_root / "model_versions"
    assert workflow.model_version_store.root.is_relative_to(expected_root)
    assert runtime.application_service.code_version == "native-quality-v1a"
    assert final_training.code_version == runtime.application_service.code_version
    assert workflow.model_version_store.code_version == runtime.application_service.code_version
    for native_root in (
        runtime.artifact_store.root,
        final_training.experiment_artifact_store.root,
        workflow.model_version_store.root,
    ):
        assert ".streamlit-artifacts" not in str(native_root)
