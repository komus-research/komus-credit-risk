"""Read/plan service; it never creates artifacts or starts experiment execution."""

from __future__ import annotations

from komus_risk.contracts import FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.model_platform import (
    ModelCatalogEntry,
    ModelCatalogService,
    ModelConfigurationError,
    ModelConfigurationService,
    ModelPluginRegistry,
)
from komus_risk.registries import FeatureRegistry

from .contracts import (
    DatasetPassport,
    ExperimentPlan,
    FeatureGroupView,
    FeatureView,
    PlanningRequestMetadata,
    PopulationSummary,
)


class ExperimentPlanningService:
    """Produces immutable plans from feature contracts and the trusted plugin catalog."""

    def __init__(self, *, model_plugin_registry: ModelPluginRegistry) -> None:
        self._model_catalog_service = ModelCatalogService(model_plugin_registry)
        self._model_configuration_service = ModelConfigurationService(
            model_plugin_registry
        )

    def describe_dataset(self, loaded_dataset: LoadedDataset) -> DatasetPassport:
        return DatasetPassport.from_contract(loaded_dataset.contract)

    def list_features(
        self, feature_registry: FeatureRegistry
    ) -> tuple[FeatureView, ...]:
        return tuple(
            self._feature_view(spec)
            for spec in sorted(
                feature_registry._features.values(),
                key=lambda item: (item.display_order, item.feature_id),
            )
        )

    def list_feature_groups(
        self, feature_registry: FeatureRegistry
    ) -> tuple[FeatureGroupView, ...]:
        return tuple(
            FeatureGroupView(
                group.group_id,
                group.name_ru,
                group.description_ru,
                group.display_order,
            )
            for group in sorted(
                feature_registry._groups.values(),
                key=lambda item: (item.display_order, item.group_id),
            )
        )

    def list_models(self) -> tuple[ModelCatalogEntry, ...]:
        """Return catalog entries without caller-supplied registries or factories."""
        return self._model_catalog_service.list_models()

    def build_plan(
        self,
        request: PlanningRequestMetadata,
        *,
        loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
    ) -> ExperimentPlan:
        if not isinstance(request, PlanningRequestMetadata):
            raise TypeError("request must be PlanningRequestMetadata.")
        contract = loaded_dataset.contract
        if (
            contract.feature_registry_id != feature_registry.registry_id
            or contract.feature_registry_hash != feature_registry.registry_hash
        ):
            raise ValueError("DatasetContract is inconsistent with FeatureRegistry.")
        dataset = self.describe_dataset(loaded_dataset)
        population_summary = PopulationSummary(
            population.population_id,
            population.population_fingerprint,
            population.partition_role,
            len(population.row_positions),
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
            model = self._model_catalog_service.get(request.model_id)
        except KeyError:
            model = None
            errors.append(f"unknown_model:{request.model_id}")
        else:
            if not model.runnable:
                errors.append(f"non_runnable_model:{request.model_id}")
        resolved_configuration = None
        if model is not None:
            try:
                resolved_configuration = self._model_configuration_service.resolve(
                    model_id=request.model_id,
                    mode=request.configuration_mode,
                    user_overrides=request.user_overrides,
                )
            except ModelConfigurationError as error:
                errors.append(f"model_configuration:{error.code}")
        selected_features = tuple(self._feature_view(spec) for spec in selected_specs)
        return ExperimentPlan(
            request=request,
            dataset=dataset,
            population=population_summary,
            selected_feature_ids=request.selected_feature_ids,
            selected_features=selected_features,
            feature_groups=tuple(sorted({spec.group_id for spec in selected_specs})),
            model=model,
            resolved_model_configuration=resolved_configuration,
            is_valid=not errors,
            validation_errors=tuple(errors),
        )

    @staticmethod
    def _feature_view(spec) -> FeatureView:
        return FeatureView(
            spec.feature_id,
            spec.column_name,
            spec.display_name_ru,
            spec.description_ru,
            spec.group_id,
            spec.usage_status,
            spec.usage_status is FeatureUsageStatus.MODEL_ALLOWED,
            spec.blocked_reason,
            spec.display_order,
        )
