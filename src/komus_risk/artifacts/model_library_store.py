"""Persistent organisational bindings for immutable model versions."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from tempfile import mkstemp


_SCHEMA_VERSION = 2
_LEGACY_SCHEMA_VERSION = 1


class ModelLibraryRecordBindingConflict(ValueError):
    """The persisted library binding is malformed or does not match its path."""


class ModelDecisionThresholdRecordIntegrityError(ValueError):
    """Persisted threshold fields do not satisfy the V2 integrity contract."""


class ModelDecisionThresholdRecordConflict(ValueError):
    """An immutable saved threshold was requested with a different value."""


@dataclass(frozen=True, slots=True)
class ModelLibraryRecord:
    """Persistent binding of an immutable ModelVersion and its decision policy."""

    schema_version: int
    experiment_artifact_id: str
    model_version_id: str
    display_name: str
    display_version: str
    saved_at: str
    decision_threshold: float | None = None
    decision_threshold_state: str = "NOT_SET"

    def __post_init__(self) -> None:
        if self.schema_version not in {_LEGACY_SCHEMA_VERSION, _SCHEMA_VERSION}:
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
        if self.schema_version == _LEGACY_SCHEMA_VERSION:
            if self.decision_threshold is not None or self.decision_threshold_state != "NOT_SET":
                raise ModelDecisionThresholdRecordIntegrityError()
        elif self.decision_threshold_state == "USER_APPLIED":
            if (
                isinstance(self.decision_threshold, bool)
                or not isinstance(self.decision_threshold, (int, float))
                or not isfinite(float(self.decision_threshold))
                or not 0 <= float(self.decision_threshold) <= 1
            ):
                raise ModelDecisionThresholdRecordIntegrityError()
        elif self.decision_threshold_state == "NOT_SET":
            if self.decision_threshold is not None:
                raise ModelDecisionThresholdRecordIntegrityError()
        else:
            raise ModelDecisionThresholdRecordIntegrityError()

    def to_dict(self) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "experiment_artifact_id": self.experiment_artifact_id,
            "model_version_id": self.model_version_id,
            "display_name": self.display_name,
            "display_version": self.display_version,
            "saved_at": self.saved_at,
        }
        if self.schema_version == _SCHEMA_VERSION:
            value["decision_threshold"] = self.decision_threshold
            value["decision_threshold_state"] = self.decision_threshold_state
        return value

    @classmethod
    def from_dict(cls, value: object) -> "ModelLibraryRecord":
        legacy_fields = {"schema_version", "experiment_artifact_id", "model_version_id", "display_name", "display_version", "saved_at"}
        current_fields = legacy_fields | {"decision_threshold", "decision_threshold_state"}
        if not isinstance(value, dict):
            raise ModelLibraryRecordBindingConflict()
        schema_version = value.get("schema_version")
        if schema_version == _LEGACY_SCHEMA_VERSION:
            if set(value) != legacy_fields:
                raise ModelLibraryRecordBindingConflict()
            return cls(**value, decision_threshold=None, decision_threshold_state="NOT_SET")
        if schema_version == _SCHEMA_VERSION:
            if set(value) != current_fields:
                raise ModelDecisionThresholdRecordIntegrityError()
            return cls(**value)
        raise ModelLibraryRecordBindingConflict()


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
            raise ModelLibraryRecordBindingConflict()
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
                raise ModelLibraryRecordBindingConflict()
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
                    raise ModelLibraryRecordBindingConflict()
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
            raise ModelLibraryRecordBindingConflict()
        existing = self._read(path)
        if (
            existing.experiment_artifact_id != experiment_artifact_id
            or existing.model_version_id != model_version_id
        ):
            raise ModelLibraryRecordBindingConflict()
        updated = ModelLibraryRecord(
            schema_version=existing.schema_version,
            experiment_artifact_id=existing.experiment_artifact_id,
            model_version_id=existing.model_version_id,
            display_name=display_name,
            display_version=existing.display_version,
            saved_at=existing.saved_at,
            decision_threshold=existing.decision_threshold,
            decision_threshold_state=existing.decision_threshold_state,
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

    def complete_decision_threshold(
        self, *, experiment_artifact_id: str, model_version_id: str, threshold: float,
    ) -> ModelLibraryRecord:
        """One permitted V1 upgrade; never alters an already applied threshold."""
        path = self.root / self._path(experiment_artifact_id)
        if not path.is_file():
            raise ModelLibraryRecordBindingConflict()
        existing = self._read(path)
        if existing.model_version_id != model_version_id:
            raise ModelLibraryRecordBindingConflict()
        if existing.decision_threshold_state == "USER_APPLIED":
            if existing.decision_threshold == threshold:
                return existing
            raise ModelDecisionThresholdRecordConflict()
        updated = ModelLibraryRecord(
            schema_version=_SCHEMA_VERSION,
            experiment_artifact_id=existing.experiment_artifact_id,
            model_version_id=existing.model_version_id,
            display_name=existing.display_name,
            display_version=existing.display_version,
            saved_at=existing.saved_at,
            decision_threshold=threshold,
            decision_threshold_state="USER_APPLIED",
        )
        descriptor, temporary_name = mkstemp(prefix=".model-library-threshold-", suffix=".json", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(updated.to_dict(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush(); os.fsync(handle.fileno())
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
        except (ModelDecisionThresholdRecordIntegrityError, ModelLibraryRecordBindingConflict):
            raise
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ModelLibraryRecordBindingConflict() from error

    @staticmethod
    def _path(experiment_artifact_id: str) -> Path:
        if not isinstance(experiment_artifact_id, str) or not experiment_artifact_id.strip():
            raise ModelLibraryRecordBindingConflict()
        return Path(f"{sha256(experiment_artifact_id.encode('utf-8')).hexdigest()}.json")
