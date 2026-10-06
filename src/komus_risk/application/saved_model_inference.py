"""Trusted transient inference preparation and explicit immutable runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from komus_risk.artifacts import (
    InferenceResultIntegrityError,
    InferenceResultNotFoundError,
    InferenceResultPersistenceError,
    InferenceViewConfigurationIntegrityError,
    InferenceViewConfigurationPersistenceError,
    SavedInferenceResultViewConfiguration,
    SavedInferenceResultViewConfigurationStore,
    SavedModelInferenceResult,
    SavedModelInferenceResultStore,
)
from .model_inference import InferenceInputError, ModelInferenceService, PreparedInferenceInput
from .model_library import ModelLibraryService


class SavedModelInferenceError(RuntimeError):
    code = "INFERENCE_INTERNAL_ERROR"
    def __init__(self, code: str | None = None) -> None:
        if code: self.code = code
        super().__init__(self.code)


class InferencePreparationError(SavedModelInferenceError): pass


_recipe_locks: dict[tuple[str, str], RLock] = {}
_recipe_locks_guard = RLock()


def _recipe_lock(root: Any, recipe_key: str) -> RLock:
    key = (str(root.resolve()), recipe_key)
    with _recipe_locks_guard:
        return _recipe_locks.setdefault(key, RLock())


@dataclass(slots=True)
class InferencePreparation:
    preparation_id: str; session_owner: str; model_version_id: str; experiment_artifact_id: str
    staged_upload: Any; snapshot: Any; prepared: PreparedInferenceInput; status: str
    created_at: datetime; updated_at: datetime; inference_result_id: str | None = None


@dataclass(frozen=True, slots=True)
class InferencePreflight:
    preparation_id: str; model_version_id: str; experiment_artifact_id: str
    model_display_name: str; display_name: str; display_version: str; training_dataset_name: str
    source_display_name: str; source_format: str; source_file_sha256: str; source_fingerprint: str
    row_count: int; column_count: int; identifier_column: str
    required_feature_columns: tuple[str, ...]; ignored_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InferenceRun:
    run_state: str; inference_result_id: str; model_version_id: str; source_display_name: str; created_at: str


@dataclass(frozen=True, slots=True)
class SavedModelInferenceSummary:
    inference_result_id: str; model_version_id: str; experiment_artifact_id: str
    display_name: str; display_version: str; model_display_name: str
    source_display_name: str; source_format: str; source_file_sha256: str; source_fingerprint: str
    created_at: str; row_count: int; column_count: int; identifier_column: str
    required_feature_count: int; ignored_column_count: int; score_min: float; score_max: float
    threshold: float; above_threshold_count: int; above_threshold_share: float
    below_threshold_count: int; below_threshold_share: float
    histogram: tuple[dict[str, float | int], ...]


@dataclass(frozen=True, slots=True)
class SavedModelInferenceObjectPage:
    inference_result_id: str; threshold: float; total_count: int; filtered_count: int
    offset: int; limit: int; items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SavedInferenceResultView:
    saved: bool
    configuration: dict[str, Any]


class SavedModelInferenceService:
    def __init__(self, *, model_library_service: ModelLibraryService, model_inference_service: ModelInferenceService,
                 result_store: SavedModelInferenceResultStore, cleanup_upload: Callable[[Any], None],
                 view_store: SavedInferenceResultViewConfigurationStore | None = None) -> None:
        self.model_library_service, self.model_inference_service = model_library_service, model_inference_service
        self.result_store, self.cleanup_upload, self.view_store = result_store, cleanup_upload, view_store
        self._items: dict[str, InferencePreparation] = {}; self._lock = RLock()

    def preflight(self, *, session_owner: str, model_version_id: str, staged_upload: Any, snapshot: Any) -> InferencePreflight:
        self._expire()
        record, loaded = self.model_library_service.load_for_inference(model_version_id)
        try: prepared = self.model_inference_service.prepare(loaded_model_version=loaded, snapshot=snapshot)
        except InferenceInputError: raise
        if prepared.model_version_id != record.model_version_id: raise SavedModelInferenceError("MODEL_VERSION_INTEGRITY_ERROR")
        # Complete every fallible trusted response fact before publishing a
        # replacement.  A failed replacement must leave the old READY item usable.
        detail = self.model_library_service.detail(model_version_id).value
        model_display_name = str(detail.get("algorithm", {}).get("model_display_name", record.model_version_id))
        training_dataset_name = str(detail.get("dataset", {}).get("dataset_name", ""))
        now = datetime.now(UTC)
        item = InferencePreparation(uuid4().hex, session_owner, record.model_version_id, record.experiment_artifact_id,
            staged_upload, snapshot, prepared, "READY", now, now)
        with self._lock:
            old = [p for p in self._items.values() if p.session_owner == session_owner and p.model_version_id == model_version_id and p.status in {"READY", "FAILED"}]
            self._items[item.preparation_id] = item
            for p in old: self._items.pop(p.preparation_id, None)
        for p in old: self.cleanup_upload(p.staged_upload)
        return InferencePreflight(item.preparation_id, record.model_version_id, record.experiment_artifact_id,
            model_display_name, record.display_name, record.display_version, training_dataset_name, staged_upload.display_name,
            snapshot.source_format, prepared.source_sha256, prepared.source_fingerprint, prepared.row_count,
            prepared.column_count, prepared.identifier_column, prepared.required_feature_columns, prepared.ignored_columns)

    def cancel(self, *, session_owner: str, model_version_id: str, preparation_id: str) -> None:
        self._expire()
        with self._lock:
            p = self._owned(session_owner, model_version_id, preparation_id)
            if p is None or p.status == "COMPLETED": return
            if p.status == "RUNNING": raise InferencePreparationError("INFERENCE_RUN_IN_PROGRESS")
            self._items.pop(preparation_id, None)
        self.cleanup_upload(p.staged_upload)

    def run(self, *, session_owner: str, model_version_id: str, preparation_id: str) -> InferenceRun:
        self._expire()
        with self._lock:
            p = self._owned(session_owner, model_version_id, preparation_id)
            if p is None: raise InferencePreparationError("INFERENCE_PREPARATION_STALE")
            if p.status == "RUNNING": raise InferencePreparationError("INFERENCE_RUN_IN_PROGRESS")
            if p.status == "COMPLETED" and p.inference_result_id:
                return self._response("REUSED", self.result_store.read(p.inference_result_id))
            if p.status not in {"READY", "FAILED"}: raise InferencePreparationError("INFERENCE_PREPARATION_STALE")
            p.status = "RUNNING"; p.updated_at = datetime.now(UTC)
        try:
            record, loaded = self.model_library_service.load_for_inference(model_version_id)
            if record.experiment_artifact_id != p.experiment_artifact_id: raise SavedModelInferenceError("MODEL_VERSION_INTEGRITY_ERROR")
            recipe = self.result_store.recipe_key(model_version_id=model_version_id, prepared=p.prepared)
            with _recipe_lock(self.result_store.root, recipe):
                found = self.result_store.find_by_recipe_key(recipe)
                if found is None:
                    batch = self.model_inference_service.predict_prepared(loaded_model_version=loaded, prepared=p.prepared)
                    found = self.result_store.create(model_version_id=record.model_version_id, experiment_artifact_id=record.experiment_artifact_id,
                        source_display_name=p.staged_upload.display_name, source_format=p.snapshot.source_format, prepared=p.prepared, prediction_batch=batch)
                    state = "CREATED"
                else: state = "REUSED"
                self.result_store.read(found.inference_result_id)
            with self._lock: p.status, p.inference_result_id, p.updated_at = "COMPLETED", found.inference_result_id, datetime.now(UTC)
            self.cleanup_upload(p.staged_upload)
            return self._response(state, found)
        except InferenceInputError as e:
            self._failed(p); raise SavedModelInferenceError(e.code) from e
        except SavedModelInferenceError:
            self._failed(p); raise
        except InferenceResultPersistenceError as e:
            self._failed(p); raise SavedModelInferenceError("INFERENCE_RESULT_PERSISTENCE_FAILED") from e
        except Exception as e:
            self._failed(p); raise SavedModelInferenceError("INFERENCE_FAILED") from e

    def summary(self, inference_result_id: str, threshold: float = 0.50) -> SavedModelInferenceSummary:
        result = self._read_result(inference_result_id)
        value = self._threshold(threshold, "INVALID_INFERENCE_RESULT_QUERY")
        try:
            detail = self.model_library_service.detail(result.model_version_id).value
            if (
                detail.get("model_version_id") != result.model_version_id
                or detail.get("experiment_artifact_id") != result.experiment_artifact_id
            ):
                raise ValueError
            display_name = detail["display_name"]
            display_version = detail["display_version"]
            model_display_name = detail["algorithm"]["model_display_name"]
            if not all(isinstance(item, str) for item in (display_name, display_version, model_display_name)):
                raise ValueError
        except Exception as error:
            raise SavedModelInferenceError("INFERENCE_RESULT_INTEGRITY_ERROR") from error
        scores = tuple(row.probability for row in result.rows)
        above = sum(score >= value for score in scores)
        count = len(scores)
        histogram = []
        for index in range(20):
            lower, upper = index / 20, (index + 1) / 20
            histogram.append({
                "lower_bound": lower, "upper_bound": upper,
                "count": sum(lower <= score <= upper if index == 19 else lower <= score < upper for score in scores),
            })
        return SavedModelInferenceSummary(
            result.inference_result_id, result.model_version_id, result.experiment_artifact_id,
            display_name, display_version, model_display_name,
            result.source_display_name, result.source_format, result.source_file_sha256, result.source_fingerprint,
            result.created_at, result.row_count, result.column_count, result.identifier_column,
            len(result.required_feature_columns), len(result.ignored_columns), min(scores), max(scores), value,
            above, above / count, count - above, (count - above) / count, tuple(histogram),
        )

    def objects(
        self, inference_result_id: str, *, threshold: float = 0.50, offset: int = 0, limit: int = 50,
        search: str | None = None, min_score: float | None = None, max_score: float | None = None,
        position_filter: str = "ALL", sort: str = "SCORE_DESC",
    ) -> SavedModelInferenceObjectPage:
        result = self._read_result(inference_result_id)
        value = self._threshold(threshold, "INVALID_INFERENCE_RESULT_QUERY")
        self._paging(offset, limit)
        minimum = self._bound(min_score)
        maximum = self._bound(max_score)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY")
        if not isinstance(search, str) and search is not None:
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY")
        if (
            not isinstance(position_filter, str)
            or not isinstance(sort, str)
            or position_filter not in {"ALL", "ABOVE", "BELOW"}
            or sort not in {"SCORE_DESC", "SCORE_ASC", "SOURCE_ASC"}
        ):
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY")
        needle = (search or "").casefold()
        selected = [
            row for row in result.rows
            if (not needle or needle in row.identifier_display.casefold())
            and (minimum is None or row.probability >= minimum)
            and (maximum is None or row.probability <= maximum)
            and (position_filter == "ALL" or (row.probability >= value) == (position_filter == "ABOVE"))
        ]
        if sort == "SCORE_DESC":
            selected.sort(key=lambda row: (-row.probability, row.source_row_position))
        elif sort == "SCORE_ASC":
            selected.sort(key=lambda row: (row.probability, row.source_row_position))
        else:
            selected.sort(key=lambda row: row.source_row_position)
        page = selected[offset : offset + limit]
        return SavedModelInferenceObjectPage(
            result.inference_result_id, value, result.row_count, len(selected), offset, limit,
            tuple({
                "row_id": row.row_id, "source_row_position": row.source_row_position,
                "identifier_display": row.identifier_display, "score": row.probability,
                "above_threshold": row.probability >= value,
            } for row in page),
        )

    def get_view_configuration(self, inference_result_id: str) -> SavedInferenceResultView:
        result = self._read_result(inference_result_id)
        store = self._view_store()
        try:
            stored = store.read(result.inference_result_id)
        except InferenceViewConfigurationIntegrityError as error:
            raise SavedModelInferenceError("INFERENCE_VIEW_CONFIGURATION_INTEGRITY_ERROR") from error
        except InferenceViewConfigurationPersistenceError as error:
            raise SavedModelInferenceError("INFERENCE_INTERNAL_ERROR") from error
        return self._view(stored, result.inference_result_id)

    def put_view_configuration(self, inference_result_id: str, *, threshold: object, min_score: object, max_score: object,
                               position_filter: object, sort: object, search: object) -> SavedInferenceResultView:
        result = self._read_result(inference_result_id)
        try:
            normalized = self._configuration(
                result.inference_result_id, threshold, min_score, max_score, position_filter, sort, search
            )
        except ValueError as error:
            raise SavedModelInferenceError("INVALID_INFERENCE_VIEW_CONFIGURATION") from error
        store = self._view_store()
        try:
            existing = store.read(result.inference_result_id)
            if existing is not None and self._configuration_values(existing) == self._configuration_values(normalized):
                return self._view(existing, result.inference_result_id)
            store.save(normalized)
        except InferenceViewConfigurationIntegrityError as error:
            raise SavedModelInferenceError("INFERENCE_VIEW_CONFIGURATION_INTEGRITY_ERROR") from error
        except InferenceViewConfigurationPersistenceError as error:
            raise SavedModelInferenceError("INFERENCE_INTERNAL_ERROR") from error
        return self._view(normalized, result.inference_result_id)

    def delete_view_configuration(self, inference_result_id: str) -> SavedInferenceResultView:
        result = self._read_result(inference_result_id)
        try:
            self._view_store().delete(result.inference_result_id)
        except InferenceViewConfigurationIntegrityError as error:
            raise SavedModelInferenceError("INFERENCE_VIEW_CONFIGURATION_INTEGRITY_ERROR") from error
        except InferenceViewConfigurationPersistenceError as error:
            raise SavedModelInferenceError("INFERENCE_INTERNAL_ERROR") from error
        return self._view(None, result.inference_result_id)

    def _owned(self, owner: str, model: str, key: str) -> InferencePreparation | None:
        p = self._items.get(key); return p if p and p.session_owner == owner and p.model_version_id == model else None
    def _failed(self, p: InferencePreparation) -> None:
        with self._lock: p.status, p.updated_at = "FAILED", datetime.now(UTC)
    def _expire(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=2)
        with self._lock: stale = [self._items.pop(k) for k, p in tuple(self._items.items()) if p.status in {"READY", "FAILED"} and p.updated_at < cutoff]
        for p in stale: self.cleanup_upload(p.staged_upload)
    @staticmethod
    def _response(state: str, result: SavedModelInferenceResult) -> InferenceRun:
        return InferenceRun(state, result.inference_result_id, result.model_version_id, result.source_display_name, result.created_at)

    def _read_result(self, inference_result_id: str) -> SavedModelInferenceResult:
        try:
            return self.result_store.read(inference_result_id)
        except InferenceResultNotFoundError as error:
            raise SavedModelInferenceError("INFERENCE_RESULT_NOT_FOUND") from error
        except InferenceResultIntegrityError as error:
            raise SavedModelInferenceError("INFERENCE_RESULT_INTEGRITY_ERROR") from error

    def _view_store(self) -> SavedInferenceResultViewConfigurationStore:
        if self.view_store is None:
            raise SavedModelInferenceError("INFERENCE_INTERNAL_ERROR")
        return self.view_store

    @staticmethod
    def _threshold(value: object, code: str) -> float:
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(float(value)) or not 0 <= float(value) <= 1:
            raise SavedModelInferenceError(code)
        return float(value)

    @staticmethod
    def _bound(value: object | None) -> float | None:
        if value is None:
            return None
        return SavedModelInferenceService._threshold(value, "INVALID_INFERENCE_RESULT_QUERY")

    @staticmethod
    def _paging(offset: object, limit: object) -> None:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY")

    @staticmethod
    def _configuration(inference_result_id: str, threshold: object, min_score: object, max_score: object,
                       position_filter: object, sort: object, search: object) -> SavedInferenceResultViewConfiguration:
        def number(value: object) -> float:
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(float(value)) or not 0 <= float(value) <= 1:
                raise ValueError
            return float(value)
        minimum, maximum = number(min_score), number(max_score)
        if (
            minimum > maximum
            or not isinstance(position_filter, str)
            or not isinstance(sort, str)
            or position_filter not in {"ALL", "ABOVE", "BELOW"}
            or sort not in {"SCORE_DESC", "SCORE_ASC", "SOURCE_ASC"}
            or not isinstance(search, str)
        ):
            raise ValueError
        return SavedInferenceResultViewConfiguration(
            1, inference_result_id, number(threshold), minimum, maximum, position_filter, sort, search,
            datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def _configuration_values(value: SavedInferenceResultViewConfiguration) -> tuple[object, ...]:
        return (value.threshold, value.min_score, value.max_score, value.position_filter, value.sort, value.search)

    @staticmethod
    def _view(value: SavedInferenceResultViewConfiguration | None, inference_result_id: str) -> SavedInferenceResultView:
        if value is None:
            return SavedInferenceResultView(False, {
                "inference_result_id": inference_result_id, "threshold": 0.50, "min_score": 0.00, "max_score": 1.00,
                "position_filter": "ALL", "sort": "SCORE_DESC", "search": "", "updated_at": None,
            })
        return SavedInferenceResultView(True, {
            "inference_result_id": value.inference_result_id, "threshold": value.threshold,
            "min_score": value.min_score, "max_score": value.max_score,
            "position_filter": value.position_filter, "sort": value.sort, "search": value.search,
            "updated_at": value.updated_at,
        })
