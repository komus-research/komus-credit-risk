"""Tests for immutable, fail-closed experiment artifact persistence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput


_METRICS = {
    "gini": 0.2, "roc_auc": 0.6, "pr_auc": 0.55,
    "precision_at_0_5": 0.5, "recall_at_0_5": 0.4, "f1_at_0_5": 0.44,
}


class ExperimentArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperimentArtifactStore(self.temp.name)
        self.config, self.contract, self.population, self.output = self._parts()

    def test_save_load_round_trip_has_required_layout_and_exact_evidence(self) -> None:
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        loaded = self.store.load(saved.artifact_id)
        directory = Path(self.temp.name) / "experiments" / saved.artifact_id

        self.assertEqual(loaded.config, self.config)
        self.assertEqual(loaded.dataset_contract, self.contract)
        self.assertEqual(loaded.population, self.population)
        self.assertEqual(loaded.run_output.result, self.output.result)
        np.testing.assert_array_equal(loaded.run_output.oof_positive_proba, self.output.oof_positive_proba)
        np.testing.assert_array_equal(loaded.run_output.fold_assignments, self.output.fold_assignments)
        self.assertEqual(loaded.run_output.row_positions, self.output.row_positions)
        self.assertTrue((directory / "manifest.json").is_file())
        self.assertTrue((directory / "evidence/oof_positive_proba.npy").is_file())
        self.assertEqual(loaded.run_output.oof_positive_proba.dtype.str, "<f8")
        self.assertEqual(loaded.run_output.fold_assignments.dtype.str, "<i8")

    def test_identity_is_root_independent_and_changes_with_one_oof_value(self) -> None:
        with TemporaryDirectory() as other_root:
            other = ExperimentArtifactStore(other_root).save(
                config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
            )
        first = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        changed_oof = self.output.oof_positive_proba.copy()
        changed_oof[0] = 0.11
        changed = replace(self.output, oof_positive_proba=changed_oof)
        second = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=changed,
        )

        self.assertEqual(first.artifact_id, other.artifact_id)
        self.assertNotEqual(first.artifact_id, second.artifact_id)

    def test_duplicate_reuses_valid_artifact_but_corrupted_existing_is_not_overwritten(self) -> None:
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        manifest = Path(self.temp.name) / "experiments" / saved.artifact_id / "manifest.json"
        before = manifest.stat().st_mtime_ns
        duplicate = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        self.assertEqual(duplicate.artifact_id, saved.artifact_id)
        self.assertEqual(manifest.stat().st_mtime_ns, before)

        manifest.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.save(
                config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
            )

    def test_load_fails_closed_for_corruption_missing_file_and_temporary_directory(self) -> None:
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        directory = Path(self.temp.name) / "experiments" / saved.artifact_id
        for index, (relative, content) in enumerate((("config.json", "not json"), ("evidence/oof_positive_proba.npy", "broken"))):
            with self.subTest(relative=relative):
                fresh = self._fresh_saved(str(index))
                path = Path(self.temp.name) / "experiments" / fresh.artifact_id / relative
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.store.load(fresh.artifact_id)
        (directory / "dataset.json").unlink()
        with self.assertRaises(ValueError):
            self.store.load(saved.artifact_id)
        temporary = Path(self.temp.name) / "experiments" / f".tmp-{saved.artifact_id}-manual"
        temporary.mkdir()
        with self.assertRaises(ValueError):
            self.store.load(temporary.name)

    def test_save_rejects_inconsistent_or_invalid_evidence(self) -> None:
        cases = (
            (self.config, self.contract, self.population, replace(self.output, result=replace(self.output.result, config_hash="wrong"))),
            (self.config, replace(self.contract, dataset_fingerprint="wrong"), self.population, self.output),
            (self.config, self.contract, replace(self.population, population_id="wrong"), self.output),
            (self.config, self.contract, self.population, replace(self.output, oof_positive_proba=np.array([np.nan] * 6))),
            (self.config, self.contract, self.population, replace(self.output, oof_positive_proba=np.array([1.1] * 6))),
            (self.config, self.contract, self.population, replace(self.output, fold_assignments=np.array([1, 2]))),
            (self.config, self.contract, self.population, replace(self.output, row_positions=(0, 1, 1, 3, 4, 5))),
        )
        for config, contract, population, output in cases:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    self.store.save(config=config, dataset_contract=contract, population=population, run_output=output)

    def test_save_rejects_dataset_id_mismatch_even_with_matching_fingerprint(self) -> None:
        config = replace(self.config, dataset_id="dataset-A")
        dataset = replace(self.contract, dataset_id="dataset-B")
        output = replace(self.output, result=replace(self.output.result, config_hash=config.config_hash))

        with self.assertRaises(ValueError):
            self.store.save(config=config, dataset_contract=dataset, population=self.population, run_output=output)

        self.assertFalse((Path(self.temp.name) / "experiments").exists())

    def test_loaded_artifacts_build_comparison_subject_without_ml_call(self) -> None:
        reference = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        candidate_config, _, _, candidate_output = self._parts(
            experiment_id="candidate", model_parameters={"depth": 8}, result_id="result-candidate"
        )
        candidate = self.store.save(
            config=candidate_config, dataset_contract=self.contract, population=self.population, run_output=candidate_output,
        )

        with patch("komus_risk.experiments.runner.ExperimentRunner.run", side_effect=AssertionError):
            comparison = ExperimentComparisonService().compare(
                self.store.load(reference.artifact_id).to_comparison_subject(),
                self.store.load(candidate.artifact_id).to_comparison_subject(),
            )

        self.assertTrue(comparison.is_comparable)
        self.assertEqual(comparison.changed_dimension, "model")

    def _fresh_saved(self, suffix: str):
        config, contract, population, output = self._parts(
            experiment_id=f"fresh-{suffix}", result_id=f"result-fresh-{suffix}"
        )
        return self.store.save(config=config, dataset_contract=contract, population=population, run_output=output)

    @staticmethod
    def _parts(
        *, experiment_id: str = "experiment-v1", model_parameters: dict[str, int] | None = None,
        result_id: str = "result-v1",
    ) -> tuple[ExperimentConfig, DatasetContract, EvaluationPopulation, ExperimentRunOutput]:
        config = ExperimentConfig(
            experiment_id, "dataset-v1", "sha256:dataset", "target", ("score",), None, ("main",),
            "catboost", "1", model_parameters or {"depth": 7}, "stratified_kfold_oof", "1", 42, 3,
            "oof", None, None, (),
        )
        contract = DatasetContract(
            "dataset-v1", "1", "Synthetic", "ready_csv", "sha256:dataset", 10, 3, "target", 1,
            "entity_id", "features-v1", "sha256:features", "validated", False,
        )
        population = EvaluationPopulation((0, 1, 2, 3, 4, 5), "working-v1", "sha256:working", "working")
        result = ExperimentResult(
            result_id, config.experiment_id, config.config_hash, config.dataset_fingerprint, config.feature_set_hash,
            config.model_id, config.model_version, config.evaluation_level, _METRICS,
            {"threshold": 0.5, "tp": 2, "tn": 2, "fp": 1, "fn": 1},
            tuple({"fold": fold, "fold_seed": 42 + fold, **_METRICS, "runtime_seconds": 0.1} for fold in (1, 2, 3)),
            0.3, {}, "test-code", "2026-01-01T00:00:00+00:00", (),
        )
        output = ExperimentRunOutput(
            result, np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7]), np.array([1, 2, 3, 1, 2, 3]),
            population.row_positions, population.population_id, population.population_fingerprint,
        )
        return config, contract, population, output


if __name__ == "__main__":
    unittest.main()
