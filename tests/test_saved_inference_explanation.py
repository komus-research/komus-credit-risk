"""Focused contract tests for immutable saved-inference local explanations."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from komus_risk.application import (
    LocalExplanationEvidence,
    LocalFeatureContribution,
    IntegrationWorkflowService,
    ModelInferenceService,
    PredictionBatch,
    PredictionRow,
    PreparedInferenceInput,
    SavedInferenceExplanationService,
    SavedModelInferenceError,
)
from komus_risk.artifacts import (
    LoadedModelVersion,
    ModelVersionSummary,
    SavedModelInferenceResultStore,
)
from komus_risk.hashing import stable_hash
from komus_risk.models.gbdt.native import NativePredictor
from komus_risk.model_platform import build_builtin_model_plugin_registry
from komus_risk.application.saved_inference_explanation import _CACHE_MAX_ENTRIES


class _Predictor:
    def predict_positive_proba(self, frame):
        return np.asarray([0.25 + 0.05 * float(frame.iloc[0, 0])], dtype=float)


class _Library:
    def __init__(self, loaded):
        self.loaded = loaded

    def load_for_inference(self, model_version_id):
        assert model_version_id == self.loaded.summary.model_version_id
        return object(), self.loaded


class _Workflow:
    def __init__(self):
        self.values = None
        self.explain_calls = 0

    @staticmethod
    def _explanation_provider(_model_id):
        return SimpleNamespace(descriptor=SimpleNamespace(provider_id="provider", provider_version="1"))

    def capabilities(self, **kwargs):
        return {
            "local_explanation": type("Capability", (), {"state": "AVAILABLE", "reason_code": "LOCAL_EXPLAINER_READY"})(),
            "result_interpretation": type("Capability", (), {"state": "DISABLED", "reason_code": "EXTERNAL_DATA_POLICY_DISABLED"})(),
        }

    def explain(self, *, loaded_model_version, prediction_batch, row_id, explanation_context=None):
        self.explain_calls += 1
        self.values = prediction_batch.validated_feature_values
        row = prediction_batch.rows[0]
        features = tuple(
            LocalFeatureContribution(f"feature-{index}", column, value, value / 100, index + 1)
            for index, (column, value) in enumerate(zip(prediction_batch.required_feature_columns, self.values[0], strict=True))
        )
        payload = {
            "evidence_version": "local_explanation_v2", "model_version_id": "model-v1",
            "experiment_artifact_id": "artifact-v1", "dataset_id": "dataset", "dataset_fingerprint": "fingerprint",
            "feature_set_hash": "binding", "model_id": "catboost", "model_version": "1",
            "row_id": row_id, "identifier_column": "id", "identifier_value": row.identifier_value,
            "probability": row.probability, "shap_output_space": "raw_margin", "raw_model_output": 0.0,
            "base_value": 0.0, "features": features, "explainer_id": "provider", "explainer_version": "1",
            "source_kind": "model_version", "source_artifact_id": "artifact-v1", "model_binding_id": "model-v1",
            "object_id": row_id, "prediction_probability": row.probability,
            "explanation_method_id": "provider", "explanation_method_version": "1", "output_space": "raw_margin",
            "explained_output_value": 0.0, "provider_id": "provider", "provider_version": "1", "provenance": {},
        }
        return LocalExplanationEvidence(**payload, created_at="2026-01-01T00:00:00+00:00", evidence_hash=stable_hash(payload))


def _service(root: Path):
    store = SavedModelInferenceResultStore(root / "results")
    values = ((2.0, 9.0),)
    prepared = PreparedInferenceInput(
        model_version_id="model-v1", source_sha256="a" * 64, source_fingerprint="source",
        physical_headers_hash="headers", row_count=1, column_count=3, identifier_column="id",
        identifier_values=("object-1",), source_row_positions=(7,), required_feature_columns=("first", "second"),
        validated_feature_values=values, ignored_columns=(),
    )
    batch = PredictionBatch("model-v1", "a" * 64, "id", ("first", "second"),
                            (PredictionRow("a" * 64 + ":7", 7, "object-1", 0.35),), (), values)
    result = store.create(model_version_id="model-v1", experiment_artifact_id="artifact-v1", source_display_name="source.csv", source_format="csv", prepared=prepared, prediction_batch=batch)
    metadata = {
        "experiment_artifact_id": "artifact-v1", "feature_columns": ["first", "second"],
        "feature_specs": [
            {"feature_id": "feature-0", "column_name": "first", "display_name_ru": "Первый", "description_ru": "d1"},
            {"feature_id": "feature-1", "column_name": "second", "display_name_ru": "Второй", "description_ru": "d2"},
        ],
    }
    loaded = LoadedModelVersion(ModelVersionSummary("model-v1", "artifact-v1", "catboost", "1", ("feature-0", "feature-1")), metadata, {}, _Predictor())
    workflow = _Workflow()
    return SavedInferenceExplanationService(result_store=store, model_library_service=_Library(loaded), integration_workflow_service=workflow), result, workflow


def test_saved_explanation_uses_the_exact_persisted_row_and_is_stably_bound():
    with TemporaryDirectory() as temp:
        service, result, workflow = _service(Path(temp))
        row_id = result.rows[0].row_id
        detail = service.detail(result.inference_result_id, row_id, threshold=0.35)
        explanation = service.explain(result.inference_result_id, row_id)
        assert detail.position == "ABOVE"
        assert [feature.raw_value for feature in detail.features] == [2.0, 9.0]
        assert workflow.values == ((2.0, 9.0),)
        assert explanation.explanation_id == stable_hash({
            "inference_result_id": result.inference_result_id, "model_version_id": "model-v1",
            "row_id": row_id, "evidence_hash": explanation.evidence_hash,
        })


def test_saved_explanation_fails_closed_for_a_foreign_row_id():
    with TemporaryDirectory() as temp:
        service, result, _workflow = _service(Path(temp))
        with pytest.raises(SavedModelInferenceError, match="INFERENCE_OBJECT_NOT_FOUND"):
            service.explain(result.inference_result_id, "foreign-row")


@pytest.mark.parametrize("evidence_file", ["scores.npy", "model_input.npy"])
def test_saved_explanation_fails_closed_when_persisted_score_or_vector_changes(evidence_file):
    with TemporaryDirectory() as temp:
        root = Path(temp)
        service, result, _workflow = _service(root)
        path = root / "results" / result.inference_result_id / "evidence" / evidence_file
        values = np.load(path, allow_pickle=False)
        values.flat[0] += 0.01
        np.save(path, values, allow_pickle=False)
        with pytest.raises(SavedModelInferenceError, match="INFERENCE_RESULT_INTEGRITY_ERROR"):
            service.explain(result.inference_result_id, result.rows[0].row_id)


def test_saved_explanation_fails_closed_for_a_foreign_model_binding():
    with TemporaryDirectory() as temp:
        service, result, _workflow = _service(Path(temp))
        loaded = service.model_library_service.loaded
        service.model_library_service.loaded = replace(
            loaded, summary=replace(loaded.summary, experiment_artifact_id="foreign-artifact"),
        )
        with pytest.raises(SavedModelInferenceError, match="INFERENCE_EXPLANATION_EVIDENCE_MISMATCH"):
            service.explain(result.inference_result_id, result.rows[0].row_id)


def test_explanation_cache_is_bounded_lru_and_evicted_evidence_recomputes():
    with TemporaryDirectory() as temp:
        service, result, workflow = _service(Path(temp))
        row_id = result.rows[0].row_id
        service.explain(result.inference_result_id, row_id)
        assert workflow.explain_calls == 1
        original = service.result_store.read_object_evidence(result.inference_result_id, row_id)
        local = next(iter(service._cache.values()))
        for index in range(_CACHE_MAX_ENTRIES):
            evidence = replace(original, inference_result_id=f"result-{index}", row_id=f"row-{index}")
            service._put_cached(evidence, local, ("provider", "1"), None)
        assert len(service._cache) == _CACHE_MAX_ENTRIES
        assert all(key[0] != result.inference_result_id for key in service._cache)
        service.explain(result.inference_result_id, row_id)
        assert workflow.explain_calls == 2


class _FinalModelBackgroundStore:
    def __init__(self, artifact_id, training_values):
        self.artifact_id = artifact_id
        self.training_values = training_values

    def load(self, artifact_id):
        assert artifact_id == self.artifact_id
        return SimpleNamespace(
            artifact_id=artifact_id,
            run_output=SimpleNamespace(
                oof_evidence=SimpleNamespace(
                    feature_columns=("feature",),
                    identifier_display=tuple(f"training-{index}" for index in range(len(self.training_values))),
                    model_input=np.asarray([[value] for value in self.training_values], dtype=float),
                ),
                row_positions=tuple(range(100, 100 + len(self.training_values))),
            ),
        )


def _builtin_workflow():
    plugins = build_builtin_model_plugin_registry()
    model_version_store = object()
    training = SimpleNamespace(model_version_store=model_version_store)
    return IntegrationWorkflowService(
        final_model_training_service=training,
        model_version_store=model_version_store,
        model_inference_service=ModelInferenceService(),
        model_plugin_registry=plugins,
    ), plugins


def _builtin_saved_service(root: Path, model_id: str):
    workflow, plugins = _builtin_workflow()
    version_id, artifact_id, value = f"{model_id}-version", f"{model_id}-artifact", 0.9
    columns, feature_ids = ("feature",), ("feature-id",)
    if model_id == "gbdt_mean":
        probability = 0.6
        predictor = NativePredictor(
            model_id, columns, lambda frame: np.full(len(frame), probability),
            component_predict={name: lambda frame: np.full(len(frame), probability) for name in ("catboost", "xgboost", "lightgbm")},
        )
    else:
        margin = 0.2
        probability = float(1 / (1 + np.exp(-margin)))
        predictor = NativePredictor(
            model_id, columns, lambda frame: np.full(len(frame), probability),
            local_shap=lambda frame: np.column_stack((np.zeros(len(frame)), np.full(len(frame), margin))),
            raw_predict=lambda frame: np.full(len(frame), margin),
        )
    loaded = LoadedModelVersion(
        ModelVersionSummary(version_id, artifact_id, model_id, "1", feature_ids),
        {
            "model_id": model_id, "model_version": "1", "experiment_artifact_id": artifact_id,
            "feature_set_hash": "feature-binding", "feature_columns": list(columns), "feature_ids": list(feature_ids),
            "feature_specs": [{"feature_id": "feature-id", "column_name": "feature", "display_name_ru": "Feature", "description_ru": "Description"}],
            "dataset_contract": {"identifier_column": "id", "dataset_id": "dataset", "dataset_fingerprint": "fingerprint"},
        }, {}, predictor,
    )
    store = SavedModelInferenceResultStore(root / "results")
    prepared = PreparedInferenceInput(
        model_version_id=version_id, source_sha256="b" * 64, source_fingerprint="persisted-source",
        physical_headers_hash="headers", row_count=1, column_count=2, identifier_column="id",
        identifier_values=("object",), source_row_positions=(0,), required_feature_columns=columns,
        validated_feature_values=((value,),), ignored_columns=(),
    )
    row_id = "b" * 64 + ":0"
    batch = PredictionBatch(version_id, "b" * 64, "id", columns, (PredictionRow(row_id, 0, "object", probability),), (), ((value,),))
    result = store.create(model_version_id=version_id, experiment_artifact_id=artifact_id, source_display_name="persisted.csv", source_format="csv", prepared=prepared, prediction_batch=batch)
    captured = []
    original_explain = workflow.explain

    def capture_explain(**kwargs):
        evidence = original_explain(**kwargs)
        captured.append((kwargs, evidence))
        return evidence

    workflow.explain = capture_explain
    service = SavedInferenceExplanationService(
        result_store=store, model_library_service=_Library(loaded), integration_workflow_service=workflow,
        experiment_artifact_store=_FinalModelBackgroundStore(artifact_id, (-1.0, 0.0, 1.0)),
    )
    return service, result, captured, plugins, probability


@pytest.mark.parametrize("model_id", ("catboost", "xgboost", "lightgbm", "gbdt_mean"))
def test_all_builtin_saved_inference_paths_use_persisted_row_and_registered_workflow_provider(model_id):
    with TemporaryDirectory() as temp:
        service, result, captured, plugins, probability = _builtin_saved_service(Path(temp), model_id)
        explanation = service.explain(result.inference_result_id, result.rows[0].row_id)
        assert len(captured) == 1
        arguments, local = captured[0]
        assert arguments["prediction_batch"].validated_feature_values == ((0.9,),)
        assert arguments["prediction_batch"].required_feature_columns == ("feature",)
        assert local.probability == result.rows[0].probability == probability
        assert local.prediction_probability == explanation.prediction_probability == probability
        assert explanation.explanation_provider_id == plugins.get(model_id).local_explanation_provider.provider_id
        if model_id != "gbdt_mean":
            assert arguments["explanation_context"] is None
            return
        context = arguments["explanation_context"]
        assert context.source_kind == "model_version"
        assert context.background_policy_id == "model_version_training_hash_top128_v1"
        assert context.background_values != ((0.9,),)
        assert set(context.background_values) == {(-1.0,), (0.0,), (1.0,)}
        assert context.validation_row_positions == ()
        assert context.fold_id is None
