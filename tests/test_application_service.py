"""Tests for frontend-independent experiment orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from komus_risk.application import ExperimentApplicationService, RunExperimentRequest
from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.contracts import DatasetContract, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry, ModelSpec


class SyntheticAdapter(BinaryClassifierAdapter):
    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        self.fit_input = (X_train, y_train)

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        return X_valid["score_a"].to_numpy(dtype=float)


class SyntheticFactory(ModelAdapterFactory):
    model_id = "synthetic-model"
    model_version = "1"
    adapter_version = "adapter-1"

    def __init__(self) -> None:
        self.created: list[tuple[dict[str, object], int]] = []

    def create(self, parameters: dict[str, object], seed: int) -> BinaryClassifierAdapter:
        self.created.append((parameters, seed))
        return SyntheticAdapter()


class ApplicationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = ModelRegistry()
        self.profile = {"nested": {"depth": 7}}
        self.spec = ModelSpec(
            "synthetic-model", "Synthetic", "1", ("binary",), "Synthetic test model", self.profile, {}, "adapter-1"
        )
        self.registry.register(self.spec)
        self.factory = SyntheticFactory()
        self.store = ExperimentArtifactStore(self.temp.name)
        self.service = ExperimentApplicationService(
            model_registry=self.registry,
            model_factories={self.factory.model_id: self.factory},
            artifact_store=self.store,
            comparison_service=ExperimentComparisonService(),
            code_version="test-code",
        )
        self.dataset, self.features, self.population = self._dataset_and_features()

    def test_request_runs_existing_runner_persists_and_preserves_feature_order(self) -> None:
        artifact = self.service.run_experiment(
            loaded_dataset=self.dataset, feature_registry=self.features, population=self.population,
            request=self._request(("b", "a")),
        )

        self.assertEqual(artifact.config.feature_ids, ("b", "a"))
        self.assertEqual(artifact.config.feature_groups, ("alpha", "zeta"))
        self.assertEqual(artifact.config.model_parameters, self.profile)
        self.assertIsNot(artifact.config.model_parameters, self.profile)
        self.assertIsNot(artifact.config.model_parameters["nested"], self.profile["nested"])
        artifact.config.model_parameters["nested"]["depth"] = 99
        self.assertEqual(self.profile, {"nested": {"depth": 7}})
        self.assertEqual(len(self.factory.created), 3)
        self.assertEqual(self.factory.created[0][1], 43)
        self.assertEqual(artifact.population, self.population)
        self.assertEqual(artifact.run_output.row_positions, self.population.row_positions)

    def test_request_protocol_fields_ids_and_reference_are_trusted(self) -> None:
        first = self.service.run_experiment(
            loaded_dataset=self.dataset, feature_registry=self.features, population=self.population,
            request=self._request(("a",)),
        )
        second = self.service.run_experiment(
            loaded_dataset=self.dataset, feature_registry=self.features, population=self.population,
            request=self._request(
                ("a",), reference_artifact_id=first.artifact_id, changed_dimension="model", changed_elements=("nested/depth",)
            ),
        )

        self.assertNotEqual(first.config.experiment_id, second.config.experiment_id)
        self.assertTrue(first.config.experiment_id and second.config.experiment_id)
        self.assertEqual(second.config.reference_result_id, first.run_output.result.result_id)
        self.assertIsNone(first.config.reference_result_id)
        self.assertEqual((second.config.protocol_id, second.config.protocol_version, second.config.seed, second.config.folds, second.config.evaluation_level), ("stratified_kfold_oof", "1", 42, 3, "oof"))

    def test_feature_and_registry_failures_happen_before_factory_create(self) -> None:
        cases = (
            self._request(("missing",)), self._request(("diagnostic",)), self._request(("blocked",)),
        )
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises((KeyError, ValueError)):
                    self.service.run_experiment(
                        loaded_dataset=self.dataset, feature_registry=self.features, population=self.population, request=request
                    )
        bad_dataset = replace(self.dataset, contract=replace(self.dataset.contract, feature_registry_hash="wrong"))
        with self.assertRaises(ValueError):
            self.service.run_experiment(
                loaded_dataset=bad_dataset, feature_registry=self.features, population=self.population, request=self._request(("a",))
            )
        self.assertEqual(self.factory.created, [])

    def test_request_and_model_failures_happen_before_runner(self) -> None:
        with self.assertRaises(ValueError):
            RunExperimentRequest(("a", "a"), "synthetic-model", "p", "1", 1, 1, "oof", None, None, ())
        with self.assertRaises(ValueError):
            RunExperimentRequest(("a",), "synthetic-model", "p", "1", 1, 1, "oof", None, "model", ("x",))
        with self.assertRaises(KeyError):
            self.service.run_experiment(
                loaded_dataset=self.dataset, feature_registry=self.features, population=self.population,
                request=self._request(("a",), model_id="unknown"),
            )
        service_without_factory = ExperimentApplicationService(
            model_registry=self.registry, model_factories={}, artifact_store=self.store,
            comparison_service=ExperimentComparisonService(), code_version="test-code",
        )
        with self.assertRaises(ValueError):
            service_without_factory.run_experiment(
                loaded_dataset=self.dataset, feature_registry=self.features, population=self.population, request=self._request(("a",))
            )
        self.assertEqual(self.factory.created, [])

    def test_constructor_rejects_bad_injected_factory_identities(self) -> None:
        with self.assertRaises(ValueError):
            ExperimentApplicationService(
                model_registry=self.registry, model_factories={"wrong": self.factory}, artifact_store=self.store,
                comparison_service=ExperimentComparisonService(), code_version="test-code",
            )
        wrong_version = SyntheticFactory()
        wrong_version.model_version = "other"
        with self.assertRaises(ValueError):
            ExperimentApplicationService(
                model_registry=self.registry, model_factories={wrong_version.model_id: wrong_version}, artifact_store=self.store,
                comparison_service=ExperimentComparisonService(), code_version="test-code",
            )

    def test_load_and_compare_delegate_without_creating_runner(self) -> None:
        artifact = self.service.run_experiment(
            loaded_dataset=self.dataset, feature_registry=self.features, population=self.population, request=self._request(("a",))
        )
        with patch("komus_risk.application.service.ExperimentRunner", side_effect=AssertionError):
            loaded = self.service.load_experiment(artifact.artifact_id)
            comparison = self.service.compare_experiments(artifact.artifact_id, artifact.artifact_id)
        self.assertEqual(loaded.artifact_id, artifact.artifact_id)
        self.assertFalse(comparison.is_comparable)

    def _request(self, feature_ids: tuple[str, ...], **changes) -> RunExperimentRequest:
        values = dict(
            selected_feature_ids=feature_ids, model_id="synthetic-model", protocol_id="stratified_kfold_oof",
            protocol_version="1", seed=42, folds=3, evaluation_level="oof", reference_artifact_id=None,
            changed_dimension=None, changed_elements=(),
        )
        values.update(changes)
        return RunExperimentRequest(**values)

    def _dataset_and_features(self) -> tuple[LoadedDataset, FeatureRegistry, EvaluationPopulation]:
        dataframe = pd.DataFrame({
            "entity_id": [f"id-{item}" for item in range(12)], "target": [0, 1] * 6,
            "score_a": [0.1, 0.9, 0.8, 0.2, 0.3, 0.7, 0.6, 0.4, 0.15, 0.85, 0.55, 0.45],
            "score_b": [0.2, 0.8, 0.7, 0.3, 0.4, 0.6, 0.5, 0.5, 0.2, 0.8, 0.6, 0.4],
            "diagnostic": list(range(12)), "blocked": list(range(12)),
        })
        specs = (
            self._spec("a", "score_a", "zeta", FeatureUsageStatus.MODEL_ALLOWED),
            self._spec("b", "score_b", "alpha", FeatureUsageStatus.MODEL_ALLOWED),
            self._spec("diagnostic", "diagnostic", "zeta", FeatureUsageStatus.DIAGNOSTIC_ONLY),
            self._spec("blocked", "blocked", "zeta", FeatureUsageStatus.BLOCKED),
        )
        features = FeatureRegistry(
            "features-v1", specs,
            (FeatureGroup("alpha", "Alpha", "Synthetic", 1, "test", ("b",)), FeatureGroup("zeta", "Zeta", "Synthetic", 2, "test", ("a", "diagnostic", "blocked"))),
        )
        contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", len(dataframe), len(dataframe.columns),
            "target", 1, "entity_id", features.registry_id, features.registry_hash, "validated", False,
        )
        dataset = LoadedDataset(dataframe, contract, Path("synthetic.csv"), "csv", "source-sha")
        population = EvaluationPopulation(tuple(range(len(dataframe))), "working-v1", "sha256:working", "working")
        return dataset, features, population

    @staticmethod
    def _spec(feature_id: str, column: str, group_id: str, status: FeatureUsageStatus) -> FeatureSpec:
        blocked_reason = "Blocked in test" if status is FeatureUsageStatus.BLOCKED else None
        return FeatureSpec(feature_id, column, feature_id, "Synthetic", group_id, "float", "numeric", "test", status, blocked_reason, None, None, 1)


if __name__ == "__main__":
    unittest.main()
