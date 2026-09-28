"""Thin FastAPI adapter for native AXION session use cases."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Cookie, FastAPI, Response
from pydantic import BaseModel, ConfigDict

from komus_risk.application import NativeSessionSnapshot, NativeSessionStore

SESSION_COOKIE_NAME = "axion_session"


class SessionResponse(BaseModel):
    current_step: int
    has_meaningful_temporary_work: bool


class NewAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_reset: bool = False


class NewAnalysisResponse(SessionResponse):
    status: Literal["STARTED", "CONFIRMATION_REQUIRED"]


class HealthResponse(BaseModel):
    status: Literal["ok"]


def _session_response(snapshot: NativeSessionSnapshot) -> SessionResponse:
    return SessionResponse(
        current_step=snapshot.current_step,
        has_meaningful_temporary_work=snapshot.has_meaningful_temporary_work,
    )


def create_app(*, session_store: NativeSessionStore | None = None) -> FastAPI:
    """Create the native HTTP adapter without constructing ML or Streamlit runtime."""
    store = session_store or NativeSessionStore()
    api = FastAPI(title="AXION Native API", version="0.0.1")

    def resolve_session(
        response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None
    ) -> tuple[str, NativeSessionSnapshot]:
        resolved_session_id, snapshot = store.get_or_create(session_id)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=resolved_session_id,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return resolved_session_id, snapshot

    @api.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @api.get("/api/v1/session", response_model=SessionResponse)
    def get_session(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SessionResponse:
        _, snapshot = resolve_session(response, session_id)
        return _session_response(snapshot)

    @api.post("/api/v1/analysis/new", response_model=NewAnalysisResponse)
    def new_analysis(
        request: NewAnalysisRequest,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> NewAnalysisResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        result = store.start_new_analysis(
            resolved_session_id, confirm_reset=request.confirm_reset
        )
        return NewAnalysisResponse(
            status=result.status,
            **_session_response(result.session).model_dump(),
        )

    return api


app = create_app()
