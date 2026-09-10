"""Контракты отдельных признаков и явно заданных групп."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class FeatureUsageStatus(StrEnum):
    """Роль признака в конкретном наборе данных."""

    MODEL_ALLOWED = "model_allowed"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    IDENTIFIER = "identifier"
    TARGET = "target"
    BLOCKED = "blocked"


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле «{name}» должно быть непустой строкой.")


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Описание признака и явное правило его использования."""

    feature_id: str
    column_name: str
    display_name_ru: str
    description_ru: str
    group_id: str
    dtype: str
    semantic_type: str
    origin: str
    usage_status: FeatureUsageStatus
    blocked_reason: str | None
    source_reference: str | None
    formula_hash: str | None
    display_order: int

    def __post_init__(self) -> None:
        for name in (
            "feature_id", "column_name", "display_name_ru", "description_ru",
            "group_id", "dtype", "semantic_type", "origin",
        ):
            _required_text(name, getattr(self, name))
        try:
            object.__setattr__(self, "usage_status", FeatureUsageStatus(self.usage_status))
        except ValueError as error:
            allowed = ", ".join(status.value for status in FeatureUsageStatus)
            raise ValueError(f"Неизвестный статус использования признака. Допустимо: {allowed}.") from error
        if self.display_order < 0:
            raise ValueError("Порядок отображения признака не может быть отрицательным.")
        if self.usage_status is FeatureUsageStatus.BLOCKED and not self.blocked_reason:
            raise ValueError("Для заблокированного признака требуется причина блокировки.")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["usage_status"] = self.usage_status.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FeatureSpec":
        return cls(**value)


@dataclass(frozen=True, slots=True)
class FeatureGroup:
    """Явно заданная группа признаков без эвристик по их именам."""

    group_id: str
    name_ru: str
    description_ru: str
    display_order: int
    source: str
    feature_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("group_id", "name_ru", "description_ru", "source"):
            _required_text(name, getattr(self, name))
        if self.display_order < 0:
            raise ValueError("Порядок отображения группы не может быть отрицательным.")
        feature_ids = tuple(self.feature_ids)
        if not feature_ids or any(not isinstance(item, str) or not item.strip() for item in feature_ids):
            raise ValueError("Группа должна содержать непустые идентификаторы признаков.")
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("Идентификаторы признаков в группе не должны повторяться.")
        object.__setattr__(self, "feature_ids", feature_ids)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["feature_ids"] = list(self.feature_ids)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FeatureGroup":
        return cls(**value)
