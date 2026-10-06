"""Trusted transient inference preparation and explicit immutable runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from komus_risk.artifacts import (
    InferenceResultPersistenceError,
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


class SavedModelInferenceService:
    def __init__(self, *, model_library_service: ModelLibraryService, model_inference_service: ModelInferenceService,
                 result_store: SavedModelInferenceResultStore, cleanup_upload: Callable[[Any], None]) -> None:
        self.model_library_service, self.model_inference_service = model_library_service, model_inference_service
        self.result_store, self.cleanup_upload = result_store, cleanup_upload
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
