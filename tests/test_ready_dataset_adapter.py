"""Проверки универсального adapter готового табличного датасета."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from komus_risk.data import ReadyDatasetAdapter


class ReadyDatasetAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ReadyDatasetAdapter()
        self.dataframe = pd.DataFrame(
            {"entity_id": ["a", "b"], "target": [0, 1], "amount": [10.5, 20.5]}
        )

    def _load(self, path: Path, **overrides: object):
        arguments = {
            "dataset_id": "source-1",
            "dataset_version": "1",
            "dataset_name": "Тестовый набор",
            "target_column": "target",
            "positive_class": 1,
            "identifier_column": "entity_id",
            "feature_registry_id": "registry-1",
            "feature_registry_hash": "sha256:registry",
            "final_test_locked": True,
        }
        arguments.update(overrides)
        return self.adapter.load(path, **arguments)

    def test_loads_csv_without_changing_rows_columns_or_fingerprint(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.CSV"
            self.dataframe.to_csv(path, index=False)

            loaded = self._load(path)
            loaded_again = self._load(path)

        pd.testing.assert_frame_equal(loaded.dataframe, self.dataframe)
        self.assertEqual(loaded.contract.row_count, 2)
        self.assertEqual(loaded.contract.column_count, 3)
        self.assertEqual(loaded.contract.target_column, "target")
        self.assertEqual(loaded.contract.identifier_column, "entity_id")
        self.assertEqual(loaded.contract.dataset_fingerprint, loaded_again.contract.dataset_fingerprint)
        self.assertEqual(loaded.contract.source_type, "ready_csv")

    def test_loads_xlsx_and_sheet_choice_changes_fingerprint(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.xlsx"
            with pd.ExcelWriter(path) as writer:
                self.dataframe.to_excel(writer, sheet_name="Первый", index=False)
                self.dataframe.iloc[1:].to_excel(writer, sheet_name="Второй", index=False)

            first = self._load(path, sheet_name="Первый")
            second = self._load(path, sheet_name="Второй")

        pd.testing.assert_frame_equal(first.dataframe, self.dataframe)
        self.assertEqual(second.contract.row_count, 1)
        self.assertNotEqual(first.contract.dataset_fingerprint, second.contract.dataset_fingerprint)
        self.assertEqual(first.contract.source_type, "ready_xlsx")

    def test_loads_parquet(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.parquet"
            self.dataframe.to_parquet(path, index=False)
            loaded = self._load(path)

        pd.testing.assert_frame_equal(loaded.dataframe, self.dataframe)
        self.assertEqual(loaded.contract.source_type, "ready_parquet")

    def test_xlsb_dispatches_to_pyxlsb_engine(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.XLSB"
            path.write_bytes(b"fixture for dispatch only")
            with (
                patch.object(
                    ReadyDatasetAdapter,
                    "_read_xlsb_header",
                    return_value=["entity_id", "target", "amount"],
                ),
                patch("komus_risk.data.ready_dataset.pd.read_excel", return_value=self.dataframe) as read_excel,
            ):
                loaded = self._load(path, sheet_name="Данные")

        read_excel.assert_called_once_with(path, sheet_name="Данные", engine="pyxlsb")
        self.assertEqual(loaded.source_format, "xlsb")
        self.assertEqual(loaded.contract.source_type, "ready_xlsb")

    def test_rejects_duplicate_csv_headers_before_pandas_renames_them(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.csv"
            path.write_text("entity_id,target,amount,amount\na,1,10,20\n", encoding="utf-8")
            with patch("komus_risk.data.ready_dataset.pd.read_csv") as read_csv:
                with self.assertRaises(ValueError) as error:
                    self._load(path)

        self.assertIn("amount", str(error.exception))
        read_csv.assert_not_called()

    def test_rejects_duplicate_xlsx_headers_before_pandas_renames_them(self) -> None:
        duplicate_dataframe = pd.DataFrame(
            [["a", 1, 10, 20]], columns=["entity_id", "target", "amount", "amount"]
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.xlsx"
            duplicate_dataframe.to_excel(path, index=False)
            with patch("komus_risk.data.ready_dataset.pd.read_excel") as read_excel:
                with self.assertRaises(ValueError) as error:
                    self._load(path)

        self.assertIn("amount", str(error.exception))
        read_excel.assert_not_called()

    def test_rejects_duplicate_xlsb_headers_before_pandas_renames_them(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.xlsb"
            path.write_bytes(b"fixture for header pre-validation only")
            cells = [
                SimpleNamespace(v=header)
                for header in ("entity_id", "target", "amount", "amount")
            ]
            with (
                patch("pyxlsb.open_workbook") as open_workbook,
                patch("komus_risk.data.ready_dataset.pd.read_excel") as read_excel,
            ):
                workbook = open_workbook.return_value.__enter__.return_value
                worksheet = workbook.get_sheet.return_value.__enter__.return_value
                worksheet.rows.return_value = iter([cells])
                with self.assertRaises(ValueError) as error:
                    self._load(path)

        self.assertIn("amount", str(error.exception))
        workbook.get_sheet.assert_called_once_with(1)
        read_excel.assert_not_called()

    def test_rejects_invalid_dataset_inputs(self) -> None:
        cases = (
            ("unsupported", pd.DataFrame({"target": [1], "entity_id": ["a"]}), {}, "Неподдерживаемое"),
            ("missing_target", pd.DataFrame({"entity_id": ["a"]}), {}, "Целевая колонка"),
            ("missing_identifier", pd.DataFrame({"target": [1]}), {}, "идентификатора"),
            ("same_columns", pd.DataFrame({"target": [1]}), {"identifier_column": "target"}, "должны различаться"),
            ("missing_positive", pd.DataFrame({"target": [0], "entity_id": ["a"]}), {}, "Положительный класс"),
            ("missing_target_value", pd.DataFrame({"target": [1, None], "entity_id": ["a", "b"]}), {}, "пропущенные"),
            ("empty", pd.DataFrame({"target": pd.Series(dtype=int), "entity_id": pd.Series(dtype=str)}), {}, "Датасет пуст"),
        )
        with TemporaryDirectory() as directory:
            for name, dataframe, overrides, message in cases:
                suffix = ".txt" if name == "unsupported" else ".csv"
                path = Path(directory) / f"{name}{suffix}"
                dataframe.to_csv(path, index=False)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                    self._load(path, **overrides)

    def test_rejects_missing_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "absent.csv"
            with self.assertRaisesRegex(FileNotFoundError, "не найден"):
                self._load(path)


if __name__ == "__main__":
    unittest.main()
