"""Framework-neutral transient state for the native AXION analysis flow.

This module owns only process-local, temporary workflow state.  Persisted
ExperimentArtifact and ModelVersion records remain outside this session layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from secrets import token_urlsafe


class NewAnalysisStatus(StrEnum):
    """Outcome of the explicit new-analysis transition."""

    STARTED = "STARTED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class NativeSessionSnapshot:
    """The native frontend's read model for one analysis session."""

    current_step: int
    has_meaningful_temporary_work: bool


@dataclass(frozen=True, slots=True)
class NewAnalysisResult:
    """Typed result returned by the new-analysis use case."""

    status: NewAnalysisStatus
    session: NativeSessionSnapshot


@dataclass(slots=True)
class _NativeAnalysisSession:
    current_step: int = 0
    has_meaningful_temporary_work: bool = False

    def snapshot(self) -> NativeSessionSnapshot:
        return NativeSessionSnapshot(
            current_step=self.current_step,
            has_meaningful_temporary_work=self.has_meaningful_temporary_work,
        )


class NativeSessionStore:
    """Process-local store for opaque native analysis sessions.

    The store deliberately has no dependency on HTTP, Streamlit, databases, or
    persisted application artifacts.  A later persistence layer can be composed
    beside it without making a browser session authoritative scientific state.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _NativeAnalysisSession] = {}

    def get_or_create(
        self, session_id: str | None
    ) -> tuple[str, NativeSessionSnapshot]:
        if session_id is not None and session_id in self._sessions:
            return session_id, self._sessions[session_id].snapshot()

        new_session_id = token_urlsafe(32)
        self._sessions[new_session_id] = _NativeAnalysisSession()
        return new_session_id, self._sessions[new_session_id].snapshot()

    def snapshot(self, session_id: str) -> NativeSessionSnapshot:
        return self._session(session_id).snapshot()

    def mark_meaningful_temporary_work(self, session_id: str) -> NativeSessionSnapshot:
        """Record temporary workflow progress for future native use cases."""
        session = self._session(session_id)
        session.has_meaningful_temporary_work = True
        return session.snapshot()

    def start_new_analysis(
        self, session_id: str, *, confirm_reset: bool = False
    ) -> NewAnalysisResult:
        """Start clean or request confirmation before discarding transient work."""
        session = self._session(session_id)
        if session.has_meaningful_temporary_work and not confirm_reset:
            return NewAnalysisResult(
                status=NewAnalysisStatus.CONFIRMATION_REQUIRED,
                session=session.snapshot(),
            )

        session.current_step = 0
        session.has_meaningful_temporary_work = False
        return NewAnalysisResult(
            status=NewAnalysisStatus.STARTED,
            session=session.snapshot(),
        )

    def _session(self, session_id: str) -> _NativeAnalysisSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError("Unknown native analysis session.") from exc
