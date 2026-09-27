"""Thin orchestration of existing dataset, runner, artifact, and comparison services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from uuid import uuid4

from komus_risk.artifacts import ExperimentArtifactStore, LoadedExperimentArtifact
from komus_risk.comparison import ComparisonResult, ExperimentComparisonService
from komus_risk.contracts import ExperimentConfig, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import (
    EvaluationPopulation,
    ExperimentProgressEvent,
    ExperimentRunner,
)
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import (
    ModelConfigurationRecord,
    ModelConfigurationService,
    ModelConfigurationSmokeTestService,
    ModelPluginRegistry,
    SmokeEvidence,
    SmokeStatus,
)
from komus_risk.models import ModelAdapterFactory
from komus_risk.planning.contracts import PlanningRequestMetadata
from komus_risk.preparation import PreparedDatasetContext
from komus_risk.registries import FeatureRegistry, ModelRegistry

from .contracts import RunExperimentRequest


class SmokeGateError(ValueError):
    """Stable fail-closed boundary for mandatory configuration smoke."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def to_planning_request_metadata(
    request: RunExperimentRequest,
) -> PlanningRequestMetadata:
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
        configuration_mode=request.configuration_mode,
        user_overrides=request.user_overrides,
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
        model_plugin_registry: ModelPluginRegistry | None = None,
    ) -> None:
        if not isinstance(code_version, str) or not code_version.strip():
            raise ValueError("code_version must be a non-empty string.")
        self.model_registry = model_registry
        self.model_factories = dict(model_factories)
        self.artifact_store = artifact_store
        self.comparison_service = comparison_service
        self.code_version = code_version
        self.model_configuration_service = (
            ModelConfigurationService(model_plugin_registry)
            if model_plugin_registry is not None
            else None
        )
        self._model_plugin_registry = model_plugin_registry
        self._smoke_service = ModelConfigurationSmokeTestService()
        self._smoke_evidence: dict[str, SmokeEvidence] = {}
        for key, factory in self.model_factories.items():
            if key != getattr(factory, "model_id", None):
                raise ValueError(
                    "Model factory mapping key must match factory.model_id."
                )
            spec = self.model_registry.get(factory.model_id)
            if (
                factory.model_version != spec.version
                or factory.adapter_version != spec.adapter_version
            ):
                raise ValueError(
                    "Model factory identity is incompatible with ModelRegistry."
                )

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
        if (
            contract.feature_registry_id != feature_registry.registry_id
            or contract.feature_registry_hash != feature_registry.registry_hash
        ):
            raise ValueError(
                "Loaded dataset is not bound to the supplied FeatureRegistry."
            )
        feature_specs = feature_registry.resolve(request.selected_feature_ids)
        if any(
            spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED
            for spec in feature_specs
        ):
            raise ValueError("Every selected feature must be MODEL_ALLOWED.")
        feature_groups = tuple(sorted({spec.group_id for spec in feature_specs}))
        model_spec = self.model_registry.get(request.model_id)
        configuration_record = None
        matching_smoke = None
        if self.model_configuration_service is None:
            if request.configuration_mode != "RECOMMENDED" or request.user_overrides:
                raise ValueError("Model configuration service is not configured.")
            resolved_parameters = deepcopy(model_spec.default_profile)
        else:
            resolved = self.model_configuration_service.resolve(
                model_id=request.model_id,
                mode=request.configuration_mode,
                user_overrides=request.user_overrides,
            )
            if (resolved.model_version, resolved.adapter_version) != (
                model_spec.version,
                model_spec.adapter_version,
            ):
                raise ValueError(
                    "Resolved model configuration is incompatible with ModelSpec."
                )
            resolved_parameters = resolved.resolved_parameters_dict()
            plugin = self._model_plugin_registry.get(request.model_id)
            configuration_record = ModelConfigurationRecord.from_resolved(
                resolved, plugin
            )
            context = self._prepared_context(
                loaded_dataset, feature_registry, population
            )
            expected_identity = self._smoke_service.expected_identity(
                context,
                request.selected_feature_ids,
                configuration_record,
                request.seed,
            )
            matching_smoke = self._smoke_evidence.get(expected_identity)
            if matching_smoke is None:
                raise SmokeGateError("SMOKE_REQUIRED")
            if matching_smoke.status is SmokeStatus.FAIL:
                raise SmokeGateError("SMOKE_FAILED")
            if matching_smoke.status is not SmokeStatus.PASS:
                raise SmokeGateError("SMOKE_NOT_MATCHING")
        try:
            factory = self.model_factories[request.model_id]
        except KeyError as error:
            raise ValueError(
                "Selected ModelSpec has no injected runtime factory."
            ) from error
        if (
            factory.model_id != model_spec.model_id
            or factory.model_version != model_spec.version
            or factory.adapter_version != model_spec.adapter_version
        ):
            raise ValueError(
                "Selected factory identity is incompatible with ModelSpec."
            )
        reference_result_id = None
        if request.reference_artifact_id is not None:
            reference_result_id = self.artifact_store.load(
                request.reference_artifact_id
            ).run_output.result.result_id
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
            model_parameters=resolved_parameters,
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
        run_output = runner.run(
            loaded_dataset, config, population, progress_listener=progress_listener
        )
        self._notify_progress(
            progress_listener,
            ExperimentProgressEvent("persistence_started", None, request.folds),
        )
        artifact = self.artifact_store.save(
            config=config,
            dataset_contract=contract,
            population=population,
            run_output=run_output,
            configuration_record=configuration_record,
            smoke_evidence=matching_smoke,
        )
        self._notify_progress(
            progress_listener, ExperimentProgressEvent("completed", None, request.folds)
        )
        return artifact

    def run_configuration_smoke(
        self,
        *,
        loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
        request: RunExperimentRequest,
    ) -> SmokeEvidence:
        """Run and retain backend-owned technical evidence for one exact request."""
        if (
            self.model_configuration_service is None
            or self._model_plugin_registry is None
        ):
            raise SmokeGateError("SMOKE_UNAVAILABLE")
        contract = loaded_dataset.contract
        if (
            contract.feature_registry_id != feature_registry.registry_id
            or contract.feature_registry_hash != feature_registry.registry_hash
        ):
            raise SmokeGateError("INVALID_DATASET_CONTEXT")
        resolved = self.model_configuration_service.resolve(
            model_id=request.model_id,
            mode=request.configuration_mode,
            user_overrides=request.user_overrides,
        )
        plugin = self._model_plugin_registry.get(request.model_id)
        context = self._prepared_context(loaded_dataset, feature_registry, population)
        evidence = self._smoke_service.run(
            context, request.selected_feature_ids, resolved, request.seed, plugin
        )
        self._smoke_evidence[evidence.smoke_identity] = evidence
        return evidence

    @staticmethod
    def _prepared_context(
        loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
    ) -> PreparedDatasetContext:
        context_id = stable_hash(
            {
                "dataset_id": loaded_dataset.contract.dataset_id,
                "dataset_fingerprint": loaded_dataset.contract.dataset_fingerprint,
                "feature_registry_id": feature_registry.registry_id,
                "feature_registry_hash": feature_registry.registry_hash,
                "population_id": population.population_id,
                "population_fingerprint": population.population_fingerprint,
            }
        )
        return PreparedDatasetContext(
            context_id,
            loaded_dataset.contract.dataset_name,
            loaded_dataset,
            feature_registry,
            population,
        )

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

    def compare_experiments(
        self, reference_artifact_id: str, candidate_artifact_id: str
    ) -> ComparisonResult:
        reference = self.artifact_store.load(reference_artifact_id)
        candidate = self.artifact_store.load(candidate_artifact_id)
        return self.comparison_service.compare(
            reference.to_comparison_subject(), candidate.to_comparison_subject()
        )
