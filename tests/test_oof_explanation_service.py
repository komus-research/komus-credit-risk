"""OOF local explanation orchestration stays fold-bound and fail closed."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np

from komus_risk.application import (
    OOFExplanationError,
    OOFExplanationService,
    OOFResultService,
)
from komus_risk.application.local_explanation import (
    LocalExplanationEvidence,
    LocalFeatureContribution,
)
from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult
from komus_risk.experiments import (
    EvaluationPopulation,
    ExperimentRunOutput,
    FoldModelEvidence,
    OOFResultEvidence,
)
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import (
    ModelConfigurationRecord,
    ProviderDescriptor,
    SmokeEvidence,
    SmokePolicy,
    SmokeStatus,
)
from komus_risk.models.gbdt.native import NativePredictor


class _PersistedTestProvider:
    """Trusted test provider that writes and reloads a deterministic predictor."""

    model_id = "catboost"
    model_version = "1"
    adapter_version = "adapter-1"
    descriptor = ProviderDescriptor(
        "oof_test_persistence", "1", "persistence", {"model_id": "catboost"}
    )

    def __init__(self, *, offset: float = 0.0) -> None:
        self.offset = offset
        self.load_calls = 0

    def native_files(self):
        return ("model.bin",)

    def validate_fitted(self, adapter, *, parameters, seed):
        return None

    def save(self, adapter, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "model.bin").write_bytes(b"persisted-oof-fold")
        return self.native_files()

    def load(self, directory: Path, feature_columns: tuple[str, ...]):
        if not (directory / "model.bin").is_file():
            raise ValueError("persisted native model is missing")
        self.load_calls += 1
        return NativePredictor(
            self.model_id,
            feature_columns,
            lambda frame: frame["score"].to_numpy(dtype=float) + self.offset,
        )


class _ExplanationProvider:
    descriptor = ProviderDescriptor(
        "oof_test_explanation", "1", "local_explanation", {"implementation": "test"}
    )
    model_id = "catboost"
    model_version = "1"
    adapter_version = "adapter-1"

    def __init__(self, *, wrong_binding: bool = False) -> None:
        self.wrong_binding = wrong_binding
        self.calls: list[tuple[str, ...]] = []

    def explain(self, **kwargs):  # pragma: no cover - service must use batch path
        raise AssertionError("OOF service must call explain_batch")

    def explain_batch(
        self, *, loaded_model_version, prediction_batch, row_ids, explanation_context
    ):
        self.calls.append(row_ids)
        row = prediction_batch.rows[0]
        self.assert_bound(
            row_ids, row, explanation_context, loaded_model_version.summary
        )
        binding_id = (
            "wrong-binding"
            if self.wrong_binding
            else explanation_context.model_binding_id
        )
        feature = LocalFeatureContribution("score", "score", 0.8, 0.0, 1)
        payload = {
            "evidence_version": "local_explanation_v2",
            "model_version_id": loaded_model_version.summary.model_version_id,
            "experiment_artifact_id": loaded_model_version.summary.experiment_artifact_id,
            "dataset_id": "dataset-v1",
            "dataset_fingerprint": "sha256:dataset",
            "feature_set_hash": "feature-set",
            "model_id": self.model_id,
            "model_version": self.model_version,
            "row_id": row.row_id,
            "identifier_column": prediction_batch.identifier_column,
            "identifier_value": row.identifier_value,
            "probability": row.probability,
            "shap_output_space": "raw_margin",
            "raw_model_output": 0.0,
            "base_value": 0.0,
            "features": (feature,),
            "explainer_id": self.descriptor.provider_id,
            "explainer_version": self.descriptor.provider_version,
            "source_kind": "oof_fold",
            "source_artifact_id": explanation_context.source_artifact_id,
            "model_binding_id": binding_id,
            "object_id": row.row_id,
            "prediction_probability": row.probability,
            "explanation_method_id": self.descriptor.provider_id,
            "explanation_method_version": self.descriptor.provider_version,
            "output_space": "raw_margin",
            "explained_output_value": 0.0,
            "provider_id": self.descriptor.provider_id,
            "provider_version": self.descriptor.provider_version,
            "provenance": {"fold_id": explanation_context.fold_id},
        }
        return (
            LocalExplanationEvidence(
                **payload,
                created_at="2026-01-01T00:00:00+00:00",
                evidence_hash=stable_hash(payload),
            ),
        )

    @staticmethod
    def assert_bound(row_ids, row, context, summary):
        if (
            row_ids != (row.row_id,)
            or context.source_kind != "oof_fold"
            or row.source_row_position not in context.validation_row_positions
            or context.model_binding_id != summary.model_version_id
        ):
            raise ValueError("batch provenance binding is invalid")


class _Registry:
    """Small trusted registry fixture; provider code remains explicit in test."""

    def __init__(self, persistence_provider, explanation_provider) -> None:
        self.plugin = SimpleNamespace(
            spec=SimpleNamespace(
                model_id="catboost", version="1", adapter_version="adapter-1"
            ),
            persistence_provider=persistence_provider.descriptor,
            local_explanation_provider=explanation_provider.descriptor,
        )
        self.persistence_providers = SimpleNamespace(
            validate_plugin_provider=lambda plugin: persistence_provider
        )
        self.explanation_providers = SimpleNamespace(
            validate_plugin_provider=lambda plugin: explanation_provider
        )

    def get(self, model_id):
        if model_id != self.plugin.spec.model_id:
            raise KeyError(model_id)
        return self.plugin


class OOFExplanationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperimentArtifactStore(self.temp.name)
        self.persistence_provider = _PersistedTestProvider()
        self.explanation_provider = _ExplanationProvider()
        self.registry = _Registry(
            self.persistence_provider, self.explanation_provider
        )
        config, contract, population, output = self._artifact_parts()
        self.artifact = self.store.save(
            config=config,
            dataset_contract=contract,
            population=population,
            run_output=output,
            configuration_record=self._configuration_record(config),
            smoke_evidence=self._smoke_evidence(config, contract, population),
            fold_model_provider=self.persistence_provider,
        )
        self.service = OOFExplanationService(self.store, self.registry)
        self.objects = OOFResultService(self.store)
        self.object_item = self.objects.objects(
            self.artifact.artifact_id, 0.5, 0, 1
        ).items[0]
        self.object_id = self.object_item.object_id
        self.object_detail = self.objects.object_detail(
            self.artifact.artifact_id, self.object_id, 0.5
        )

    def test_real_v3_artifact_loads_exact_fold_and_explains_oof_object(self) -> None:
        artifact_dir = Path(self.temp.name) / "experiments" / self.artifact.artifact_id
        fold_dir = artifact_dir / "fold_models" / f"fold-{self.object_detail.fold_number:03d}"
        self.assertTrue((fold_dir / "metadata.json").is_file())
        self.assertTrue((fold_dir / "native" / "model.bin").is_file())

        loaded_fold = self.store.load_oof_fold_model(
            self.artifact.artifact_id,
            self.object_detail.fold_number,
            provider=self.persistence_provider,
        )
        load_calls_before_local = self.persistence_provider.load_calls
        result = self.service.local(self.artifact.artifact_id, self.object_id)
        stored_score = self.object_item.score

        self.assertGreater(self.persistence_provider.load_calls, load_calls_before_local)
        self.assertEqual(self.object_detail.fold_number, loaded_fold.fold_number)
        self.assertEqual("oof_fold", result.source_kind)
        self.assertEqual(self.artifact.artifact_id, result.source_artifact_id)
        self.assertEqual(self.object_id, result.object_id)
        self.assertEqual(stored_score, result.prediction_probability)
        self.assertEqual(loaded_fold.model_binding_id, result.model_binding_id)
        self.assertEqual(str(self.object_detail.fold_number), result.provenance["fold_id"])
        self.assertEqual(((self.object_id,),), tuple(self.explanation_provider.calls))
        self.assertEqual("local_explanation_v2", result.evidence_version)

    def test_unknown_object_replay_mismatch_and_provider_mismatch_fail_closed(self) -> None:
        with self.assertRaisesRegex(OOFExplanationError, "OBJECT_NOT_FOUND"):
            self.service.local(self.artifact.artifact_id, "unknown")

        mismatched_persistence = _PersistedTestProvider(offset=0.01)
        mismatch_service = OOFExplanationService(
            self.store,
            _Registry(mismatched_persistence, self.explanation_provider),
        )
        with self.assertRaisesRegex(
            OOFExplanationError, "OOF_PREDICTION_MISMATCH"
        ):
            mismatch_service.local(self.artifact.artifact_id, self.object_id)

        mismatched_explanation = _ExplanationProvider(wrong_binding=True)
        provenance_service = OOFExplanationService(
            self.store,
            _Registry(self.persistence_provider, mismatched_explanation),
        )
        with self.assertRaisesRegex(OOFExplanationError, "PROVENANCE_MISMATCH"):
            provenance_service.local(self.artifact.artifact_id, self.object_id)

    @staticmethod
    def _artifact_parts():
        config = ExperimentConfig(
            "oof-explanation-test", "dataset-v1", "sha256:dataset", "target",
            ("score",), None, ("main",), "catboost", "1", {"depth": 7},
            "stratified_kfold_oof", "1", 42, 3, "oof", None, None, (),
        )
        contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", 10,
            3, "target", 1, "entity_id", "features-v1", "sha256:features",
            "validated", False,
        )
        population = EvaluationPopulation(
            (0, 1, 2, 3, 4, 5), "working-v1", "sha256:working", "working"
        )
        scores = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7])
        folds = np.array([1, 2, 3, 1, 2, 3])
        y_true = np.array([0, 1, 1, 0, 0, 1])
        metrics = {
            "gini": 0.2,
            "roc_auc": 0.6,
            "pr_auc": 0.55,
            "precision_at_0_5": 2 / 3,
            "recall_at_0_5": 2 / 3,
            "f1_at_0_5": 2 / 3,
        }
        result = ExperimentResult(
            "result-v1", config.experiment_id, config.config_hash,
            config.dataset_fingerprint, config.feature_set_hash, config.model_id,
            config.model_version, config.evaluation_level, metrics,
            {"threshold": 0.5, "tp": 2, "tn": 2, "fp": 1, "fn": 1},
            tuple(
                {"fold": fold, "fold_seed": config.seed + fold, **metrics}
                for fold in (1, 2, 3)
            ),
            0.3, {}, "test-code", "2026-01-01T00:00:00+00:00", (),
        )
        output = ExperimentRunOutput(
            result,
            scores,
            folds,
            population.row_positions,
            population.population_id,
            population.population_fingerprint,
            OOFResultEvidence(
                y_true=y_true,
                identifier_display=tuple(
                    f"entity-{position}" for position in population.row_positions
                ),
                model_input=scores.reshape(-1, 1),
                feature_ids=("score",),
                feature_columns=("score",),
                fold_models=tuple(
                    FoldModelEvidence(fold, config.seed + fold, object())
                    for fold in (1, 2, 3)
                ),
            ),
        )
        return config, contract, population, output

    @staticmethod
    def _configuration_record(config):
        value = {
            "record_schema_version": "1",
            "model_id": config.model_id,
            "model_version": config.model_version,
            "adapter_version": "adapter-1",
            "plugin_contract_hash": "plugin-hash",
            "schema_id": "schema",
            "schema_version": "1",
            "schema_hash": "schema-hash",
            "recommended_profile_id": "profile",
            "recommended_profile_hash": "profile-hash",
            "mode": "RECOMMENDED",
            "user_overrides": {},
            "resolved_parameters": config.model_parameters,
            "resolved_configuration_hash": "resolved-hash",
        }
        return ModelConfigurationRecord(
            **value, configuration_record_id=stable_hash(value)
        )

    @classmethod
    def _smoke_evidence(cls, config, contract, population):
        policy = SmokePolicy()
        record = cls._configuration_record(config)
        base = {
            "evidence_schema_version": "1",
            "status": SmokeStatus.PASS,
            "context_id": "context",
            "dataset_id": contract.dataset_id,
            "dataset_fingerprint": contract.dataset_fingerprint,
            "feature_registry_id": contract.feature_registry_id,
            "feature_registry_hash": contract.feature_registry_hash,
            "population_id": population.population_id,
            "population_fingerprint": population.population_fingerprint,
            "population_row_positions_hash": stable_hash(
                {"row_positions": list(population.row_positions)}
            ),
            "selected_feature_ids": config.feature_ids,
            "selected_feature_set_hash": stable_hash(
                {"ordered_feature_ids": list(config.feature_ids)}
            ),
            "plugin_contract_hash": record.plugin_contract_hash,
            "resolved_configuration_hash": record.resolved_configuration_hash,
            "configuration_record_id": record.configuration_record_id,
            "seed": config.seed,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "policy_hash": policy.policy_hash,
            "sampled_row_positions": population.row_positions,
            "sampled_rows_hash": stable_hash(
                {"row_positions": list(population.row_positions)}
            ),
            "failure_code": None,
        }
        identity = {
            key: value
            for key, value in base.items()
            if key
            not in {"status", "sampled_row_positions", "sampled_rows_hash", "failure_code"}
        }
        return SmokeEvidence(**base, smoke_identity=stable_hash(identity))


if __name__ == "__main__":
    unittest.main()
