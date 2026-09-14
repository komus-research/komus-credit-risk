"""Thin orchestration of existing dataset, runner, artifact, and comparison services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from komus_risk.artifacts import ExperimentArtifactStore, LoadedExperimentArtifact
from komus_risk.comparison import ComparisonResult, ExperimentComparisonService
from komus_risk.contracts import ExperimentConfig, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentProgressEvent, ExperimentRunner
from komus_risk.models import ModelAdapterFactory
from komus_risk.planning.contracts import PlanningRequestMetadata
from komus_risk.registries import FeatureRegistry, ModelRegistry

from .contracts import RunExperimentRequest


def to_planning_request_metadata(request: RunExperimentRequest) -> PlanningRequestMetadata:
    """Explicitly adapt an application request for the planning boundary."""
    if not isinstance(request, RunExperimentRequest):
        raise TypeError("request must be RunExperimentRequest.")
    return PlanningRequestMetadata(
        selected_feature_ids=request.selected_feature_ids,
        model_id=request.model_id,
        protocol_id=request.protocol_id,
        protocol_version=request.protocol_version,
        seed=request.seed,
        folds=request.folds,
        evaluation_level=request.evaluation_level,
        reference_artifact_id=request.reference_artifact_id,
        changed_dimension=request.changed_dimension,
        changed_elements=request.changed_elements,
    )


class ExperimentApplicationService:
    """Runs one trusted request and persists the completed evidence bundle."""

    def __init__(
        self,
        *,
        model_registry: ModelRegistry,
        model_factories: Mapping[str, ModelAdapterFactory],
        artifact_store: ExperimentArtifactStore,
        comparison_service: ExperimentComparisonService,
        code_version: str,
    ) -> None:
        if not isinstance(code_version, str) or not code_version.strip():
            raise ValueError("code_version must be a non-empty string.")
        self.model_registry = model_registry
        self.model_factories = dict(model_factories)
        self.artifact_store = artifact_store
        self.comparison_service = comparison_service
        self.code_version = code_version
        for key, factory in self.model_factories.items():
            if key != getattr(factory, "model_id", None):
                raise ValueError("Model factory mapping key must match factory.model_id.")
            spec = self.model_registry.get(factory.model_id)
            if factory.model_version != spec.version or factory.adapter_version != spec.adapter_version:
                raise ValueError("Model factory identity is incompatible with ModelRegistry.")

    def run_experiment(
        self,
        *,
        loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
        request: RunExperimentRequest,
        progress_listener: Callable[[ExperimentProgressEvent], None] | None = None,
    ) -> LoadedExperimentArtifact:
        if not isinstance(request, RunExperimentRequest):
            raise TypeError("request must be RunExperimentRequest.")
        contract = loaded_dataset.contract
        if contract.feature_registry_id != feature_registry.registry_id or contract.feature_registry_hash != feature_registry.registry_hash:
            raise ValueError("Loaded dataset is not bound to the supplied FeatureRegistry.")
        feature_specs = feature_registry.resolve(request.selected_feature_ids)
        if any(spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED for spec in feature_specs):
            raise ValueError("Every selected feature must be MODEL_ALLOWED.")
        feature_groups = tuple(sorted({spec.group_id for spec in feature_specs}))
        model_spec = self.model_registry.get(request.model_id)
        try:
            factory = self.model_factories[request.model_id]
        except KeyError as error:
            raise ValueError("Selected ModelSpec has no injected runtime factory.") from error
        if (
            factory.model_id != model_spec.model_id
            or factory.model_version != model_spec.version
            or factory.adapter_version != model_spec.adapter_version
        ):
            raise ValueError("Selected factory identity is incompatible with ModelSpec.")
        reference_result_id = None
        if request.reference_artifact_id is not None:
            reference_result_id = self.artifact_store.load(request.reference_artifact_id).run_output.result.result_id
        config = ExperimentConfig(
            experiment_id=str(uuid4()),
            dataset_id=contract.dataset_id,
            dataset_fingerprint=contract.dataset_fingerprint,
            target=contract.target_column,
            feature_ids=request.selected_feature_ids,
            feature_set_hash=None,
            feature_groups=feature_groups,
            model_id=model_spec.model_id,
            model_version=model_spec.version,
            model_parameters=deepcopy(model_spec.default_profile),
            protocol_id=request.protocol_id,
            protocol_version=request.protocol_version,
            seed=request.seed,
            folds=request.folds,
            evaluation_level=request.evaluation_level,
            reference_result_id=reference_result_id,
            changed_dimension=request.changed_dimension,
            changed_elements=request.changed_elements,
        )
        runner = ExperimentRunner(
            feature_registry=feature_registry,
            model_registry=self.model_registry,
            adapter_factory=factory,
            code_version=self.code_version,
        )
        run_output = runner.run(loaded_dataset, config, population, progress_listener=progress_listener)
        self._notify_progress(progress_listener, ExperimentProgressEvent("persistence_started", None, request.folds))
        artifact = self.artifact_store.save(
            config=config,
            dataset_contract=contract,
            population=population,
            run_output=run_output,
        )
        self._notify_progress(progress_listener, ExperimentProgressEvent("completed", None, request.folds))
        return artifact

    @staticmethod
    def _notify_progress(
        listener: Callable[[ExperimentProgressEvent], None] | None,
        event: ExperimentProgressEvent,
    ) -> None:
        if listener is None:
            return
        try:
            listener(event)
        except Exception:
            return

    def load_experiment(self, artifact_id: str) -> LoadedExperimentArtifact:
        return self.artifact_store.load(artifact_id)

    def compare_experiments(self, reference_artifact_id: str, candidate_artifact_id: str) -> ComparisonResult:
        reference = self.artifact_store.load(reference_artifact_id)
        candidate = self.artifact_store.load(candidate_artifact_id)
        return self.comparison_service.compare(
            reference.to_comparison_subject(), candidate.to_comparison_subject()
        )
