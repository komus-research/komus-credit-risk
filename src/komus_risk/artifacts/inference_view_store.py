"""Mutable, non-scientific view preferences for immutable inference results."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from numbers import Real
from pathlib import Path
from tempfile import NamedTemporaryFile


_SCHEMA_VERSION = 1
_REPORT_DRAFT_SCHEMA_VERSION = 1
_POSITION_FILTERS = frozenset({"ALL", "ABOVE", "BELOW"})
_SORTS = frozenset({"SCORE_DESC", "SCORE_ASC", "SOURCE_ASC"})


class InferenceViewConfigurationIntegrityError(ValueError):
    """A published view configuration is malformed or has been tampered with."""


class InferenceViewConfigurationPersistenceError(RuntimeError):
    """View configuration could not be read, written, or removed safely."""


class InferenceReportDraftIntegrityError(ValueError):
    """A persisted report draft is malformed or does not match its result."""


class InferenceReportDraftPersistenceError(RuntimeError):
    """A report draft could not be read or written safely."""


@dataclass(frozen=True, slots=True)
class SavedInferenceResultViewConfiguration:
    schema_version: int
    inference_result_id: str
    threshold: float
    min_score: float
    max_score: float
    position_filter: str
    sort: str
    search: str
    updated_at: str


class SavedInferenceResultViewConfigurationStore:
    """One atomically-written convenience configuration per inference result."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, inference_result_id: str) -> SavedInferenceResultViewConfiguration | None:
        path = self._path(inference_result_id)
        if not path.is_file():
            return None
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise InferenceViewConfigurationPersistenceError() from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise InferenceViewConfigurationIntegrityError() from error
        try:
            return self._from_payload(payload, inference_result_id)
        except (TypeError, ValueError) as error:
            if isinstance(error, InferenceViewConfigurationIntegrityError):
                raise
            raise InferenceViewConfigurationIntegrityError() from error

    def save(self, configuration: SavedInferenceResultViewConfiguration) -> None:
        self._validate(configuration, configuration.inference_result_id)
        path = self._path(configuration.inference_result_id)
        payload = {
            "schema_version": configuration.schema_version,
            "inference_result_id": configuration.inference_result_id,
            "threshold": configuration.threshold,
            "min_score": configuration.min_score,
            "max_score": configuration.max_score,
            "position_filter": configuration.position_filter,
            "sort": configuration.sort,
            "search": configuration.search,
            "updated_at": configuration.updated_at,
        }
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, prefix=".view-", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as error:
            raise InferenceViewConfigurationPersistenceError() from error
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def delete(self, inference_result_id: str) -> None:
        path = self._path(inference_result_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise InferenceViewConfigurationPersistenceError() from error

    def _path(self, inference_result_id: str) -> Path:
        if not self._valid_id(inference_result_id):
            raise InferenceViewConfigurationIntegrityError()
        return self.root / f"{inference_result_id}.json"

    @classmethod
    def _from_payload(cls, payload: object, expected_id: str) -> SavedInferenceResultViewConfiguration:
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version", "inference_result_id", "threshold", "min_score", "max_score",
            "position_filter", "sort", "search", "updated_at",
        }:
            raise InferenceViewConfigurationIntegrityError()
        try:
            configuration = SavedInferenceResultViewConfiguration(**payload)
        except TypeError as error:
            raise InferenceViewConfigurationIntegrityError() from error
        cls._validate(configuration, expected_id)
        return configuration

    @classmethod
    def _validate(cls, value: SavedInferenceResultViewConfiguration, expected_id: str) -> None:
        if (
            isinstance(value.schema_version, bool)
            or not isinstance(value.schema_version, int)
            or value.schema_version != _SCHEMA_VERSION
            or value.inference_result_id != expected_id
            or not cls._valid_id(value.inference_result_id)
            or value.position_filter not in _POSITION_FILTERS
            or value.sort not in _SORTS
            or not isinstance(value.search, str)
            or not isinstance(value.updated_at, str)
            or not cls._timestamp(value.updated_at)
        ):
            raise InferenceViewConfigurationIntegrityError()
        for number in (value.threshold, value.min_score, value.max_score):
            if isinstance(number, bool) or not isinstance(number, Real) or not isfinite(float(number)) or not 0 <= float(number) <= 1:
                raise InferenceViewConfigurationIntegrityError()
        if float(value.min_score) > float(value.max_score):
            raise InferenceViewConfigurationIntegrityError()

    @staticmethod
    def _timestamp(value: str) -> bool:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
        except ValueError:
            return False

    @staticmethod
    def _valid_id(value: object) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class SavedInferenceReportDraft:
    schema_version: int
    inference_result_id: str
    selected_row_ids: tuple[str, ...]
    created_at: str
    updated_at: str


class SavedInferenceReportDraftStore:
    """Atomically persisted analyst-selected row references for one inference result."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, inference_result_id: str) -> SavedInferenceReportDraft | None:
        path = self._path(inference_result_id)
        if not path.is_file():
            return None
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise InferenceReportDraftPersistenceError() from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise InferenceReportDraftIntegrityError() from error
        try:
            return self._from_payload(payload, inference_result_id)
        except (TypeError, ValueError) as error:
            if isinstance(error, InferenceReportDraftIntegrityError):
                raise
            raise InferenceReportDraftIntegrityError() from error

    def save(self, draft: SavedInferenceReportDraft) -> None:
        self._validate(draft, draft.inference_result_id)
        path = self._path(draft.inference_result_id)
        payload = {
            "schema_version": draft.schema_version,
            "inference_result_id": draft.inference_result_id,
            "selected_row_ids": list(draft.selected_row_ids),
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
        }
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, prefix=".report-draft-", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as error:
            raise InferenceReportDraftPersistenceError() from error
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def delete(self, inference_result_id: str) -> None:
        path = self._path(inference_result_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise InferenceReportDraftPersistenceError() from error

    def _path(self, inference_result_id: str) -> Path:
        if not SavedInferenceResultViewConfigurationStore._valid_id(inference_result_id):
            raise InferenceReportDraftIntegrityError()
        return self.root / f"{inference_result_id}.json"

    @classmethod
    def _from_payload(cls, payload: object, expected_id: str) -> SavedInferenceReportDraft:
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version", "inference_result_id", "selected_row_ids", "created_at", "updated_at",
        }:
            raise InferenceReportDraftIntegrityError()
        if not isinstance(payload["selected_row_ids"], list):
            raise InferenceReportDraftIntegrityError()
        try:
            value = SavedInferenceReportDraft(
                schema_version=payload["schema_version"],
                inference_result_id=payload["inference_result_id"],
                selected_row_ids=tuple(payload["selected_row_ids"]),
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
            )
        except (KeyError, TypeError) as error:
            raise InferenceReportDraftIntegrityError() from error
        cls._validate(value, expected_id)
        return value

    @classmethod
    def _validate(cls, value: SavedInferenceReportDraft, expected_id: str) -> None:
        if (
            isinstance(value.schema_version, bool)
            or not isinstance(value.schema_version, int)
            or value.schema_version != _REPORT_DRAFT_SCHEMA_VERSION
            or value.inference_result_id != expected_id
            or not SavedInferenceResultViewConfigurationStore._valid_id(value.inference_result_id)
            or not isinstance(value.selected_row_ids, tuple)
            or not value.selected_row_ids
            or len(value.selected_row_ids) != len(set(value.selected_row_ids))
            or not all(cls._valid_row_id(row_id) for row_id in value.selected_row_ids)
            or not isinstance(value.created_at, str)
            or not isinstance(value.updated_at, str)
            or not SavedInferenceResultViewConfigurationStore._timestamp(value.created_at)
            or not SavedInferenceResultViewConfigurationStore._timestamp(value.updated_at)
        ):
            raise InferenceReportDraftIntegrityError()

    @staticmethod
    def _valid_row_id(value: object) -> bool:
        return isinstance(value, str) and 1 <= len(value) <= 256 and all(character.isprintable() for character in value)
