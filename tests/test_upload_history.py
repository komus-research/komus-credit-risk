"""Persistent upload history remains browser-scoped across Streamlit reloads."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.local_file_picker import persist_uploaded_file
from app.upload_history import (
    HISTORY_QUERY_KEY,
    UploadHistoryError,
    history_token,
    load_upload_history,
    save_upload_history,
)


class UploadHistoryTests(TestCase):
    def test_token_survives_reload_and_different_urls_are_isolated(self) -> None:
        first_url = {}
        first = history_token(first_url)
        self.assertEqual(first_url[HISTORY_QUERY_KEY], first)
        self.assertEqual(history_token(dict(first_url)), first)
        self.assertNotEqual(history_token({}), first)

    def test_saved_history_survives_reload_and_does_not_leak_to_other_token(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            uploads = root / "uploads"
            records = root / "history"
            path = Path(persist_uploaded_file("data.csv", b"x\n1\n", (".csv", ".xlsb"), upload_root=uploads))
            token = history_token({})
            entry = {"name": "data.csv", "path": str(path), "size": path.stat().st_size}

            save_upload_history(token, [entry], history_root=records, upload_root=uploads)

            self.assertEqual(load_upload_history(token, history_root=records, upload_root=uploads), [entry])
            self.assertEqual(load_upload_history(history_token({}), history_root=records, upload_root=uploads), [])
            self.assertNotIn(str(path), (records / f"{token}.json").read_text(encoding="utf-8"))

    def test_xlsx_upload_is_restored_after_reload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            uploads = root / "uploads"
            records = root / "history"
            path = Path(persist_uploaded_file("data.xlsx", b"fixture", (".csv", ".xlsx", ".xlsb"), upload_root=uploads))
            token = history_token({})
            entry = {"name": "data.xlsx", "path": str(path), "size": path.stat().st_size}
            save_upload_history(token, [entry], history_root=records, upload_root=uploads)
            self.assertEqual(load_upload_history(token, history_root=records, upload_root=uploads), [entry])

    def test_missing_or_outside_files_are_not_restored(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            uploads = root / "uploads"
            records = root / "history"
            path = Path(persist_uploaded_file("data.xlsb", b"file", (".xlsb",), upload_root=uploads))
            outside = root / "outside.csv"
            outside.write_bytes(b"x")
            token = history_token({})
            history = [
                {"name": "outside.csv", "path": str(outside), "size": 1},
                {"name": "data.xlsb", "path": str(path), "size": 4},
            ]
            save_upload_history(token, history, history_root=records, upload_root=uploads)
            self.assertEqual(len(load_upload_history(token, history_root=records, upload_root=uploads)), 1)
            path.unlink()
            self.assertEqual(load_upload_history(token, history_root=records, upload_root=uploads), [])

    def test_invalid_token_or_broken_registry_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(UploadHistoryError):
                load_upload_history("../outside", history_root=root)
            token = history_token({})
            (root / f"{token}.json").write_text(json.dumps({"files": []}), encoding="utf-8")
            with self.assertRaises(UploadHistoryError):
                load_upload_history(token, history_root=root)

    def test_streamlit_restores_history_visible_after_new_session(self) -> None:
        import app.streamlit_app as prototype

        params = {}
        entry = {"name": "data.csv", "path": "stored.csv", "size": 5}
        stub = SimpleNamespace(query_params=params)
        with patch.object(prototype, "st", stub), patch.object(prototype, "load_upload_history", return_value=[entry]) as load:
            first_session = {}
            prototype._restore_upload_history(first_session)
            self.assertTrue(first_session[prototype._UPLOAD_HISTORY_VISIBLE_KEY])
            first_token = first_session[prototype._UPLOAD_HISTORY_TOKEN_KEY]

            second_session = {}
            prototype._restore_upload_history(second_session)
            self.assertEqual(second_session[prototype._UPLOAD_HISTORY_TOKEN_KEY], first_token)
            self.assertEqual(second_session[prototype._UPLOAD_HISTORY_KEY], [entry])
            self.assertTrue(second_session[prototype._UPLOAD_HISTORY_VISIBLE_KEY])
            self.assertEqual(load.call_count, 2)

    def test_live_session_history_is_migrated_without_showing_it_immediately(self) -> None:
        import app.streamlit_app as prototype

        entry = {"name": "data.csv", "path": "stored.csv", "size": 5}
        state = {prototype._UPLOAD_HISTORY_KEY: [entry], prototype._UPLOAD_HISTORY_VISIBLE_KEY: False}
        stub = SimpleNamespace(query_params={})
        with (
            patch.object(prototype, "st", stub),
            patch.object(prototype, "load_upload_history", side_effect=[[], [entry]]),
            patch.object(prototype, "save_upload_history") as save,
        ):
            prototype._restore_upload_history(state)

        save.assert_called_once_with(state[prototype._UPLOAD_HISTORY_TOKEN_KEY], [entry])
        self.assertEqual(state[prototype._UPLOAD_HISTORY_KEY], [entry])
        self.assertFalse(state[prototype._UPLOAD_HISTORY_VISIBLE_KEY])
