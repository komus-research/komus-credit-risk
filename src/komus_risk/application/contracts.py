"""Frontend-independent request contract for an experiment use case."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RunExperimentRequest:
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
    configuration_mode: str = "RECOMMENDED"
    user_overrides: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        feature_ids = tuple(self.selected_feature_ids)
        changed_elements = tuple(self.changed_elements)
        if not feature_ids or any(not isinstance(item, str) or not item.strip() for item in feature_ids):
            raise ValueError("selected_feature_ids must be a non-empty sequence of feature IDs.")
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("selected_feature_ids must not contain duplicates.")
        for name in ("model_id", "protocol_id", "protocol_version", "evaluation_level"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
        if self.folds < 1:
            raise ValueError("folds must be at least one.")
        if self.changed_dimension not in {None, "model", "feature_set"}:
            raise ValueError("changed_dimension must be None, model, or feature_set.")
        if self.reference_artifact_id is None and (self.changed_dimension is not None or changed_elements):
            raise ValueError("Change declaration requires reference_artifact_id.")
        if self.changed_dimension is None and changed_elements:
            raise ValueError("changed_elements requires changed_dimension.")
        if self.configuration_mode not in {"RECOMMENDED", "ADVANCED"}:
            raise ValueError("configuration_mode must be RECOMMENDED or ADVANCED.")
        if not isinstance(self.user_overrides, Mapping) or any(
            not isinstance(key, str) for key in self.user_overrides
        ):
            raise ValueError("user_overrides must be a mapping with string paths.")
        object.__setattr__(self, "selected_feature_ids", feature_ids)
        object.__setattr__(self, "changed_elements", changed_elements)
        object.__setattr__(self, "user_overrides", deepcopy(dict(self.user_overrides)))
