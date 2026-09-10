"""Явный runtime-реестр признаков и групп."""

from __future__ import annotations

from collections.abc import Iterable

from komus_risk.contracts import FeatureGroup, FeatureSpec
from komus_risk.hashing import stable_hash


class FeatureRegistry:
    """Хранит спецификации признаков без эвристик или изменения их статусов."""

    def __init__(
        self,
        registry_id: str,
        feature_specs: Iterable[FeatureSpec],
        feature_groups: Iterable[FeatureGroup] = (),
    ) -> None:
        if not isinstance(registry_id, str) or not registry_id.strip():
            raise ValueError("Идентификатор реестра признаков должен быть непустой строкой.")
        self.registry_id = registry_id
        self._features = self._index_features(feature_specs)
        self._groups = self._index_groups(feature_groups)
        self._validate_cross_integrity(self._features, self._groups)
        self.registry_hash = stable_hash(
            {
                "registry_id": self.registry_id,
                "feature_specs": [self._features[key].to_dict() for key in sorted(self._features)],
                "feature_groups": [self._groups[key].to_dict() for key in sorted(self._groups)],
            }
        )

    @staticmethod
    def _index_features(feature_specs: Iterable[FeatureSpec]) -> dict[str, FeatureSpec]:
        features: dict[str, FeatureSpec] = {}
        for spec in feature_specs:
            if not isinstance(spec, FeatureSpec):
                raise TypeError("Реестр признаков принимает только FeatureSpec.")
            if spec.feature_id in features:
                raise ValueError(f"Идентификатор признака «{spec.feature_id}» повторяется в реестре.")
            features[spec.feature_id] = spec
        return features

    @staticmethod
    def _index_groups(feature_groups: Iterable[FeatureGroup]) -> dict[str, FeatureGroup]:
        groups: dict[str, FeatureGroup] = {}
        for group in feature_groups:
            if not isinstance(group, FeatureGroup):
                raise TypeError("Реестр групп принимает только FeatureGroup.")
            if group.group_id in groups:
                raise ValueError(f"Идентификатор группы «{group.group_id}» повторяется в реестре.")
            groups[group.group_id] = group
        return groups

    @staticmethod
    def _validate_cross_integrity(
        features: dict[str, FeatureSpec], groups: dict[str, FeatureGroup]
    ) -> None:
        for spec in features.values():
            if spec.group_id not in groups:
                raise ValueError(
                    f"Признак «{spec.feature_id}» ссылается на неизвестную группу «{spec.group_id}»."
                )
        for group in groups.values():
            for feature_id in group.feature_ids:
                if feature_id not in features:
                    raise ValueError(
                        f"Группа «{group.group_id}» содержит неизвестный признак «{feature_id}»."
                    )
                actual_group_id = features[feature_id].group_id
                if actual_group_id != group.group_id:
                    raise ValueError(
                        f"Признак «{feature_id}» указан в группе «{group.group_id}"
                        f"», но FeatureSpec относит его к группе «{actual_group_id}»."
                    )

    def get(self, feature_id: str) -> FeatureSpec:
        """Возвращает признак по ID."""
        try:
            return self._features[feature_id]
        except KeyError as error:
            raise KeyError(f"Признак с идентификатором «{feature_id}» не зарегистрирован.") from error

    def resolve(self, feature_ids: Iterable[str]) -> tuple[FeatureSpec, ...]:
        """Разрешает переданный порядок идентификаторов в спецификации."""
        return tuple(self.get(feature_id) for feature_id in feature_ids)
