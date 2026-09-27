"""Regression coverage for browser upload staging at the Streamlit boundary."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.bootstrap import LocalDatasetSourceResolver, prepare_resolved_source
from app.upload_staging import (
    EmptyUploadError,
    UnsupportedUploadExtension,
    UploadReadError,
    cleanup_staged_upload,
    stage_browser_upload,
)


class _Upload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


class BrowserUploadStagingTests(unittest.TestCase):
    def test_browser_upload_stages_a_local_file_for_existing_resolver_and_preparation(
        self,
    ) -> None:
        upload = _Upload(
            "client data.csv", b"client_id,target,score\n1,0,0.1\n2,1,0.9\n"
        )
        with TemporaryDirectory() as directory:
            staged = stage_browser_upload(upload, staging_root=Path(directory))
            try:
                self.assertTrue(staged.local_path.is_file())
                self.assertEqual(staged.local_path.read_bytes(), upload.getvalue())
                self.assertEqual(staged.display_name, "client data.csv")
                source = LocalDatasetSourceResolver().resolve_explicit_local_path(
                    staged.local_path
                )
                result = prepare_resolved_source(source)
            finally:
                cleanup_staged_upload(staged)

        self.assertEqual(source.file_name, "client data.csv")
        self.assertEqual(result.preparation_status, "context_not_prepared")
        self.assertIsNotNone(result.snapshot)

    def test_all_supported_extensions_are_staged(self) -> None:
        with TemporaryDirectory() as directory:
            for extension in (".csv", ".xlsx", ".xlsb", ".parquet"):
                with self.subTest(extension=extension):
                    staged = stage_browser_upload(
                        _Upload(f"dataset{extension}", b"not-empty"),
                        staging_root=Path(directory),
                    )
                    self.assertEqual(staged.local_path.suffix, extension)
                    cleanup_staged_upload(staged)

    def test_unsupported_extension_is_rejected_before_staging(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(UnsupportedUploadExtension):
                stage_browser_upload(
                    _Upload("dataset.exe", b"not-empty"), staging_root=Path(directory)
                )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_empty_upload_is_rejected_before_staging(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(EmptyUploadError):
                stage_browser_upload(
                    _Upload("dataset.csv", b""), staging_root=Path(directory)
                )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_replacement_removes_only_the_previous_staged_file_after_new_copy_exists(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = stage_browser_upload(
                _Upload("first.csv", b"id,target\n1,0\n"), staging_root=root
            )
            second = stage_browser_upload(
                _Upload("..\\second.csv", b"id,target\n2,1\n"),
                previous=first,
                staging_root=root,
            )

            self.assertFalse(first.local_path.exists())
            self.assertTrue(second.local_path.is_file())
            self.assertEqual(second.display_name, "second.csv")
            cleanup_staged_upload(second)

    def test_staging_filesystem_failures_preserve_the_previous_upload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            previous = stage_browser_upload(
                _Upload("previous.csv", b"id,target\n1,0\n"), staging_root=root
            )
            for failure in (
                patch.object(Path, "mkdir", side_effect=OSError("read-only")),
                patch(
                    "app.upload_staging.tempfile.mkdtemp",
                    side_effect=OSError("no space"),
                ),
            ):
                with self.subTest(failure=failure):
                    with failure, self.assertRaises(UploadReadError):
                        stage_browser_upload(
                            _Upload("replacement.csv", b"id,target\n2,1\n"),
                            previous=previous,
                            staging_root=root,
                        )
                    self.assertTrue(previous.local_path.is_file())
                    self.assertEqual(
                        previous.local_path.read_bytes(), b"id,target\n1,0\n"
                    )
            cleanup_staged_upload(previous)

    def test_data_upload_control_has_no_manual_host_path_fallback(self) -> None:
        import app.streamlit_app as prototype

        source = inspect.getsource(prototype._render_local_source_controls)
        self.assertIn("st.file_uploader", source)
        self.assertNotIn("text_input", source)
        self.assertNotIn("расположение файла вручную", source)
