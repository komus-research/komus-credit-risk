from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from komus_risk.application import AnalysisHistoryError, AnalysisHistoryService
from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput


class AnalysisHistoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperimentArtifactStore(self.temp.name)
        self.service = AnalysisHistoryService(self.store)

    def _save(self, *, created_at: str, model_id: str = "catboost", dataset_name: str = "Synthetic") -> str:
        config = ExperimentConfig(
            f"experiment-{created_at}", "dataset-1", "dataset-fingerprint", "target",
            ("score", "age"), None, ("main",), model_id, "model-v7", {},
            "stratified_kfold_oof", "protocol-v2", 21, 2, "oof", None, None, (),
        )
        dataset = DatasetContract(
            "dataset-1", "dataset-v3", dataset_name, "ready_csv", "dataset-fingerprint", 8, 3,
            "target", 1, "entity_id", "features-v1", "feature-hash", "validated", False,
        )
        population = EvaluationPopulation((0, 1, 2, 3), "population-1", "population-fingerprint", "working")
        metrics = {"gini": 0.31, "nested": {"safe": [1, 2]}}
        result = ExperimentResult(
            f"result-{created_at}", config.experiment_id, config.config_hash, config.dataset_fingerprint,
            config.feature_set_hash, config.model_id, config.model_version, config.evaluation_level,
            metrics, {"tp": 1, "tn": 2}, ({"fold": 1, "gini": 0.2}, {"fold": 2, "gini": 0.4}),
            1.25, {}, "code-v5", created_at, ("historical limitation",),
        )
        output = ExperimentRunOutput(
            result, np.array([0.1, 0.9, 0.2, 0.8]), np.array([1, 2, 1, 2]),
            population.row_positions, population.population_id, population.population_fingerprint,
        )
        artifact = self.store.save(config=config, dataset_contract=dataset, population=population, run_output=output)
        return artifact.artifact_id

    def test_created_sort_is_persisted_timestamp_with_stable_artifact_tie_break_and_mtime_irrelevant(self) -> None:
        first = self._save(created_at="2026-02-01T00:00:00+00:00")
        second = self._save(created_at="2026-04-01T00:00:00+00:00", model_id="xgboost")
        third = self._save(created_at="2026-04-01T00:00:00+00:00", model_id="lightgbm")
        experiments = Path(self.temp.name) / "experiments"
        os.utime(experiments / first, (5, 5))
        os.utime(experiments / second, (50, 50))
        os.utime(experiments / third, (1, 1))
        desc = self.service.list(0, 10)
        asc = self.service.list(0, 10, sort="CREATED_ASC")
        self.assertEqual([item.artifact_id for item in desc.items], sorted((second, third)) + [first])
        self.assertEqual([item.artifact_id for item in asc.items], [first] + sorted((second, third)))

    def test_search_filter_pagination_and_persisted_item_facts(self) -> None:
        self._save(created_at="2026-01-01T00:00:00+00:00", dataset_name="North Portfolio")
        selected = self._save(created_at="2026-02-01T00:00:00+00:00", model_id="CatBoost", dataset_name="South book")
        self._save(created_at="2026-03-01T00:00:00+00:00", model_id="xgboost")
        page = self.service.list(0, 1, search="SOUTH", model_id="CatBoost")
        self.assertEqual((page.total_count, page.filtered_count, page.offset, page.limit, page.returned_count), (3, 1, 0, 1, 1))
        item = page.items[0]
        self.assertEqual(item.artifact_id, selected)
        self.assertEqual((item.model_id, item.model_version, item.feature_count, item.folds, item.gini), ("CatBoost", "model-v7", 2, 2, 0.31))
        self.assertEqual(item.result_access, "LEGACY_SUMMARY_ONLY")
        self.assertEqual(self.service.list(0, 10, search="CATBOOST").filtered_count, 2)

    def test_detail_uses_full_store_load_and_returns_copy_safe_historical_summary(self) -> None:
        artifact_id = self._save(created_at="2026-01-01T00:00:00+00:00")
        detail = self.service.detail(artifact_id)
        self.assertEqual(detail.artifact_id, artifact_id)
        self.assertEqual((detail.dataset_version, detail.protocol_id, detail.protocol_version), ("dataset-v3", "stratified_kfold_oof", "protocol-v2"))
        self.assertEqual(detail.metrics["gini"], 0.31)
        self.assertEqual(detail.confusion["tp"], 1)
        self.assertEqual(detail.fold_metrics[0]["fold"], 1)
        self.assertEqual(detail.limitations, ("historical limitation",))
        self.assertEqual(detail.code_version, "code-v5")
        with self.assertRaises(TypeError):
            detail.metrics["new"] = 1
        with self.assertRaises(TypeError):
            detail.metrics["nested"]["safe"] = ()

    def test_result_access_schema_mapping_and_invalid_query_errors(self) -> None:
        artifact_id = self._save(created_at="2026-01-01T00:00:00+00:00")
        metadata = self.store.read_metadata(artifact_id)
        metadata_v3 = replace(metadata, artifact_schema_version="3")
        self.assertEqual(AnalysisHistoryService._item(metadata_v3).result_access, "FULL_RESULT_V2")
        self.assertEqual(AnalysisHistoryService._item(replace(metadata, artifact_schema_version="2")).result_access, "LEGACY_SUMMARY_ONLY")
        for args in ((-1, 5), (0, 0), (0, 101), (True, 1), (0, 1, None, None, "mtime")):
            with self.subTest(args=args), self.assertRaises(AnalysisHistoryError) as caught:
                self.service.list(*args)
            self.assertEqual(caught.exception.code, "INVALID_QUERY")

    def test_storage_failures_are_stable_application_errors(self) -> None:
        with self.assertRaises(AnalysisHistoryError) as list_error:
            AnalysisHistoryService(_BrokenStore()).list(0, 5)
        self.assertEqual(list_error.exception.code, "HISTORY_STORE_INVALID")
        with self.assertRaises(AnalysisHistoryError) as detail_error:
            self.service.detail("missing")
        self.assertEqual(detail_error.exception.code, "ARTIFACT_NOT_FOUND_OR_INVALID")


class _BrokenStore:
    def browse_metadata(self):
        raise OSError("private path detail")


if __name__ == "__main__":
    unittest.main()
