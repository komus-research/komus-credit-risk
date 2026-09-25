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
from .interpreter_policy import (
    OutboundInterpreterPolicy,
    PolicyBoundResultInterpreterClient,
    ProviderDispatchReceipt,
)
from .result_interpreter import (
    ResultInterpreterClient,
    ResultInterpreterRequest,
    ResultInterpreterResponse,
    ResultInterpreterService,
)


_CAPABILITY_STATES = frozenset({
    "AVAILABLE", "WAITING_FOR_INPUT", "UNSUPPORTED", "DISABLED", "MISCONFIGURED",
})


@dataclass(frozen=True, slots=True)
class ResultInterpreterRuntimeConfiguration:
    """Provider-neutral, secret-free interpretation readiness configuration."""

    policy_mode: str = "DISABLED"
    provider_configured: bool = False
    provider_registered: bool = False
    model_configured: bool = False
    credentials_configured: bool = False

    @classmethod
    def disabled(cls) -> "ResultInterpreterRuntimeConfiguration":
        return cls()

    @property
    def is_ready(self) -> bool:
        return (
            self.policy_mode == "REDACTED_V1"
            and self.provider_configured
            and self.provider_registered
            and self.model_configured
            and self.credentials_configured
        )


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


@dataclass(frozen=True, slots=True)
class ResultInterpretationOutcome:
    response: ResultInterpreterResponse
    dispatch_receipt: ProviderDispatchReceipt


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
        result_interpreter_service: ResultInterpreterService | None = None,
        result_interpreter_client: ResultInterpreterClient | None = None,
        outbound_interpreter_policy: OutboundInterpreterPolicy | None = None,
        result_interpreter_runtime: ResultInterpreterRuntimeConfiguration | None = None,
    ) -> None:
        self.final_model_training_service = final_model_training_service
        self.model_version_store = model_version_store
        self.model_inference_service = model_inference_service
        self.local_explainers = dict(local_explainers)
        self.result_interpreter_service = result_interpreter_service
        self.result_interpreter_client = result_interpreter_client
        self.outbound_interpreter_policy = outbound_interpreter_policy
        self.result_interpreter_runtime = result_interpreter_runtime or ResultInterpreterRuntimeConfiguration.disabled()
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

    def prepare_interpretation(
        self,
        *,
        evidence: LocalExplanationEvidence,
        descriptions_by_feature_id: Mapping[str, str] | None = None,
    ) -> ResultInterpreterRequest:
        if self.result_interpreter_service is None:
            raise ValueError("Result interpreter service is not configured.")
        return self.result_interpreter_service.build_request(
            evidence=evidence,
            descriptions_by_feature_id=descriptions_by_feature_id,
        )

    def interpret(
        self,
        *,
        request: ResultInterpreterRequest,
    ) -> ResultInterpretationOutcome:
        # The application boundary is deliberately authoritative.  A frontend
        # must not be able to bypass a disabled or incomplete runtime setup.
        if not self.result_interpreter_runtime.is_ready:
            raise ValueError("Result interpreter runtime is not ready.")
        if self.result_interpreter_service is None:
            raise ValueError("Result interpreter service is not configured.")
        if self.result_interpreter_client is None:
            raise ValueError("Result interpreter client is not configured.")
        if self.outbound_interpreter_policy is None:
            raise ValueError("Outbound interpreter policy is not configured.")
        if (
            self.outbound_interpreter_policy.policy_id != "REDACTED_V1"
            or self.outbound_interpreter_policy.policy_version != 1
        ):
            raise ValueError("Only REDACTED_V1 outbound interpreter policy is permitted.")

        self.result_interpreter_service.validate_request(request)
        dispatch = self.outbound_interpreter_policy.project(request)
        response = self.result_interpreter_service.interpret_request(
            request=request,
            client=PolicyBoundResultInterpreterClient(
                underlying_client=self.result_interpreter_client,
                dispatch=dispatch,
            ),
        )
        return ResultInterpretationOutcome(
            response=response,
            dispatch_receipt=dispatch.receipt,
        )

    def capabilities(
        self,
        *,
        experiment_artifact_id: str | None = None,
        prepared_dataset_context: Any | None = None,
        loaded_model_version: LoadedModelVersion | None = None,
        prediction_batch: PredictionBatch | None = None,
        selected_row_id: str | None = None,
        local_explanation_evidence: LocalExplanationEvidence | None = None,
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
            "result_interpretation": self._result_interpretation_capability(local_explanation_evidence),
        }

    def _result_interpretation_capability(
        self,
        evidence: LocalExplanationEvidence | None,
    ) -> CapabilityStatus:
        runtime = self.result_interpreter_runtime
        if evidence is None:
            return CapabilityStatus("WAITING_FOR_INPUT", "LOCAL_EXPLANATION_MISSING")
        if runtime.policy_mode == "DISABLED":
            return CapabilityStatus("DISABLED", "EXTERNAL_DATA_POLICY_DISABLED")
        if runtime.policy_mode != "REDACTED_V1":
            return CapabilityStatus("MISCONFIGURED", "EXTERNAL_DATA_POLICY_INVALID")
        if not runtime.provider_configured:
            return CapabilityStatus("MISCONFIGURED", "RESULT_INTERPRETER_PROVIDER_MISSING")
        if not runtime.provider_registered:
            return CapabilityStatus("MISCONFIGURED", "RESULT_INTERPRETER_PROVIDER_NOT_REGISTERED")
        if not runtime.model_configured:
            return CapabilityStatus("MISCONFIGURED", "RESULT_INTERPRETER_MODEL_MISSING")
        if not runtime.credentials_configured:
            return CapabilityStatus("MISCONFIGURED", "RESULT_INTERPRETER_CREDENTIALS_MISSING")
        if (
            self.result_interpreter_service is None
            or self.result_interpreter_client is None
            or self.outbound_interpreter_policy is None
            or self.outbound_interpreter_policy.policy_id != "REDACTED_V1"
            or self.outbound_interpreter_policy.policy_version != 1
        ):
            return CapabilityStatus("MISCONFIGURED", "RESULT_INTERPRETER_RUNTIME_INCOMPLETE")
        return CapabilityStatus("AVAILABLE", "RESULT_INTERPRETER_READY")
