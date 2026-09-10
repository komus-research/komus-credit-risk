"""Regression tests for the locked equal-weight GBDT composite."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from komus_risk.contracts import DatasetContract, ExperimentConfig, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentRunner
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.models.gbdt import GBDT_MEAN_MODEL_SPEC, GBDT_MEAN_PROFILE, GBDTMeanFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry


class SpyAdapter(BinaryClassifierAdapter):
    def __init__(self, prediction: object, *, fail_fit: bool = False) -> None:
        self.prediction = prediction
        self.fail_fit = fail_fit
        self.fit_calls: list[tuple[pd.DataFrame, pd.Series]] = []
        self.predict_calls = 0

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        self.fit_calls.append((X_train, y_train))
        if self.fail_fit:
            raise RuntimeError("component failure")

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        self.predict_calls += 1
        if callable(self.prediction):
            return np.asarray(self.prediction(X_valid), dtype=float)
        return np.asarray(self.prediction, dtype=float)


class SpyFactory(ModelAdapterFactory):
    model_version = "accepted_stage1_v2"
    adapter_version = "1"

    def __init__(self, model_id: str, prediction: object, *, fail_fit: bool = False) -> None:
        self.model_id = model_id
        self.prediction = prediction
        self.fail_fit = fail_fit
        self.received: list[tuple[dict[str, object], int]] = []
        self.instances: list[SpyAdapter] = []

    def create(self, parameters: dict[str, object], seed: int) -> BinaryClassifierAdapter:
        self.received.append((deepcopy(parameters), seed))
        adapter = SpyAdapter(self.prediction, fail_fit=self.fail_fit)
        self.instances.append(adapter)
        return adapter


def component_factories(predictions: dict[str, object] | None = None) -> dict[str, SpyFactory]:
    predictions = predictions or {
        "catboost": np.array([0.1, 0.4]),
        "xgboost": np.array([0.2, 0.5]),
        "lightgbm": np.array([0.3, 0.6]),
    }
    return {model_id: SpyFactory(model_id, prediction) for model_id, prediction in predictions.items()}


class GBDTMeanTests(unittest.TestCase):
    def test_fresh_composite_passes_shared_data_seed_and_means_predictions(self) -> None:
        factories = component_factories()
        factory = GBDTMeanFactory(factories)
        first = factory.create(deepcopy(GBDT_MEAN_PROFILE), 19)
        second = factory.create(deepcopy(GBDT_MEAN_PROFILE), 19)
        X_train = pd.DataFrame({"score": [0.1, 0.9, 0.2, 0.8]})
        y_train = pd.Series([0, 1, 0, 1])
        X_valid = pd.DataFrame({"score": [0.25, 0.75]})

        self.assertIsNot(first, second)
        first.fit(X_train, y_train)
        probabilities = first.predict_positive_proba(X_valid)

        np.testing.assert_allclose(probabilities, np.array([0.2, 0.5]))
        for model_id, component_factory in factories.items():
            self.assertEqual(len(component_factory.instances), 2)
            self.assertIsNot(component_factory.instances[0], component_factory.instances[1])
            self.assertEqual(component_factory.received[0][0], GBDT_MEAN_PROFILE["components"][model_id]["profile"])
            self.assertEqual(component_factory.received[0][1], 19)
            self.assertIs(component_factory.instances[0].fit_calls[0][0], X_train)
            self.assertIs(component_factory.instances[0].fit_calls[0][1], y_train)
            self.assertEqual(component_factory.instances[0].predict_calls, 1)

    def test_factory_rejects_wrong_component_set_or_identity_before_training(self) -> None:
        factories = component_factories()
        with self.assertRaises(ValueError):
            GBDTMeanFactory({key: value for key, value in factories.items() if key != "lightgbm"})
        with self.assertRaises(ValueError):
            GBDTMeanFactory({**factories, "other": SpyFactory("other", [0.1, 0.2])})
        wrong = component_factories()
        wrong["catboost"] = SpyFactory("not-catboost", [0.1, 0.2])
        with self.assertRaises(ValueError):
            GBDTMeanFactory(wrong)

        self.assertTrue(all(not factory.instances for factory in factories.values()))

    def test_factory_rejects_any_nested_profile_change(self) -> None:
        profile = deepcopy(GBDT_MEAN_PROFILE)
        profile["components"]["catboost"]["profile"]["estimator_params"]["iterations"] = 1

        with self.assertRaisesRegex(ValueError, "frozen composite profile"):
            GBDTMeanFactory(component_factories()).create(profile, 42)

    def test_predict_rejects_invalid_component_probabilities(self) -> None:
        cases = (
            {"catboost": np.array([0.1]), "xgboost": np.array([0.2, 0.3]), "lightgbm": np.array([0.3, 0.4])},
            {"catboost": np.array([[0.1, 0.2]]), "xgboost": np.array([0.2, 0.3]), "lightgbm": np.array([0.3, 0.4])},
            {"catboost": np.array([0.1, np.nan]), "xgboost": np.array([0.2, 0.3]), "lightgbm": np.array([0.3, 0.4])},
            {"catboost": np.array([0.1, 1.1]), "xgboost": np.array([0.2, 0.3]), "lightgbm": np.array([0.3, 0.4])},
        )
        X_train = pd.DataFrame({"score": [0.1, 0.9]})
        y_train = pd.Series([0, 1])
        X_valid = pd.DataFrame({"score": [0.2, 0.8]})

        for predictions in cases:
            with self.subTest(predictions=predictions):
                adapter = GBDTMeanFactory(component_factories(predictions)).create(deepcopy(GBDT_MEAN_PROFILE), 42)
                adapter.fit(X_train, y_train)
                with self.assertRaises(ValueError):
                    adapter.predict_positive_proba(X_valid)

    def test_component_failure_has_no_partial_ensemble(self) -> None:
        factories = component_factories()
        factories["xgboost"] = SpyFactory("xgboost", [0.2, 0.5], fail_fit=True)
        adapter = GBDTMeanFactory(factories).create(deepcopy(GBDT_MEAN_PROFILE), 42)
        X_train = pd.DataFrame({"score": [0.1, 0.9]})
        y_train = pd.Series([0, 1])

        with self.assertRaisesRegex(RuntimeError, "xgboost") as error:
            adapter.fit(X_train, y_train)

        self.assertIsInstance(error.exception.__cause__, RuntimeError)
        with self.assertRaises(RuntimeError):
            adapter.predict_positive_proba(pd.DataFrame({"score": [0.2, 0.8]}))

    def test_reordered_components_preserve_profile_hash_semantics(self) -> None:
        reordered = deepcopy(GBDT_MEAN_PROFILE)
        reordered["components"] = {
            model_id: reordered["components"][model_id]
            for model_id in ("xgboost", "lightgbm", "catboost")
        }

        self.assertEqual(reordered, GBDT_MEAN_PROFILE)
        first = self._config(deepcopy(GBDT_MEAN_PROFILE))
        second = self._config(reordered)
        self.assertEqual(first.config_hash, second.config_hash)
        GBDTMeanFactory(component_factories()).create(reordered, 42)

    def test_tiny_oof_runs_through_unchanged_runner(self) -> None:
        dataframe = pd.DataFrame(
            {
                "entity_id": [f"entity-{index}" for index in range(12)],
                "target": [0, 1] * 6,
                "score": [0.10, 0.90, 0.80, 0.20, 0.30, 0.70, 0.60, 0.40, 0.15, 0.85, 0.55, 0.45],
            }
        )
        feature = FeatureSpec(
            "score", "score", "Score", "Synthetic score", "main", "float", "numeric", "test",
            FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 1,
        )
        feature_registry = FeatureRegistry(
            "features-v1", (feature,), (FeatureGroup("main", "Main", "Synthetic", 1, "test", ("score",)),)
        )
        contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", len(dataframe), len(dataframe.columns),
            "target", 1, "entity_id", feature_registry.registry_id, feature_registry.registry_hash, "validated", False,
        )
        model_registry = ModelRegistry()
        model_registry.register(GBDT_MEAN_MODEL_SPEC)
        score_prediction = lambda X: X["score"].to_numpy(dtype=float)
        runner = ExperimentRunner(
            feature_registry=feature_registry,
            model_registry=model_registry,
            adapter_factory=GBDTMeanFactory(
                component_factories({model_id: score_prediction for model_id in ("catboost", "xgboost", "lightgbm")})
            ),
            code_version="test-code",
        )

        output = runner.run(
            LoadedDataset(dataframe, contract, Path("synthetic.csv"), "csv", "source-sha"),
            self._config(deepcopy(GBDT_MEAN_PROFILE)),
            EvaluationPopulation(tuple(range(len(dataframe))), "working-v1", "sha256:working", "working"),
        )

        self.assertEqual(output.result.model_id, "gbdt_mean")
        np.testing.assert_allclose(output.oof_positive_proba, dataframe["score"].to_numpy())

    @staticmethod
    def _config(parameters: dict[str, object]) -> ExperimentConfig:
        return ExperimentConfig(
            "gbdt-mean-oof", "dataset-v1", "sha256:dataset", "target", ("score",), None, ("main",),
            "gbdt_mean", "accepted_stage1_v2_equal_mean", parameters,
            "stratified_kfold_oof", "1", 42, 3, "oof", None, None, (),
        )


if __name__ == "__main__":
    unittest.main()
