"""Browser-upload staging for local-path based dataset workflows.

The dataset preparation services deliberately consume local runtime paths.  This
module is the boundary between a browser upload and that existing contract; it
does not inspect or interpret tabular data.
"""

from __future__ import annotations

import atexit
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

SUPPORTED_UPLOAD_EXTENSIONS = frozenset({".csv", ".xlsx", ".xlsb", ".parquet"})
_DEFAULT_STAGING_ROOT = Path(tempfile.gettempdir()) / "komus-streamlit-upload-staging"
_REGISTERED_ROOTS: set[Path] = set()


class BrowserUpload(Protocol):
    """Minimal browser-upload adapter contract used by the staging boundary."""

    name: str

    def getvalue(self) -> bytes: ...


class UploadStagingError(ValueError):
    """Base class for errors that happen before dataset preparation."""


class UnsupportedUploadExtension(UploadStagingError):
    """The browser file name does not have a supported extension."""


class EmptyUploadError(UploadStagingError):
    """The browser supplied no bytes."""


class UploadReadError(UploadStagingError):
    """The browser upload could not be read or staged safely."""


@dataclass(frozen=True)
class StagedUpload:
    """A session-owned, server-local copy of a browser-selected file."""

    local_path: Path
    display_name: str
    digest: str
    staging_root: Path


def stage_browser_upload(
    upload: BrowserUpload,
    *,
    previous: StagedUpload | None = None,
    staging_root: Path | None = None,
) -> StagedUpload:
    """Persist one browser upload and return its controlled local path.

    A replacement is written completely before its predecessor is removed, so a
    failed upload cannot invalidate a source currently used by the workflow.
    """
    return stage_upload_bytes(
        _upload_name(upload), _upload_bytes(upload), previous=previous, staging_root=staging_root
    )


def stage_upload_bytes(
    name: str,
    data: bytes,
    *,
    previous: StagedUpload | None = None,
    staging_root: Path | None = None,
) -> StagedUpload:
    """Stage bytes from any HTTP/UI adapter using the same safety rules."""
    safe_name = _safe_filename(name)
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise UnsupportedUploadExtension(extension or "(без расширения)")

    if not data:
        raise EmptyUploadError("Загруженный файл не содержит данных.")
    digest = sha256(data).hexdigest()
    if previous is not None and (
        previous.display_name == safe_name
        and previous.digest == digest
        and previous.local_path.is_file()
    ):
        previous.local_path.touch()
        previous.local_path.parent.touch()
        return previous

    directory: Path | None = None
    try:
        root = (staging_root or _DEFAULT_STAGING_ROOT).resolve()
        root.mkdir(parents=True, exist_ok=True)
        _REGISTERED_ROOTS.add(root)
        cleanup_expired_staged_uploads(root)
        directory = Path(tempfile.mkdtemp(prefix="upload-", dir=root))
        destination = directory / safe_name
        temporary = directory / f".{uuid4().hex}.uploading"
        temporary.write_bytes(data)
        temporary.replace(destination)
    except OSError as error:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        raise UploadReadError("Не удалось сохранить загруженный файл.") from error

    staged = StagedUpload(destination, safe_name, digest, root)
    if previous is not None:
        cleanup_staged_upload(previous)
    return staged


def cleanup_staged_upload(staged: StagedUpload | None) -> None:
    """Remove a session-owned staged upload, never an arbitrary local path."""
    if staged is None:
        return
    root = staged.staging_root.resolve()
    parent = staged.local_path.resolve(strict=False).parent
    try:
        parent.relative_to(root)
    except ValueError:
        return
    if parent.parent != root or not parent.name.startswith("upload-"):
        return
    shutil.rmtree(parent, ignore_errors=True)


def cleanup_expired_staged_uploads(
    staging_root: Path, *, max_age_seconds: int = 7 * 24 * 60 * 60
) -> None:
    """Collect abandoned session directories on a later upload request.

    There is no background collector, so a live workflow is never deleted by a
    timer.  Replacement/reset cleanups are immediate; only directories untouched
    for seven days are treated as abandoned.
    """
    root = staging_root.resolve()
    if not root.is_dir():
        return
    deadline = time.time() - max_age_seconds
    for candidate in root.iterdir():
        if not candidate.is_dir() or not candidate.name.startswith("upload-"):
            continue
        try:
            if candidate.stat().st_mtime < deadline:
                shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue


def _upload_name(upload: BrowserUpload) -> str:
    try:
        name = str(upload.name)
    except Exception as error:  # Browser adapter failures have no safe filename.
        raise UploadReadError("Не удалось получить имя загруженного файла.") from error
    return name


def _upload_bytes(upload: BrowserUpload) -> bytes:
    try:
        data = upload.getvalue()
    except Exception as error:
        raise UploadReadError(
            "Не удалось получить содержимое загруженного файла."
        ) from error
    if not isinstance(data, bytes):
        raise UploadReadError("Загруженный файл имеет недопустимое содержимое.")
    return data


def _safe_filename(name: str) -> str:
    """Keep a display-friendly basename without ever trusting it as a path."""
    basename = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^\w.() -]", "_", basename, flags=re.UNICODE).strip(". ")
    if cleaned:
        return cleaned
    return "dataset"


@atexit.register
def _cleanup_on_process_exit() -> None:
    """Release controlled runtime files once the Streamlit process terminates."""
    for root in tuple(_REGISTERED_ROOTS):
        shutil.rmtree(root, ignore_errors=True)
