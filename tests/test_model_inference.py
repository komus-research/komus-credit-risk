from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from komus_risk.application import ModelInferenceService
from komus_risk.artifacts import LoadedModelVersion, ModelVersionSummary
from komus_risk.data import TabularSnapshot


class RecordingPredictor:
    def __init__(self, output: object | None = None) -> None:
        self.output = output
        self.received: pd.DataFrame | None = None

    def predict_positive_proba(self, dataframe: pd.DataFrame) -> object:
        self.received = dataframe.copy()
        return self.output if self.output is not None else np.full(len(dataframe), 0.25)


class ModelInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ModelInferenceService()
        self.predictor = RecordingPredictor()
        self.model = LoadedModelVersion(
            ModelVersionSummary("model-v1", "experiment-v1", "fake", "v1", ("f_a", "f_b")),
            {"dataset_contract": {"identifier_column": "company_code"}, "feature_columns": ["f_a", "f_b"]},
            {}, self.predictor,
        )

    @staticmethod
    def _snapshot(frame: pd.DataFrame, *, headers: tuple[str, ...] | None = None) -> TabularSnapshot:
        physical_headers = headers if headers is not None else tuple(frame.columns)
        return TabularSnapshot(Path("new-file.csv"), "csv", {}, "a" * 64, "snapshot", len(frame), len(frame.columns), frame, physical_headers)

    def test_generic_identifier_duplicates_order_extras_and_validated_values(self) -> None:
        snapshot = self._snapshot(pd.DataFrame({
            "extra": ["ignore", "ignore"], "f_b": [20, 40], "company_code": ["A-X", "A-X"], "f_a": [1, 2],
        }))
        batch = self.service.predict(loaded_model_version=self.model, snapshot=snapshot)

        self.assertEqual("company_code", batch.identifier_column)
        self.assertEqual(("f_a", "f_b"), batch.required_feature_columns)
        self.assertEqual(("extra",), batch.ignored_columns)
        self.assertEqual(((1.0, 20.0), (2.0, 40.0)), batch.validated_feature_values)
        self.assertEqual(("f_a", "f_b"), tuple(self.predictor.received.columns))
        self.assertEqual(batch.validated_feature_values, tuple(tuple(row) for row in self.predictor.received.to_numpy()))
        self.assertEqual("A-X", batch.rows[0].identifier_value)
        self.assertNotEqual(batch.rows[0].row_id, batch.rows[1].row_id)
        self.assertEqual((0, 1), tuple(row.source_row_position for row in batch.rows))

    def test_target_column_is_not_required_for_inference(self) -> None:
        batch = self.service.predict(loaded_model_version=self.model, snapshot=self._snapshot(pd.DataFrame({"company_code": ["x"], "f_b": [2], "f_a": [1]})))
        self.assertEqual(1, len(batch.rows))

    def test_missing_feature_and_empty_identifier_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "feature columns"):
            self.service.predict(loaded_model_version=self.model, snapshot=self._snapshot(pd.DataFrame({"company_code": ["x"], "f_a": [1]})))
        with self.assertRaisesRegex(ValueError, "empty"):
            self.service.predict(loaded_model_version=self.model, snapshot=self._snapshot(pd.DataFrame({"company_code": [None], "f_a": [1], "f_b": [2]})))

    def test_invalid_predictor_values_fail(self) -> None:
        for value in ("not-a-number", np.nan, np.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.service.predict(loaded_model_version=self.model, snapshot=self._snapshot(pd.DataFrame({"company_code": ["x"], "f_a": [value], "f_b": [2]})))

    def test_nonnumeric_predictor_dtypes_fail_before_predictor_call(self) -> None:
        for value in (pd.Series(pd.to_datetime(["2026-01-01"])), pd.Series([1 + 2j])):
            with self.subTest(dtype=value.dtype):
                snapshot = self._snapshot(pd.DataFrame({"company_code": ["x"], "f_a": value, "f_b": [2]}))
                with self.assertRaisesRegex(ValueError, "predictor values"):
                    self.service.predict(loaded_model_version=self.model, snapshot=snapshot)
                self.assertIsNone(self.predictor.received)

    def test_invalid_predictor_outputs_fail_closed(self) -> None:
        for output in ([0.2, 0.3], [np.nan], [np.inf], [-0.1], [1.1]):
            with self.subTest(output=output):
                model = LoadedModelVersion(self.model.summary, self.model.metadata, {}, RecordingPredictor(output))
                with self.assertRaisesRegex(ValueError, "invalid positive probabilities"):
                    self.service.predict(loaded_model_version=model, snapshot=self._snapshot(pd.DataFrame({"company_code": ["x"], "f_a": [1], "f_b": [2]})))

    def test_physical_dataframe_header_mismatch_fails(self) -> None:
        snapshot = self._snapshot(pd.DataFrame({"company_code": ["x"], "f_a": [1], "f_b": [2]}), headers=("company_code", "f_b", "f_a"))
        with self.assertRaisesRegex(ValueError, "physical headers"):
            self.service.predict(loaded_model_version=self.model, snapshot=snapshot)


if __name__ == "__main__":
    unittest.main()
