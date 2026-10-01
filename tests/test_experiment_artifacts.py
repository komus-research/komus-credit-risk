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
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput, FoldModelEvidence, OOFResultEvidence
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import ModelConfigurationRecord, ProviderDescriptor, SmokeEvidence, SmokePolicy, SmokeStatus
from komus_risk.models.gbdt.native import NativePredictor


_METRICS = {
    "gini": 0.2, "roc_auc": 0.6, "pr_auc": 0.55,
    "precision_at_0_5": 0.5, "recall_at_0_5": 0.4, "f1_at_0_5": 0.44,
}


class _RoundTripProvider:
    """A trusted test double whose native payload replays the saved score column."""

    model_id = "catboost"
    model_version = "1"
    adapter_version = "adapter-1"
    descriptor = ProviderDescriptor("test_native_persistence", "1", "persistence", {"model_id": "catboost"})

    def __init__(self, *, mismatch: bool = False) -> None:
        self.mismatch = mismatch
        self.load_calls = 0

    def native_files(self) -> tuple[str, ...]:
        return ("model.bin",)

    def validate_fitted(self, adapter, *, parameters: dict, seed: int) -> None:
        if not isinstance(adapter, object):
            raise ValueError("missing fitted adapter")

    def save(self, adapter, directory: Path) -> tuple[str, ...]:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "model.bin").write_bytes(b"test-fold-model")
        return self.native_files()

    def load(self, directory: Path, feature_columns: tuple[str, ...]) -> NativePredictor:
        self.load_calls += 1
        offset = 0.01 if self.mismatch else 0.0
        return NativePredictor("catboost", feature_columns, lambda X: X["score"].to_numpy(dtype=float) + offset)


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

    def test_browse_metadata_is_empty_for_missing_root_and_ignores_non_artifact_entries(self) -> None:
        with TemporaryDirectory() as root:
            store = ExperimentArtifactStore(root)
            self.assertEqual(store.browse_metadata(), ())
            experiments = Path(root) / "experiments"
            experiments.mkdir()
            (experiments / ".tmp-manual").mkdir()
            (experiments / "not-an-id").mkdir()
            (experiments / "ordinary-file").write_text("ignored", encoding="utf-8")
            self.assertEqual(store.browse_metadata(), ())

    def test_browse_metadata_finds_published_artifact_without_loading_arrays_or_models(self) -> None:
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        with patch("komus_risk.artifacts.store.np.load", side_effect=AssertionError("array load is forbidden")):
            metadata = self.store.browse_metadata()
        self.assertEqual([item.artifact_id for item in metadata], [saved.artifact_id])
        self.assertEqual(metadata[0].result.created_at, self.output.result.created_at)
        self.assertEqual(metadata[0].population_size, len(self.population.row_positions))

    def test_browse_metadata_fails_closed_on_canonical_artifact_corruption(self) -> None:
        for index, relative in enumerate(("manifest.json", "result.json")):
            with self.subTest(relative=relative):
                saved = self._fresh_saved(str(index))
                directory = Path(self.temp.name) / "experiments" / saved.artifact_id
                path = directory / relative
                original = path.read_bytes()
                path.write_text("not json", encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.store.browse_metadata()
                path.write_bytes(original)

    def test_browse_metadata_uses_result_json_created_at_not_filesystem_time(self) -> None:
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        directory = Path(self.temp.name) / "experiments" / saved.artifact_id
        (directory / "result.json").touch()
        metadata = self.store.read_metadata(saved.artifact_id)
        self.assertEqual(metadata.result.created_at, self.output.result.created_at)

    def test_metadata_read_rejects_rehashed_metadata_with_stale_content_address(self) -> None:
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output,
        )
        directory = Path(self.temp.name) / "experiments" / saved.artifact_id
        result_path = directory / "result.json"
        result_data = self.store._read_json(result_path)
        result_data["created_at"] = "2026-01-02T00:00:00+00:00"
        self.store._write_json(result_path, result_data)

        manifest_path = directory / "manifest.json"
        manifest = self.store._read_json(manifest_path)
        manifest["files"]["result.json"]["sha256"] = self.store._raw_hash(result_path)
        manifest["files"]["result.json"]["size_bytes"] = result_path.stat().st_size
        manifest["content_hashes"]["result"] = stable_hash(result_data)
        self.store._write_json(manifest_path, manifest)

        with patch("komus_risk.artifacts.store.np.load", side_effect=AssertionError("array load is forbidden")):
            with self.assertRaises(ValueError):
                self.store.read_metadata(saved.artifact_id)

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

    def test_v3_persists_aligned_input_and_reloads_each_fold_model_before_publish(self) -> None:
        output = self._v3_output()
        saved = self.store.save(
            config=self.config,
            dataset_contract=self.contract,
            population=self.population,
            run_output=output,
            configuration_record=self._configuration_record(),
            smoke_evidence=self._smoke_evidence(),
            fold_model_provider=_RoundTripProvider(),
        )
        loaded = self.store.load(saved.artifact_id)
        evidence = loaded.run_output.oof_evidence
        directory = Path(self.temp.name) / "experiments" / saved.artifact_id

        self.assertEqual(loaded.manifest["artifact_schema_version"], "3")
        self.assertIsNotNone(evidence)
        assert evidence is not None
        np.testing.assert_array_equal(evidence.y_true, np.array([0, 1, 1, 0, 0, 1]))
        np.testing.assert_array_equal(evidence.model_input[:, 0], self.output.oof_positive_proba)
        self.assertEqual(evidence.identifier_display, tuple(f"entity-{index}" for index in self.population.row_positions))
        self.assertEqual(evidence.feature_columns, ("score",))
        self.assertEqual(len(list((directory / "fold_models").glob("fold-*"))), self.config.folds)
        self.assertFalse((directory / "evidence" / "target.npy").exists())

    def test_v3_fold_load_is_provider_bound_and_has_deterministic_opaque_identity(self) -> None:
        provider = _RoundTripProvider()
        saved = self.store.save(
            config=self.config, dataset_contract=self.contract, population=self.population,
            run_output=self._v3_output(), configuration_record=self._configuration_record(),
            smoke_evidence=self._smoke_evidence(), fold_model_provider=provider,
        )
        first = self.store.load_oof_fold_model(saved.artifact_id, 1, provider=provider)
        second = self.store.load_oof_fold_model(saved.artifact_id, 1, provider=provider)

        self.assertEqual(first.model_binding_id, second.model_binding_id)
        self.assertNotEqual(first.model_binding_id, "fold-1")
        self.assertEqual(first.metadata["validation_row_positions"], [0, 3])
        incompatible = _RoundTripProvider()
        incompatible.descriptor = ProviderDescriptor(
            "other_provider", "1", "persistence", {"model_id": "catboost"}
        )
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.store.load_oof_fold_model(saved.artifact_id, 1, provider=incompatible)

    def test_v3_semantic_y_true_mismatch_fails_closed_without_publication(self) -> None:
        output = self._v3_output()
        evidence = output.oof_evidence
        assert evidence is not None
        wrong_y_true = np.array([1, 0, 1, 0, 0, 1])
        mismatched = replace(
            output,
            oof_evidence=replace(evidence, y_true=wrong_y_true),
        )
        provider = _RoundTripProvider()
        with self.assertRaisesRegex(ValueError, "canonical ExperimentResult confusion"):
            self.store.save(
                config=self.config,
                dataset_contract=self.contract,
                population=self.population,
                run_output=mismatched,
                configuration_record=self._configuration_record(),
                smoke_evidence=self._smoke_evidence(),
                fold_model_provider=provider,
            )
        self.assertEqual(provider.load_calls, self.config.folds)
        experiments = Path(self.temp.name) / "experiments"
        self.assertFalse(experiments.exists() and any(experiments.iterdir()))

    def test_v3_probability_mismatch_fails_closed_without_publication(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            self.store.save(
                config=self.config,
                dataset_contract=self.contract,
                population=self.population,
                run_output=self._v3_output(),
                configuration_record=self._configuration_record(),
                smoke_evidence=self._smoke_evidence(),
                fold_model_provider=_RoundTripProvider(mismatch=True),
            )
        experiments = Path(self.temp.name) / "experiments"
        self.assertFalse(experiments.exists() and any(experiments.iterdir()))

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

    def _v3_output(self) -> ExperimentRunOutput:
        canonical_result = replace(
            self.output.result,
            metrics={
                **self.output.result.metrics,
                "precision_at_0_5": 2 / 3,
                "recall_at_0_5": 2 / 3,
                "f1_at_0_5": 2 / 3,
            },
        )
        return replace(
            self.output,
            result=canonical_result,
            oof_evidence=OOFResultEvidence(
                y_true=np.array([0, 1, 1, 0, 0, 1]),
                identifier_display=tuple(f"entity-{index}" for index in self.population.row_positions),
                model_input=self.output.oof_positive_proba.reshape(-1, 1),
                feature_ids=("score",),
                feature_columns=("score",),
                fold_models=tuple(
                    FoldModelEvidence(fold, self.config.seed + fold, object())
                    for fold in range(1, self.config.folds + 1)
                ),
            ),
        )

    def _configuration_record(self) -> ModelConfigurationRecord:
        value = {
            "record_schema_version": "1", "model_id": self.config.model_id,
            "model_version": self.config.model_version, "adapter_version": "adapter-1",
            "plugin_contract_hash": "plugin-hash", "schema_id": "schema", "schema_version": "1",
            "schema_hash": "schema-hash", "recommended_profile_id": "profile",
            "recommended_profile_hash": "profile-hash", "mode": "RECOMMENDED",
            "user_overrides": {}, "resolved_parameters": self.config.model_parameters,
            "resolved_configuration_hash": "resolved-hash",
        }
        return ModelConfigurationRecord(**value, configuration_record_id=stable_hash(value))

    def _smoke_evidence(self) -> SmokeEvidence:
        policy = SmokePolicy()
        base = {
            "evidence_schema_version": "1", "status": SmokeStatus.PASS,
            "context_id": "context", "dataset_id": self.contract.dataset_id,
            "dataset_fingerprint": self.contract.dataset_fingerprint,
            "feature_registry_id": self.contract.feature_registry_id,
            "feature_registry_hash": self.contract.feature_registry_hash,
            "population_id": self.population.population_id,
            "population_fingerprint": self.population.population_fingerprint,
            "population_row_positions_hash": stable_hash({"row_positions": list(self.population.row_positions)}),
            "selected_feature_ids": self.config.feature_ids,
            "selected_feature_set_hash": stable_hash({"ordered_feature_ids": list(self.config.feature_ids)}),
            "plugin_contract_hash": "plugin-hash", "resolved_configuration_hash": "resolved-hash",
            "configuration_record_id": self._configuration_record().configuration_record_id,
            "seed": self.config.seed, "policy_id": policy.policy_id,
            "policy_version": policy.policy_version, "policy_hash": policy.policy_hash,
            "sampled_row_positions": self.population.row_positions,
            "sampled_rows_hash": stable_hash({"row_positions": list(self.population.row_positions)}),
            "failure_code": None,
        }
        identity = {
            key: value for key, value in base.items()
            if key not in {"status", "sampled_row_positions", "sampled_rows_hash", "failure_code"}
        }
        return SmokeEvidence(**base, smoke_identity=stable_hash(identity))

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
