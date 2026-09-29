"""Framework-neutral feature selection derived from a trusted prepared context."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from komus_risk.contracts import FeatureUsageStatus
from komus_risk.preparation import PreparedDatasetContext


class FeatureSelectionError(ValueError):
    """Stable validation error for a feature-selection request."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FeatureSelectionDatasetSummary:
    display_name: str
    row_count: int
    column_count: int
    source_type: str
    source_format: str


@dataclass(frozen=True, slots=True)
class SelectableFeature:
    feature_id: str
    display_name_ru: str
    description_ru: str
    column_name: str
    group_id: str
    display_order: int


@dataclass(frozen=True, slots=True)
class SelectableFeatureGroup:
    group_id: str
    name_ru: str
    description_ru: str
    display_order: int


@dataclass(frozen=True, slots=True)
class FeatureSelectionView:
    dataset: FeatureSelectionDatasetSummary
    available_count: int
    selected_feature_ids: tuple[str, ...]
    selected_count: int
    groups: tuple[SelectableFeatureGroup, ...]
    features: tuple[SelectableFeature, ...]


class FeatureSelectionService:
    """Reads and validates only MODEL_ALLOWED rows from FeatureRegistry."""

    def initial_selection(self, context: PreparedDatasetContext) -> tuple[str, ...]:
        return tuple(item.feature_id for item in self._allowed_specs(context))

    def normalize_selection(self, context: PreparedDatasetContext, requested_ids: Iterable[str]) -> tuple[str, ...]:
        requested = tuple(requested_ids)
        if len(requested) != len(set(requested)):
            raise FeatureSelectionError("DUPLICATE_FEATURE_ID")
        all_specs = {item.feature_id: item for item in context.feature_registry.ordered_features()}
        for feature_id in requested:
            if not isinstance(feature_id, str) or not feature_id.strip():
                raise FeatureSelectionError("INVALID_FEATURE_ID")
            spec = all_specs.get(feature_id)
            if spec is None:
                raise FeatureSelectionError("UNKNOWN_FEATURE_ID")
            if spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED:
                raise FeatureSelectionError("FORBIDDEN_FEATURE_ID")
        requested_set = set(requested)
        return tuple(item.feature_id for item in self._allowed_specs(context) if item.feature_id in requested_set)

    def describe(self, context: PreparedDatasetContext, selected_feature_ids: Iterable[str]) -> FeatureSelectionView:
        selected = self.normalize_selection(context, selected_feature_ids)
        allowed = self._allowed_specs(context)
        allowed_group_ids = {item.group_id for item in allowed}
        contract = context.loaded_dataset.contract
        return FeatureSelectionView(
            dataset=FeatureSelectionDatasetSummary(context.display_name, contract.row_count, contract.column_count, contract.source_type, context.loaded_dataset.source_format),
            available_count=len(allowed), selected_feature_ids=selected, selected_count=len(selected),
            groups=tuple(SelectableFeatureGroup(group.group_id, group.name_ru, group.description_ru, group.display_order) for group in context.feature_registry.ordered_groups() if group.group_id in allowed_group_ids),
            features=tuple(SelectableFeature(item.feature_id, item.display_name_ru, item.description_ru, item.column_name, item.group_id, item.display_order) for item in allowed),
        )

    @staticmethod
    def _allowed_specs(context: PreparedDatasetContext):
        return tuple(item for item in context.feature_registry.ordered_features() if item.usage_status is FeatureUsageStatus.MODEL_ALLOWED)
