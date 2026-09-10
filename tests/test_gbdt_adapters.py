"""Smoke и contract-проверки зафиксированных Stage 1 GBDT adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from komus_risk.contracts import DatasetContract, ExperimentConfig, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentRunner
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.models.gbdt import (
    CATBOOST_MODEL_SPEC,
    CATBOOST_PROFILE,
    LIGHTGBM_MODEL_SPEC,
    LIGHTGBM_PROFILE,
    XGBOOST_MODEL_SPEC,
    XGBOOST_PROFILE,
    CatBoostAdapter,
    CatBoostFactory,
    LightGBMAdapter,
    LightGBMFactory,
    XGBoostAdapter,
    XGBoostFactory,
)
from komus_risk.registries import FeatureRegistry, ModelRegistry


@dataclass
class FakeEstimator:
    """Минимальный estimator для проверки search/refit, без ML-библиотеки."""

    parameters: dict
    best_value: int | None = None

    instances: list["FakeEstimator"] = None  # type: ignore[assignment]

    def __init__(self, **parameters: object) -> None:
        self.parameters = dict(parameters)
        self.best_value = None
        type(self).instances.append(self)

    def fit(self, *args: object, **kwargs: object) -> "FakeEstimator":
        return self

    def get_best_iteration(self) -> int:
        return 4

    @property
    def best_iteration(self) -> int:
        return 4

    @property
    def best_iteration_(self) -> int:
        return 5

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.column_stack((np.full(len(X), 0.4), np.full(len(X), 0.6)))


FakeEstimator.instances = []


class GBDTAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.X = pd.DataFrame(
            {
                "score": np.linspace(0.05, 0.95, 30),
                "flag": [index % 2 == 0 for index in range(30)],
            }
        )
        self.y = pd.Series([0, 1] * 15)

    def test_factories_adapters_and_model_specs_have_locked_identity(self) -> None:
        cases = (
            (CatBoostFactory, CatBoostAdapter, CATBOOST_MODEL_SPEC, "catboost", "1.2.10"),
            (XGBoostFactory, XGBoostAdapter, XGBOOST_MODEL_SPEC, "xgboost", "3.4.1"),
            (LightGBMFactory, LightGBMAdapter, LIGHTGBM_MODEL_SPEC, "lightgbm", "4.7.0"),
        )
        for factory_type, adapter_type, spec, model_id, library_version in cases:
            with self.subTest(model_id=model_id):
                factory = factory_type()
                self.assertIsInstance(factory, ModelAdapterFactory)
                self.assertEqual((factory.model_id, factory.model_version, factory.adapter_version), (model_id, "accepted_stage1_v2", "1"))
                self.assertEqual(factory.model_spec, spec)
                self.assertIn("binary", spec.task_types)
                self.assertEqual(spec.runtime_requirements["library"]["version"], library_version)
                self.assertEqual(spec.default_profile["fit_recipe"]["inner_validation_fraction"], 0.10)
                self.assertEqual(spec.default_profile["fit_recipe"]["early_stopping_rounds"], 40)
                self.assertEqual(spec.default_profile["runtime_policy"], {"device": "cpu"})

    def test_profiles_version_and_instances_are_guarded(self) -> None:
        cases = (
            (CatBoostFactory, CATBOOST_PROFILE),
            (XGBoostFactory, XGBOOST_PROFILE),
            (LightGBMFactory, LIGHTGBM_PROFILE),
        )
        for factory_type, profile in cases:
            with self.subTest(factory=factory_type.__name__):
                factory = factory_type()
                first = factory.create(deepcopy(profile), seed=11)
                second = factory.create(deepcopy(profile), seed=11)
                self.assertIsNot(first, second)
                self.assertIsInstance(first, BinaryClassifierAdapter)
                with self.assertRaises(ValueError):
                    factory.create({}, seed=11)
                changed = deepcopy(profile)
                changed["runtime_policy"]["device"] = "gpu"
                with self.assertRaises(ValueError):
                    factory.create(changed, seed=11)

        with patch("komus_risk.models.gbdt.common.version", return_value="0.0.0"):
            with self.assertRaisesRegex(ValueError, "требуется версия"):
                CatBoostFactory().create(deepcopy(CATBOOST_PROFILE), seed=11)

    def test_input_policy_rejects_categorical_missing_and_infinite_values(self) -> None:
        adapter = CatBoostFactory().create(deepcopy(CATBOOST_PROFILE), seed=11)
        invalid_inputs = (
            pd.DataFrame({"score": pd.Series(["a"] * 30, dtype="category")}),
            self.X.assign(score=np.nan),
            self.X.assign(score=np.inf),
        )
        for invalid_X in invalid_inputs:
            with self.subTest(columns=tuple(invalid_X.columns)):
                with self.assertRaises(ValueError):
                    adapter.fit(invalid_X, self.y)

    def test_search_and_refit_are_separate_and_transfer_best_iteration(self) -> None:
        cases = (
            ("komus_risk.models.gbdt.catboost.CatBoostClassifier", CatBoostAdapter, CATBOOST_PROFILE, "iterations", 5),
            ("komus_risk.models.gbdt.xgboost.XGBClassifier", XGBoostAdapter, XGBOOST_PROFILE, "n_estimators", 5),
            ("komus_risk.models.gbdt.lightgbm.LGBMClassifier", LightGBMAdapter, LIGHTGBM_PROFILE, "n_estimators", 5),
        )
        for target, adapter_type, profile, iteration_key, expected_iterations in cases:
            with self.subTest(adapter=adapter_type.__name__):
                FakeEstimator.instances = []
                with patch(target, FakeEstimator):
                    if adapter_type is LightGBMAdapter:
                        with patch("komus_risk.models.gbdt.lightgbm.early_stopping", return_value=object()):
                            adapter = adapter_type(deepcopy(profile), seed=11)
                            adapter.fit(self.X, self.y)
                    else:
                        adapter = adapter_type(deepcopy(profile), seed=11)
                        adapter.fit(self.X, self.y)
                self.assertIsNot(adapter.search_estimator, adapter.refit_estimator)
                self.assertEqual(adapter.best_iteration, expected_iterations)
                self.assertEqual(adapter.refit_estimator.parameters[iteration_key], expected_iterations)

    def test_fixed_seed_is_reproducible(self) -> None:
        cases = (
            (CatBoostFactory, CATBOOST_PROFILE),
            (XGBoostFactory, XGBOOST_PROFILE),
            (LightGBMFactory, LIGHTGBM_PROFILE),
        )
        for factory_type, profile in cases:
            with self.subTest(factory=factory_type.__name__):
                first = factory_type().create(deepcopy(profile), seed=17)
                second = factory_type().create(deepcopy(profile), seed=17)
                first.fit(self.X, self.y)
                second.fit(self.X, self.y)
                np.testing.assert_allclose(
                    first.predict_positive_proba(self.X), second.predict_positive_proba(self.X)
                )

    def test_tiny_oof_integration_for_each_factory(self) -> None:
        allowed_spec = FeatureSpec(
            "score", "score", "Сигнал", "Тестовый numeric signal", "main", "float", "numeric", "test",
            FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 1,
        )
        registry = FeatureRegistry(
            "features-v1", (allowed_spec,), (FeatureGroup("main", "Основная", "Тестовая", 1, "test", ("score",)),)
        )
        dataframe = pd.DataFrame({"entity_id": range(30), "target": [0, 1] * 15, "score": self.X["score"]})
        contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", 30, 3, "target", 1,
            "entity_id", registry.registry_id, registry.registry_hash, "validated", False,
        )
        loaded = LoadedDataset(dataframe, contract, Path("synthetic.csv"), "csv", "sha256:file")
        population = EvaluationPopulation(tuple(range(30)), "full-v1", "sha256:population", "full")
        cases = (
            (CatBoostFactory(), CATBOOST_MODEL_SPEC, CATBOOST_PROFILE),
            (XGBoostFactory(), XGBOOST_MODEL_SPEC, XGBOOST_PROFILE),
            (LightGBMFactory(), LIGHTGBM_MODEL_SPEC, LIGHTGBM_PROFILE),
        )
        for factory, spec, profile in cases:
            with self.subTest(model=spec.model_id):
                model_registry = ModelRegistry()
                model_registry.register(spec)
                config = ExperimentConfig(
                    f"integration-{spec.model_id}", "dataset-v1", "sha256:dataset", "target", ("score",), None,
                    ("main",), spec.model_id, spec.version, deepcopy(profile), "stratified_kfold_oof", "1",
                    42, 3, "oof", None, None, (),
                )
                output = ExperimentRunner(
                    feature_registry=registry,
                    model_registry=model_registry,
                    adapter_factory=factory,
                    code_version="test",
                ).run(loaded, config, population)
                self.assertFalse(np.isnan(output.oof_positive_proba).any())
                self.assertEqual(output.result.model_id, spec.model_id)
                self.assertEqual(output.result.model_version, "accepted_stage1_v2")


if __name__ == "__main__":
    unittest.main()
