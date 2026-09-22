"""Optional glossary matching and persistence must not alter model files."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from app.feature_descriptions import FeatureDescriptionStore, historical_descriptions, parse_description_file


class FeatureDescriptionTests(unittest.TestCase):
    def test_xlsx_dictionary_matches_features_by_exact_name(self) -> None:
        workbook = BytesIO()
        pd.DataFrame({"column_name": ["A1", "A2"], "description": ["Капитал", ""]}).to_excel(workbook, index=False)
        mapping, missing = parse_description_file("dictionary.xlsx", workbook.getvalue(), ("A1", "A2", "A3"))
        self.assertEqual(mapping, {"A1": "Капитал"})
        self.assertEqual(missing, ("A2", "A3"))

    def test_exact_matching_allows_missing_but_rejects_unknown_or_duplicate(self) -> None:
        mapping, missing = parse_description_file(
            "dictionary.csv", "column_name,description\nA1,Капитал\nA2,\n".encode("utf-8"),
            ("A1", "A2", "A3"),
        )
        self.assertEqual(mapping, {"A1": "Капитал"})
        self.assertEqual(missing, ("A2", "A3"))
        with self.assertRaisesRegex(ValueError, "проверьте алфавит"):
            parse_description_file("dictionary.csv", "column_name,description\nА1,Текст\n".encode("utf-8"), ("A1",))
        with self.assertRaisesRegex(ValueError, "уникальными"):
            parse_description_file("dictionary.csv", b"column_name,description\nA1,One\nA1,Two\n", ("A1",))

    def test_revisions_are_separate_for_datasets_and_survive_restart(self) -> None:
        with TemporaryDirectory() as directory:
            store = FeatureDescriptionStore(directory)
            first = store.save("dataset-one", {"A1": "Капитал"}, ("A1", "A2"))
            second = store.save("dataset-one", {"A1": "Капитал компании"}, ("A1", "A2"))
            self.assertNotEqual(first, second)
            self.assertEqual(FeatureDescriptionStore(directory).load("dataset-one"), {"A1": "Капитал компании"})
            self.assertEqual(store.load("dataset-two"), {})
            self.assertEqual(len(list(Path(directory).rglob("*.json"))), 3)
            with self.assertRaisesRegex(ValueError, "другого датасета"):
                store.save("dataset-one", {"unknown": "Текст"}, ("A1",))

    def test_only_historical_identity_receives_confirmed_meanings(self) -> None:
        confirmed = historical_descriptions("komus-historical-data-final")
        self.assertEqual(len(confirmed), 17)
        self.assertEqual(confirmed["Q_A1_norm"], "Регион регистрации")
        self.assertEqual(historical_descriptions("user-dataset"), {})

    def test_streamlit_upload_confirms_and_persists_dictionary(self) -> None:
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            stub = SimpleNamespace(
                subheader=Mock(), caption=Mock(), download_button=Mock(), success=Mock(), error=Mock(),
                dataframe=Mock(), rerun=Mock(),
                file_uploader=Mock(return_value=SimpleNamespace(
                    name="dictionary.csv", getvalue=lambda: "column_name,description\nA1,Капитал\n".encode("utf-8"),
                )),
                button=Mock(return_value=True),
            )
            runtime = SimpleNamespace(model_store=SimpleNamespace(root=Path(directory) / "models"))
            with patch.object(prototype, "st", stub):
                prototype._render_description_upload(runtime, "dataset-one", ("A1", "A2"), "test")
            self.assertEqual(FeatureDescriptionStore(directory).load("dataset-one"), {"A1": "Капитал"})
            self.assertEqual(stub.dataframe.call_args.args[0].data.iloc[1]["Описание"], "Описание не указано")
            self.assertIn(("color", "#ff6b6b"), stub.dataframe.call_args.args[0]._compute().ctx[(1, 1)])
            stub.rerun.assert_called_once()


if __name__ == "__main__":
    unittest.main()
