"""Thin FastAPI adapter for native AXION session use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Cookie, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from komus_risk.application import (
    DatasetDraftError,
    NativeDatasetOnboardingService,
    NativeSessionSnapshot,
    NativeSessionStore,
)
from komus_risk.preparation import DatasetPreparationError, PreparedDatasetContextAuthority
from komus_risk.application.native_session import (
    DatasetInspectionProgress,
    DatasetInspectionStage,
    NativeSessionTransitionError,
)
from app.upload_staging import cleanup_staged_upload, stage_upload_bytes

SESSION_COOKIE_NAME = "axion_session"
ASSETS_DIRECTORY = Path(__file__).resolve().parent.parent / "assets"

_NATIVE_INSPECTION_STAGES = {
    "reading_source": DatasetInspectionStage.READING_SOURCE,
    "inspecting_dataset": DatasetInspectionStage.INSPECTING_DATASET,
    "analyzing_preparation": DatasetInspectionStage.ANALYZING_PREPARATION,
}


class SessionResponse(BaseModel):
    current_step: int
    analysis_active: bool
    data_substep: Literal["FILE", "ROLES", "CONFIRMATION", "PREPARED"]
    has_meaningful_temporary_work: bool
    resume_route: str


class NewAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_reset: bool = False


class NewAnalysisResponse(SessionResponse):
    status: Literal["STARTED", "CONFIRMATION_REQUIRED"]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class DatasetSourceResponse(BaseModel):
    handle: str
    display_name: str
    format: str
    size: int
    rows: int
    columns: int


class PreparationDraftResponse(BaseModel):
    target: str | None
    positive_class: Any | None
    identifier: str | None


class PreparationOptionsResponse(BaseModel):
    columns: list[str]
    positive_classes: list[Any]


class PreparationSummaryResponse(BaseModel):
    permission_counts: dict[str, int]
    warnings: list[str]
    actions: list[str]
    population_policy: str
    population_policy_acknowledged: bool


class DatasetPreparationResponse(BaseModel):
    source: DatasetSourceResponse
    draft: PreparationDraftResponse
    options: PreparationOptionsResponse
    summary: PreparationSummaryResponse


class DatasetInspectionProgressResponse(BaseModel):
    """Read-only, deliberately non-diagnostic progress DTO."""

    status: Literal["IDLE", "RUNNING", "READY", "ERROR"]
    stage: str | None
    stage_label: str | None
    started_at: str | None
    updated_at: str | None
    message: str | None = None


class PreparationDraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str | None = None
    positive_class: Any | None = None
    identifier: str | None = None


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    population_policy_acknowledged: bool = False


def _session_response(snapshot: NativeSessionSnapshot) -> SessionResponse:
    return SessionResponse(
        current_step=snapshot.current_step,
        analysis_active=snapshot.analysis_active,
        data_substep=snapshot.data_substep,
        has_meaningful_temporary_work=snapshot.has_meaningful_temporary_work,
        resume_route=snapshot.resume_route,
    )


def _progress_response(progress: DatasetInspectionProgress) -> DatasetInspectionProgressResponse:
    return DatasetInspectionProgressResponse(
        status=progress.status.value,
        stage=progress.stage.value if progress.stage is not None else None,
        stage_label=progress.stage_label,
        started_at=progress.started_at.isoformat() if progress.started_at is not None else None,
        updated_at=progress.updated_at.isoformat() if progress.updated_at is not None else None,
        message=progress.message,
    )


def create_app(*, session_store: NativeSessionStore | None = None) -> FastAPI:
    """Create the native HTTP adapter without constructing ML or Streamlit runtime."""
    store = session_store or NativeSessionStore()
    onboarding = NativeDatasetOnboardingService()
    context_authority = PreparedDatasetContextAuthority()
    api = FastAPI(title="AXION Native API", version="0.0.1")
    api.mount("/native-assets", StaticFiles(directory=ASSETS_DIRECTORY), name="native-assets")

    def resolve_session(
        response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None
    ) -> tuple[str, NativeSessionSnapshot]:
        resolved_session_id, snapshot = store.get_or_create(session_id)
        snapshot = store.reconcile_prepared_context(
            resolved_session_id,
            lambda context_id: context_authority.resolve(context_id) is not None,
        )
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
        try:
            result = store.start_new_analysis(
                resolved_session_id, confirm_reset=request.confirm_reset
            )
        except NativeSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": "Недопустимый переход этапа подготовки данных."}) from None
        if result.discarded_upload is not None:
            for discarded_upload in result.discarded_upload:
                cleanup_staged_upload(discarded_upload)
        return NewAnalysisResponse(
            status=result.status,
            **_session_response(result.session).model_dump(),
        )

    def preparation_response(session_id: str) -> DatasetPreparationResponse:
        try:
            dataset, draft, handle = store.dataset_state(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "DATASET_NOT_UPLOADED", "message": "Сначала загрузите файл датасета."},
            ) from exc
        return DatasetPreparationResponse(
            source=DatasetSourceResponse(
                handle=handle,
                display_name=dataset.display_name,
                format=dataset.source_format,
                size=dataset.size,
                rows=dataset.snapshot.row_count,
                columns=dataset.snapshot.column_count,
            ),
            draft=PreparationDraftResponse(
                target=draft.target_column,
                positive_class=draft.positive_class,
                identifier=draft.identifier_column,
            ),
            options=PreparationOptionsResponse(
                columns=list(dataset.snapshot.physical_headers),
                positive_classes=list(onboarding.positive_class_choices(dataset, draft.target_column)),
            ),
            summary=PreparationSummaryResponse(
                permission_counts=onboarding.permission_counts(dataset, draft),
                warnings=[
                    reason
                    for warning in dataset.proposal.warnings
                    for reason in warning.reasons_ru
                ],
                actions=["Проверьте автоматически заполненные роли колонок перед подтверждением."],
                population_policy=draft.population_policy,
                population_policy_acknowledged=draft.population_policy_acknowledged,
            ),
        )

    @api.post("/api/v1/dataset/upload", response_model=DatasetPreparationResponse)
    async def upload_dataset(
        response: Response,
        file: Annotated[UploadFile, File(...)],
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> DatasetPreparationResponse | JSONResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            inspection_token = store.start_dataset_inspection(resolved_session_id)
        except NativeSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": "Недопустимый переход этапа подготовки данных."}) from None
        staged = None
        try:
            upload_bytes = await file.read()
            store.update_dataset_inspection_progress(
                resolved_session_id, inspection_token, "STAGING_FILE"
            )
            staged = await run_in_threadpool(
                stage_upload_bytes, file.filename or "dataset", upload_bytes
            )
            if not store.set_inspection_upload(resolved_session_id, inspection_token, staged):
                cleanup_staged_upload(staged)
                raise RuntimeError("Dataset inspection was superseded before staging completed.")
            dataset = await run_in_threadpool(
                onboarding.inspect,
                staged.local_path,
                display_name=staged.display_name,
                size=staged.local_path.stat().st_size,
                progress_listener=lambda stage: store.update_dataset_inspection_progress(
                    resolved_session_id,
                    inspection_token,
                    _NATIVE_INSPECTION_STAGES[stage],
                ),
            )
            draft = onboarding.default_draft(dataset)
            previous, _ = store.set_dataset(
                resolved_session_id,
                staged_upload=staged,
                inspected_dataset=dataset,
                preparation_draft=draft,
                inspection_token=inspection_token,
            )
            cleanup_staged_upload(previous)
            store.finish_dataset_inspection(resolved_session_id, inspection_token)
        except Exception as exc:
            cleanup_staged_upload(staged)
            store.fail_dataset_inspection(resolved_session_id, inspection_token)
            code = getattr(exc, "code", "INVALID_DATASET")
            error_response = JSONResponse(
                status_code=422,
                content={"detail": {"code": code, "message": "Не удалось обработать загруженный файл."}},
            )
            error_response.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=resolved_session_id,
                httponly=True,
                samesite="lax",
                path="/",
            )
            return error_response
        return preparation_response(resolved_session_id)

    @api.get("/api/v1/dataset/progress", response_model=DatasetInspectionProgressResponse)
    def get_dataset_progress(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> DatasetInspectionProgressResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        return _progress_response(store.dataset_inspection_progress(resolved_session_id))

    @api.get("/api/v1/dataset/preparation", response_model=DatasetPreparationResponse)
    def get_dataset_preparation(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> DatasetPreparationResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        return preparation_response(resolved_session_id)

    @api.patch("/api/v1/dataset/preparation/draft", response_model=DatasetPreparationResponse)
    def patch_dataset_preparation_draft(
        request: PreparationDraftPatch,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> DatasetPreparationResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            store.require_roles(resolved_session_id)
            dataset, current, _ = store.dataset_state(resolved_session_id)
            changes: dict[str, Any] = {}
            if "target" in request.model_fields_set:
                changes["target_column"] = request.target
            if "identifier" in request.model_fields_set:
                changes["identifier_column"] = request.identifier
            if "positive_class" in request.model_fields_set:
                changes["positive_class"] = request.positive_class
            draft = onboarding.update_draft(dataset, current, **changes)
            store.set_preparation_draft(resolved_session_id, draft)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "DATASET_NOT_UPLOADED", "message": "Сначала загрузите файл датасета."}) from exc
        except NativeSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": "Недопустимый переход этапа подготовки данных."}) from None
        except DatasetDraftError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": "Проверьте выбранные роли колонок."}) from exc
        return preparation_response(resolved_session_id)

    @api.post("/api/v1/dataset/preparation/review", response_model=SessionResponse)
    def review_dataset_preparation(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SessionResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            return _session_response(store.begin_confirmation(resolved_session_id))
        except NativeSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": "Недопустимый переход этапа подготовки данных."}) from None
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "DATASET_NOT_UPLOADED", "message": "Сначала загрузите файл датасета."}) from exc

    @api.post("/api/v1/dataset/preparation/roles", response_model=SessionResponse)
    def return_to_dataset_roles(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SessionResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            return _session_response(store.return_to_roles(resolved_session_id))
        except NativeSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": "Недопустимый переход этапа подготовки данных."}) from None
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "DATASET_NOT_UPLOADED", "message": "Сначала загрузите файл датасета."}) from exc

    @api.post("/api/v1/dataset/preparation/confirm", response_model=SessionResponse)
    def confirm_dataset_preparation(
        request: ConfirmationRequest,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SessionResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        operation_token: str | None = None
        try:
            operation_token, dataset, draft = store.begin_confirmation_materialization(
                resolved_session_id
            )
            draft = onboarding.acknowledge_population_policy(
                draft, request.population_policy_acknowledged
            )
            context, _, _ = onboarding.materialize_confirmation(
                dataset, draft, context_authority=context_authority
            )
            snapshot = store.complete_confirmation_materialization(
                resolved_session_id,
                operation_token,
                acknowledged_draft=draft,
                context_id=context.context_id,
            )
            operation_token = None
            return _session_response(snapshot)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "DATASET_NOT_UPLOADED", "message": "Сначала загрузите файл датасета."}) from exc
        except NativeSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": "Недопустимый переход этапа подготовки данных."}) from None
        except (DatasetDraftError, DatasetPreparationError, ValueError) as exc:
            code = getattr(exc, "code", "INVALID_CONFIRMATION")
            raise HTTPException(status_code=422, detail={"code": code, "message": "Не удалось подтвердить подготовку данных. Проверьте выбранные роли и подтверждение политики."}) from exc
        except Exception:
            raise HTTPException(status_code=500, detail={"code": "PREPARATION_FAILED", "message": "Не удалось завершить подготовку данных."}) from None
        finally:
            if operation_token is not None:
                store.abort_confirmation_materialization(
                    resolved_session_id, operation_token
                )

    return api


app = create_app()
