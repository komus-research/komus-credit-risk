"""Trusted project bindings over immutable saved-model inference Results."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from komus_risk.artifacts.project_workspace_store import (
    ProjectWorkspaceRecord, ProjectWorkspaceRecordIntegrityError, ProjectWorkspaceStore,
)

from .saved_model_inference import SavedModelInferenceError, SavedModelInferenceService


class ProjectWorkspaceError(RuntimeError):
    code = "PROJECT_WORKSPACE_INTERNAL_ERROR"
    def __init__(self, code: str | None = None) -> None:
        if code:
            self.code = code
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ProjectWorkspacePage:
    total_count: int
    resumable_count: int
    offset: int
    limit: int
    items: tuple[dict[str, Any], ...]


class ProjectWorkspaceService:
    """Owns create/list/open; only the Result artifact retains analytical payload."""

    def __init__(self, *, store: ProjectWorkspaceStore, saved_inference_service: SavedModelInferenceService) -> None:
        self.store = store
        self.saved_inference_service = saved_inference_service

    def suggested_name(self, inference_result_id: str) -> str:
        summary = self._summary(inference_result_id)
        return f"{summary.display_name} — {summary.source_display_name} — {self._date(summary.created_at)}"

    def save(self, *, inference_result_id: str, name: str) -> ProjectWorkspaceRecord:
        summary = self._summary(inference_result_id)
        custom_name = self._name(name)
        try:
            with self.store.inference_lock(inference_result_id):
                existing = next((record for record in self.store.list() if record.inference_result_id == inference_result_id), None)
                if existing is not None:
                    self._validate_binding(existing, summary)
                    return existing
                now = self.store.now()
                return self.store.create(ProjectWorkspaceRecord(
                    schema_version=1, project_id=uuid4().hex, name=custom_name,
                    work_type="SAVED_MODEL_INFERENCE", inference_result_id=summary.inference_result_id,
                    model_version_id=summary.model_version_id,
                    source_fingerprint=getattr(summary, "source_fingerprint", None),
                    created_at=now, updated_at=now, last_opened_at=None,
                ))
        except ProjectWorkspaceError:
            raise
        except ProjectWorkspaceRecordIntegrityError as error:
            raise ProjectWorkspaceError("PROJECT_WORKSPACE_INTEGRITY_ERROR") from error

    def list(self, *, offset: int = 0, limit: int = 50) -> ProjectWorkspacePage:
        if isinstance(offset, bool) or isinstance(limit, bool) or not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or not 1 <= limit <= 100:
            raise ProjectWorkspaceError("INVALID_PROJECT_WORKSPACE_QUERY")
        try:
            records = sorted(self.store.list(), key=self._recent_key, reverse=True)
        except ProjectWorkspaceRecordIntegrityError as error:
            raise ProjectWorkspaceError("PROJECT_WORKSPACE_INTEGRITY_ERROR") from error
        items = tuple(self._list_item(record) for record in records)
        return ProjectWorkspacePage(len(records), sum(item["resumable"] for item in items), offset, limit, items[offset:offset + limit])

    def detail(self, project_id: str) -> dict[str, Any]:
        try:
            record = self.store.get(project_id)
        except ProjectWorkspaceRecordIntegrityError as error:
            raise ProjectWorkspaceError("PROJECT_WORKSPACE_NOT_FOUND") from error
        return self._view(record, self._summary(record.inference_result_id))

    def open(self, project_id: str) -> dict[str, Any]:
        """Validate the exact binding before and only before recording access."""
        try:
            record = self.store.get(project_id)
            summary = self._summary(record.inference_result_id)
            self._validate_binding(record, summary)
            opened = self.store.update(replace(record, last_opened_at=self.store.now()))
            return self._view(opened, summary)
        except ProjectWorkspaceError:
            raise
        except ProjectWorkspaceRecordIntegrityError as error:
            raise ProjectWorkspaceError("PROJECT_WORKSPACE_INTEGRITY_ERROR") from error

    def _list_item(self, record: ProjectWorkspaceRecord) -> dict[str, Any]:
        try:
            return self._view(record, self._summary(record.inference_result_id)) | {"resumable": True, "unavailable_code": None}
        except ProjectWorkspaceError as error:
            return self._unavailable_view(record, error.code)

    def _view(self, record: ProjectWorkspaceRecord, summary: Any) -> dict[str, Any]:
        self._validate_binding(record, summary)
        return {**record.to_dict(), "model_display_name": summary.display_name,
                "source_display_name": summary.source_display_name, "row_count": summary.row_count}

    @staticmethod
    def _unavailable_view(record: ProjectWorkspaceRecord, code: str) -> dict[str, Any]:
        return {**record.to_dict(), "model_display_name": None, "source_display_name": None,
                "row_count": None, "resumable": False, "unavailable_code": code}

    def _summary(self, inference_result_id: str):
        try:
            return self.saved_inference_service.summary(inference_result_id)
        except SavedModelInferenceError as error:
            raise ProjectWorkspaceError("PROJECT_INFERENCE_RESULT_UNAVAILABLE") from error

    @staticmethod
    def _validate_binding(record: ProjectWorkspaceRecord, summary: Any) -> None:
        if (
            record.work_type != "SAVED_MODEL_INFERENCE"
            or record.model_version_id != summary.model_version_id
            or record.source_fingerprint is not None and record.source_fingerprint != getattr(summary, "source_fingerprint", None)
        ):
            raise ProjectWorkspaceError("PROJECT_WORKSPACE_INTEGRITY_ERROR")

    @staticmethod
    def _name(value: object) -> str:
        if not isinstance(value, str):
            raise ProjectWorkspaceError("INVALID_PROJECT_NAME")
        normalized = value.strip()
        if not 1 <= len(normalized) <= 160:
            raise ProjectWorkspaceError("INVALID_PROJECT_NAME")
        return normalized

    @staticmethod
    def _date(value: str) -> str:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y")
        except ValueError as error:
            raise ProjectWorkspaceError("PROJECT_INFERENCE_RESULT_UNAVAILABLE") from error

    @staticmethod
    def _recent_key(record: ProjectWorkspaceRecord) -> tuple[datetime, datetime]:
        def stamp(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp(record.last_opened_at or record.updated_at), stamp(record.updated_at)
