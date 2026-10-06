"""Canonical ProjectWorkspace V1 filesystem persistence."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp, mkstemp
from time import sleep


_PROJECT_ID = re.compile(r"^[0-9a-f]{32}$")
_SCHEMA_VERSION = 1
_WORK_TYPE = "SAVED_MODEL_INFERENCE"


class ProjectWorkspaceRecordIntegrityError(ValueError):
    """A persisted ProjectWorkspace is malformed or path-bound incorrectly."""


@dataclass(frozen=True, slots=True)
class ProjectWorkspaceRecord:
    schema_version: int
    project_id: str
    name: str
    work_type: str
    inference_result_id: str
    model_version_id: str
    source_fingerprint: str | None
    created_at: str
    updated_at: str
    last_opened_at: str | None

    def __post_init__(self) -> None:
        if (
            self.schema_version != _SCHEMA_VERSION or self.work_type != _WORK_TYPE
            or not _PROJECT_ID.fullmatch(self.project_id)
            or any(not isinstance(value, str) or not value.strip() for value in (
                self.name, self.inference_result_id, self.model_version_id, self.created_at, self.updated_at,
            ))
            or self.source_fingerprint is not None and (not isinstance(self.source_fingerprint, str) or not self.source_fingerprint.strip())
        ):
            raise ProjectWorkspaceRecordIntegrityError()
        for value in (self.created_at, self.updated_at, self.last_opened_at):
            if value is None:
                continue
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Project timestamps must be timezone-aware.")
            except ValueError as error:
                raise ProjectWorkspaceRecordIntegrityError() from error

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "project_id": self.project_id, "name": self.name,
                "work_type": self.work_type, "inference_result_id": self.inference_result_id,
                "model_version_id": self.model_version_id, "source_fingerprint": self.source_fingerprint,
                "created_at": self.created_at, "updated_at": self.updated_at, "last_opened_at": self.last_opened_at}

    @classmethod
    def from_dict(cls, value: object) -> "ProjectWorkspaceRecord":
        fields = {"schema_version", "project_id", "name", "work_type", "inference_result_id",
                  "model_version_id", "source_fingerprint", "created_at", "updated_at", "last_opened_at"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ProjectWorkspaceRecordIntegrityError()
        return cls(**value)


class ProjectWorkspaceStore:
    """Stores each project at ``projects/<opaque-id>/project.json`` only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, project_id: str) -> ProjectWorkspaceRecord:
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise ProjectWorkspaceRecordIntegrityError()
        return self._read(self.root / project_id / "project.json", project_id)

    def list(self) -> tuple[ProjectWorkspaceRecord, ...]:
        try:
            directories = tuple(path for path in self.root.iterdir() if path.is_dir() and not path.name.startswith("."))
        except OSError as error:
            raise ProjectWorkspaceRecordIntegrityError() from error
        return tuple(self._read(directory / "project.json", directory.name) for directory in sorted(directories))

    def create(self, record: ProjectWorkspaceRecord) -> ProjectWorkspaceRecord:
        destination = self.root / record.project_id
        if destination.exists():
            raise ProjectWorkspaceRecordIntegrityError()
        temporary = Path(mkdtemp(prefix=".project-", dir=self.root))
        try:
            self._write(temporary / "project.json", record)
            try:
                os.replace(temporary, destination)
            except FileExistsError as error:
                raise ProjectWorkspaceRecordIntegrityError() from error
            return self.get(record.project_id)
        except OSError as error:
            raise ProjectWorkspaceRecordIntegrityError() from error
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def update(self, record: ProjectWorkspaceRecord) -> ProjectWorkspaceRecord:
        path = self.root / record.project_id / "project.json"
        existing = self._read(path, record.project_id)
        if existing.inference_result_id != record.inference_result_id:
            raise ProjectWorkspaceRecordIntegrityError()
        descriptor, temporary_name = mkstemp(prefix=".project-update-", suffix=".json", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
            return self.get(record.project_id)
        except OSError as error:
            raise ProjectWorkspaceRecordIntegrityError() from error
        finally:
            if temporary.exists():
                temporary.unlink()

    def inference_lock(self, inference_result_id: str):
        return _InferenceResultLock(self.root, inference_result_id)

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _write(path: Path, record: ProjectWorkspaceRecord) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(record.to_dict(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())

    @staticmethod
    def _read(path: Path, expected_project_id: str) -> ProjectWorkspaceRecord:
        if not _PROJECT_ID.fullmatch(expected_project_id):
            raise ProjectWorkspaceRecordIntegrityError()
        try:
            with path.open(encoding="utf-8") as handle:
                record = ProjectWorkspaceRecord.from_dict(json.load(handle))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProjectWorkspaceRecordIntegrityError() from error
        if record.project_id != expected_project_id:
            raise ProjectWorkspaceRecordIntegrityError()
        return record


class _InferenceResultLock:
    """Cross-process lock guarding scan-plus-create inference deduplication."""

    def __init__(self, root: Path, inference_result_id: str) -> None:
        if not isinstance(inference_result_id, str) or not inference_result_id.strip():
            raise ProjectWorkspaceRecordIntegrityError()
        from hashlib import sha256
        self.path = root / ".locks" / sha256(inference_result_id.encode("utf-8")).hexdigest()

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(500):
            try:
                self.path.mkdir()
                return self
            except FileExistsError:
                sleep(.01)
        raise ProjectWorkspaceRecordIntegrityError()

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self.path.rmdir()
        except OSError:
            pass
