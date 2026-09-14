"""Immutable read DTOs for planning an experiment without executing it."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from komus_risk.contracts import DatasetContract, FeatureUsageStatus


def freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DatasetPassport:
    dataset_id: str
    dataset_version: str
    dataset_fingerprint: str
    dataset_name: str
    source_type: str
    row_count: int
    column_count: int
    target_column: str
    positive_class: str | int | float | bool
    identifier_column: str
    feature_registry_id: str
    feature_registry_hash: str
    validation_status: str
    final_test_locked: bool

    @classmethod
    def from_contract(cls, contract: DatasetContract) -> "DatasetPassport":
        return cls(**contract.to_dict())


@dataclass(frozen=True, slots=True)
class FeatureView:
    feature_id: str
    column_name: str
    display_name_ru: str
    description_ru: str
    group_id: str
    usage_status: FeatureUsageStatus
    selectable: bool
    display_order: int


@dataclass(frozen=True, slots=True)
class ModelView:
    model_id: str
    display_name_ru: str
    model_version: str
    task_types: tuple[str, ...]
    description_ru: str
    default_profile: Mapping[str, Any]
    runtime_requirements: Mapping[str, Any]
    adapter_version: str
    runnable: bool


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    population_id: str
    population_fingerprint: str
    partition_role: str
    population_size: int


@dataclass(frozen=True, slots=True)
class PlanningRequestMetadata:
    selected_feature_ids: tuple[str, ...]
    model_id: str
    protocol_id: str
    protocol_version: str
    seed: int
    folds: int
    evaluation_level: str
    reference_artifact_id: str | None
    changed_dimension: str | None
    changed_elements: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_feature_ids", tuple(self.selected_feature_ids))
        object.__setattr__(self, "changed_elements", tuple(self.changed_elements))


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    request: PlanningRequestMetadata
    dataset: DatasetPassport
    population: PopulationSummary
    selected_feature_ids: tuple[str, ...]
    selected_features: tuple[FeatureView, ...]
    feature_groups: tuple[str, ...]
    model: ModelView | None
    is_valid: bool
    validation_errors: tuple[str, ...]
