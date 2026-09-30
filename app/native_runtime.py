"""Minimal native experiment composition, deliberately excluding Streamlit and result services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.bootstrap import SUPPORTED_PROTOCOL, SupportedProtocol
from app.experiment_runtime import compose_experiment_models
from komus_risk.application import ExperimentApplicationService
from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.model_platform import builtin_model_presentation_registry
from komus_risk.planning import ExperimentPlanningService
from komus_risk.preparation import PreparedDatasetContextAuthority


@dataclass(frozen=True, slots=True)
class NativeExperimentRuntime:
    planning_service: ExperimentPlanningService
    application_service: ExperimentApplicationService
    supported_protocol: SupportedProtocol
    prepared_context_authority: PreparedDatasetContextAuthority


def create_native_experiment_runtime() -> NativeExperimentRuntime:
    """Compose only dependencies required by native planning and technical smoke."""
    model_runtime = compose_experiment_models()
    plugins = model_runtime.plugin_registry
    authority = PreparedDatasetContextAuthority()
    return NativeExperimentRuntime(
        planning_service=ExperimentPlanningService(
            model_plugin_registry=plugins,
            model_presentation_registry=builtin_model_presentation_registry(plugins),
        ),
        application_service=ExperimentApplicationService(
            model_registry=model_runtime.model_registry,
            model_factories=model_runtime.model_factories,
            artifact_store=ExperimentArtifactStore(Path(".native-quality-artifacts")),
            comparison_service=ExperimentComparisonService(),
            code_version="native-quality-v1a",
            model_plugin_registry=plugins,
            prepared_context_authority=authority,
        ),
        supported_protocol=SUPPORTED_PROTOCOL,
        prepared_context_authority=authority,
    )
