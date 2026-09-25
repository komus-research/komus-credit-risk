"""Application facade for the local saved-model use flow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from komus_risk.artifacts import LoadedModelVersion, ModelVersionStore
from komus_risk.data import TabularSnapshot

from .local_explanation import LocalExplanationEvidence
from .model_inference import ModelInferenceService, PredictionBatch
from .model_training import FinalModelTrainingService


_CAPABILITY_STATES = frozenset({
    "AVAILABLE", "WAITING_FOR_INPUT", "UNSUPPORTED", "DISABLED", "MISCONFIGURED",
})


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    """A small immutable statement of whether a workflow action may run."""

    state: str
    reason_code: str

    def __post_init__(self) -> None:
        if self.state not in _CAPABILITY_STATES:
            raise ValueError("Unknown capability state.")
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise ValueError("Capability reason_code must be non-empty.")


class LocalExplanationProvider(Protocol):
    """One registered local explanation implementation."""

    def explain(
        self,
        *,
        loaded_model_version: LoadedModelVersion,
        prediction_batch: PredictionBatch,
        row_id: str,
    ) -> LocalExplanationEvidence: ...


class IntegrationWorkflowService:
    """Orchestrates accepted local training, inference and explanation services."""

    def __init__(
        self,
        *,
        final_model_training_service: FinalModelTrainingService,
        model_version_store: ModelVersionStore,
        model_inference_service: ModelInferenceService,
        local_explainers: Mapping[str, LocalExplanationProvider],
    ) -> None:
        self.final_model_training_service = final_model_training_service
        self.model_version_store = model_version_store
        self.model_inference_service = model_inference_service
        self.local_explainers = dict(local_explainers)
        training_store = getattr(final_model_training_service, "model_version_store", model_version_store)
        if training_store is not model_version_store:
            raise ValueError("FinalModelTrainingService must use the supplied ModelVersionStore.")

    def save_model(
        self,
        *,
        experiment_artifact_id: str,
        prepared_dataset_context: Any,
    ) -> LoadedModelVersion:
        """Final-fit the exact accepted experiment and reload its persisted version."""
        loaded_dataset = getattr(prepared_dataset_context, "loaded_dataset", None)
        feature_registry = getattr(prepared_dataset_context, "feature_registry", None)
        population = getattr(prepared_dataset_context, "population", None)
        if loaded_dataset is None or feature_registry is None or population is None:
            raise ValueError("PreparedDatasetContext is incomplete for final model save.")
        summary = self.final_model_training_service.train(
            experiment_artifact_id=experiment_artifact_id,
            loaded_dataset=loaded_dataset,
            feature_registry=feature_registry,
            population=population,
        )
        return self.model_version_store.load(summary.model_version_id)

    def predict(
        self,
        *,
        loaded_model_version: LoadedModelVersion,
        snapshot: TabularSnapshot,
    ) -> PredictionBatch:
        """Delegate targetless physical-file inference to the accepted service."""
        return self.model_inference_service.predict(
            loaded_model_version=loaded_model_version,
            snapshot=snapshot,
        )

    def explain(
        self,
        *,
        loaded_model_version: LoadedModelVersion,
        prediction_batch: PredictionBatch,
        row_id: str,
    ) -> LocalExplanationEvidence:
        """Delegate only to the provider registered for the saved model family."""
        provider = self.local_explainers.get(loaded_model_version.summary.model_id)
        if provider is None:
            raise ValueError("Local explanation is unsupported for this saved model version.")
        return provider.explain(
            loaded_model_version=loaded_model_version,
            prediction_batch=prediction_batch,
            row_id=row_id,
        )

    def capabilities(
        self,
        *,
        experiment_artifact_id: str | None = None,
        prepared_dataset_context: Any | None = None,
        loaded_model_version: LoadedModelVersion | None = None,
        prediction_batch: PredictionBatch | None = None,
        selected_row_id: str | None = None,
    ) -> dict[str, CapabilityStatus]:
        """Describe prerequisites without leaking model-specific rules to a frontend."""
        save = (
            CapabilityStatus("AVAILABLE", "EXPERIMENT_AND_CONTEXT_READY")
            if experiment_artifact_id and prepared_dataset_context is not None
            else CapabilityStatus("WAITING_FOR_INPUT", "EXPERIMENT_OR_CONTEXT_MISSING")
        )
        inference = (
            CapabilityStatus("AVAILABLE", "MODEL_VERSION_READY")
            if loaded_model_version is not None
            else CapabilityStatus("WAITING_FOR_INPUT", "MODEL_VERSION_MISSING")
        )
        if loaded_model_version is None:
            explanation = CapabilityStatus("WAITING_FOR_INPUT", "MODEL_VERSION_MISSING")
        elif loaded_model_version.summary.model_id not in self.local_explainers:
            explanation = CapabilityStatus("UNSUPPORTED", "LOCAL_EXPLAINER_NOT_REGISTERED")
        elif prediction_batch is None:
            explanation = CapabilityStatus("WAITING_FOR_INPUT", "PREDICTION_BATCH_MISSING")
        elif not selected_row_id:
            explanation = CapabilityStatus("WAITING_FOR_INPUT", "PREDICTION_ROW_MISSING")
        else:
            explanation = CapabilityStatus("AVAILABLE", "LOCAL_EXPLAINER_READY")
        return {
            "final_model_save": save,
            "inference": inference,
            "local_explanation": explanation,
            "result_interpretation": CapabilityStatus("DISABLED", "STAGE_III_C2_NOT_ENABLED"),
        }
