"""Tests for the read-only experiment planning layer."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from komus_risk.application import RunExperimentRequest
from komus_risk.application.service import to_planning_request_metadata
from komus_risk.contracts import (
    DatasetContract,
    FeatureGroup,
    FeatureSpec,
    FeatureUsageStatus,
)
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.model_platform import build_builtin_model_plugin_registry
from komus_risk.planning import ExperimentPlanningService
from komus_risk.planning.contracts import PlanningRequestMetadata
from komus_risk.registries import FeatureRegistry


class ExperimentPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ExperimentPlanningService(
            model_plugin_registry=build_builtin_model_plugin_registry()
        )
        self.dataset, self.features, self.population = self._dataset()

    def test_dataset_passport_uses_contract_without_reading_source(self) -> None:
        passport = self.service.describe_dataset(self.dataset)

        self.assertEqual(passport.dataset_id, "dataset-v1")
        self.assertEqual(passport.dataset_fingerprint, "sha256:dataset")
        self.assertEqual(passport.row_count, 6)

    def test_application_adapter_preserves_all_request_metadata(self) -> None:
        request = RunExperimentRequest(
            selected_feature_ids=("b", "a"),
            model_id="catboost",
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
        self.assertEqual(views[0].blocked_reason, "Blocked")
        self.assertTrue(views[1].selectable)
        groups = self.service.list_feature_groups(self.features)
        self.assertEqual(
            [(group.group_id, group.name_ru) for group in groups],
            [("alpha", "Alpha"), ("zeta", "Zeta")],
        )

    def test_build_plan_preserves_selected_order_and_never_runs_runner(self) -> None:
        request = self._request(("a", "b"))
        with patch(
            "komus_risk.experiments.runner.ExperimentRunner.run",
            side_effect=AssertionError,
        ):
            plan = self.service.build_plan(
                request,
                loaded_dataset=self.dataset,
                feature_registry=self.features,
                population=self.population,
            )

        self.assertTrue(plan.is_valid)
        self.assertEqual(plan.selected_feature_ids, ("a", "b"))
        self.assertEqual(
            [view.feature_id for view in plan.selected_features], ["a", "b"]
        )
        self.assertEqual(plan.feature_groups, ("alpha", "zeta"))
        self.assertEqual(plan.model.model_id, "catboost")
        self.assertNotIn("experiment_id", plan.__dataclass_fields__)

    def test_plan_owns_immutable_planning_request_snapshot(self) -> None:
        request = RunExperimentRequest(
            ("a", "b"),
            "custom-planning-model",
            "stratified_kfold_oof",
            "1",
            42,
            3,
            "oof",
            None,
            None,
            (),
        )
        plan = self.service.build_plan(
            to_planning_request_metadata(request),
            loaded_dataset=self.dataset,
            feature_registry=self.features,
            population=self.population,
        )

        self.assertNotIsInstance(plan.request, RunExperimentRequest)
        self.assertEqual(plan.request.selected_feature_ids, ("a", "b"))
        object.__setattr__(request, "selected_feature_ids", ("b",))
        self.assertEqual(plan.request.selected_feature_ids, ("a", "b"))
        with self.assertRaises(AttributeError):
            plan.request.model_id = "other"

    def test_invalid_user_selection_or_model_returns_invalid_plan(self) -> None:
        forbidden = self.service.build_plan(
            self._request(("forbidden",)),
            loaded_dataset=self.dataset,
            feature_registry=self.features,
            population=self.population,
        )
        unknown = self.service.build_plan(
            self._request(("missing",), model_id="missing-model"),
            loaded_dataset=self.dataset,
            feature_registry=self.features,
            population=self.population,
        )

        self.assertFalse(forbidden.is_valid)
        self.assertEqual(forbidden.validation_errors, ("forbidden_feature:forbidden",))
        self.assertFalse(unknown.is_valid)
        self.assertIn("unknown_feature:missing", unknown.validation_errors)
        self.assertIn("unknown_model:missing-model", unknown.validation_errors)

    def test_models_are_catalog_backed_and_detached(self) -> None:
        model = next(
            item for item in self.service.list_models() if item.model_id == "catboost"
        )
        self.assertEqual(model.default_profile["estimator_params"]["depth"], 7)
        with self.assertRaises(TypeError):
            model.default_profile["fit_recipe"] = {}

    @staticmethod
    def _request(
        feature_ids: tuple[str, ...], model_id: str = "catboost"
    ) -> PlanningRequestMetadata:
        return to_planning_request_metadata(
            RunExperimentRequest(
                feature_ids,
                model_id,
                "stratified_kfold_oof",
                "1",
                42,
                3,
                "oof",
                None,
                None,
                (),
            )
        )

    def _dataset(self) -> tuple[LoadedDataset, FeatureRegistry, EvaluationPopulation]:
        specs = (
            FeatureSpec(
                "a",
                "a",
                "A",
                "A",
                "zeta",
                "float",
                "numeric",
                "test",
                FeatureUsageStatus.MODEL_ALLOWED,
                None,
                None,
                None,
                2,
            ),
            FeatureSpec(
                "b",
                "b",
                "B",
                "B",
                "alpha",
                "float",
                "numeric",
                "test",
                FeatureUsageStatus.MODEL_ALLOWED,
                None,
                None,
                None,
                1,
            ),
            FeatureSpec(
                "forbidden",
                "forbidden",
                "F",
                "F",
                "zeta",
                "float",
                "numeric",
                "test",
                FeatureUsageStatus.BLOCKED,
                "Blocked",
                None,
                None,
                0,
            ),
        )
        features = FeatureRegistry(
            "features-v1",
            specs,
            (
                FeatureGroup("alpha", "Alpha", "Synthetic", 1, "test", ("b",)),
                FeatureGroup(
                    "zeta", "Zeta", "Synthetic", 2, "test", ("a", "forbidden")
                ),
            ),
        )
        dataframe = pd.DataFrame(
            {
                "entity": list(range(6)),
                "target": [0, 1, 0, 1, 0, 1],
                "a": [0.1] * 6,
                "b": [0.2] * 6,
                "forbidden": [0] * 6,
            }
        )
        contract = DatasetContract(
            "dataset-v1",
            "1",
            "Synthetic",
            "ready_csv",
            "sha256:dataset",
            6,
            5,
            "target",
            1,
            "entity",
            features.registry_id,
            features.registry_hash,
            "validated",
            False,
        )
        return (
            LoadedDataset(
                dataframe, contract, Path("not-read.csv"), "csv", "source-sha"
            ),
            features,
            EvaluationPopulation(
                (0, 1, 2, 3, 4, 5), "working", "sha256:working", "working"
            ),
        )


if __name__ == "__main__":
    unittest.main()
