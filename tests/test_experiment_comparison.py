"""Tests for the pure controlled-comparison service."""

from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from komus_risk.comparison import ComparisonSubject, ExperimentComparisonService
from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult


METRICS = {
    "gini": 0.20,
    "roc_auc": 0.60,
    "pr_auc": 0.55,
    "precision_at_0_5": 0.50,
    "recall_at_0_5": 0.40,
    "f1_at_0_5": 0.44,
}
CONFUSION = {"threshold": 0.5, "tp": 4, "tn": 5, "fp": 2, "fn": 3}


class ExperimentComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ExperimentComparisonService()
        self.contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", 20, 5, "target", 1,
            "entity_id", "features-v1", "sha256:features", "validated", False,
        )
        self.reference_config = self._config("reference", ("a", "b"))
        self.reference = self._subject(self.reference_config, "result-reference")

    def test_only_model_change_is_comparable_and_has_candidate_minus_reference_deltas(self) -> None:
        candidate = self._subject(
            replace(self._config("candidate", ("a", "b")), model_id="xgboost", model_version="2"),
            "result-candidate",
            metric_offset=0.10,
            confusion_offset=1,
            runtime=3.0,
        )

        result = self.service.compare(self.reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.status, "COMPARABLE_MODEL_CHANGE")
        self.assertEqual(result.changed_dimension, "model")
        self.assertEqual(result.model_change["changed_fields"], ("model_id", "model_version"))
        self.assertAlmostEqual(result.metric_deltas["gini"], 0.10)
        self.assertEqual(result.confusion_deltas, {"tp": 1.0, "tn": 1.0, "fp": 1.0, "fn": 1.0})
        self.assertEqual(result.runtime_delta_seconds, 1.0)
        self.assertAlmostEqual(result.fold_deltas[0]["delta_gini"], 0.10)
        self.assertAlmostEqual(result.fold_deltas[0]["delta_runtime_seconds"], 0.5)

    def test_only_model_parameters_changed_is_model_comparison(self) -> None:
        candidate = self._subject(
            replace(self._config("candidate", ("a", "b")), model_parameters={"depth": 8}), "result-candidate"
        )

        result = self.service.compare(self.reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.changed_dimension, "model")
        self.assertEqual(result.model_change["changed_fields"], ("model_parameters",))

    def test_top_level_parameter_declaration_uses_parameter_path_not_container(self) -> None:
        candidate = self._subject(
            replace(
                self._config("candidate", ("a", "b")), model_parameters={"depth": 8},
                changed_dimension="model", changed_elements=("depth",),
            ),
            "result-candidate",
        )

        result = self.service.compare(self.reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.declaration_check["actual_elements"], ("depth",))
        self.assertTrue(result.declaration_check["is_consistent"])

    def test_old_model_parameters_container_declaration_is_rejected(self) -> None:
        candidate = self._subject(
            replace(
                self._config("candidate", ("a", "b")), model_parameters={"depth": 8},
                changed_dimension="model", changed_elements=("model_parameters",),
            ),
            "result-candidate",
        )

        self.assertEqual(self.service.compare(self.reference, candidate).status, "DECLARED_CHANGE_MISMATCH")

    def test_nested_model_parameters_have_canonical_json_pointer_paths(self) -> None:
        reference_config = replace(
            self._config("nested-reference", ("a", "b")),
            model_parameters={"fit_recipe": {"early_stopping_rounds": 40, "a/b~c": 1}},
        )
        reference = self._subject(reference_config, "result-nested-reference")
        candidate = self._subject(
            replace(
                self._config("nested-candidate", ("a", "b")),
                model_parameters={"fit_recipe": {"early_stopping_rounds": 50, "a/b~c": 2}},
                changed_dimension="model",
                changed_elements=("fit_recipe/a~1b~0c", "fit_recipe/early_stopping_rounds"),
            ),
            "result-nested-candidate",
        )

        result = self.service.compare(reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(
            result.declaration_check["actual_elements"],
            ("fit_recipe/a~1b~0c", "fit_recipe/early_stopping_rounds"),
        )

    def test_model_identity_and_parameter_elements_follow_canonical_order(self) -> None:
        candidate = self._subject(
            replace(
                self._config("candidate", ("a", "b")), model_id="xgboost", model_version="2",
                model_parameters={"depth": 8}, changed_dimension="model",
                changed_elements=("@model_id", "@model_version", "depth"),
            ),
            "result-candidate",
        )

        result = self.service.compare(self.reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.declaration_check["actual_elements"], ("@model_id", "@model_version", "depth"))

    def test_only_feature_change_is_comparable_with_deterministic_membership_diff(self) -> None:
        candidate = self._subject(self._config("candidate", ("b", "c", "d")), "result-candidate")

        result = self.service.compare(self.reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.status, "COMPARABLE_FEATURE_SET_CHANGE")
        self.assertEqual(result.feature_change, {"added": ("c", "d"), "removed": ("a",), "unchanged": ("b",)})

    def test_feature_declaration_uses_removed_then_added_canonical_order(self) -> None:
        reference = self._subject(self._config("features-reference", ("f1", "f2")), "result-features-reference")
        candidate = self._subject(
            replace(
                self._config("features-candidate", ("f2", "f3")), changed_dimension="feature_set",
                changed_elements=("removed:f1", "added:f3"),
            ),
            "result-features-candidate",
        )

        result = self.service.compare(reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.declaration_check["actual_elements"], ("removed:f1", "added:f3"))

    def test_feature_declaration_requires_exact_canonical_tuple_order(self) -> None:
        reference = self._subject(self._config("features-reference", ("f1", "f2")), "result-features-reference")
        candidate = self._subject(
            replace(
                self._config("features-candidate", ("f2", "f3")), changed_dimension="feature_set",
                changed_elements=("added:f3", "removed:f1"),
            ),
            "result-features-candidate",
        )

        result = self.service.compare(reference, candidate)

        self.assertFalse(result.is_comparable)
        self.assertEqual(result.status, "DECLARED_CHANGE_MISMATCH")

    def test_dataset_population_and_semantic_changes_are_rejected(self) -> None:
        changed_dataset = self._subject(
            self._config("candidate", ("a", "b")), "result-candidate", contract=replace(self.contract, dataset_version="2")
        )
        changed_population = replace(self._subject(self._config("candidate", ("a", "b")), "result-candidate"), population_id="other")
        changed_positive_class = self._subject(
            self._config("candidate", ("a", "b")), "result-candidate", contract=replace(self.contract, positive_class=0)
        )
        target_config = replace(self._config("candidate", ("a", "b")), target="other_target")
        changed_target = self._subject(
            target_config, "result-candidate", contract=replace(self.contract, target_column="other_target")
        )

        for candidate in (changed_dataset, changed_population, changed_positive_class, changed_target):
            with self.subTest(candidate=candidate):
                result = self.service.compare(self.reference, candidate)
                self.assertFalse(result.is_comparable)
                self.assertEqual(result.status, "NOT_COMPARABLE_CONTROLLED_V1")

    def test_protocol_seed_folds_and_evaluation_changes_are_rejected(self) -> None:
        for field, value in (("protocol_id", "other"), ("seed", 7), ("folds", 4), ("evaluation_level", "holdout")):
            with self.subTest(field=field):
                candidate = self._subject(replace(self._config("candidate", ("a", "b")), **{field: value}), "result-candidate")
                result = self.service.compare(self.reference, candidate)
                self.assertFalse(result.is_comparable)
                self.assertEqual(result.status, "NOT_COMPARABLE_CONTROLLED_V1")

    def test_model_and_features_or_only_feature_order_are_rejected(self) -> None:
        uncontrolled = self._subject(
            replace(self._config("candidate", ("a", "c")), model_id="lightgbm"), "result-candidate"
        )
        order_only = self._subject(self._config("candidate", ("b", "a")), "result-candidate")

        self.assertEqual(self.service.compare(self.reference, uncontrolled).status, "UNCONTROLLED_MULTIPLE_CHANGES")
        self.assertEqual(self.service.compare(self.reference, order_only).status, "unsupported_feature_order_change")

    def test_declarations_are_checked_after_factual_diff(self) -> None:
        wrong_dimension = self._subject(
            replace(self._config("candidate", ("a", "c")), changed_dimension="model"), "result-candidate"
        )
        wrong_elements = self._subject(
            replace(self._config("candidate", ("a", "c")), changed_dimension="feature_set", changed_elements=("model_id",)),
            "result-candidate",
        )
        wrong_reference = self._subject(
            replace(self._config("candidate", ("a", "c")), reference_result_id="not-reference"), "result-candidate"
        )

        self.assertEqual(self.service.compare(self.reference, wrong_dimension).status, "DECLARED_CHANGE_MISMATCH")
        self.assertEqual(self.service.compare(self.reference, wrong_elements).status, "DECLARED_CHANGE_MISMATCH")
        self.assertEqual(self.service.compare(self.reference, wrong_reference).status, "REFERENCE_RESULT_MISMATCH")

    def test_subject_integrity_mismatches_raise_value_error(self) -> None:
        invalid_result = replace(self.reference.result, config_hash="wrong")
        invalid = replace(self.reference, result=invalid_result)

        with self.assertRaisesRegex(ValueError, "Invalid comparison input"):
            self.service.compare(invalid, self.reference)

    def test_code_version_is_provenance_not_control_gate_and_service_does_not_run_ml(self) -> None:
        candidate = self._subject(
            replace(self._config("candidate", ("a", "b")), model_parameters={"depth": 9}),
            "result-candidate",
            code_version="candidate-code",
        )

        with patch("komus_risk.experiments.runner.ExperimentRunner.run", side_effect=AssertionError):
            result = self.service.compare(self.reference, candidate)

        self.assertTrue(result.is_comparable)
        self.assertEqual(result.provenance["reference"]["code_version"], "reference-code")
        self.assertEqual(result.provenance["candidate"]["code_version"], "candidate-code")

    def test_comparison_id_is_deterministic(self) -> None:
        candidate = self._subject(
            replace(self._config("candidate", ("a", "b")), model_parameters={"depth": 9}), "result-candidate"
        )

        self.assertEqual(
            self.service.compare(self.reference, candidate).comparison_id,
            self.service.compare(self.reference, candidate).comparison_id,
        )

    def _config(self, experiment_id: str, feature_ids: tuple[str, ...]) -> ExperimentConfig:
        return ExperimentConfig(
            experiment_id, "dataset-v1", "sha256:dataset", "target", feature_ids, None, ("main",),
            "catboost", "1", {"depth": 7}, "stratified_kfold_oof", "1", 42, 3, "oof", None, None, (),
        )

    def _subject(
        self,
        config: ExperimentConfig,
        result_id: str,
        *,
        contract: DatasetContract | None = None,
        metric_offset: float = 0.0,
        confusion_offset: int = 0,
        runtime: float = 2.0,
        code_version: str = "reference-code",
    ) -> ComparisonSubject:
        metrics = {name: value + metric_offset for name, value in METRICS.items()}
        confusion = {name: value + confusion_offset for name, value in CONFUSION.items()}
        folds = tuple(
            {
                "fold": fold,
                "fold_seed": 42 + fold,
                **metrics,
                "runtime_seconds": runtime / 2,
            }
            for fold in (1, 2, 3)
        )
        result = ExperimentResult(
            result_id, config.experiment_id, config.config_hash, config.dataset_fingerprint, config.feature_set_hash,
            config.model_id, config.model_version, config.evaluation_level, metrics, confusion, folds, runtime,
            {}, code_version, "2026-01-01T00:00:00+00:00", (),
        )
        return ComparisonSubject(config, result, contract or self.contract, "working-v1", "sha256:working")


if __name__ == "__main__":
    unittest.main()
