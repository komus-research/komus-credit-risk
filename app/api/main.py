"""Thin FastAPI adapter for native AXION session use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Cookie, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from komus_risk.application import (
    DatasetDraftError,
    FeatureSelectionError,
    FeatureSelectionService,
    NativeDatasetOnboardingService,
    NativeSessionSnapshot,
    NativeSessionStore,
    NativeQualityService,
)
from komus_risk.application.oof_result import OOFResultError
from komus_risk.application.oof_explanation import OOFExplanationError
from komus_risk.preparation import DatasetPreparationError
from komus_risk.application.native_session import (
    DatasetInspectionProgress,
    DatasetInspectionStage,
    NativeSessionTransitionError,
)
from komus_risk.planning import ExperimentPlanningService
from app.upload_staging import cleanup_staged_upload, stage_upload_bytes
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


class ResultOverviewResponse(BaseModel):
    summary: ResultSummaryResponse
    threshold: ResultThresholdResponse


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


class ResultInterpretationResponse(BaseModel):
    artifact_id: str
    object_id: str
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


def create_app(*, session_store: NativeSessionStore | None = None, planning_service: ExperimentPlanningService | None = None, oof_result_service: Any | None = None, oof_explanation_service: Any | None = None, prepared_context_authority: Any | None = None, experiment_artifact_store: Any | None = None, integration_workflow_service: Any | None = None) -> FastAPI:
    """Compose native experiment dependencies once, then expose them through thin routes."""
    store = session_store or NativeSessionStore()
    onboarding = NativeDatasetOnboardingService()
    runtime = create_native_experiment_runtime()
    result_service = oof_result_service or runtime.oof_result_service
    explanation_service = oof_explanation_service or runtime.oof_explanation_service
    workflow = (
        integration_workflow_service
        if integration_workflow_service is not None
        else runtime.integration_workflow_service
    )
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
        )

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
                explanation_service.global_oof, artifact_id_at_start
            )
        except OOFExplanationError as exc:
            if exc.code == "GLOBAL_OOF_EXPLANATION_UNSUPPORTED":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": exc.code,
                        "message": "Для этой модели глобальное OOF-объяснение недоступно.",
                    },
                ) from None
            integrity_codes = {
                "OOF_RESULT_EVIDENCE_INCOMPLETE",
                "FOLD_MODEL_UNAVAILABLE",
                "PROVENANCE_MISMATCH",
                "OOF_PREDICTION_MISMATCH",
                "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE",
            }
            if exc.code in integrity_codes:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": exc.code,
                        "message": (
                            "Не удалось безопасно построить глобальное объяснение "
                            "сохранённого OOF-результата. Сам результат остаётся доступен."
                        ),
                    },
                ) from None
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "GLOBAL_OOF_EXPLANATION_ERROR",
                    "message": (
                        "Не удалось построить глобальное объяснение. "
                        "Сам результат остаётся доступен."
                    ),
                },
            ) from None
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "GLOBAL_OOF_EXPLANATION_ERROR",
                    "message": (
                        "Не удалось построить глобальное объяснение. "
                        "Сам результат остаётся доступен."
                    ),
                },
            ) from None

        artifact_id_at_end = store.current_result_artifact_id(resolved_session_id)
        if artifact_id_at_end != artifact_id_at_start:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESULT_CHANGED",
                    "message": (
                        "Текущий результат изменился. Откройте влияние признаков заново."
                    ),
                },
            )

        features = list(evidence.features)
        ranks = [feature.rank for feature in features]
        if ranks != list(range(1, evidence.feature_count + 1)) or len(features) != evidence.feature_count:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE",
                    "message": (
                        "Не удалось безопасно построить глобальное объяснение "
                        "сохранённого OOF-результата. Сам результат остаётся доступен."
                    ),
                },
            )

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
