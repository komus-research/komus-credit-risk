"""Persistent organisational bindings for immutable model versions."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkstemp


_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ModelLibraryRecord:
    """The deliberately small V1 catalogue record for one saved experiment."""

    schema_version: int
    experiment_artifact_id: str
    model_version_id: str
    display_name: str
    display_version: str
    saved_at: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("Unsupported ModelLibraryRecord schema version.")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.experiment_artifact_id,
                self.model_version_id,
                self.display_name,
                self.display_version,
                self.saved_at,
            )
        ):
            raise ValueError("ModelLibraryRecord fields must be non-empty strings.")
        if not self.display_version.startswith("v") or not self.display_version[1:].isdigit():
            raise ValueError("ModelLibraryRecord display_version must be vN.")
        try:
            datetime.fromisoformat(self.saved_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("ModelLibraryRecord saved_at must be ISO-8601.") from error

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_artifact_id": self.experiment_artifact_id,
            "model_version_id": self.model_version_id,
            "display_name": self.display_name,
            "display_version": self.display_version,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ModelLibraryRecord":
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "experiment_artifact_id",
            "model_version_id",
            "display_name",
            "display_version",
            "saved_at",
        }:
            raise ValueError("ModelLibraryRecord structure is invalid.")
        return cls(**value)


class ModelLibraryRecordStore:
    """Filesystem store indexed only by trusted ExperimentArtifact identity."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def find_by_experiment_artifact_id(self, experiment_artifact_id: str) -> ModelLibraryRecord | None:
        path = self.root / self._path(experiment_artifact_id)
        if not path.is_file():
            return None
        record = self._read(path)
        if record.experiment_artifact_id != experiment_artifact_id:
            raise ValueError("MODEL_SAVE_BINDING_CONFLICT")
        return record

    def list(self) -> tuple[ModelLibraryRecord, ...]:
        return tuple(
            self._read(path)
            for path in sorted(self.root.glob("*.json"))
        )

    def save(self, record: ModelLibraryRecord) -> ModelLibraryRecord:
        path = self.root / self._path(record.experiment_artifact_id)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("MODEL_SAVE_BINDING_CONFLICT")
            return existing
        descriptor, temporary_name = mkstemp(prefix=".model-library-", suffix=".json", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(temporary, path)
            except FileExistsError:
                existing = self._read(path)
                if existing != record:
                    raise ValueError("MODEL_SAVE_BINDING_CONFLICT")
                return existing
            return record
        finally:
            if temporary.exists():
                temporary.unlink()

    def update_display_name(
        self,
        *,
        experiment_artifact_id: str,
        model_version_id: str,
        display_name: str,
    ) -> ModelLibraryRecord:
        path = self.root / self._path(experiment_artifact_id)
        if not path.is_file():
            raise ValueError("MODEL_VERSION_NOT_FOUND")
        existing = self._read(path)
        if (
            existing.experiment_artifact_id != experiment_artifact_id
            or existing.model_version_id != model_version_id
        ):
            raise ValueError("MODEL_SAVE_BINDING_CONFLICT")
        updated = ModelLibraryRecord(
            schema_version=existing.schema_version,
            experiment_artifact_id=existing.experiment_artifact_id,
            model_version_id=existing.model_version_id,
            display_name=display_name,
            display_version=existing.display_version,
            saved_at=existing.saved_at,
        )
        descriptor, temporary_name = mkstemp(prefix=".model-library-rename-", suffix=".json", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(updated.to_dict(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            return updated
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _read(path: Path) -> ModelLibraryRecord:
        try:
            with path.open(encoding="utf-8") as handle:
                return ModelLibraryRecord.from_dict(json.load(handle))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("MODEL_SAVE_BINDING_CONFLICT") from error

    @staticmethod
    def _path(experiment_artifact_id: str) -> Path:
        if not isinstance(experiment_artifact_id, str) or not experiment_artifact_id.strip():
            raise ValueError("Experiment artifact id is invalid.")
        return Path(f"{sha256(experiment_artifact_id.encode('utf-8')).hexdigest()}.json")
