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
_POSITION_FILTERS = frozenset({"ALL", "ABOVE", "BELOW"})
_SORTS = frozenset({"SCORE_DESC", "SCORE_ASC", "SOURCE_ASC"})


class InferenceViewConfigurationIntegrityError(ValueError):
    """A published view configuration is malformed or has been tampered with."""


class InferenceViewConfigurationPersistenceError(RuntimeError):
    """View configuration could not be read, written, or removed safely."""


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
