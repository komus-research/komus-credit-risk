"""Framework-neutral transient state for the native AXION analysis flow.

This module owns only process-local, temporary workflow state.  Persisted
ExperimentArtifact and ModelVersion records remain outside this session layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from secrets import token_urlsafe
from threading import RLock
from typing import Any, Callable

from .dataset_onboarding import InspectedDataset, PreparationDraft


class NativeSessionTransitionError(ValueError):
    """Stable error for an invalid native workflow transition."""

    code = "INVALID_DATA_TRANSITION"

    def __init__(self) -> None:
        super().__init__(self.code)


class NewAnalysisStatus(StrEnum):
    """Outcome of the explicit new-analysis transition."""

    STARTED = "STARTED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


class DatasetInspectionStatus(StrEnum):
    """Public lifecycle of a transient dataset inspection."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    READY = "READY"
    ERROR = "ERROR"


class DatasetInspectionStage(StrEnum):
    """Truthful stages emitted around existing inspection operations."""

    RECEIVING_FILE = "RECEIVING_FILE"
    STAGING_FILE = "STAGING_FILE"
    READING_SOURCE = "READING_SOURCE"
    INSPECTING_DATASET = "INSPECTING_DATASET"
    ANALYZING_PREPARATION = "ANALYZING_PREPARATION"
    READY = "READY"
    ERROR = "ERROR"


DATASET_INSPECTION_STAGE_LABELS: dict[DatasetInspectionStage, str] = {
    DatasetInspectionStage.RECEIVING_FILE: "Получаем файл",
    DatasetInspectionStage.STAGING_FILE: "Сохраняем временную копию",
    DatasetInspectionStage.READING_SOURCE: "Читаем таблицу",
    DatasetInspectionStage.INSPECTING_DATASET: "Проверяем структуру данных",
    DatasetInspectionStage.ANALYZING_PREPARATION: "Определяем роли колонок",
    DatasetInspectionStage.READY: "Файл успешно проверен",
    DatasetInspectionStage.ERROR: "Не удалось проверить файл",
}


@dataclass(frozen=True, slots=True)
class DatasetInspectionProgress:
    """Safe, session-owned read model; it deliberately has no file internals."""

    status: DatasetInspectionStatus
    stage: DatasetInspectionStage | None
    stage_label: str | None
    started_at: datetime | None
    updated_at: datetime | None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class NativeSessionSnapshot:
    """The native frontend's read model for one analysis session."""

    current_step: int
    analysis_active: bool
    data_substep: str
    has_meaningful_temporary_work: bool
    resume_route: str


@dataclass(frozen=True, slots=True)
class NewAnalysisResult:
    """Typed result returned by the new-analysis use case."""

    status: NewAnalysisStatus
    session: NativeSessionSnapshot
    discarded_upload: Any | None = None


@dataclass(slots=True)
class _NativeAnalysisSession:
    current_step: int = 0
    analysis_active: bool = False
    has_meaningful_temporary_work: bool = False
    staged_upload: Any | None = None
    inspection_upload: Any | None = None
    inspected_dataset: InspectedDataset | None = None
    preparation_draft: PreparationDraft | None = None
    source_handle: str | None = None
    prepared_context_id: str | None = None
    confirmation_operation_token: str | None = None
    data_substep: str = "FILE"
    inspection_progress: DatasetInspectionProgress | None = None
    inspection_token: str | None = None

    def snapshot(self) -> NativeSessionSnapshot:
        return NativeSessionSnapshot(
            current_step=self.current_step,
            analysis_active=self.analysis_active,
            data_substep=self.data_substep,
            has_meaningful_temporary_work=self.has_meaningful_temporary_work,
            resume_route=self.resume_route(),
        )

    def resume_route(self) -> str:
        """Return the public route justified by the actual transient state."""
        if not self.analysis_active:
            return "#/home"
        if self.data_substep == "ROLES" and (
            self.inspected_dataset is not None and self.preparation_draft is not None
        ):
            return "#/analysis/data/roles"
        if self.data_substep == "CONFIRMATION" and (
            self.inspected_dataset is not None and self.preparation_draft is not None
        ):
            return "#/analysis/data/confirmation"
        if self.data_substep == "PREPARED" and self.prepared_context_id:
            return "#/analysis/features"
        return "#/analysis/data/file"


class NativeSessionStore:
    """Process-local store for opaque native analysis sessions.

    The store deliberately has no dependency on HTTP, Streamlit, databases, or
    persisted application artifacts.  A later persistence layer can be composed
    beside it without making a browser session authoritative scientific state.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _NativeAnalysisSession] = {}
        self._lock = RLock()

    def get_or_create(
        self, session_id: str | None
    ) -> tuple[str, NativeSessionSnapshot]:
        with self._lock:
            if session_id is not None and session_id in self._sessions:
                return session_id, self._sessions[session_id].snapshot()

            new_session_id = token_urlsafe(32)
            self._sessions[new_session_id] = _NativeAnalysisSession()
            return new_session_id, self._sessions[new_session_id].snapshot()

    def snapshot(self, session_id: str) -> NativeSessionSnapshot:
        with self._lock:
            return self._session(session_id).snapshot()

    def reconcile_prepared_context(
        self, session_id: str, context_is_trusted: Callable[[str], bool]
    ) -> NativeSessionSnapshot:
        """Fail closed when an opaque prepared-context reference is no longer trusted."""
        with self._lock:
            session = self._session(session_id)
            context_id = session.prepared_context_id
            if session.data_substep != "PREPARED" or not context_id:
                return session.snapshot()
            try:
                trusted = context_is_trusted(context_id)
            except Exception:
                trusted = False
            if trusted:
                return session.snapshot()
            session.prepared_context_id = None
            session.data_substep = (
                "ROLES"
                if session.inspected_dataset is not None and session.preparation_draft is not None
                else "FILE"
            )
            return session.snapshot()

    def mark_meaningful_temporary_work(self, session_id: str) -> NativeSessionSnapshot:
        """Record temporary workflow progress for future native use cases."""
        with self._lock:
            session = self._session(session_id)
            session.analysis_active = True
            session.has_meaningful_temporary_work = True
            return session.snapshot()

    def start_dataset_inspection(self, session_id: str) -> str:
        """Start a new transient progress lifecycle and return its ownership token."""
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                raise NativeSessionTransitionError()
            token = token_urlsafe(24)
            now = _now()
            session.inspection_token = token
            session.inspection_upload = None
            session.analysis_active = True
            session.has_meaningful_temporary_work = True
            session.inspection_progress = DatasetInspectionProgress(
                status=DatasetInspectionStatus.RUNNING,
                stage=DatasetInspectionStage.RECEIVING_FILE,
                stage_label=DATASET_INSPECTION_STAGE_LABELS[DatasetInspectionStage.RECEIVING_FILE],
                started_at=now,
                updated_at=now,
            )
            return token

    def set_inspection_upload(self, session_id: str, token: str, staged_upload: Any) -> bool:
        """Attach the temporary file to its active inspection for reset cleanup."""
        with self._lock:
            session = self._session(session_id)
            if session.inspection_token != token:
                return False
            session.inspection_upload = staged_upload
            return True

    def update_dataset_inspection_progress(
        self, session_id: str, token: str, stage: DatasetInspectionStage | str
    ) -> bool:
        """Record one real stage, ignoring work superseded by reset or a new upload."""
        parsed_stage = DatasetInspectionStage(stage)
        with self._lock:
            session = self._session(session_id)
            progress = session.inspection_progress
            if session.inspection_token != token or progress is None:
                return False
            now = _now()
            session.inspection_progress = DatasetInspectionProgress(
                status=DatasetInspectionStatus.RUNNING,
                stage=parsed_stage,
                stage_label=DATASET_INSPECTION_STAGE_LABELS[parsed_stage],
                started_at=progress.started_at,
                updated_at=now,
            )
            return True

    def finish_dataset_inspection(self, session_id: str, token: str) -> bool:
        with self._lock:
            session = self._session(session_id)
            progress = session.inspection_progress
            if session.inspection_token != token or progress is None:
                return False
            session.inspection_progress = DatasetInspectionProgress(
                status=DatasetInspectionStatus.READY,
                stage=DatasetInspectionStage.READY,
                stage_label=DATASET_INSPECTION_STAGE_LABELS[DatasetInspectionStage.READY],
                started_at=progress.started_at,
                updated_at=_now(),
            )
            session.inspection_upload = None
            return True

    def fail_dataset_inspection(self, session_id: str, token: str) -> bool:
        """Expose only a stable message; exception text and paths remain private."""
        with self._lock:
            session = self._session(session_id)
            progress = session.inspection_progress
            if session.inspection_token != token or progress is None:
                return False
            session.inspection_progress = DatasetInspectionProgress(
                status=DatasetInspectionStatus.ERROR,
                stage=DatasetInspectionStage.ERROR,
                stage_label=DATASET_INSPECTION_STAGE_LABELS[DatasetInspectionStage.ERROR],
                started_at=progress.started_at,
                updated_at=_now(),
                message="Не удалось обработать загруженный файл.",
            )
            session.inspection_upload = None
            session.has_meaningful_temporary_work = (
                session.inspected_dataset is not None and session.preparation_draft is not None
            )
            return True

    def dataset_inspection_progress(self, session_id: str) -> DatasetInspectionProgress:
        with self._lock:
            progress = self._session(session_id).inspection_progress
            if progress is not None:
                return progress
            return DatasetInspectionProgress(
                status=DatasetInspectionStatus.IDLE,
                stage=None,
                stage_label=None,
                started_at=None,
                updated_at=None,
            )

    def set_dataset(
        self,
        session_id: str,
        *,
        staged_upload: Any,
        inspected_dataset: InspectedDataset,
        preparation_draft: PreparationDraft,
        inspection_token: str | None = None,
    ) -> tuple[Any | None, str]:
        """Attach session-owned pre-confirmation data and return a replacement."""
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                raise NativeSessionTransitionError()
            if inspection_token is not None and session.inspection_token != inspection_token:
                raise KeyError("Dataset inspection was superseded before completion.")
            previous = session.staged_upload
            session.staged_upload = staged_upload
            session.inspected_dataset = inspected_dataset
            session.preparation_draft = preparation_draft
            session.source_handle = token_urlsafe(24)
            session.prepared_context_id = None
            session.inspection_upload = None
            session.analysis_active = True
            session.data_substep = "ROLES"
            session.has_meaningful_temporary_work = True
            return previous, session.source_handle

    def dataset_state(self, session_id: str) -> tuple[InspectedDataset, PreparationDraft, str]:
        with self._lock:
            session = self._session(session_id)
            if session.inspected_dataset is None or session.preparation_draft is None:
                raise KeyError("No staged dataset for this native analysis session.")
            if session.source_handle is None:  # pragma: no cover - store invariant
                raise KeyError("Missing opaque source handle.")
            return session.inspected_dataset, session.preparation_draft, session.source_handle

    def set_preparation_draft(
        self, session_id: str, draft: PreparationDraft, *, preserve_substep: bool = False
    ) -> NativeSessionSnapshot:
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                raise NativeSessionTransitionError()
            expected_substep = "CONFIRMATION" if preserve_substep else "ROLES"
            if session.data_substep != expected_substep:
                raise NativeSessionTransitionError()
            if session.inspected_dataset is None:
                raise KeyError("No staged dataset for this native analysis session.")
            session.preparation_draft = draft
            session.analysis_active = True
            if not preserve_substep:
                session.data_substep = "ROLES"
            session.has_meaningful_temporary_work = True
            return session.snapshot()

    def require_roles(self, session_id: str) -> None:
        """Validate that editable draft operations are still on the roles step."""
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                raise NativeSessionTransitionError()
            if session.data_substep != "ROLES":
                raise NativeSessionTransitionError()
            if session.inspected_dataset is None or session.preparation_draft is None:
                raise KeyError("No staged dataset for this native analysis session.")

    def begin_confirmation(self, session_id: str) -> NativeSessionSnapshot:
        """Move to the review step without turning a draft into accepted truth."""
        with self._lock:
            session = self._session(session_id)
            if session.data_substep != "ROLES":
                raise NativeSessionTransitionError()
            if session.inspected_dataset is None or session.preparation_draft is None:
                raise KeyError("No staged dataset for this native analysis session.")
            session.analysis_active = True
            session.data_substep = "CONFIRMATION"
            session.has_meaningful_temporary_work = True
            return session.snapshot()

    def return_to_roles(self, session_id: str) -> NativeSessionSnapshot:
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                raise NativeSessionTransitionError()
            if session.data_substep != "CONFIRMATION":
                raise NativeSessionTransitionError()
            if session.inspected_dataset is None or session.preparation_draft is None:
                raise KeyError("No staged dataset for this native analysis session.")
            session.data_substep = "ROLES"
            return session.snapshot()

    def begin_confirmation_materialization(
        self, session_id: str
    ) -> tuple[str, InspectedDataset, PreparationDraft]:
        """Reserve this session's confirmation while materialization runs unlocked."""
        with self._lock:
            session = self._session(session_id)
            if (
                session.data_substep != "CONFIRMATION"
                or session.confirmation_operation_token is not None
            ):
                raise NativeSessionTransitionError()
            if session.inspected_dataset is None or session.preparation_draft is None:
                raise KeyError("No staged dataset for this native analysis session.")
            operation_token = token_urlsafe(24)
            session.confirmation_operation_token = operation_token
            return operation_token, session.inspected_dataset, session.preparation_draft

    def complete_confirmation_materialization(
        self,
        session_id: str,
        operation_token: str,
        *,
        acknowledged_draft: PreparationDraft,
        context_id: str,
    ) -> NativeSessionSnapshot:
        """Atomically publish the accepted draft and finish CONFIRMATION → PREPARED."""
        with self._lock:
            session = self._session(session_id)
            if (
                not operation_token
                or session.confirmation_operation_token != operation_token
                or session.data_substep != "CONFIRMATION"
                or session.inspected_dataset is None
                or session.preparation_draft is None
                or not context_id
            ):
                raise NativeSessionTransitionError()
            session.preparation_draft = acknowledged_draft
            session.prepared_context_id = context_id
            session.data_substep = "PREPARED"
            session.analysis_active = True
            session.has_meaningful_temporary_work = True
            session.confirmation_operation_token = None
            return session.snapshot()

    def abort_confirmation_materialization(
        self, session_id: str, operation_token: str
    ) -> bool:
        """Release a failed operation without changing its confirmation draft/state."""
        with self._lock:
            session = self._session(session_id)
            if (
                not operation_token
                or session.confirmation_operation_token != operation_token
            ):
                return False
            session.confirmation_operation_token = None
            return True

    def set_prepared_context(
        self, session_id: str, context_id: str
    ) -> NativeSessionSnapshot:
        """Keep only an opaque trusted-context identity in the browser session."""
        if not context_id:
            raise ValueError("Missing prepared context identity.")
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                raise NativeSessionTransitionError()
            if session.inspected_dataset is None or session.preparation_draft is None:
                raise KeyError("No staged dataset for this native analysis session.")
            if session.data_substep != "CONFIRMATION":
                raise ValueError("Confirmation step is not active.")
            session.prepared_context_id = context_id
            session.analysis_active = True
            session.data_substep = "PREPARED"
            session.has_meaningful_temporary_work = True
            return session.snapshot()

    def start_new_analysis(
        self, session_id: str, *, confirm_reset: bool = False
    ) -> NewAnalysisResult:
        """Start clean or request confirmation before discarding transient work."""
        with self._lock:
            session = self._session(session_id)
            if session.confirmation_operation_token is not None:
                if confirm_reset:
                    raise NativeSessionTransitionError()
            if session.has_meaningful_temporary_work and not confirm_reset:
                return NewAnalysisResult(
                    status=NewAnalysisStatus.CONFIRMATION_REQUIRED,
                    session=session.snapshot(),
                )

            discarded_uploads = (session.staged_upload, session.inspection_upload)
            session.current_step = 0
            session.analysis_active = True
            session.has_meaningful_temporary_work = False
            session.staged_upload = None
            session.inspection_upload = None
            session.inspected_dataset = None
            session.preparation_draft = None
            session.source_handle = None
            session.prepared_context_id = None
            session.confirmation_operation_token = None
            session.data_substep = "FILE"
            session.inspection_progress = None
            session.inspection_token = None
            return NewAnalysisResult(
                status=NewAnalysisStatus.STARTED,
                session=session.snapshot(),
                discarded_upload=discarded_uploads,
            )

    def _session(self, session_id: str) -> _NativeAnalysisSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError("Unknown native analysis session.") from exc


def _now() -> datetime:
    return datetime.now(UTC)
