"""Tests for the read-only experiment planning layer."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from komus_risk.application import RunExperimentRequest
from komus_risk.application.service import to_planning_request_metadata
from komus_risk.contracts import DatasetContract, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.models import ModelAdapterFactory
from komus_risk.planning import ExperimentPlanningService
from komus_risk.planning.contracts import PlanningRequestMetadata
from komus_risk.registries import FeatureRegistry, ModelRegistry, ModelSpec


class PlanningFactory(ModelAdapterFactory):
    model_id = "custom-planning-model"
    model_version = "1"
    adapter_version = "adapter-1"

    def create(self, parameters, seed):
        raise AssertionError("Planning must not create adapters.")


class ExperimentPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ExperimentPlanningService()
        self.registry = ModelRegistry()
        self.profile = {"fit_recipe": {"depth": 7}}
        self.spec = ModelSpec(
            "custom-planning-model", "Custom", "1", ("binary",), "Synthetic", self.profile, {}, "adapter-1"
        )
        self.registry.register(self.spec)
        self.factory = PlanningFactory()
        self.dataset, self.features, self.population = self._dataset()

    def test_dataset_passport_uses_contract_without_reading_source(self) -> None:
        passport = self.service.describe_dataset(self.dataset)

        self.assertEqual(passport.dataset_id, "dataset-v1")
        self.assertEqual(passport.dataset_fingerprint, "sha256:dataset")
        self.assertEqual(passport.row_count, 6)

    def test_application_adapter_preserves_all_request_metadata(self) -> None:
        request = RunExperimentRequest(
            selected_feature_ids=("b", "a"),
            model_id="custom-planning-model",
            protocol_id="stratified_kfold_oof",
            protocol_version="2",
            seed=43,
            folds=4,
            evaluation_level="oof",
            reference_artifact_id="artifact-1",
            changed_dimension="feature_set",
            changed_elements=("removed/a", "added/b"),
        )

        metadata = to_planning_request_metadata(request)

        self.assertIsInstance(metadata, PlanningRequestMetadata)
        self.assertEqual(metadata.selected_feature_ids, ("b", "a"))
        self.assertEqual(metadata.model_id, request.model_id)
        self.assertEqual(metadata.protocol_id, request.protocol_id)
        self.assertEqual(metadata.protocol_version, request.protocol_version)
        self.assertEqual(metadata.seed, request.seed)
        self.assertEqual(metadata.folds, request.folds)
        self.assertEqual(metadata.evaluation_level, request.evaluation_level)
        self.assertEqual(metadata.reference_artifact_id, request.reference_artifact_id)
        self.assertEqual(metadata.changed_dimension, request.changed_dimension)
        self.assertEqual(metadata.changed_elements, ("removed/a", "added/b"))

    def test_feature_views_are_status_controlled_and_ui_order_is_separate(self) -> None:
        views = self.service.list_features(self.features)

        self.assertEqual([view.feature_id for view in views], ["forbidden", "b", "a"])
        self.assertFalse(views[0].selectable)
        self.assertTrue(views[1].selectable)

    def test_build_plan_preserves_selected_order_and_never_runs_runner(self) -> None:
        request = self._request(("a", "b"))
        with patch("komus_risk.experiments.runner.ExperimentRunner.run", side_effect=AssertionError):
            plan = self.service.build_plan(
                request, loaded_dataset=self.dataset, feature_registry=self.features, model_registry=self.registry,
                model_factories={self.factory.model_id: self.factory}, population=self.population,
            )

        self.assertTrue(plan.is_valid)
        self.assertEqual(plan.selected_feature_ids, ("a", "b"))
        self.assertEqual([view.feature_id for view in plan.selected_features], ["a", "b"])
        self.assertEqual(plan.feature_groups, ("alpha", "zeta"))
        self.assertEqual(plan.model.model_id, self.spec.model_id)
        self.assertNotIn("experiment_id", plan.__dataclass_fields__)

    def test_plan_owns_immutable_planning_request_snapshot(self) -> None:
        request = RunExperimentRequest(("a", "b"), "custom-planning-model", "stratified_kfold_oof", "1", 42, 3, "oof", None, None, ())
        plan = self.service.build_plan(
            to_planning_request_metadata(request), loaded_dataset=self.dataset, feature_registry=self.features, model_registry=self.registry,
            model_factories={self.factory.model_id: self.factory}, population=self.population,
        )

        self.assertNotIsInstance(plan.request, RunExperimentRequest)
        self.assertEqual(plan.request.selected_feature_ids, ("a", "b"))
        object.__setattr__(request, "selected_feature_ids", ("b",))
        self.assertEqual(plan.request.selected_feature_ids, ("a", "b"))
        with self.assertRaises(AttributeError):
            plan.request.model_id = "other"

    def test_invalid_user_selection_or_model_returns_invalid_plan(self) -> None:
        forbidden = self.service.build_plan(
            self._request(("forbidden",)), loaded_dataset=self.dataset, feature_registry=self.features,
            model_registry=self.registry, model_factories={self.factory.model_id: self.factory}, population=self.population,
        )
        unknown = self.service.build_plan(
            self._request(("missing",), model_id="missing-model"), loaded_dataset=self.dataset, feature_registry=self.features,
            model_registry=self.registry, model_factories={}, population=self.population,
        )
        non_runnable = self.service.build_plan(
            self._request(("a",)), loaded_dataset=self.dataset, feature_registry=self.features,
            model_registry=self.registry, model_factories={}, population=self.population,
        )

        self.assertFalse(forbidden.is_valid)
        self.assertEqual(forbidden.validation_errors, ("forbidden_feature:forbidden",))
        self.assertFalse(unknown.is_valid)
        self.assertIn("unknown_feature:missing", unknown.validation_errors)
        self.assertIn("unknown_model:missing-model", unknown.validation_errors)
        self.assertEqual(non_runnable.validation_errors, ("non_runnable_model:custom-planning-model",))

    def test_model_profile_is_deep_copied_and_broken_factory_contract_raises(self) -> None:
        model = self.service.list_models(self.registry, {self.factory.model_id: self.factory})[0]
        self.assertEqual(model.default_profile, self.profile)
        with self.assertRaises(TypeError):
            model.default_profile["fit_recipe"] = {}
        self.assertEqual(self.profile, {"fit_recipe": {"depth": 7}})

        wrong = PlanningFactory()
        wrong.model_version = "other"
        with self.assertRaises(ValueError):
            self.service.list_models(self.registry, {wrong.model_id: wrong})

    @staticmethod
    def _request(feature_ids: tuple[str, ...], model_id: str = "custom-planning-model") -> PlanningRequestMetadata:
        return to_planning_request_metadata(
            RunExperimentRequest(feature_ids, model_id, "stratified_kfold_oof", "1", 42, 3, "oof", None, None, ())
        )

    def _dataset(self) -> tuple[LoadedDataset, FeatureRegistry, EvaluationPopulation]:
        specs = (
            FeatureSpec("a", "a", "A", "A", "zeta", "float", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 2),
            FeatureSpec("b", "b", "B", "B", "alpha", "float", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 1),
            FeatureSpec("forbidden", "forbidden", "F", "F", "zeta", "float", "numeric", "test", FeatureUsageStatus.BLOCKED, "Blocked", None, None, 0),
        )
        features = FeatureRegistry(
            "features-v1", specs,
            (FeatureGroup("alpha", "Alpha", "Synthetic", 1, "test", ("b",)), FeatureGroup("zeta", "Zeta", "Synthetic", 2, "test", ("a", "forbidden"))),
        )
        dataframe = pd.DataFrame({"entity": list(range(6)), "target": [0, 1, 0, 1, 0, 1], "a": [0.1] * 6, "b": [0.2] * 6, "forbidden": [0] * 6})
        contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", 6, 5, "target", 1, "entity",
            features.registry_id, features.registry_hash, "validated", False,
        )
        return (
            LoadedDataset(dataframe, contract, Path("not-read.csv"), "csv", "source-sha"),
            features,
            EvaluationPopulation((0, 1, 2, 3, 4, 5), "working", "sha256:working", "working"),
        )


if __name__ == "__main__":
    unittest.main()
