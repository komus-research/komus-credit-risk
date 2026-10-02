"""Native experiment composition for planning, execution, results, and history."""

from __future__ import annotations

from dataclasses import dataclass
from app.bootstrap import SUPPORTED_PROTOCOL, SupportedProtocol, _repository_root
from app.experiment_runtime import compose_experiment_models
from app.result_interpreter_runtime import compose_result_interpreter_runtime
from komus_risk.application import (
    ExperimentApplicationService,
    FinalModelTrainingService,
    IntegrationWorkflowService,
    ModelInferenceService,
    ResultInterpreterService,
)
from komus_risk.artifacts import ExperimentArtifactStore, ModelVersionStore
from komus_risk.application.history import AnalysisHistoryService
from komus_risk.application.oof_explanation import OOFExplanationService
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
    analysis_history_service: AnalysisHistoryService
    artifact_store: ExperimentArtifactStore
    integration_workflow_service: IntegrationWorkflowService
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
    integration_workflow_service = IntegrationWorkflowService(
        final_model_training_service=final_model_training_service,
        model_version_store=model_version_store,
        model_inference_service=ModelInferenceService(),
        model_plugin_registry=plugins,
        result_interpreter_service=ResultInterpreterService(interpreter_runtime.prompt_loader),
        result_interpreter_client=interpreter_runtime.client,
        outbound_interpreter_policy=interpreter_runtime.outbound_policy,
        result_interpreter_runtime=interpreter_runtime.configuration,
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
        oof_explanation_service=OOFExplanationService(artifact_store, plugins),
        analysis_history_service=AnalysisHistoryService(artifact_store),
        artifact_store=artifact_store,
        integration_workflow_service=integration_workflow_service,
        supported_protocol=SUPPORTED_PROTOCOL,
        prepared_context_authority=authority,
    )
