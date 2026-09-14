"""Точечные проверки runtime OOF-контура без concrete ML-адаптеров."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

from komus_risk.contracts import (
    DatasetContract,
    ExperimentConfig,
    FeatureGroup,
    FeatureSpec,
    FeatureUsageStatus,
)
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentRunner
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry, ModelSpec


class DeterministicAdapter(BinaryClassifierAdapter):
    """Тестовый adapter: вероятность уже хранится в разрешённом признаке."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.fit_calls: list[tuple[pd.DataFrame, pd.Series]] = []

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        self.fit_calls.append((X_train.copy(), y_train.copy()))

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        return X_valid["score"].to_numpy(dtype=float)


class DeterministicFactory(ModelAdapterFactory):
    model_id = "test-binary"
    model_version = "1"
    adapter_version = "adapter-1"

    def __init__(self) -> None:
        self.instances: list[DeterministicAdapter] = []

    def create(self, parameters: dict[str, object], seed: int) -> BinaryClassifierAdapter:
        adapter = DeterministicAdapter(seed)
        self.instances.append(adapter)
        return adapter


class ExperimentRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataframe = pd.DataFrame(
            {
                "entity_id": [f"entity-{index}" for index in range(12)],
                "target": [0, 1] * 6,
                "score": [0.10, 0.90, 0.80, 0.20, 0.30, 0.70, 0.60, 0.40, 0.15, 0.85, 0.55, 0.45],
                "diagnostic": list(range(12)),
            }
        )
        self.allowed_spec = self._feature_spec("score", "score", FeatureUsageStatus.MODEL_ALLOWED)
        self.diagnostic_spec = self._feature_spec(
            "diagnostic", "diagnostic", FeatureUsageStatus.DIAGNOSTIC_ONLY
        )
        self.feature_registry = FeatureRegistry(
            "features-v1",
            (self.allowed_spec, self.diagnostic_spec),
            (FeatureGroup("main", "Основная", "Тестовая группа", 1, "test", ("score", "diagnostic")),),
        )
        self.model_registry = ModelRegistry()
        self.model_registry.register(
            ModelSpec(
                "test-binary", "Тестовая модель", "1", ("binary",), "Детерминированная модель",
                {}, {}, "adapter-1",
            )
        )
        self.factory = DeterministicFactory()
        self.runner = ExperimentRunner(
            feature_registry=self.feature_registry,
            model_registry=self.model_registry,
            adapter_factory=self.factory,
            code_version="test-code",
        )
        self.contract = DatasetContract(
            dataset_id="dataset-v1",
            dataset_version="1",
            dataset_name="Синтетический набор",
            source_type="ready_csv",
            dataset_fingerprint="sha256:dataset",
            row_count=len(self.dataframe),
            column_count=len(self.dataframe.columns),
            target_column="target",
            positive_class=1,
            identifier_column="entity_id",
            feature_registry_id=self.feature_registry.registry_id,
            feature_registry_hash=self.feature_registry.registry_hash,
            validation_status="validated",
            final_test_locked=True,
        )
        self.loaded_dataset = LoadedDataset(
            dataframe=self.dataframe,
            contract=self.contract,
            source_path=Path("synthetic.csv"),
            source_format="csv",
            source_file_sha256="source-sha",
        )
        self.config = ExperimentConfig(
            experiment_id="experiment-v1",
            dataset_id=self.contract.dataset_id,
            dataset_fingerprint=self.contract.dataset_fingerprint,
            target="target",
            feature_ids=("score",),
            feature_set_hash=None,
            feature_groups=("main",),
            model_id="test-binary",
            model_version="1",
            model_parameters={"test_parameter": True},
            protocol_id="stratified_kfold_oof",
            protocol_version="1",
            seed=42,
            folds=3,
            evaluation_level="oof",
            reference_result_id=None,
            changed_dimension=None,
            changed_elements=(),
        )
        self.population = EvaluationPopulation(
            tuple(range(len(self.dataframe))), "working-v1", "sha256:working", "working"
        )

    @staticmethod
    def _feature_spec(feature_id: str, column_name: str, status: FeatureUsageStatus) -> FeatureSpec:
        return FeatureSpec(
            feature_id=feature_id,
            column_name=column_name,
            display_name_ru="Тестовый признак",
            description_ru="Для runtime-теста",
            group_id="main",
            dtype="float",
            semantic_type="numeric",
            origin="test",
            usage_status=status,
            blocked_reason=None,
            source_reference=None,
            formula_hash=None,
            display_order=1,
        )

    def test_happy_path_has_full_oof_coverage_and_fresh_adapter_per_fold(self) -> None:
        output = self.runner.run(self.loaded_dataset, self.config, self.population)

        self.assertEqual(len(output.oof_positive_proba), len(self.dataframe))
        self.assertFalse(np.isnan(output.oof_positive_proba).any())
        self.assertEqual(set(output.fold_assignments), {1, 2, 3})
        self.assertEqual(tuple(output.row_positions), self.population.row_positions)
        self.assertEqual(len(self.factory.instances), 3)
        self.assertEqual([adapter.seed for adapter in self.factory.instances], [43, 44, 45])
        self.assertTrue(all(len(adapter.fit_calls) == 1 for adapter in self.factory.instances))
        self.assertEqual(len(output.result.fold_metrics), 3)
        self.assertEqual(output.result.comparison, {})

    def test_progress_sequence_is_observational_and_does_not_change_oof_evidence(self) -> None:
        without_listener = self.runner.run(self.loaded_dataset, self.config, self.population)
        events = []
        with_listener = self.runner.run(self.loaded_dataset, self.config, self.population, progress_listener=events.append)

        self.assertEqual(
            [(event.stage, event.fold_number, event.folds_total) for event in events],
            [
                ("run_started", None, 3),
                ("fold_started", 1, 3), ("fold_completed", 1, 3),
                ("fold_started", 2, 3), ("fold_completed", 2, 3),
                ("fold_started", 3, 3), ("fold_completed", 3, 3),
                ("aggregate_metrics_started", None, 3),
            ],
        )
        np.testing.assert_array_equal(without_listener.oof_positive_proba, with_listener.oof_positive_proba)
        np.testing.assert_array_equal(without_listener.fold_assignments, with_listener.fold_assignments)
        self.assertEqual(without_listener.result.metrics, with_listener.result.metrics)
        self.assertEqual(without_listener.result.confusion, with_listener.result.confusion)

    def test_listener_overhead_is_excluded_from_reported_runtime(self) -> None:
        class ControlledClock:
            def __init__(self) -> None:
                self.current = 0.0

            def __call__(self) -> float:
                return self.current

            def advance(self, duration: float) -> None:
                self.current += duration

        clock = ControlledClock()

        def slow_listener(_event) -> None:
            clock.advance(10.0)

        with patch("komus_risk.experiments.runner.perf_counter", clock):
            output = self.runner.run(
                self.loaded_dataset,
                self.config,
                self.population,
                progress_listener=slow_listener,
            )

        self.assertEqual(output.result.runtime_seconds, 0.0)

    def test_same_seed_is_reproducible_and_changed_seed_changes_split(self) -> None:
        first = self.runner.run(self.loaded_dataset, self.config, self.population)
        second = self.runner.run(self.loaded_dataset, self.config, self.population)
        changed_seed = self.runner.run(
            self.loaded_dataset, replace(self.config, experiment_id="experiment-v2", seed=7), self.population
        )

        np.testing.assert_array_equal(first.oof_positive_proba, second.oof_positive_proba)
        np.testing.assert_array_equal(first.fold_assignments, second.fold_assignments)
        self.assertFalse(np.array_equal(first.fold_assignments, changed_seed.fold_assignments))

    def test_global_metrics_match_independent_calculation(self) -> None:
        output = self.runner.run(self.loaded_dataset, self.config, self.population)
        y_true = self.dataframe["target"]
        probabilities = self.dataframe["score"].to_numpy()
        predicted = probabilities >= 0.5
        expected_auc = roc_auc_score(y_true, probabilities)

        self.assertAlmostEqual(output.result.metrics["roc_auc"], expected_auc)
        self.assertAlmostEqual(output.result.metrics["gini"], 2 * expected_auc - 1)
        self.assertAlmostEqual(output.result.metrics["pr_auc"], average_precision_score(y_true, probabilities))
        self.assertAlmostEqual(output.result.metrics["precision_at_0_5"], precision_score(y_true, predicted))
        self.assertAlmostEqual(output.result.metrics["recall_at_0_5"], recall_score(y_true, predicted))
        self.assertAlmostEqual(output.result.metrics["f1_at_0_5"], f1_score(y_true, predicted))
        self.assertEqual(output.result.confusion, {"threshold": 0.5, "tp": 3, "tn": 3, "fp": 3, "fn": 3})

    def test_identity_and_feature_guards_run_before_fit(self) -> None:
        wrong_dataset = replace(self.config, dataset_id="other-dataset")
        with self.assertRaisesRegex(ValueError, "Идентичность датасета"):
            self.runner.run(self.loaded_dataset, wrong_dataset, self.population)

        wrong_registry_contract = replace(self.contract, feature_registry_id="other-registry")
        with self.assertRaisesRegex(ValueError, "FeatureRegistry"):
            self.runner.run(replace(self.loaded_dataset, contract=wrong_registry_contract), self.config, self.population)

        diagnostic_config = replace(self.config, feature_ids=("diagnostic",), feature_set_hash=None)
        with self.assertRaisesRegex(ValueError, "не разрешён"):
            self.runner.run(self.loaded_dataset, diagnostic_config, self.population)

        wrong_factory = DeterministicFactory()
        wrong_factory.model_version = "other"
        wrong_runner = ExperimentRunner(
            feature_registry=self.feature_registry,
            model_registry=self.model_registry,
            adapter_factory=wrong_factory,
            code_version="test-code",
        )
        with self.assertRaisesRegex(ValueError, "ModelAdapterFactory"):
            wrong_runner.run(self.loaded_dataset, self.config, self.population)

        self.assertEqual(self.factory.instances, [])

    def test_locked_full_population_is_rejected_before_fit(self) -> None:
        forbidden_population = EvaluationPopulation(
            tuple(range(len(self.dataframe))), "full-v1", "sha256:full", "full"
        )
        with self.assertRaisesRegex(ValueError, "закрытым final test"):
            self.runner.run(self.loaded_dataset, self.config, forbidden_population)

        self.assertEqual(self.factory.instances, [])

    def test_feature_registry_rejects_feature_with_unknown_group(self) -> None:
        orphan_feature = replace(self.allowed_spec, group_id="missing-group")
        with self.assertRaises(ValueError) as error:
            FeatureRegistry("invalid-registry", (orphan_feature,), ())

        self.assertIn("score", str(error.exception))
        self.assertIn("missing-group", str(error.exception))

    def test_feature_registry_rejects_group_with_unknown_feature(self) -> None:
        group = FeatureGroup("main", "Основная", "Тестовая группа", 1, "test", ("missing-feature",))
        with self.assertRaises(ValueError) as error:
            FeatureRegistry("invalid-registry", (self.allowed_spec,), (group,))

        self.assertIn("main", str(error.exception))
        self.assertIn("missing-feature", str(error.exception))

    def test_feature_registry_rejects_feature_listed_in_another_group(self) -> None:
        main_group = FeatureGroup("main", "Основная", "Тестовая группа", 1, "test", ("diagnostic",))
        other_group = FeatureGroup("other", "Другая", "Другая группа", 2, "test", ("score",))
        with self.assertRaises(ValueError) as error:
            FeatureRegistry(
                "invalid-registry", (self.allowed_spec, self.diagnostic_spec), (main_group, other_group)
            )

        self.assertIn("score", str(error.exception))
        self.assertIn("other", str(error.exception))
        self.assertIn("main", str(error.exception))


if __name__ == "__main__":
    unittest.main()
