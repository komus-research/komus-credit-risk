"""Thin FastAPI adapter for native AXION session use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Cookie, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from komus_risk.application import (
    DatasetDraftError,
    FeatureSelectionError,
    FeatureSelectionService,
    NativeDatasetOnboardingService,
    NativeSessionSnapshot,
    NativeSessionStore,
    NativeQualityService,
    ModelSaveBindingConflict,
    ModelSaveContextNotReady,
    ModelDecisionThresholdBindingMismatch,
    ModelSaveError,
    InvalidModelDisplayName,
    InvalidModelLibraryQuery,
    ModelLibraryError,
    ModelSourceResultUnavailable,
    ModelVersionIntegrityError,
    ModelVersionNotFound,
    InferenceInputError,
    InferencePreparationError,
    SavedModelInferenceError,
    SavedInferenceExplanationService,
    SavedInferenceInterpretationUnavailable,
    AnalystReportError,
)
from komus_risk.application.oof_result import OOFResultError
from komus_risk.application.oof_explanation import OOFExplanationError
from komus_risk.application.dataset_onboarding import (
    preparation_warning_counts,
    project_preparation_warnings,
)
from komus_risk.preparation import DatasetPreparationError
from komus_risk.application.native_session import (
    DatasetInspectionProgress,
    DatasetInspectionStage,
    NativeSessionTransitionError,
    ResultThresholdState,
)
from komus_risk.planning import ExperimentPlanningService
from komus_risk.data import TabularReadError, TabularReader
from app.upload_staging import (
    EmptyUploadError,
    UnsupportedUploadExtension,
    UploadReadError,
    cleanup_staged_upload,
    stage_upload_bytes,
)
from app.native_runtime import create_native_experiment_runtime

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


class PreparationWarningResponse(BaseModel):
    code: str
    severity: Literal["WARNING", "INFO"]
    scope: Literal["COLUMN", "DATASET"]
    column_name: str | None
    detected_reasons: list[str]
    detected_requires_confirmation: bool
    resolution_state: Literal["ACTION_REQUIRED", "RESOLVED", "INFO"]
    resolution_code: str
    subject_ru: str
    title_ru: str
    detail_ru: str
    check_ru: str | None
    resolution_note_ru: str | None
    action: Literal[
        "REVIEW_COLUMN",
        "REVIEW_TARGET",
        "REVIEW_IDENTIFIER",
        "REVIEW_DATASET",
    ] | None


class PreparationSummaryResponse(BaseModel):
    permission_counts: dict[str, int]
    warnings: list[PreparationWarningResponse]
    warning_counts: dict[Literal["action_required", "resolved", "info"], int]
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


class FeatureDatasetResponse(BaseModel):
    display_name: str
    row_count: int
    column_count: int
    source_type: str
    source_format: str


class FeatureGroupResponse(BaseModel):
    group_id: str
    name_ru: str
    description_ru: str
    display_order: int


class FeatureRowResponse(BaseModel):
    feature_id: str
    display_name_ru: str
    description_ru: str
    column_name: str
    group_id: str
    display_order: int


class FeaturesResponse(BaseModel):
    dataset: FeatureDatasetResponse
    available_count: int
    selected_feature_ids: list[str]
    selected_count: int
    groups: list[FeatureGroupResponse]
    features: list[FeatureRowResponse]


class FeatureSelectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_feature_ids: list[str]


class ModelSelectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str


class AlgorithmConfigurationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration_mode: Literal["RECOMMENDED", "ADVANCED"]
    user_overrides: dict[str, Any] = Field(default_factory=dict)


class QualitySettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folds: int | None = None
    seed: int | None = None


class ResultSummaryResponse(BaseModel):
    artifact_id: str
    result_id: str
    model_id: str
    model_version: str
    object_count: int
    feature_count: int
    folds: int
    evaluation_level: str
    runtime_seconds: float | None
    gini: float
    roc_auc: float
    pr_auc: float
    fold_metrics: list[dict[str, Any]]
    limitations: list[str]


class ResultCapturePointResponse(BaseModel):
    object_share: float
    event_share: float


class ResultCaptureResponse(BaseModel):
    total_positive_events: int
    points: list[ResultCapturePointResponse]
    marker: ResultCapturePointResponse | None


class ResultThresholdResponse(BaseModel):
    threshold: float
    tp: int
    tn: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    above_threshold_count: int
    above_threshold_share: float


class SavedModelResponse(BaseModel):
    model_version_id: str
    display_name: str
    display_version: str
    saved_at: str
    decision_threshold: float | None
    decision_threshold_state: Literal["USER_APPLIED", "NOT_SET"]


class ModelVersionSaveResponse(SavedModelResponse):
    save_state: Literal["CREATED", "ALREADY_SAVED"]
    artifact_id: str


class ModelVersionListItemResponse(BaseModel):
    model_version_id: str
    experiment_artifact_id: str
    display_name: str
    display_version: str
    saved_at: str
    model_id: str
    model_display_name: str
    algorithm_version: str
    dataset_id: str
    dataset_name: str
    feature_count: int
    oof_gini: float
    oof_roc_auc: float
    oof_pr_auc: float


class ModelVersionListResponse(BaseModel):
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    returned_count: int
    items: list[ModelVersionListItemResponse]


class ModelVersionDetailResponse(BaseModel):
    model_version_id: str
    experiment_artifact_id: str
    display_name: str
    display_version: str
    saved_at: str
    status: Literal["SAVED"]
    decision_threshold: float | None = None
    decision_threshold_state: Literal["USER_APPLIED", "NOT_SET"] = "NOT_SET"
    algorithm: dict[str, Any]
    dataset: dict[str, Any]
    population: dict[str, Any]
    target: str
    positive_class: Any
    identifier: str
    features: list[dict[str, Any]]
    configuration: dict[str, Any]
    oof_quality: dict[str, float]
    source_result: dict[str, str]
    technical_provenance: dict[str, Any]


class ModelVersionRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: Any


class ModelVersionRenameResponse(BaseModel):
    model_version_id: str
    display_name: str


class SavedModelInferencePreflightResponse(BaseModel):
    preparation_id: str
    model_version_id: str
    experiment_artifact_id: str
    model_display_name: str
    display_name: str
    display_version: str
    training_dataset_name: str
    source_display_name: str
    source_format: str
    source_file_sha256: str
    source_fingerprint: str
    row_count: int
    column_count: int
    identifier_column: str
    required_feature_count: int
    required_feature_columns: list[str]
    ignored_column_count: int
    ignored_columns: list[str]
    status: Literal["COMPATIBLE"]
    checks: dict[str, Literal["PASS"]]


class SavedModelInferenceRunResponse(BaseModel):
    run_state: Literal["CREATED", "REUSED"]
    inference_result_id: str
    model_version_id: str
    source_display_name: str
    created_at: str


class InferenceScoreHistogramBinResponse(BaseModel):
    lower_bound: float
    upper_bound: float
    count: int


class SavedModelInferenceSummaryResponse(BaseModel):
    inference_result_id: str
    model_version_id: str
    experiment_artifact_id: str
    display_name: str
    display_version: str
    model_display_name: str
    source_display_name: str
    source_format: str
    source_file_sha256: str
    source_fingerprint: str
    created_at: str
    status: Literal["COMPLETED"]
    row_count: int
    column_count: int
    identifier_column: str
    required_feature_count: int
    ignored_column_count: int
    score_min: float
    score_max: float
    threshold: float
    above_threshold_count: int
    above_threshold_share: float
    below_threshold_count: int
    below_threshold_share: float
    histogram: list[InferenceScoreHistogramBinResponse]


class SavedModelInferenceObjectItemResponse(BaseModel):
    row_id: str
    source_row_position: int
    identifier_display: str
    score: float
    above_threshold: bool


class SavedModelInferenceObjectListResponse(BaseModel):
    inference_result_id: str
    threshold: float
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    returned_count: int
    items: list[SavedModelInferenceObjectItemResponse]


class SavedInferenceObjectFeatureResponse(BaseModel):
    feature_id: str
    column_name: str
    display_name_ru: str | None
    description_ru: str | None
    raw_value: float


class CapabilityResponse(BaseModel):
    state: Literal["AVAILABLE", "WAITING_FOR_INPUT", "UNSUPPORTED", "DISABLED", "MISCONFIGURED"]
    reason_code: str


class SavedInferenceObjectDetailResponse(BaseModel):
    inference_result_id: str
    model_version_id: str
    row_id: str
    source_row_position: int
    identifier_column: str
    identifier_display: str
    score: float
    threshold: float
    position: Literal["ABOVE", "BELOW"]
    features: list[SavedInferenceObjectFeatureResponse]
    capabilities: dict[str, CapabilityResponse]


class SavedInferenceExplanationFeatureResponse(BaseModel):
    feature_id: str
    column_name: str
    display_name_ru: str | None
    description_ru: str | None
    raw_value: float
    shap_value: float
    rank: int
    direction: Literal["increases_output", "decreases_output", "neutral"]


class SavedInferenceExplanationResponse(BaseModel):
    inference_result_id: str
    model_version_id: str
    row_id: str
    explanation_id: str
    evidence_hash: str
    prediction_probability: float
    base_value: float
    explained_output_value: float
    output_space: str
    explanation_method_id: str
    explanation_method_version: str
    explanation_provider_id: str
    explanation_provider_version: str
    features: list[SavedInferenceExplanationFeatureResponse]
    remainder: LocalExplanationRemainderResponse | None
    result_interpretation_capability: CapabilityResponse


class SavedInferenceInterpretationResponse(BaseModel):
    inference_result_id: str
    model_version_id: str
    row_id: str
    explanation_id: str
    evidence_hash: str
    role: str
    text: str
    created_at: str
    response_hash: str


class InferenceViewConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float
    min_score: float
    max_score: float
    position_filter: str
    sort: str
    search: str


class InferenceViewConfigurationResponse(BaseModel):
    inference_result_id: str
    threshold: float
    min_score: float
    max_score: float
    position_filter: Literal["ALL", "ABOVE", "BELOW"]
    sort: Literal["SCORE_DESC", "SCORE_ASC", "SOURCE_ASC"]
    search: str
    updated_at: str | None


class SavedInferenceViewResponse(BaseModel):
    saved: bool
    configuration: InferenceViewConfigurationResponse
    model_decision_threshold: float | None = None
    default_threshold: float = 0.50
    default_threshold_source: Literal["MODEL_DECISION", "TECHNICAL_DEFAULT"] = "TECHNICAL_DEFAULT"


class SavedInferenceReportDraftItemResponse(BaseModel):
    row_id: str
    source_row_position: int
    identifier_display: str
    score: float
    threshold: float
    position: Literal["ABOVE", "BELOW"]


class SavedInferenceReportDraftResponse(BaseModel):
    schema_version: Literal[1]
    inference_result_id: str
    selected_row_ids: list[str]
    created_at: str | None
    updated_at: str | None
    threshold: float
    items: list[SavedInferenceReportDraftItemResponse]


class AnalystReportGenerationResponse(BaseModel):
    report_id: str
    created_at: str
    generation_state: Literal["CREATED", "REUSED"]


class AnalystReportResponse(BaseModel):
    schema_version: Literal[1]
    report_id: str
    content_hash: str
    created_at: str
    source: dict[str, Any]
    decision_context: dict[str, Any]
    selection: dict[str, Any]
    companies: list[dict[str, Any]]


class ResultOverviewResponse(BaseModel):
    summary: ResultSummaryResponse
    threshold: ResultThresholdResponse
    capture: ResultCaptureResponse
    saved_model: SavedModelResponse | None = None


class ResultObjectItemResponse(BaseModel):
    object_id: str
    identifier_display: str
    y_true: int
    score: float
    predicted_positive: bool
    outcome: str


class ResultObjectListResponse(BaseModel):
    artifact_id: str
    threshold: float
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    returned_count: int
    items: list[ResultObjectItemResponse]


class ResultObjectDetailResponse(BaseModel):
    artifact_id: str
    object_id: str
    identifier_display: str
    y_true: int
    score: float
    threshold: float
    predicted_positive: bool
    outcome: str
    fold_number: int


class LocalExplanationFeatureResponse(BaseModel):
    feature_id: str
    column_name: str
    display_name_ru: str | None
    description_ru: str | None
    raw_value: float
    shap_value: float
    abs_rank: int
    direction: Literal["increases_output", "decreases_output", "neutral"]


class LocalExplanationRemainderResponse(BaseModel):
    feature_count: int
    shap_value: float
    direction: Literal["increases_output", "decreases_output", "neutral"]


class LocalExplanationResponse(BaseModel):
    evidence_version: str
    artifact_id: str
    object_id: str
    evidence_hash: str
    prediction_probability: float
    base_value: float
    explained_output_value: float
    output_space: str
    explanation_method_id: str
    explanation_method_version: str
    explanation_provider_id: str
    explanation_provider_version: str
    features: list[LocalExplanationFeatureResponse]
    remainder: LocalExplanationRemainderResponse | None


class GlobalOOFFeatureImportanceResponse(BaseModel):
    feature_id: str
    column_name: str
    mean_abs_shap: float
    rank: int


class GlobalOOFExplanationResponse(BaseModel):
    artifact_id: str
    model_id: str
    model_version: str
    dataset_name: str
    row_count: int
    feature_count: int
    folds: int
    output_space: str
    evidence_hash: str
    features: list[GlobalOOFFeatureImportanceResponse]


class GlobalOOFRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry: bool = False


class GlobalOOFOperationResponse(BaseModel):
    artifact_id: str
    derivation_key: str
    status: Literal["NOT_STARTED", "RUNNING", "READY", "FAILED"]
    stage: Literal["VALIDATING", "PROCESSING_FOLD", "AGGREGATING", "PERSISTING", "READY", "FAILED"]
    stage_label: str
    current_fold: int | None
    total_folds: int
    processed_rows: int
    total_rows: int
    started_at: str | None
    updated_at: str
    elapsed_seconds: float
    safe_error_code: str | None
    message: str | None


class ResultInterpretationResponse(BaseModel):
    artifact_id: str
    object_id: str
    role: str
    text: str
    created_at: str
    response_hash: str


class GlobalResultInterpretationResponse(BaseModel):
    artifact_id: str
    role: str
    text: str
    created_at: str
    response_hash: str


class ResultThresholdPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: Any


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


def create_app(*, session_store: NativeSessionStore | None = None, planning_service: ExperimentPlanningService | None = None, oof_result_service: Any | None = None, oof_explanation_service: Any | None = None, prepared_context_authority: Any | None = None, experiment_artifact_store: Any | None = None, integration_workflow_service: Any | None = None, model_library_service: Any | None = None, saved_model_inference_service: Any | None = None, saved_inference_explanation_service: SavedInferenceExplanationService | None = None, analyst_report_service: Any | None = None) -> FastAPI:
    """Compose native experiment dependencies once, then expose them through thin routes."""
    store = session_store or NativeSessionStore()
    onboarding = NativeDatasetOnboardingService()
    tabular_reader = TabularReader()
    runtime = create_native_experiment_runtime()
    result_service = oof_result_service or runtime.oof_result_service
    explanation_service = oof_explanation_service or runtime.oof_explanation_service
    workflow = (
        integration_workflow_service
        if integration_workflow_service is not None
        else runtime.integration_workflow_service
    )
    model_library = (
        model_library_service
        if model_library_service is not None
        else runtime.model_library_service
    )
    saved_inference = (
        saved_model_inference_service
        if saved_model_inference_service is not None
        else runtime.saved_model_inference_service
    )
    saved_explanation = (
        saved_inference_explanation_service
        if saved_inference_explanation_service is not None
        else runtime.saved_inference_explanation_service
    )
    analyst_reports = analyst_report_service if analyst_report_service is not None else runtime.analyst_report_service
    artifact_store = experiment_artifact_store or runtime.artifact_store
    context_authority = prepared_context_authority or runtime.prepared_context_authority
    feature_selection = FeatureSelectionService()
    planning = planning_service or runtime.planning_service
    quality = NativeQualityService(
        session_store=store,
        planning_service=planning,
        application_service=runtime.application_service,
        prepared_context_authority=context_authority,
        supported_protocol=runtime.supported_protocol,
    )
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

    @api.get("/api/v1/result", response_model=ResultOverviewResponse)
    def get_current_result(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ResultOverviewResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        if artifact_id is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        current_threshold = store.current_result_threshold(resolved_session_id)
        if current_threshold is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        try:
            summary = result_service.summary(artifact_id)
            threshold = result_service.threshold(artifact_id, current_threshold)
        except OOFResultError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "RESULT_READ_ERROR", "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        try:
            saved = model_library.find_for_experiment(artifact_id)
        except ModelSaveBindingConflict:
            raise HTTPException(
                status_code=409,
                detail={"code": "MODEL_SAVE_BINDING_CONFLICT", "message": "Сохранённая модель имеет конфликтующую привязку."},
            ) from None
        return ResultOverviewResponse(
            summary=ResultSummaryResponse(
                artifact_id=summary.artifact_id,
                result_id=summary.result_id,
                model_id=summary.model_id,
                model_version=summary.model_version,
                object_count=summary.object_count,
                feature_count=summary.feature_count,
                folds=summary.folds,
                evaluation_level=summary.evaluation_level,
                runtime_seconds=summary.runtime_seconds,
                gini=summary.gini,
                roc_auc=summary.roc_auc,
                pr_auc=summary.pr_auc,
                fold_metrics=[dict(item) for item in summary.fold_metrics],
                limitations=list(summary.limitations),
            ),
            threshold=ResultThresholdResponse(
                threshold=threshold.threshold,
                tp=threshold.tp,
                tn=threshold.tn,
                fp=threshold.fp,
                fn=threshold.fn,
                precision=threshold.precision,
                recall=threshold.recall,
                f1=threshold.f1,
                above_threshold_count=threshold.above_threshold_count,
                above_threshold_share=threshold.above_threshold_share,
            ),
            capture=ResultCaptureResponse(
                total_positive_events=summary.capture.total_positive_events,
                points=[
                    ResultCapturePointResponse(
                        object_share=point.object_share,
                        event_share=point.event_share,
                    )
                    for point in summary.capture.points
                ],
                marker=(
                    None
                    if summary.capture.marker is None
                    else ResultCapturePointResponse(
                        object_share=summary.capture.marker.object_share,
                        event_share=summary.capture.marker.event_share,
                    )
                ),
            ),
            saved_model=(
                None
                if saved is None
                else SavedModelResponse(
                    model_version_id=saved.model_version_id,
                    display_name=saved.display_name,
                    display_version=saved.display_version,
                    saved_at=saved.saved_at,
                    decision_threshold=saved.decision_threshold,
                    decision_threshold_state=saved.decision_threshold_state,
                )
            ),
        )

    @api.post("/api/v1/result/model-version", response_model=ModelVersionSaveResponse)
    async def save_current_result_model(
        request: Request,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ModelVersionSaveResponse:
        if await request.body():
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_MODEL_SAVE_REQUEST", "message": "Сохранение модели не принимает параметры."},
            )
        resolved_session_id, _ = resolve_session(response, session_id)
        binding = store.current_result_save_binding(resolved_session_id)
        if binding is None:
            raise HTTPException(status_code=409, detail={
                "code": "MODEL_SAVE_CONTEXT_NOT_READY",
                "message": "Контекст текущего результата недоступен для сохранения модели.",
            })
        if binding.threshold_state is not ResultThresholdState.USER_APPLIED:
            raise HTTPException(status_code=409, detail={
                "code": "MODEL_DECISION_THRESHOLD_REQUIRED",
                "message": "Сначала выберите и примените рабочий порог классификации.",
            })
        try:
            try:
                context = context_authority.resolve(binding.prepared_context_id)
            except Exception as error:
                raise ModelSaveContextNotReady() from error
            if store.current_result_save_binding(resolved_session_id) != binding:
                raise ModelDecisionThresholdBindingMismatch()
            saved = await run_in_threadpool(
                model_library.ensure_saved,
                experiment_artifact_id=binding.artifact_id,
                prepared_dataset_context=context,
                decision_threshold=binding.threshold,
            )
        except ModelSaveError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": error.code, "message": "Невозможно безопасно сохранить модель текущего результата."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "MODEL_SAVE_FAILED", "message": "Не удалось сохранить модель текущего результата."},
            ) from None
        record = saved.record
        return ModelVersionSaveResponse(
            save_state=saved.save_state,
            artifact_id=record.experiment_artifact_id,
            model_version_id=record.model_version_id,
            display_name=record.display_name,
            display_version=record.display_version,
            saved_at=record.saved_at,
            decision_threshold=record.decision_threshold,
            decision_threshold_state=record.decision_threshold_state,
        )

    def model_library_error(exc: ModelLibraryError) -> HTTPException:
        status = (
            422 if isinstance(exc, InvalidModelDisplayName)
            else 400 if isinstance(exc, InvalidModelLibraryQuery)
            else 404 if isinstance(exc, ModelVersionNotFound)
            else 409 if isinstance(exc, (ModelVersionIntegrityError, ModelSourceResultUnavailable))
            else 500
        )
        message = (
            "Название модели должно содержать от 1 до 160 символов в одной строке."
            if isinstance(exc, InvalidModelDisplayName)
            else "Model library request could not be completed."
        )
        return HTTPException(status_code=status, detail={"code": exc.code, "message": message})

    def saved_inference_error(exc: SavedModelInferenceError) -> HTTPException:
        status_by_code = {
            "INFERENCE_SOURCE_UNSUPPORTED_FORMAT": 415,
            "INFERENCE_SOURCE_UNREADABLE": 422,
            "INFERENCE_PHYSICAL_HEADERS_INVALID": 422,
            "INFERENCE_SOURCE_EMPTY": 422,
            "INFERENCE_IDENTIFIER_MISSING": 422,
            "INFERENCE_REQUIRED_FEATURE_MISSING": 422,
            "INFERENCE_DTYPE_INCOMPATIBLE": 422,
            "INFERENCE_VALUES_INVALID": 422,
            "INFERENCE_PREPARATION_STALE": 409,
            "INFERENCE_RUN_IN_PROGRESS": 409,
            "MODEL_VERSION_NOT_FOUND": 404,
            "MODEL_VERSION_INTEGRITY_ERROR": 409,
            "MODEL_SOURCE_RESULT_UNAVAILABLE": 409,
            "MODEL_INFERENCE_UNSUPPORTED": 409,
            "INFERENCE_FAILED": 500,
            "INFERENCE_RESULT_PERSISTENCE_FAILED": 500,
            "INFERENCE_RESULT_NOT_FOUND": 404,
            "INFERENCE_RESULT_INTEGRITY_ERROR": 409,
            "INFERENCE_OBJECT_NOT_FOUND": 404,
            "INFERENCE_LOCAL_EXPLANATION_UNSUPPORTED": 409,
            "INFERENCE_EXPLANATION_EVIDENCE_MISMATCH": 409,
            "INFERENCE_EXPLANATION_BACKGROUND_UNAVAILABLE": 409,
            "INFERENCE_LOCAL_EXPLANATION_FAILED": 500,
            "INFERENCE_EXPLANATION_INTERNAL_ERROR": 500,
            "RESULT_INTERPRETER_ERROR": 502,
            "INVALID_INFERENCE_RESULT_QUERY": 400,
            "INVALID_INFERENCE_VIEW_CONFIGURATION": 422,
            "INFERENCE_VIEW_CONFIGURATION_INTEGRITY_ERROR": 409,
            "INFERENCE_REPORT_DRAFT_INTEGRITY_ERROR": 409,
            "INFERENCE_RESULT_ROW_NOT_FOUND": 404,
            "INFERENCE_INTERNAL_ERROR": 500,
        }
        messages = {
            "INFERENCE_SOURCE_UNSUPPORTED_FORMAT": "Формат файла не поддерживается для прогноза.",
            "INFERENCE_SOURCE_UNREADABLE": "Не удалось безопасно прочитать файл для прогноза.",
            "INFERENCE_PHYSICAL_HEADERS_INVALID": "Заголовки колонок в новых данных некорректны.",
            "INFERENCE_SOURCE_EMPTY": "В новых данных нет объектов для прогноза.",
            "INFERENCE_IDENTIFIER_MISSING": "В новых данных отсутствует обязательный идентификатор или есть пустое значение.",
            "INFERENCE_REQUIRED_FEATURE_MISSING": "В новых данных отсутствует обязательный признак модели.",
            "INFERENCE_DTYPE_INCOMPATIBLE": "Тип одного из обязательных признаков несовместим с моделью.",
            "INFERENCE_VALUES_INVALID": "Обязательные признаки содержат недопустимые значения.",
            "INFERENCE_PREPARATION_STALE": "Проверенные данные для прогноза устарели или недоступны. Загрузите файл заново.",
            "INFERENCE_RUN_IN_PROGRESS": "Расчёт прогноза уже выполняется.",
            "MODEL_VERSION_INTEGRITY_ERROR": "Сохранённая модель не прошла проверку целостности.",
            "MODEL_SOURCE_RESULT_UNAVAILABLE": "Не удалось подтвердить исходный результат сохранённой модели.",
            "MODEL_INFERENCE_UNSUPPORTED": "Эту сохранённую модель нельзя безопасно использовать для прогноза.",
            "INFERENCE_FAILED": "Не удалось выполнить прогноз сохранённой моделью.",
            "INFERENCE_RESULT_PERSISTENCE_FAILED": "Не удалось безопасно сохранить результат прогноза.",
            "INFERENCE_OBJECT_NOT_FOUND": "Объект не найден; исходный результат прогноза остаётся доступен.",
            "INFERENCE_LOCAL_EXPLANATION_UNSUPPORTED": "Локальное объяснение недоступно; исходный результат прогноза остаётся доступен.",
            "INFERENCE_EXPLANATION_EVIDENCE_MISMATCH": "Проверка доказательств объяснения не пройдена; исходный результат прогноза остаётся доступен.",
            "INFERENCE_EXPLANATION_BACKGROUND_UNAVAILABLE": "Фон объяснения недоступен; исходный результат прогноза остаётся доступен.",
            "INFERENCE_LOCAL_EXPLANATION_FAILED": "Не удалось построить локальное объяснение; исходный результат прогноза остаётся доступен.",
            "INFERENCE_EXPLANATION_INTERNAL_ERROR": "Внутренняя ошибка объяснения; исходный результат прогноза остаётся доступен.",
            "RESULT_INTERPRETER_ERROR": "Не удалось сформировать интерпретацию. Результат модели и SHAP остаются доступными.",
            "INFERENCE_INTERNAL_ERROR": "Не удалось безопасно выполнить прогноз сохранённой моделью.",
            "INFERENCE_REPORT_DRAFT_INTEGRITY_ERROR": "Черновик отчёта не прошёл проверку целостности.",
            "INFERENCE_RESULT_ROW_NOT_FOUND": "Объект не найден в сохранённом результате прогноза.",
        }
        messages.update({
            "INFERENCE_RESULT_NOT_FOUND": "Inference Result was not found.",
            "INFERENCE_RESULT_INTEGRITY_ERROR": "Result integrity could not be verified; the original prediction Result remains available.",
            "INFERENCE_OBJECT_NOT_FOUND": "Object was not found; the original prediction Result remains available.",
            "MODEL_VERSION_NOT_FOUND": "Saved ModelVersion was not found; the original prediction Result remains available.",
            "MODEL_VERSION_INTEGRITY_ERROR": "ModelVersion integrity could not be verified; the original prediction Result remains available.",
            "MODEL_SOURCE_RESULT_UNAVAILABLE": "Model source evidence is unavailable; the original prediction Result remains available.",
        })
        return HTTPException(
            status_code=status_by_code.get(exc.code, 500),
            detail={
                "code": exc.code,
                "message": messages.get(exc.code, "Не удалось безопасно выполнить прогноз сохранённой моделью."),
            },
        )

    def analyst_report_error(exc: AnalystReportError) -> HTTPException:
        status_by_code = {
            "ANALYST_REPORT_DRAFT_NOT_FOUND": 404,
            "ANALYST_REPORT_DRAFT_EMPTY": 409,
            "ANALYST_REPORT_SOURCE_UNAVAILABLE": 404,
            "ANALYST_REPORT_SELECTED_OBJECT_UNAVAILABLE": 404,
            "ANALYST_REPORT_NOT_FOUND": 404,
            "ANALYST_REPORT_DRAFT_INTEGRITY_ERROR": 409,
            "ANALYST_REPORT_SOURCE_INTEGRITY_ERROR": 409,
            "ANALYST_REPORT_LOCAL_EXPLANATION_INTEGRITY_ERROR": 409,
            "ANALYST_REPORT_INTERPRETATION_INTEGRITY_ERROR": 409,
            "ANALYST_REPORT_INTEGRITY_ERROR": 409,
            "ANALYST_REPORT_LOCAL_EXPLANATION_UNAVAILABLE": 409,
            "ANALYST_REPORT_PERSISTENCE_ERROR": 500,
        }
        return HTTPException(
            status_code=status_by_code.get(exc.code, 500),
            detail={"code": exc.code, "message": "Analyst report could not be safely resolved."},
        )

    @api.get("/api/v1/model-versions", response_model=ModelVersionListResponse)
    def list_model_versions(
        offset: str = "0",
        limit: str = "50",
        search: str | None = None,
        model_id: str | None = None,
        dataset_id: str | None = None,
        saved_from: str | None = None,
        saved_to: str | None = None,
        sort: str = "SAVED_DESC",
    ) -> ModelVersionListResponse:
        try:
            if not offset.isdecimal() or not limit.isdecimal():
                raise InvalidModelLibraryQuery()
            page = model_library.list(
                offset=int(offset), limit=int(limit), search=search, model_id=model_id,
                dataset_id=dataset_id, saved_from=saved_from, saved_to=saved_to, sort=sort,
            )
        except ModelLibraryError as error:
            raise model_library_error(error) from None
        except Exception:
            raise model_library_error(ModelLibraryError()) from None
        return ModelVersionListResponse(
            total_count=page.total_count, filtered_count=page.filtered_count,
            offset=page.offset, limit=page.limit, returned_count=len(page.items),
            items=[ModelVersionListItemResponse(**item) for item in page.items],
        )

    @api.get("/api/v1/model-versions/{model_version_id}", response_model=ModelVersionDetailResponse)
    def get_model_version(model_version_id: str) -> ModelVersionDetailResponse:
        try:
            return ModelVersionDetailResponse(**model_library.detail(model_version_id).value)
        except ModelLibraryError as error:
            raise model_library_error(error) from None
        except Exception:
            raise model_library_error(ModelLibraryError()) from None

    @api.patch("/api/v1/model-versions/{model_version_id}/display-name", response_model=ModelVersionRenameResponse)
    def rename_model_version(
        model_version_id: str,
        payload: ModelVersionRenameRequest,
    ) -> ModelVersionRenameResponse:
        try:
            record = model_library.rename(model_version_id, payload.display_name)
        except ModelLibraryError as error:
            raise model_library_error(error) from None
        except Exception:
            raise model_library_error(ModelLibraryError()) from None
        return ModelVersionRenameResponse(
            model_version_id=record.model_version_id,
            display_name=record.display_name,
        )

    @api.post("/api/v1/model-versions/{model_version_id}/inference/preflight", response_model=SavedModelInferencePreflightResponse)
    async def preflight_saved_model_inference(
        model_version_id: str,
        response: Response,
        file: Annotated[UploadFile, File(...)],
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SavedModelInferencePreflightResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        staged = None
        try:
            upload_bytes = await file.read()
            staged = await run_in_threadpool(stage_upload_bytes, file.filename or "inference-data", upload_bytes)
            snapshot = await run_in_threadpool(tabular_reader.read, staged.local_path)
            preflight = await run_in_threadpool(
                saved_inference.preflight,
                session_owner=resolved_session_id,
                model_version_id=model_version_id,
                staged_upload=staged,
                snapshot=snapshot,
            )
        except ModelLibraryError as error:
            cleanup_staged_upload(staged)
            raise model_library_error(error) from None
        except UnsupportedUploadExtension:
            cleanup_staged_upload(staged)
            raise saved_inference_error(SavedModelInferenceError("INFERENCE_SOURCE_UNSUPPORTED_FORMAT")) from None
        except (EmptyUploadError, UploadReadError):
            cleanup_staged_upload(staged)
            raise saved_inference_error(SavedModelInferenceError("INFERENCE_SOURCE_UNREADABLE")) from None
        except InferenceInputError as error:
            cleanup_staged_upload(staged)
            raise saved_inference_error(SavedModelInferenceError(error.code)) from None
        except SavedModelInferenceError as error:
            cleanup_staged_upload(staged)
            raise saved_inference_error(error) from None
        except TabularReadError as error:
            cleanup_staged_upload(staged)
            code = "INFERENCE_SOURCE_UNSUPPORTED_FORMAT" if error.code == "unsupported_format" else "INFERENCE_SOURCE_UNREADABLE"
            raise saved_inference_error(SavedModelInferenceError(code)) from None
        except Exception:
            cleanup_staged_upload(staged)
            raise saved_inference_error(SavedModelInferenceError("INFERENCE_INTERNAL_ERROR")) from None
        return SavedModelInferencePreflightResponse(
            preparation_id=preflight.preparation_id,
            model_version_id=preflight.model_version_id,
            experiment_artifact_id=preflight.experiment_artifact_id,
            model_display_name=preflight.model_display_name,
            display_name=preflight.display_name,
            display_version=preflight.display_version,
            training_dataset_name=preflight.training_dataset_name,
            source_display_name=preflight.source_display_name,
            source_format=preflight.source_format,
            source_file_sha256=preflight.source_file_sha256,
            source_fingerprint=preflight.source_fingerprint,
            row_count=preflight.row_count,
            column_count=preflight.column_count,
            identifier_column=preflight.identifier_column,
            required_feature_count=len(preflight.required_feature_columns),
            required_feature_columns=list(preflight.required_feature_columns),
            ignored_column_count=len(preflight.ignored_columns),
            ignored_columns=list(preflight.ignored_columns),
            status="COMPATIBLE",
            checks={name: "PASS" for name in ("required_features", "input_types", "feature_binding", "rows", "identifier")},
        )

    @api.post("/api/v1/model-versions/{model_version_id}/inference/{preparation_id}/run", response_model=SavedModelInferenceRunResponse)
    async def run_saved_model_inference(
        model_version_id: str,
        preparation_id: str,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SavedModelInferenceRunResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            result = await run_in_threadpool(
                saved_inference.run,
                session_owner=resolved_session_id,
                model_version_id=model_version_id,
                preparation_id=preparation_id,
            )
        except ModelLibraryError as error:
            raise model_library_error(error) from None
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError("INFERENCE_FAILED")) from None
        return SavedModelInferenceRunResponse(
            run_state=result.run_state,
            inference_result_id=result.inference_result_id,
            model_version_id=result.model_version_id,
            source_display_name=result.source_display_name,
            created_at=result.created_at,
        )

    @api.delete("/api/v1/model-versions/{model_version_id}/inference/{preparation_id}", status_code=204)
    async def cancel_saved_model_inference(
        model_version_id: str, preparation_id: str, response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> Response:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            await run_in_threadpool(
                saved_inference.cancel, session_owner=resolved_session_id,
                model_version_id=model_version_id, preparation_id=preparation_id,
            )
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        return Response(status_code=204)

    def inference_view_response(value: Any) -> SavedInferenceViewResponse:
        return SavedInferenceViewResponse(
            saved=value.saved,
            configuration=value.configuration,
            model_decision_threshold=getattr(value, "model_decision_threshold", None),
            default_threshold=getattr(value, "default_threshold", 0.50),
            default_threshold_source=getattr(value, "default_threshold_source", "TECHNICAL_DEFAULT"),
        )

    def inference_report_draft_response(value: Any) -> SavedInferenceReportDraftResponse:
        return SavedInferenceReportDraftResponse(
            schema_version=value.schema_version,
            inference_result_id=value.inference_result_id,
            selected_row_ids=list(value.selected_row_ids),
            created_at=value.created_at,
            updated_at=value.updated_at,
            threshold=value.threshold,
            items=[SavedInferenceReportDraftItemResponse(**item) for item in value.items],
        )

    def inference_query_number(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY") from error

    def inference_query_integer(value: str) -> int:
        try:
            if not value or value.strip() != value:
                raise ValueError
            return int(value)
        except (TypeError, ValueError) as error:
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY") from error

    @api.get("/api/v1/inference-results/{inference_result_id}", response_model=SavedModelInferenceSummaryResponse)
    def get_saved_inference_result(
        inference_result_id: str, threshold: str = "0.50",
    ) -> SavedModelInferenceSummaryResponse:
        try:
            value = saved_inference.summary(inference_result_id, inference_query_number(threshold))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None
        return SavedModelInferenceSummaryResponse(
            inference_result_id=value.inference_result_id, model_version_id=value.model_version_id,
            experiment_artifact_id=value.experiment_artifact_id, display_name=value.display_name,
            display_version=value.display_version, model_display_name=value.model_display_name,
            source_display_name=value.source_display_name, source_format=value.source_format,
            source_file_sha256=value.source_file_sha256, source_fingerprint=value.source_fingerprint,
            created_at=value.created_at, status="COMPLETED", row_count=value.row_count,
            column_count=value.column_count, identifier_column=value.identifier_column,
            required_feature_count=value.required_feature_count, ignored_column_count=value.ignored_column_count,
            score_min=value.score_min, score_max=value.score_max, threshold=value.threshold,
            above_threshold_count=value.above_threshold_count, above_threshold_share=value.above_threshold_share,
            below_threshold_count=value.below_threshold_count, below_threshold_share=value.below_threshold_share,
            histogram=[InferenceScoreHistogramBinResponse(**item) for item in value.histogram],
        )

    @api.get("/api/v1/inference-results/{inference_result_id}/objects", response_model=SavedModelInferenceObjectListResponse)
    def get_saved_inference_objects(
        inference_result_id: str, threshold: str = "0.50", offset: str = "0", limit: str = "50",
        search: str | None = None, min_score: str | None = None, max_score: str | None = None,
        position_filter: str = "ALL", sort: str = "SCORE_DESC",
    ) -> SavedModelInferenceObjectListResponse:
        try:
            value = saved_inference.objects(
                inference_result_id, threshold=inference_query_number(threshold),
                offset=inference_query_integer(offset), limit=inference_query_integer(limit), search=search,
                min_score=inference_query_number(min_score), max_score=inference_query_number(max_score),
                position_filter=position_filter, sort=sort,
            )
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None
        return SavedModelInferenceObjectListResponse(
            inference_result_id=value.inference_result_id, threshold=value.threshold,
            total_count=value.total_count, filtered_count=value.filtered_count,
            offset=value.offset, limit=value.limit, returned_count=len(value.items),
            items=[SavedModelInferenceObjectItemResponse(**item) for item in value.items],
        )

    @api.get("/api/v1/inference-results/{inference_result_id}/objects/{row_id}", response_model=SavedInferenceObjectDetailResponse)
    def get_saved_inference_object_detail(
        inference_result_id: str, row_id: str, threshold: str = "0.50",
    ) -> SavedInferenceObjectDetailResponse:
        try:
            value = saved_explanation.detail(inference_result_id, row_id, threshold=inference_query_number(threshold))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError("INFERENCE_EXPLANATION_INTERNAL_ERROR")) from None
        return SavedInferenceObjectDetailResponse(
            inference_result_id=value.inference_result_id, model_version_id=value.model_version_id,
            row_id=value.row_id, source_row_position=value.source_row_position,
            identifier_column=value.identifier_column, identifier_display=value.identifier_display,
            score=value.score, threshold=value.threshold, position=value.position,
            features=[SavedInferenceObjectFeatureResponse(**item.__dict__) if hasattr(item, "__dict__") else SavedInferenceObjectFeatureResponse(feature_id=item.feature_id, column_name=item.column_name, display_name_ru=item.display_name_ru, description_ru=item.description_ru, raw_value=item.raw_value) for item in value.features],
            capabilities={key: CapabilityResponse(state=item.state, reason_code=item.reason_code) for key, item in value.capabilities.items()},
        )

    @api.get("/api/v1/inference-results/{inference_result_id}/objects/{row_id}/explanation", response_model=SavedInferenceExplanationResponse)
    def get_saved_inference_object_explanation(
        inference_result_id: str, row_id: str,
    ) -> SavedInferenceExplanationResponse:
        try:
            value = saved_explanation.explain(inference_result_id, row_id)
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError("INFERENCE_EXPLANATION_INTERNAL_ERROR")) from None
        return SavedInferenceExplanationResponse(
            inference_result_id=value.inference_result_id, model_version_id=value.model_version_id,
            row_id=value.row_id, explanation_id=value.explanation_id, evidence_hash=value.evidence_hash,
            prediction_probability=value.prediction_probability, base_value=value.base_value,
            explained_output_value=value.explained_output_value, output_space=value.output_space,
            explanation_method_id=value.explanation_method_id, explanation_method_version=value.explanation_method_version,
            explanation_provider_id=value.explanation_provider_id, explanation_provider_version=value.explanation_provider_version,
            features=[SavedInferenceExplanationFeatureResponse(feature_id=item.feature_id, column_name=item.column_name, display_name_ru=item.display_name_ru, description_ru=item.description_ru, raw_value=item.raw_value, shap_value=item.shap_value, rank=item.abs_rank, direction=item.direction) for item in value.features],
            remainder=value.remainder,
            result_interpretation_capability=CapabilityResponse(state=value.result_interpretation_capability.state, reason_code=value.result_interpretation_capability.reason_code),
        )

    @api.post(
        "/api/v1/inference-results/{inference_result_id}/objects/{row_id}/interpretations/{role}",
        response_model=SavedInferenceInterpretationResponse,
    )
    def create_saved_inference_interpretation(
        inference_result_id: str, row_id: str, role: str,
    ) -> SavedInferenceInterpretationResponse:
        allowed_roles = {"sales_manager", "credit_controller", "lawyer", "information_security"}
        if role not in allowed_roles:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_INTERPRETER_ROLE", "message": "Роль интерпретации не поддерживается."},
            )
        try:
            value = saved_explanation.interpret(inference_result_id, row_id, role=role)
        except SavedInferenceInterpretationUnavailable as error:
            # Capability is recomputed from trusted evidence here; the UI hint
            # in GET /explanation is never an authorization mechanism.
            raise HTTPException(
                status_code=409,
                detail={"code": error.reason_code, "message": "Интерпретация результата сейчас недоступна."},
            ) from None
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError("RESULT_INTERPRETER_ERROR")) from None
        return SavedInferenceInterpretationResponse(
            inference_result_id=value.inference_result_id,
            model_version_id=value.model_version_id,
            row_id=value.row_id,
            explanation_id=value.explanation_id,
            evidence_hash=value.evidence_hash,
            role=value.role,
            text=value.text,
            created_at=value.created_at,
            response_hash=value.response_hash,
        )

    @api.get("/api/v1/inference-results/{inference_result_id}/configuration", response_model=SavedInferenceViewResponse)
    def get_saved_inference_configuration(inference_result_id: str) -> SavedInferenceViewResponse:
        try:
            return inference_view_response(saved_inference.get_view_configuration(inference_result_id))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None

    @api.put("/api/v1/inference-results/{inference_result_id}/configuration", response_model=SavedInferenceViewResponse)
    async def put_saved_inference_configuration(inference_result_id: str, request: Request) -> SavedInferenceViewResponse:
        try:
            body = InferenceViewConfigurationRequest.model_validate(await request.json())
        except (ValidationError, ValueError, TypeError):
            raise saved_inference_error(SavedModelInferenceError("INVALID_INFERENCE_VIEW_CONFIGURATION")) from None
        try:
            return inference_view_response(saved_inference.put_view_configuration(inference_result_id, **body.model_dump()))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None

    @api.delete("/api/v1/inference-results/{inference_result_id}/configuration", response_model=SavedInferenceViewResponse)
    def delete_saved_inference_configuration(inference_result_id: str) -> SavedInferenceViewResponse:
        try:
            return inference_view_response(saved_inference.delete_view_configuration(inference_result_id))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None

    @api.get("/api/v1/inference-results/{inference_result_id}/report-draft", response_model=SavedInferenceReportDraftResponse)
    def get_saved_inference_report_draft(inference_result_id: str) -> SavedInferenceReportDraftResponse:
        try:
            return inference_report_draft_response(saved_inference.get_report_draft(inference_result_id))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None

    @api.post("/api/v1/inference-results/{inference_result_id}/report-draft/rows/{row_id}", response_model=SavedInferenceReportDraftResponse)
    def add_saved_inference_report_row(inference_result_id: str, row_id: str) -> SavedInferenceReportDraftResponse:
        try:
            return inference_report_draft_response(saved_inference.add_report_row(inference_result_id, row_id))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None

    @api.delete("/api/v1/inference-results/{inference_result_id}/report-draft/rows/{row_id}", response_model=SavedInferenceReportDraftResponse)
    def remove_saved_inference_report_row(inference_result_id: str, row_id: str) -> SavedInferenceReportDraftResponse:
        try:
            return inference_report_draft_response(saved_inference.remove_report_row(inference_result_id, row_id))
        except SavedModelInferenceError as error:
            raise saved_inference_error(error) from None
        except Exception:
            raise saved_inference_error(SavedModelInferenceError()) from None

    @api.post("/api/v1/inference-results/{inference_result_id}/report", response_model=AnalystReportGenerationResponse)
    def generate_analyst_report(inference_result_id: str) -> AnalystReportGenerationResponse:
        try:
            report, state = analyst_reports.generate(inference_result_id)
        except AnalystReportError as error:
            raise analyst_report_error(error) from None
        except Exception:
            raise analyst_report_error(AnalystReportError("ANALYST_REPORT_PERSISTENCE_ERROR")) from None
        return AnalystReportGenerationResponse(
            report_id=report["report_id"], created_at=report["created_at"], generation_state=state,
        )

    @api.get("/api/v1/analyst-reports/{report_id}", response_model=AnalystReportResponse)
    def get_analyst_report(report_id: str) -> AnalystReportResponse:
        try:
            return AnalystReportResponse(**analyst_reports.get(report_id))
        except AnalystReportError as error:
            raise analyst_report_error(error) from None
        except Exception:
            raise analyst_report_error(AnalystReportError("ANALYST_REPORT_INTEGRITY_ERROR")) from None

    @api.get("/api/v1/result/objects", response_model=ResultObjectListResponse)
    def get_current_result_objects(
        response: Response,
        offset: int = 0,
        limit: int = 50,
        search: str | None = None,
        target: str = "ANY",
        outcomes: Annotated[list[str] | None, Query()] = None,
        min_score: float | None = None,
        max_score: float | None = None,
        sort: str = "SCORE_DESC",
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ResultObjectListResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        current_threshold = store.current_result_threshold(resolved_session_id)
        if artifact_id is None or current_threshold is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        try:
            objects = result_service.objects(
                artifact_id,
                current_threshold,
                offset,
                limit,
                search=search,
                target=target,
                outcomes=outcomes,
                min_score=min_score,
                max_score=max_score,
                sort=sort,
            )
        except OOFResultError as exc:
            if exc.code == "INVALID_QUERY":
                raise HTTPException(
                    status_code=422,
                    detail={"code": "INVALID_QUERY", "message": "Параметры списка объектов некорректны."},
                ) from None
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "RESULT_READ_ERROR", "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        return ResultObjectListResponse(
            artifact_id=objects.artifact_id,
            threshold=objects.threshold,
            total_count=objects.total_count,
            filtered_count=objects.filtered_count,
            offset=objects.offset,
            limit=objects.limit,
            returned_count=objects.returned_count,
            items=[
                ResultObjectItemResponse(
                    object_id=item.object_id,
                    identifier_display=item.identifier_display,
                    y_true=item.y_true,
                    score=item.score,
                    predicted_positive=item.predicted_positive,
                    outcome=item.outcome,
                )
                for item in objects.items
            ],
        )

    @api.get("/api/v1/result/objects/{object_id}", response_model=ResultObjectDetailResponse)
    def get_current_result_object_detail(
        object_id: str,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ResultObjectDetailResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        current_threshold = store.current_result_threshold(resolved_session_id)
        if artifact_id is None or current_threshold is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        try:
            detail = result_service.object_detail(artifact_id, object_id, current_threshold)
        except OOFResultError as exc:
            if exc.code == "OBJECT_NOT_FOUND":
                raise HTTPException(
                    status_code=404,
                    detail={"code": "OBJECT_NOT_FOUND", "message": "Объект не найден в текущем OOF-результате."},
                ) from None
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "RESULT_READ_ERROR", "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        return ResultObjectDetailResponse(
            artifact_id=detail.artifact_id,
            object_id=detail.object_id,
            identifier_display=detail.identifier_display,
            y_true=detail.y_true,
            score=detail.score,
            threshold=detail.threshold,
            predicted_positive=detail.predicted_positive,
            outcome=detail.outcome,
            fold_number=detail.fold_number,
        )

    @api.get(
        "/api/v1/result/objects/{object_id}/explanation",
        response_model=LocalExplanationResponse,
    )
    def get_current_result_object_explanation(
        object_id: str,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> LocalExplanationResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        if artifact_id is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )

        try:
            evidence = explanation_service.local(artifact_id, object_id)
        except OOFExplanationError as exc:
            if exc.code == "OBJECT_NOT_FOUND":
                raise HTTPException(
                    status_code=404,
                    detail={"code": "OBJECT_NOT_FOUND", "message": "Объект не найден в текущем OOF-результате."},
                ) from None
            if exc.code == "LOCAL_OOF_EXPLANATION_UNSUPPORTED":
                raise HTTPException(
                    status_code=409,
                    detail={"code": exc.code, "message": "Для этой модели локальное объяснение недоступно."},
                ) from None
            integrity_codes = {
                "OOF_RESULT_EVIDENCE_INCOMPLETE",
                "FOLD_MODEL_UNAVAILABLE",
                "PROVENANCE_MISMATCH",
                "OOF_PREDICTION_MISMATCH",
            }
            if exc.code in integrity_codes:
                message = "Не удалось безопасно построить объяснение для сохранённой OOF-оценки. Сам результат объекта остаётся доступен."
            else:
                message = "Не удалось построить объяснение. Сам результат объекта остаётся доступен."
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": message},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "LOCAL_EXPLANATION_ERROR", "message": "Не удалось построить объяснение. Сам результат объекта остаётся доступен."},
            ) from None

        features = [
            LocalExplanationFeatureResponse(
                feature_id=feature.feature_id,
                column_name=feature.column_name,
                display_name_ru=feature.display_name_ru,
                description_ru=feature.description_ru,
                raw_value=feature.raw_value,
                shap_value=feature.shap_value,
                abs_rank=feature.abs_rank,
                direction=feature.direction,
            )
            for feature in evidence.features
        ]
        remainder_features = [feature for feature in features if feature.abs_rank > 5]
        remainder = None
        if len(features) > 5:
            remainder_value = sum(feature.shap_value for feature in remainder_features)
            remainder_direction = (
                "increases_output" if remainder_value > 0
                else "decreases_output" if remainder_value < 0
                else "neutral"
            )
            remainder = LocalExplanationRemainderResponse(
                feature_count=len(remainder_features),
                shap_value=remainder_value,
                direction=remainder_direction,
            )
        return LocalExplanationResponse(
            evidence_version=evidence.evidence_version,
            artifact_id=artifact_id,
            object_id=evidence.object_id,
            evidence_hash=evidence.evidence_hash,
            prediction_probability=evidence.prediction_probability,
            base_value=evidence.base_value,
            explained_output_value=evidence.explained_output_value,
            output_space=evidence.output_space,
            explanation_method_id=evidence.explanation_method_id,
            explanation_method_version=evidence.explanation_method_version,
            explanation_provider_id=evidence.provider_id,
            explanation_provider_version=evidence.provider_version,
            features=features,
            remainder=remainder,
        )

    @api.post(
        "/api/v1/result/objects/{object_id}/interpretations/{role}",
        response_model=ResultInterpretationResponse,
    )
    def create_result_interpretation(
        object_id: str,
        role: str,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ResultInterpretationResponse:
        allowed_roles = {
            "sales_manager",
            "credit_controller",
            "lawyer",
            "information_security",
        }
        if role not in allowed_roles:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_INTERPRETER_ROLE", "message": "Роль интерпретации не поддерживается."},
            )

        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id_at_start = store.current_result_artifact_id(resolved_session_id)
        if artifact_id_at_start is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )

        try:
            evidence = explanation_service.local(artifact_id_at_start, object_id)
        except OOFExplanationError as exc:
            if exc.code == "OBJECT_NOT_FOUND":
                raise HTTPException(
                    status_code=404,
                    detail={"code": "OBJECT_NOT_FOUND", "message": "Объект не найден в текущем OOF-результате."},
                ) from None
            if exc.code == "LOCAL_OOF_EXPLANATION_UNSUPPORTED":
                raise HTTPException(
                    status_code=409,
                    detail={"code": exc.code, "message": "Для этой модели локальное объяснение недоступно."},
                ) from None
            if exc.code in {
                "OOF_RESULT_EVIDENCE_INCOMPLETE",
                "FOLD_MODEL_UNAVAILABLE",
                "PROVENANCE_MISMATCH",
                "OOF_PREDICTION_MISMATCH",
            }:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": exc.code,
                        "message": "Не удалось безопасно построить объяснение для сохранённой OOF-оценки. Сам результат объекта остаётся доступен.",
                    },
                ) from None
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": "Не удалось построить объяснение. Сам результат объекта остаётся доступен.",
                },
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "LOCAL_EXPLANATION_ERROR",
                    "message": "Не удалось построить объяснение. Сам результат объекта остаётся доступен.",
                },
            ) from None

        if getattr(evidence, "object_id", None) != object_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROVENANCE_MISMATCH",
                    "message": "Не удалось безопасно построить объяснение для сохранённой OOF-оценки. Сам результат объекта остаётся доступен.",
                },
            )

        try:
            capability = workflow.capabilities(
                local_explanation_evidence=evidence
            )["result_interpretation"]
            if capability.state != "AVAILABLE":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": capability.reason_code,
                        "message": "Интерпретация результата сейчас недоступна.",
                    },
                )
            request = workflow.prepare_interpretation(
                evidence=evidence,
                recipient_role=role,
            )
            outcome = workflow.interpret(request=request)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "RESULT_INTERPRETER_ERROR",
                    "message": "Не удалось сформировать интерпретацию. Результат модели и SHAP остаются доступными.",
                },
            ) from None

        artifact_id_at_end = store.current_result_artifact_id(resolved_session_id)
        if artifact_id_at_end != artifact_id_at_start:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESULT_CHANGED",
                    "message": "Текущий результат изменился. Откройте объект заново.",
                },
            )

        result = outcome.response
        return ResultInterpretationResponse(
            artifact_id=artifact_id_at_start,
            object_id=object_id,
            role=role,
            text=result.text,
            created_at=result.created_at,
            response_hash=result.response_hash,
        )

    def global_oof_safe_message(code: str | None) -> str:
        if code == "GLOBAL_OOF_RESULT_NOT_READY":
            return "Расчёт влияния признаков ещё не готов."
        if code == "GLOBAL_OOF_EXPLANATION_UNSUPPORTED":
            return "Для этой модели глобальное OOF-объяснение недоступно."
        if code in {
            "OOF_RESULT_EVIDENCE_INCOMPLETE", "FOLD_MODEL_UNAVAILABLE",
            "PROVENANCE_MISMATCH", "OOF_PREDICTION_MISMATCH",
            "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE",
        }:
            return "Не удалось безопасно построить глобальное объяснение сохранённого OOF-результата. Сам результат остаётся доступен."
        return "Не удалось рассчитать влияние признаков. Сам результат модели остаётся доступен."

    def operation_response(snapshot: Any) -> GlobalOOFOperationResponse:
        code = snapshot.safe_error_code
        return GlobalOOFOperationResponse(
            artifact_id=snapshot.artifact_id, derivation_key=snapshot.derivation_key,
            status=snapshot.status, stage=snapshot.stage, stage_label=snapshot.stage_label,
            current_fold=snapshot.current_fold, total_folds=snapshot.total_folds,
            processed_rows=snapshot.processed_rows, total_rows=snapshot.total_rows,
            started_at=snapshot.started_at, updated_at=snapshot.updated_at,
            elapsed_seconds=snapshot.elapsed_seconds, safe_error_code=code,
            message=global_oof_safe_message(code) if code else None,
        )

    def result_changed() -> HTTPException:
        return HTTPException(status_code=409, detail={
            "code": "RESULT_CHANGED",
            "message": "Текущий результат изменился. Откройте влияние признаков заново.",
        })

    @api.post("/api/v1/result/explanation/global/run", response_model=GlobalOOFOperationResponse)
    async def run_current_global_oof_explanation(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
        payload: GlobalOOFRunRequest = GlobalOOFRunRequest(),
    ) -> GlobalOOFOperationResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id_at_start = store.current_result_artifact_id(resolved_session_id)
        if artifact_id_at_start is None:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed()
            raise HTTPException(status_code=409, detail={
                "code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."
            })
        try:
            if payload.retry:
                try:
                    snapshot = await run_in_threadpool(explanation_service.retry_global_oof, artifact_id_at_start)
                except ValueError as exc:
                    if str(exc) != "GLOBAL_OOF_RETRY_NOT_AVAILABLE":
                        raise
                    snapshot = await run_in_threadpool(explanation_service.start_global_oof, artifact_id_at_start)
            else:
                snapshot = await run_in_threadpool(explanation_service.start_global_oof, artifact_id_at_start)
        except OOFExplanationError as exc:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed() from None
            raise HTTPException(status_code=409, detail={
                "code": exc.code, "message": global_oof_safe_message(exc.code)
            }) from None
        except Exception:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed() from None
            raise HTTPException(status_code=500, detail={
                "code": "GLOBAL_OOF_EXPLANATION_FAILED",
                "message": global_oof_safe_message("GLOBAL_OOF_EXPLANATION_FAILED")
            }) from None
        if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
            raise result_changed()
        return operation_response(snapshot)

    @api.get("/api/v1/result/explanation/global/status", response_model=GlobalOOFOperationResponse)
    async def get_current_global_oof_status(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> GlobalOOFOperationResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id_at_start = store.current_result_artifact_id(resolved_session_id)
        if artifact_id_at_start is None:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed()
            raise HTTPException(status_code=409, detail={
                "code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."
            })
        try:
            snapshot = await run_in_threadpool(explanation_service.global_oof_status, artifact_id_at_start)
        except OOFExplanationError as exc:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed() from None
            raise HTTPException(status_code=409, detail={
                "code": exc.code, "message": global_oof_safe_message(exc.code)
            }) from None
        except Exception:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed() from None
            raise HTTPException(status_code=500, detail={
                "code": "GLOBAL_OOF_EXPLANATION_FAILED",
                "message": global_oof_safe_message("GLOBAL_OOF_EXPLANATION_FAILED")
            }) from None
        if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
            raise result_changed()
        return operation_response(snapshot)

    @api.get(
        "/api/v1/result/explanation/global",
        response_model=GlobalOOFExplanationResponse,
    )
    async def get_current_global_oof_explanation(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> GlobalOOFExplanationResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id_at_start = store.current_result_artifact_id(resolved_session_id)
        if artifact_id_at_start is None:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESULT_NOT_READY",
                    "message": "Результат полного обучения ещё не готов.",
                },
            )

        try:
            artifact = artifact_store.load(artifact_id_at_start)
            evidence = await run_in_threadpool(
                explanation_service.global_oof_ready_result, artifact_id_at_start
            )
        except OOFExplanationError as exc:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed() from None
            safe_codes = {
                "GLOBAL_OOF_RESULT_NOT_READY", "GLOBAL_OOF_EXPLANATION_UNSUPPORTED",
                "OOF_RESULT_EVIDENCE_INCOMPLETE", "FOLD_MODEL_UNAVAILABLE",
                "PROVENANCE_MISMATCH", "OOF_PREDICTION_MISMATCH",
                "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE",
            }
            code = exc.code if exc.code in safe_codes else "GLOBAL_OOF_EXPLANATION_FAILED"
            status_code = 409 if code in safe_codes else 500
            raise HTTPException(status_code=status_code, detail={
                "code": code, "message": global_oof_safe_message(code),
            }) from None
        except Exception:
            if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
                raise result_changed() from None
            raise HTTPException(status_code=500, detail={
                "code": "GLOBAL_OOF_EXPLANATION_FAILED",
                "message": global_oof_safe_message("GLOBAL_OOF_EXPLANATION_FAILED"),
            }) from None

        if store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start:
            raise result_changed()

        features = list(evidence.features)
        ranks = [feature.rank for feature in features]
        if ranks != list(range(1, evidence.feature_count + 1)) or len(features) != evidence.feature_count:
            raise HTTPException(status_code=409, detail={
                "code": "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE",
                "message": global_oof_safe_message("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE"),
            })

        return GlobalOOFExplanationResponse(
            artifact_id=artifact_id_at_start,
            model_id=evidence.model_id,
            model_version=evidence.model_version,
            dataset_name=artifact.dataset_contract.dataset_name,
            row_count=evidence.row_count,
            feature_count=evidence.feature_count,
            folds=artifact.config.folds,
            output_space=evidence.output_space,
            evidence_hash=evidence.evidence_hash,
            features=[
                GlobalOOFFeatureImportanceResponse(
                    feature_id=feature.feature_id,
                    column_name=feature.column_name,
                    mean_abs_shap=feature.mean_abs_shap,
                    rank=feature.rank,
                )
                for feature in features
            ],
        )

    @api.post(
        "/api/v1/result/interpretations/{role}",
        response_model=GlobalResultInterpretationResponse,
    )
    def create_global_result_interpretation(
        role: str,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> GlobalResultInterpretationResponse:
        allowed_roles = {
            "sales_manager",
            "credit_controller",
            "lawyer",
            "information_security",
        }
        if role not in allowed_roles:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_INTERPRETER_ROLE", "message": "Роль интерпретации не поддерживается."},
            )

        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id_at_start = store.current_result_artifact_id(resolved_session_id)
        threshold_at_start = store.current_result_threshold(resolved_session_id)
        if artifact_id_at_start is None or threshold_at_start is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )

        try:
            summary = result_service.summary(artifact_id_at_start)
            threshold = result_service.threshold(artifact_id_at_start, threshold_at_start)
            global_explanation = explanation_service.global_oof_ready_result(artifact_id_at_start)
        except OOFExplanationError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": global_oof_safe_message(exc.code)},
            ) from None
        except OOFResultError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый OOF-результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "GLOBAL_RESULT_INTERPRETER_EVIDENCE_ERROR", "message": "Не удалось подготовить подтверждённые данные для интерпретации."},
            ) from None

        capability = workflow.global_result_interpretation_capability(
            global_evidence_ready=True
        )
        if capability.state != "AVAILABLE":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": capability.reason_code,
                    "message": "Интерпретация общего результата сейчас недоступна.",
                },
            )

        try:
            request = workflow.prepare_global_interpretation(
                summary=summary,
                threshold=threshold,
                global_explanation=global_explanation,
                recipient_role=role,
            )
            outcome = workflow.interpret_global(request=request)
        except Exception:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "GLOBAL_RESULT_INTERPRETER_ERROR",
                    "message": "Не удалось сформировать интерпретацию. Результат модели и агрегированный SHAP остаются доступными.",
                },
            ) from None

        if (
            store.current_result_artifact_id(resolved_session_id) != artifact_id_at_start
            or store.current_result_threshold(resolved_session_id) != threshold_at_start
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESULT_CHANGED",
                    "message": "Текущий результат или порог изменился. Сформируйте объяснение заново.",
                },
            )

        result = outcome.response
        return GlobalResultInterpretationResponse(
            artifact_id=artifact_id_at_start,
            role=role,
            text=result.text,
            created_at=result.created_at,
            response_hash=result.response_hash,
        )

    @api.get("/api/v1/result/threshold", response_model=ResultThresholdResponse)
    def preview_current_result_threshold(
        threshold: Annotated[float, Query(ge=0.0, le=1.0)],
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ResultThresholdResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        if artifact_id is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        try:
            value = result_service.threshold(artifact_id, threshold)
        except OOFResultError as exc:
            if exc.code == "INVALID_THRESHOLD":
                raise HTTPException(
                    status_code=422,
                    detail={"code": "INVALID_THRESHOLD", "message": "Порог должен быть числом от 0 до 1."},
                ) from None
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "RESULT_READ_ERROR", "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        return ResultThresholdResponse(
            threshold=value.threshold,
            tp=value.tp,
            tn=value.tn,
            fp=value.fp,
            fn=value.fn,
            precision=value.precision,
            recall=value.recall,
            f1=value.f1,
            above_threshold_count=value.above_threshold_count,
            above_threshold_share=value.above_threshold_share,
        )

    @api.get("/api/v1/result/threshold/sweep", response_model=list[ResultThresholdResponse])
    def get_current_result_threshold_sweep(
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> list[ResultThresholdResponse]:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        if artifact_id is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        try:
            values = result_service.threshold_sweep(artifact_id)
        except OOFResultError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "RESULT_READ_ERROR", "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        return [
            ResultThresholdResponse(
                threshold=value.threshold,
                tp=value.tp,
                tn=value.tn,
                fp=value.fp,
                fn=value.fn,
                precision=value.precision,
                recall=value.recall,
                f1=value.f1,
                above_threshold_count=value.above_threshold_count,
                above_threshold_share=value.above_threshold_share,
            )
            for value in values
        ]

    @api.patch("/api/v1/result/threshold", response_model=ResultThresholdResponse)
    def update_current_result_threshold(
        payload: ResultThresholdPatch,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> ResultThresholdResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        artifact_id = store.current_result_artifact_id(resolved_session_id)
        if artifact_id is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        try:
            threshold = result_service.threshold(artifact_id, payload.threshold)
        except OOFResultError as exc:
            if exc.code == "INVALID_THRESHOLD":
                raise HTTPException(
                    status_code=422,
                    detail={"code": "INVALID_THRESHOLD", "message": "Порог должен быть числом от 0 до 1."},
                ) from None
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": "Не удалось прочитать сохранённый результат."},
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": "RESULT_READ_ERROR", "message": "Не удалось прочитать сохранённый результат."},
            ) from None

        if not store.set_current_result_threshold(
            resolved_session_id, artifact_id, threshold.threshold
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "RESULT_NOT_READY", "message": "Результат полного обучения ещё не готов."},
            )
        return ResultThresholdResponse(
            threshold=threshold.threshold,
            tp=threshold.tp,
            tn=threshold.tn,
            fp=threshold.fp,
            fn=threshold.fn,
            precision=threshold.precision,
            recall=threshold.recall,
            f1=threshold.f1,
            above_threshold_count=threshold.above_threshold_count,
            above_threshold_share=threshold.above_threshold_share,
        )

    def features_response(session_id: str) -> FeaturesResponse:
        try:
            context_id, selected_ids, _ = store.feature_selection(session_id)
            context = context_authority.resolve(context_id)
            view = feature_selection.describe(context, selected_ids)
        except Exception as exc:
            if isinstance(exc, FeatureSelectionError):
                raise
            raise HTTPException(status_code=409, detail={"code": "PREPARED_CONTEXT_REQUIRED", "message": "Сначала завершите подготовку данных."}) from None
        return FeaturesResponse(
            dataset=FeatureDatasetResponse(
                display_name=view.dataset.display_name,
                row_count=view.dataset.row_count,
                column_count=view.dataset.column_count,
                source_type=view.dataset.source_type,
                source_format=view.dataset.source_format,
            ),
            available_count=view.available_count,
            selected_feature_ids=list(view.selected_feature_ids),
            selected_count=view.selected_count,
            groups=[FeatureGroupResponse(group_id=item.group_id, name_ru=item.name_ru, description_ru=item.description_ru, display_order=item.display_order) for item in view.groups],
            features=[FeatureRowResponse(feature_id=item.feature_id, display_name_ru=item.display_name_ru, description_ru=item.description_ru, column_name=item.column_name, group_id=item.group_id, display_order=item.display_order) for item in view.features],
        )

    def algorithm_response(session_id: str) -> dict[str, Any]:
        try:
            context_id, selected_ids, selected_model_id, mode, overrides, hidden, _ = store.algorithm_state(session_id)
            context = context_authority.resolve(context_id)
        except Exception as exc:
            raise HTTPException(status_code=409, detail={"code": "FEATURES_CONTINUE_REQUIRED", "message": "Сначала подтвердите выбор признаков."}) from exc
        try:
            catalog = [entry.to_dict() for entry in planning.list_models()]
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "MODEL_CATALOG_UNAVAILABLE", "message": "Не удалось получить каталог алгоритмов."}) from exc
        return {"dataset_name": context.loaded_dataset.contract.dataset_name, "selected_feature_count": len(selected_ids), "available_feature_count": len([spec for spec in context.feature_registry.ordered_features() if spec.usage_status.value == "model_allowed"]), "selected_model_id": selected_model_id, "configuration_mode": mode, "user_overrides": overrides, "hidden_model_ids": sorted(hidden), "models": catalog}

    def available_model(session_id: str, model_id: str) -> dict[str, Any]:
        payload = algorithm_response(session_id)
        found = next((item for item in payload["models"] if item["model_id"] == model_id), None)
        if found is None or found["state"] != "AVAILABLE" or model_id in payload["hidden_model_ids"]:
            raise HTTPException(status_code=422, detail={"code": "MODEL_NOT_SELECTABLE", "message": "Выбранный алгоритм сейчас недоступен."})
        return payload

    @api.get("/api/v1/features", response_model=FeaturesResponse)
    def get_features(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> FeaturesResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        return features_response(resolved_session_id)

    @api.patch("/api/v1/features/selection", response_model=FeaturesResponse)
    def patch_feature_selection(request: FeatureSelectionPatch, response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> FeaturesResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            context_id, _, _ = store.feature_selection(resolved_session_id)
            selected = feature_selection.normalize_selection(context_authority.resolve(context_id), request.selected_feature_ids)
            store.update_feature_selection(resolved_session_id, selected)
        except FeatureSelectionError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": "Недопустимый выбор признаков."}) from None
        except Exception:
            raise HTTPException(status_code=409, detail={"code": "PREPARED_CONTEXT_REQUIRED", "message": "Сначала завершите подготовку данных."}) from None
        return features_response(resolved_session_id)

    @api.post("/api/v1/features/continue", response_model=SessionResponse)
    def continue_features(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> SessionResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            _, selected, _ = store.feature_selection(resolved_session_id)
            if not selected:
                raise FeatureSelectionError("FEATURE_SELECTION_REQUIRED")
            return _session_response(store.continue_from_features(resolved_session_id))
        except FeatureSelectionError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": "Выберите хотя бы один разрешённый признак."}) from None
        except NativeSessionTransitionError:
            raise HTTPException(status_code=409, detail={"code": "PREPARED_CONTEXT_REQUIRED", "message": "Сначала завершите подготовку данных."}) from None

    @api.get("/api/v1/algorithm")
    def get_algorithm(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        return algorithm_response(resolved_session_id)

    @api.patch("/api/v1/algorithm/model")
    def patch_algorithm_model(request: ModelSelectionPatch, response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        available_model(resolved_session_id, request.model_id)
        store.select_model(resolved_session_id, request.model_id)
        return algorithm_response(resolved_session_id)

    @api.patch("/api/v1/algorithm/configuration")
    def patch_algorithm_configuration(request: AlgorithmConfigurationPatch, response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        state = algorithm_response(resolved_session_id)
        selected = state["selected_model_id"]
        model = next((item for item in state["models"] if item["model_id"] == selected), None)
        if model is None or model["state"] != "AVAILABLE" or selected in state["hidden_model_ids"]:
            raise HTTPException(status_code=422, detail={"code": "MODEL_NOT_SELECTABLE", "message": "Сначала выберите доступный алгоритм."})
        parameters = {item["parameter_path"]: item for item in model["parameter_schema"]["parameters"] if item["editable"]}
        clean = {} if request.configuration_mode == "RECOMMENDED" else {key: value for key, value in request.user_overrides.items() if key in parameters and value != parameters[key]["recommended_value"]}
        store.set_algorithm_configuration(resolved_session_id, request.configuration_mode, clean)
        return algorithm_response(resolved_session_id)

    @api.post("/api/v1/algorithm/models/{model_id}/hide")
    def hide_algorithm_model(model_id: str, response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        state = algorithm_response(resolved_session_id)
        if not any(item["model_id"] == model_id for item in state["models"]):
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_MODEL", "message": "Алгоритм отсутствует в каталоге."})
        store.hide_model(resolved_session_id, model_id)
        return algorithm_response(resolved_session_id)

    @api.post("/api/v1/algorithm/models/{model_id}/restore")
    def restore_algorithm_model(model_id: str, response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        store.restore_model(resolved_session_id, model_id)
        return algorithm_response(resolved_session_id)

    @api.post("/api/v1/algorithm/continue", response_model=SessionResponse)
    def continue_algorithm(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> SessionResponse:
        resolved_session_id, _ = resolve_session(response, session_id)
        state = algorithm_response(resolved_session_id)
        if state["selected_model_id"] is None:
            raise HTTPException(status_code=422, detail={"code": "MODEL_SELECTION_REQUIRED", "message": "Выберите алгоритм."})
        available_model(resolved_session_id, state["selected_model_id"])
        return _session_response(store.continue_from_algorithm(resolved_session_id))

    def quality_response(session_id: str) -> dict[str, Any]:
        try:
            return quality.state(session_id)
        except Exception as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "ALGORITHM_CONTINUE_REQUIRED", "message": "Сначала завершите выбор алгоритма."},
            ) from exc

    @api.get("/api/v1/quality")
    def get_quality(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        return quality_response(resolved_session_id)

    @api.patch("/api/v1/quality/settings")
    def patch_quality_settings(request: QualitySettingsPatch, response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        current = quality_response(resolved_session_id)
        seed = current["settings"]["seed"] if request.seed is None else request.seed
        folds = current["settings"]["folds"] if request.folds is None else request.folds
        try:
            return quality.update_settings(resolved_session_id, seed=seed, folds=folds)
        except ValueError as exc:
            code = str(exc)
            message = "Количество частей проверки меньше допустимого." if code == "INVALID_FOLDS" else "Seed должен быть целым числом."
            raise HTTPException(status_code=422, detail={"code": code, "message": message}) from None

    @api.post("/api/v1/quality/preflight")
    async def run_quality_preflight(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        quality_response(resolved_session_id)
        try:
            return await run_in_threadpool(quality.preflight, resolved_session_id)
        except ValueError as exc:
            if str(exc) != "TRAINING_ALREADY_RUNNING":
                raise
            raise HTTPException(status_code=409, detail={"code": str(exc), "message": "Обучение уже выполняется."}) from None

    @api.post("/api/v1/quality/training")
    async def run_quality_training(response: Response, session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None) -> dict[str, Any]:
        resolved_session_id, _ = resolve_session(response, session_id)
        try:
            return await run_in_threadpool(quality.train, resolved_session_id)
        except ValueError as exc:
            code = str(exc)
            messages = {
                "TRAINING_ALREADY_RUNNING": "Обучение уже выполняется.",
                "TRAINING_ALREADY_COMPLETED": "Обучение для текущей конфигурации уже завершено.",
                "PREFLIGHT_REQUIRED": "Сначала успешно выполните предварительную проверку.",
            }
            raise HTTPException(status_code=409, detail={"code": code, "message": messages.get(code, "Не удалось запустить обучение.")}) from None

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
        warning_views = project_preparation_warnings(dataset.proposal.warnings, draft)
        warning_counts = preparation_warning_counts(warning_views)
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
                    PreparationWarningResponse(
                        code=warning.code,
                        severity=warning.severity,
                        scope=warning.scope,
                        column_name=warning.column_name,
                        detected_reasons=list(warning.detected_reasons),
                        detected_requires_confirmation=warning.detected_requires_confirmation,
                        resolution_state=warning.resolution_state,
                        resolution_code=warning.resolution_code,
                        subject_ru=warning.subject_ru,
                        title_ru=warning.title_ru,
                        detail_ru=warning.detail_ru,
                        check_ru=warning.check_ru,
                        resolution_note_ru=warning.resolution_note_ru,
                        action=warning.action,
                    )
                    for warning in warning_views
                ],
                warning_counts={
                    "action_required": warning_counts.action_required,
                    "resolved": warning_counts.resolved,
                    "info": warning_counts.info,
                },
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
                selected_feature_ids=feature_selection.initial_selection(context),
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
