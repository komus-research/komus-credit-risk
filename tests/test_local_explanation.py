from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from catboost import CatBoostClassifier
import numpy as np
import pandas as pd

from komus_risk.application import LocalExplanationService, ModelInferenceService
from komus_risk.artifacts import LoadedModelVersion, ModelVersionSummary
from komus_risk.data import TabularSnapshot
from komus_risk.models.gbdt.native import load_native_predictor


class LocalExplanationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.columns = ("f_a", "f_b")
        train = pd.DataFrame({
            "f_a": [0.0, 0.2, 0.8, 1.0, 0.1, 0.9, 0.3, 0.7],
            "f_b": [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0],
        })
        target = [0, 0, 1, 1, 0, 1, 0, 1]
        model = CatBoostClassifier(iterations=20, depth=3, learning_rate=0.15, loss_function="Logloss", verbose=False, allow_writing_files=False, random_seed=7)
        model.fit(train, target)
        native_dir = Path(self.temp.name) / "native"
        native_dir.mkdir()
        model.save_model(native_dir / "model.cbm")
        predictor = load_native_predictor("catboost", native_dir, self.columns)
        self.summary = ModelVersionSummary("model-version-1", "experiment-1", "catboost", "test-v1", ("feature-a", "feature-b"))
        self.metadata = {
            "model_id": "catboost",
            "model_version": "test-v1",
            "experiment_artifact_id": "experiment-1",
            "dataset_contract": {"dataset_id": "dataset-1", "dataset_fingerprint": "fingerprint-1", "identifier_column": "company_id"},
            "feature_set_hash": "feature-set-1",
            "feature_columns": list(self.columns),
            "feature_ids": ["feature-a", "feature-b"],
            "feature_specs": [
                {"feature_id": "feature-a", "column_name": "f_a"},
                {"feature_id": "feature-b", "column_name": "f_b"},
            ],
        }
        self.loaded = LoadedModelVersion(self.summary, self.metadata, {}, predictor)
        snapshot = TabularSnapshot(
            source_path=Path(self.temp.name) / "inference.csv",
            source_format="csv",
            read_options={"separator": ",", "encoding": "utf-8"},
            fingerprint="inference-fingerprint",
            row_count=2,
            column_count=3,
            dataframe=pd.DataFrame({"company_id": ["a-1", "b-2"], "f_a": [0.15, 0.85], "f_b": [1.0, 0.0]}),
            source_file_sha256="a" * 64,
            physical_headers=("company_id", "f_a", "f_b"),
        )
        self.batch = ModelInferenceService().predict(loaded_model_version=self.loaded, snapshot=snapshot)
        self.service = LocalExplanationService()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_real_native_catboost_local_shap_evidence(self) -> None:
        evidence = self.service.explain(loaded_model_version=self.loaded, prediction_batch=self.batch, row_id=self.batch.rows[0].row_id)
        self.assertEqual(self.batch.rows[0].probability, evidence.probability)
        self.assertEqual("raw_margin", evidence.shap_output_space)
        self.assertAlmostEqual(evidence.raw_model_output, evidence.base_value + sum(item.shap_value for item in evidence.features), places=7)
        self.assertEqual({"f_a": 0.15, "f_b": 1.0}, {item.column_name: item.raw_value for item in evidence.features})
        self.assertEqual({"f_a": "feature-a", "f_b": "feature-b"}, {item.column_name: item.feature_id for item in evidence.features})
        self.assertEqual([1, 2], [item.abs_rank for item in evidence.features])
        self.assertEqual(
            sorted(evidence.features, key=lambda item: (-abs(item.shap_value), self.columns.index(item.column_name))),
            list(evidence.features),
        )
        repeat = self.service.explain(loaded_model_version=self.loaded, prediction_batch=self.batch, row_id=self.batch.rows[0].row_id)
        self.assertEqual(evidence.evidence_hash, repeat.evidence_hash)

    def test_unknown_row_wrong_version_and_changed_probability_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.service.explain(loaded_model_version=self.loaded, prediction_batch=self.batch, row_id="unknown")
        with self.assertRaisesRegex(ValueError, "model_version_id"):
            self.service.explain(loaded_model_version=self.loaded, prediction_batch=replace(self.batch, model_version_id="other-version"), row_id=self.batch.rows[0].row_id)
        changed_row = replace(self.batch.rows[0], probability=0.123456)
        changed_batch = replace(self.batch, rows=(changed_row, *self.batch.rows[1:]))
        with self.assertRaisesRegex(ValueError, "Recomputed probability"):
            self.service.explain(loaded_model_version=self.loaded, prediction_batch=changed_batch, row_id=changed_row.row_id)

    def test_non_catboost_is_explicitly_unsupported(self) -> None:
        unsupported = LoadedModelVersion(
            replace(self.summary, model_id="xgboost"),
            {**self.metadata, "model_id": "xgboost"},
            {},
            self.loaded.predictor,
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.service.explain(loaded_model_version=unsupported, prediction_batch=self.batch, row_id=self.batch.rows[0].row_id)


if __name__ == "__main__":
    unittest.main()
