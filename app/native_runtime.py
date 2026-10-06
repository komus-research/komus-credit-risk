"""Native experiment composition for planning, execution, results, and history."""

from __future__ import annotations

from dataclasses import dataclass
from app.bootstrap import SUPPORTED_PROTOCOL, SupportedProtocol, _repository_root
from app.experiment_runtime import compose_experiment_models
from app.result_interpreter_runtime import compose_result_interpreter_runtime
from app.upload_staging import cleanup_staged_upload
from komus_risk.application import (
    ExperimentApplicationService,
    FinalModelTrainingService,
    GlobalRedactedV1OutboundPolicy,
    GlobalResultInterpreterService,
    IntegrationWorkflowService,
    ModelLibraryService,
    ModelInferenceService,
    SavedModelInferenceService,
    SavedInferenceExplanationService,
    AnalystReportService,
    ResultInterpreterPromptLoader,
    ResultInterpreterService,
)
from komus_risk.artifacts import (
    ExperimentArtifactStore,
    ModelLibraryRecordStore,
    ModelVersionStore,
    SavedModelInferenceResultStore,
    SavedInferenceResultViewConfigurationStore,
    AnalystReportStore,
    SavedInferenceInterpretationStore,
)
from komus_risk.artifacts.inference_view_store import SavedInferenceReportDraftStore
from komus_risk.application.history import AnalysisHistoryService
from komus_risk.application.oof_explanation import OOFExplanationService
from komus_risk.application.global_oof_operation import GlobalOOFDerivedStore, GlobalOOFOperationService
from komus_risk.application.oof_result import OOFResultService
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.model_platform import builtin_model_presentation_registry
from komus_risk.planning import ExperimentPlanningService
from komus_risk.preparation import PreparedDatasetContextAuthority


@dataclass(frozen=True, slots=True)
class NativeExperimentRuntime:
    planning_service: ExperimentPlanningService
    application_service: ExperimentApplicationService
    oof_result_service: OOFResultService
    oof_explanation_service: OOFExplanationService
    global_oof_operation_service: GlobalOOFOperationService
    analysis_history_service: AnalysisHistoryService
    artifact_store: ExperimentArtifactStore
    integration_workflow_service: IntegrationWorkflowService
    model_library_service: ModelLibraryService
    saved_model_inference_service: SavedModelInferenceService
    saved_inference_explanation_service: SavedInferenceExplanationService
    analyst_report_service: AnalystReportService
    supported_protocol: SupportedProtocol
    prepared_context_authority: PreparedDatasetContextAuthority


def create_native_experiment_runtime() -> NativeExperimentRuntime:
    """Compose only dependencies required by native planning and technical smoke."""
    model_runtime = compose_experiment_models()
    plugins = model_runtime.plugin_registry
    authority = PreparedDatasetContextAuthority()
    store_root = _repository_root() / ".axion-artifacts"
    code_version = "native-quality-v1a"
    artifact_store = ExperimentArtifactStore(store_root)
    global_oof_operation_service = GlobalOOFOperationService(GlobalOOFDerivedStore(store_root))
    persistence_provider_registry = plugins.persistence_providers
    if persistence_provider_registry is None:  # pragma: no cover - builtin invariant
        raise RuntimeError("Builtin model plugins require persistence providers.")
    model_version_store = ModelVersionStore(
        store_root / "model_versions",
        code_version=code_version,
        model_specs={plugin.spec.model_id: plugin.spec for plugin in plugins.list()},
        model_plugin_registry=plugins,
        persistence_provider_registry=persistence_provider_registry,
    )
    final_model_training_service = FinalModelTrainingService(
        experiment_artifact_store=artifact_store,
        model_version_store=model_version_store,
        model_registry=model_runtime.model_registry,
        model_factories=model_runtime.model_factories,
        code_version=code_version,
        model_plugin_registry=plugins,
    )
    interpreter_runtime = compose_result_interpreter_runtime()
    global_prompt_loader = ResultInterpreterPromptLoader(
        _repository_root() / "resources" / "prompts" / "global_result_interpreter"
    )
    integration_workflow_service = IntegrationWorkflowService(
        final_model_training_service=final_model_training_service,
        model_version_store=model_version_store,
        model_inference_service=ModelInferenceService(),
        model_plugin_registry=plugins,
        result_interpreter_service=ResultInterpreterService(interpreter_runtime.prompt_loader),
        result_interpreter_client=interpreter_runtime.client,
        outbound_interpreter_policy=interpreter_runtime.outbound_policy,
        global_result_interpreter_service=GlobalResultInterpreterService(global_prompt_loader),
        global_outbound_interpreter_policy=GlobalRedactedV1OutboundPolicy(),
        result_interpreter_runtime=interpreter_runtime.configuration,
    )
    model_library_service = ModelLibraryService(
        record_store=ModelLibraryRecordStore(store_root / "model_library"),
        model_version_store=model_version_store,
        integration_workflow_service=integration_workflow_service,
        experiment_artifact_store=artifact_store,
    )
    saved_model_inference_service = SavedModelInferenceService(
        model_library_service=model_library_service,
        model_inference_service=integration_workflow_service.model_inference_service,
        result_store=SavedModelInferenceResultStore(store_root / "inference_results"),
        view_store=SavedInferenceResultViewConfigurationStore(store_root / "inference_view_configurations"),
        report_draft_store=SavedInferenceReportDraftStore(store_root / "inference_report_drafts"),
        cleanup_upload=cleanup_staged_upload,
    )
    interpretation_store = SavedInferenceInterpretationStore(store_root / "inference_interpretations")
    saved_inference_explanation_service = SavedInferenceExplanationService(
        result_store=SavedModelInferenceResultStore(store_root / "inference_results"),
        model_library_service=model_library_service,
        integration_workflow_service=integration_workflow_service,
        experiment_artifact_store=artifact_store,
        interpretation_store=interpretation_store,
    )
    analyst_report_service = AnalystReportService(
        result_store=SavedModelInferenceResultStore(store_root / "inference_results"),
        draft_store=SavedInferenceReportDraftStore(store_root / "inference_report_drafts"),
        explanation_service=saved_inference_explanation_service,
        model_library_service=model_library_service,
        interpretation_store=interpretation_store,
        report_store=AnalystReportStore(store_root / "analyst_reports"),
    )
    return NativeExperimentRuntime(
        planning_service=ExperimentPlanningService(
            model_plugin_registry=plugins,
            model_presentation_registry=builtin_model_presentation_registry(plugins),
        ),
        application_service=ExperimentApplicationService(
            model_registry=model_runtime.model_registry,
            model_factories=model_runtime.model_factories,
            artifact_store=artifact_store,
            comparison_service=ExperimentComparisonService(),
            code_version=code_version,
            model_plugin_registry=plugins,
            prepared_context_authority=authority,
        ),
        oof_result_service=OOFResultService(artifact_store),
        oof_explanation_service=OOFExplanationService(artifact_store, plugins, global_oof_operation_service),
        global_oof_operation_service=global_oof_operation_service,
        analysis_history_service=AnalysisHistoryService(artifact_store),
        artifact_store=artifact_store,
        integration_workflow_service=integration_workflow_service,
        model_library_service=model_library_service,
        saved_model_inference_service=saved_model_inference_service,
        saved_inference_explanation_service=saved_inference_explanation_service,
        analyst_report_service=analyst_report_service,
        supported_protocol=SUPPORTED_PROTOCOL,
        prepared_context_authority=authority,
    )
