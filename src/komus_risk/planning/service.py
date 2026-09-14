"""Read/plan service; it never creates artifacts or starts experiment execution."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from komus_risk.contracts import FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.models import ModelAdapterFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry

from .contracts import (
    DatasetPassport,
    ExperimentPlan,
    FeatureView,
    ModelView,
    PlanningRequestMetadata,
    PopulationSummary,
    freeze_value,
)


class ExperimentPlanningService:
    """Produces immutable planning DTOs from trusted contracts and metadata."""

    def describe_dataset(self, loaded_dataset: LoadedDataset) -> DatasetPassport:
        return DatasetPassport.from_contract(loaded_dataset.contract)

    def list_features(self, feature_registry: FeatureRegistry) -> tuple[FeatureView, ...]:
        return tuple(
            self._feature_view(spec)
            for spec in sorted(feature_registry._features.values(), key=lambda item: (item.display_order, item.feature_id))
        )

    def list_models(
        self, model_registry: ModelRegistry, model_factories: Mapping[str, ModelAdapterFactory],
    ) -> tuple[ModelView, ...]:
        factories = self._validated_factories(model_registry, model_factories)
        return tuple(self._model_view(spec, factories.get(spec.model_id)) for spec in model_registry.list())

    def build_plan(
        self,
        request: PlanningRequestMetadata,
        *,
        loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry,
        model_registry: ModelRegistry,
        model_factories: Mapping[str, ModelAdapterFactory],
        population: EvaluationPopulation,
    ) -> ExperimentPlan:
        if not isinstance(request, PlanningRequestMetadata):
            raise TypeError("request must be PlanningRequestMetadata.")
        contract = loaded_dataset.contract
        if contract.feature_registry_id != feature_registry.registry_id or contract.feature_registry_hash != feature_registry.registry_hash:
            raise ValueError("DatasetContract is inconsistent with FeatureRegistry.")
        factories = self._validated_factories(model_registry, model_factories)
        dataset = self.describe_dataset(loaded_dataset)
        population_summary = PopulationSummary(
            population.population_id, population.population_fingerprint, population.partition_role, len(population.row_positions)
        )
        selected_specs = []
        errors: list[str] = []
        for feature_id in request.selected_feature_ids:
            try:
                spec = feature_registry.get(feature_id)
            except KeyError:
                errors.append(f"unknown_feature:{feature_id}")
                continue
            if spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED:
                errors.append(f"forbidden_feature:{feature_id}")
                continue
            selected_specs.append(spec)
        try:
            model_spec = model_registry.get(request.model_id)
        except KeyError:
            model = None
            errors.append(f"unknown_model:{request.model_id}")
        else:
            model = self._model_view(model_spec, factories.get(model_spec.model_id))
            if not model.runnable:
                errors.append(f"non_runnable_model:{request.model_id}")
        selected_features = tuple(self._feature_view(spec) for spec in selected_specs)
        return ExperimentPlan(
            request=request,
            dataset=dataset,
            population=population_summary,
            selected_feature_ids=request.selected_feature_ids,
            selected_features=selected_features,
            feature_groups=tuple(sorted({spec.group_id for spec in selected_specs})),
            model=model,
            is_valid=not errors,
            validation_errors=tuple(errors),
        )

    @staticmethod
    def _validated_factories(
        model_registry: ModelRegistry, model_factories: Mapping[str, ModelAdapterFactory],
    ) -> dict[str, ModelAdapterFactory]:
        factories = dict(model_factories)
        for key, factory in factories.items():
            if key != getattr(factory, "model_id", None):
                raise ValueError("Model factory mapping key must match factory.model_id.")
            spec = model_registry.get(factory.model_id)
            if factory.model_version != spec.version or factory.adapter_version != spec.adapter_version:
                raise ValueError("Model factory identity is inconsistent with ModelRegistry.")
        return factories

    @staticmethod
    def _feature_view(spec) -> FeatureView:
        return FeatureView(
            spec.feature_id, spec.column_name, spec.display_name_ru, spec.description_ru, spec.group_id,
            spec.usage_status, spec.usage_status is FeatureUsageStatus.MODEL_ALLOWED, spec.display_order,
        )

    @staticmethod
    def _model_view(spec, factory: ModelAdapterFactory | None) -> ModelView:
        return ModelView(
            spec.model_id, spec.display_name_ru, spec.version, spec.task_types, spec.description_ru,
            freeze_value(deepcopy(spec.default_profile)), freeze_value(deepcopy(spec.runtime_requirements)),
            spec.adapter_version, factory is not None,
        )
