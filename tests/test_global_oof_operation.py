"""Filesystem integrity and dedup lifecycle for global OOF derivations."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from komus_risk.application import (
    GlobalOOFDerivedStore,
    GlobalOOFOperationService,
    GlobalOOFExplanation,
    GlobalOOFFeatureImportance,
)
from komus_risk.hashing import stable_hash


class GlobalOOFOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GlobalOOFDerivedStore(Path(self.temp.name) / ".axion-artifacts")
        self.identity = {
            "artifact_id": "artifact-a", "row_count": 3, "feature_count": 2,
            "aggregation_method_id": "sum_absolute_shap", "aggregation_method_version": "1",
            "provider_id": "native", "provider_version": "1",
            "explanation_method_id": "native", "explanation_method_version": "1",
            "feature_binding_hash": "features", "fold_model_binding_ids": ["fold-a", "fold-b"],
            "fold_background_hashes": [[1, "background-a"], [2, "background-b"]],
            "feature_ids": ["f1", "f2"], "feature_columns": ["first", "second"],
            "output_space": "raw_margin", "background_policy_id": "outer_train_hash_top128_v1",
            "numerical_validation_profile_id": "profile", "numerical_validation_profile_version": "1",
            "chunk_implementation_policy": "global_oof_chunk_2048_v1",
        }
        self.key = stable_hash(self.identity)

    def result(self):
        result = GlobalOOFExplanation(
            artifact_id="artifact-a", model_id="xgboost", model_version="3",
            row_count=3, feature_count=2, output_space="raw_margin",
            provider_id="native", provider_version="1", explanation_method_id="native",
            explanation_method_version="1", background_policy_id="outer_train_hash_top128_v1",
            feature_binding_hash="features", fold_model_binding_ids=("fold-a", "fold-b"),
            features=(GlobalOOFFeatureImportance("f1", "first", 0.75, 1),
                      GlobalOOFFeatureImportance("f2", "second", 0.25, 2)),
            evidence_hash="",
        )
        payload = {
            "artifact_id": result.artifact_id, "model_id": result.model_id,
            "model_version": result.model_version, "row_count": result.row_count,
            "feature_count": result.feature_count, "output_space": result.output_space,
            "provider_id": result.provider_id, "provider_version": result.provider_version,
            "explanation_method_id": result.explanation_method_id,
            "explanation_method_version": result.explanation_method_version,
            "background_policy_id": result.background_policy_id,
            "feature_binding_hash": result.feature_binding_hash,
            "fold_model_binding_ids": list(result.fold_model_binding_ids),
            "fold_background_hashes": self.identity["fold_background_hashes"],
            "aggregation_method_id": self.identity["aggregation_method_id"],
            "aggregation_method_version": self.identity["aggregation_method_version"],
            "numerical_validation_profile_id": self.identity["numerical_validation_profile_id"],
            "numerical_validation_profile_version": self.identity["numerical_validation_profile_version"],
            "features": [(f.feature_id, f.column_name, f.mean_abs_shap, f.rank) for f in result.features],
        }
        from dataclasses import replace
        return replace(result, evidence_hash=stable_hash(payload))

    def test_publish_and_restart_reads_ready_result_without_compute(self):
        calls = []
        service = GlobalOOFOperationService(self.store)
        self.assertEqual("NOT_STARTED", service.status(self.key).status)
        result = self.result()

        def compute(token, progress):
            calls.append(token)
            progress(1, 2)
            progress(2, 3)
            return result

        actual = service.get_or_run(artifact_id="artifact-a", derivation_key=self.key,
            identity=self.identity, total_rows=3, total_folds=2, compute=compute)
        self.assertEqual(result.evidence_hash, actual.evidence_hash)
        self.assertEqual(1, len(calls))
        self.assertEqual("READY", service.status(self.key).status)

        restarted = GlobalOOFOperationService(GlobalOOFDerivedStore(Path(self.temp.name) / ".axion-artifacts"))
        loaded = restarted.get_or_run(artifact_id="artifact-a", derivation_key=self.key,
            identity=self.identity, total_rows=3, total_folds=2,
            compute=lambda *_: self.fail("persisted READY result must avoid computation"))
        self.assertEqual(result, loaded)
        self.assertEqual("READY", restarted.status(self.key).status)
        self.assertEqual("Готово", restarted.status(self.key).stage_label)

    def test_not_started_snapshot_is_stable_and_does_not_block_start(self):
        service = GlobalOOFOperationService(self.store)
        first = service.status(self.key, artifact_id="artifact-a", identity=self.identity,
                               total_rows=3, total_folds=2)
        second = service.status(self.key, artifact_id="artifact-a", identity=self.identity,
                                total_rows=3, total_folds=2)
        self.assertEqual("NOT_STARTED", first.status)
        self.assertEqual("NOT_STARTED", second.status)
        self.assertEqual(first.updated_at, second.updated_at)
        self.assertEqual(0, second.processed_rows)
        self.assertIsNone(second.started_at)

        entered = threading.Event()
        release = threading.Event()
        calls = []

        def compute(token, progress):
            calls.append(token)
            entered.set()
            release.wait(5)
            return self.result()

        service.start(artifact_id="artifact-a", derivation_key=self.key, identity=self.identity,
            total_rows=3, total_folds=2, compute=compute)
        self.assertTrue(entered.wait(2))
        running = service.status(self.key)
        self.assertEqual("RUNNING", running.status)
        self.assertIsNotNone(running.started_at)
        release.set()
        self.assertEqual(self.result(), service.wait_result(self.key, timeout=5))
        self.assertEqual(1, len(calls))
        self.assertEqual("READY", service.status(self.key).status)

    def test_changed_artifact_identity_uses_a_separate_derived_key(self):
        result = self.result()
        self.store.publish(self.key, self.identity, result)
        identity_b = dict(self.identity, artifact_id="artifact-b")
        key_b = stable_hash(identity_b)
        self.assertNotEqual(self.key, key_b)
        self.assertIsNone(self.store.load(key_b, identity_b))
        self.assertEqual("artifact-a", self.store.load(self.key, self.identity).artifact_id)

    def test_changed_fold_background_binding_changes_derivation_key(self):
        changed = {**self.identity, "fold_background_hashes": [[1, "changed"], [2, "background-b"]]}
        self.assertNotEqual(self.key, stable_hash(changed))

    def test_persisted_ready_result_rejects_mismatched_fold_background_binding(self):
        self.store.publish(self.key, self.identity, self.result())
        changed = {**self.identity, "fold_background_hashes": [[1, "changed"], [2, "background-b"]]}
        with self.assertRaisesRegex(ValueError, "GLOBAL_OOF_DERIVED_EVIDENCE_INVALID"):
            self.store.load(self.key, changed)

    def test_two_starts_share_one_attempt_and_progress_is_monotonic(self):
        service = GlobalOOFOperationService(self.store)
        started = threading.Event()
        release = threading.Event()
        calls = []
        result = self.result()

        def compute(token, progress):
            calls.append(token)
            progress(1, 1)
            started.set()
            release.wait(5)
            progress(2, 2)
            progress(2, 3)
            return result

        first = service.start(artifact_id="artifact-a", derivation_key=self.key, identity=self.identity,
            total_rows=3, total_folds=2, compute=compute)
        self.assertTrue(started.wait(2))
        second = service.start(artifact_id="artifact-a", derivation_key=self.key, identity=self.identity,
            total_rows=3, total_folds=2, compute=lambda *_: self.fail("duplicate start"))
        self.assertEqual(first.derivation_key, second.derivation_key)
        self.assertEqual("RUNNING", second.status)
        release.set()
        self.assertEqual(result, service.wait_result(self.key, timeout=5))
        self.assertEqual(1, len(calls))
        self.assertEqual(3, service.status(self.key).processed_rows)
        self.assertEqual("READY", service.status(self.key).stage)
        self.assertEqual("Готово", service.status(self.key).stage_label)

    def test_corrupt_published_result_fails_closed(self):
        result = self.result()
        self.store.publish(self.key, self.identity, result)
        result_path = self.store.root / self.key / "result.json"
        result_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "GLOBAL_OOF_DERIVED_EVIDENCE_INVALID"):
            self.store.load(self.key, self.identity)

    def test_failed_state_is_stable_and_retry_gets_a_new_attempt(self):
        service = GlobalOOFOperationService(self.store)
        old_tokens = []

        def fail(token, progress):
            old_tokens.append(token)
            progress(2, 1)
            raise ValueError("SECRET_API_KEY_ABC123")

        with self.assertRaisesRegex(ValueError, "GLOBAL_OOF_EXPLANATION_FAILED"):
            service.get_or_run(artifact_id="artifact-a", derivation_key=self.key,
                identity=self.identity, total_rows=3, total_folds=2, compute=fail)
        self.assertEqual("FAILED", service.status(self.key).status)
        self.assertEqual("Ошибка", service.status(self.key).stage_label)
        self.assertIsNone(service.status(self.key).current_fold)
        self.assertEqual("GLOBAL_OOF_EXPLANATION_FAILED", service.status(self.key).safe_error_code)
        self.assertNotIn("SECRET_API_KEY_ABC123", service.status(self.key).safe_error_code)
        service.start(artifact_id="artifact-a", derivation_key=self.key,
                identity=self.identity, total_rows=3, total_folds=2,
                compute=lambda *_: self.fail("failed state is stable until retry"))
        with self.assertRaisesRegex(ValueError, "GLOBAL_OOF_EXPLANATION_FAILED"):
            service.wait_result(self.key)
        service.retry(self.key)
        result = self.result()
        actual = service.get_or_run(artifact_id="artifact-a", derivation_key=self.key,
            identity=self.identity, total_rows=3, total_folds=2,
            compute=lambda token, progress: (old_tokens.append(token), result)[1])
        self.assertEqual(result, actual)
        self.assertEqual(2, len(old_tokens))
        self.assertNotEqual(old_tokens[0], old_tokens[1])

    def test_running_status_updates_elapsed_without_faking_progress_event(self):
        service = GlobalOOFOperationService(self.store)
        entered = threading.Event()
        release = threading.Event()

        def compute(token, progress):
            progress(2, 1)
            entered.set()
            release.wait(5)
            return self.result()

        service.start(artifact_id="artifact-a", derivation_key=self.key, identity=self.identity,
            total_rows=3, total_folds=2, compute=compute)
        self.assertTrue(entered.wait(2))
        first = service.status(self.key)
        threading.Event().wait(0.04)
        second = service.status(self.key)
        self.assertGreater(second.elapsed_seconds, first.elapsed_seconds)
        self.assertEqual(first.updated_at, second.updated_at)
        self.assertEqual("PROCESSING_FOLD", second.stage)
        self.assertEqual("Обработка части", second.stage_label)
        self.assertEqual(2, second.current_fold)

        attempt = service._attempts[self.key]
        service._progress_stage(self.key, attempt.token, "AGGREGATING")
        aggregating = service.status(self.key)
        self.assertIsNone(aggregating.current_fold)
        self.assertEqual("Агрегация", aggregating.stage_label)
        service._progress_stage(self.key, attempt.token, "PERSISTING")
        persisting = service.status(self.key)
        self.assertIsNone(persisting.current_fold)
        self.assertEqual("Сохранение", persisting.stage_label)
        release.set()
        service.wait_result(self.key, timeout=5)


if __name__ == "__main__":
    unittest.main()
