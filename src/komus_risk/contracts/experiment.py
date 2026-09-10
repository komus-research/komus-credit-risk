"""Контракты конфигурации и результата эксперимента без запуска ML."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from komus_risk.hashing import stable_hash


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле «{name}» должно быть непустой строкой.")


def _feature_set_hash(feature_ids: tuple[str, ...]) -> str:
    """Хеширует набор идентификаторов независимо от порядка передачи."""
    return stable_hash({"feature_ids": sorted(feature_ids)})


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Воспроизводимое описание будущего эксперимента, без ML-runner."""

    experiment_id: str
    dataset_id: str
    dataset_fingerprint: str
    target: str
    feature_ids: tuple[str, ...]
    feature_set_hash: str | None
    feature_groups: tuple[str, ...]
    model_id: str
    model_version: str
    model_parameters: dict[str, Any]
    protocol_id: str
    protocol_version: str
    seed: int
    folds: int
    evaluation_level: str
    reference_result_id: str | None
    changed_dimension: str | None
    changed_elements: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "experiment_id", "dataset_id", "dataset_fingerprint", "target", "model_id",
            "model_version", "protocol_id", "protocol_version", "evaluation_level",
        ):
            _required_text(name, getattr(self, name))
        feature_ids = tuple(self.feature_ids)
        feature_groups = tuple(self.feature_groups)
        changed_elements = tuple(self.changed_elements)
        if not feature_ids or any(not isinstance(item, str) or not item.strip() for item in feature_ids):
            raise ValueError("Эксперимент должен содержать непустой список идентификаторов признаков.")
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("Идентификаторы признаков эксперимента не должны повторяться.")
        if self.folds < 1:
            raise ValueError("Количество фолдов должно быть не меньше единицы.")
        if not isinstance(self.model_parameters, dict):
            raise ValueError("Параметры модели должны быть словарём.")
        object.__setattr__(self, "feature_ids", feature_ids)
        object.__setattr__(self, "feature_groups", feature_groups)
        object.__setattr__(self, "changed_elements", changed_elements)
        object.__setattr__(self, "model_parameters", dict(self.model_parameters))
        expected_hash = _feature_set_hash(feature_ids)
        if self.feature_set_hash is None:
            object.__setattr__(self, "feature_set_hash", expected_hash)
        elif self.feature_set_hash != expected_hash:
            raise ValueError("Хеш набора признаков не соответствует переданным идентификаторам.")

    @property
    def config_hash(self) -> str:
        """Детерминированный идентификатор конфигурации."""
        return stable_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["feature_ids"] = list(self.feature_ids)
        value["feature_groups"] = list(self.feature_groups)
        value["changed_elements"] = list(self.changed_elements)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExperimentConfig":
        return cls(**value)


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """Формат готового результата; метрики этим классом не рассчитываются."""

    result_id: str
    experiment_config_id: str
    config_hash: str
    dataset_fingerprint: str
    feature_set_hash: str
    model_id: str
    model_version: str
    evaluation_level: str
    metrics: dict[str, Any]
    confusion: dict[str, Any]
    fold_metrics: tuple[dict[str, Any], ...]
    runtime_seconds: float | None
    comparison: dict[str, Any]
    code_version: str
    created_at: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "result_id", "experiment_config_id", "config_hash", "dataset_fingerprint",
            "feature_set_hash", "model_id", "model_version", "evaluation_level",
            "code_version", "created_at",
        ):
            _required_text(name, getattr(self, name))
        if self.runtime_seconds is not None and self.runtime_seconds < 0:
            raise ValueError("Время выполнения не может быть отрицательным.")
        for name in ("metrics", "confusion", "comparison"):
            if not isinstance(getattr(self, name), dict):
                raise ValueError(f"Поле «{name}» должно быть словарём.")
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "confusion", dict(self.confusion))
        object.__setattr__(self, "comparison", dict(self.comparison))
        object.__setattr__(self, "fold_metrics", tuple(dict(item) for item in self.fold_metrics))
        object.__setattr__(self, "limitations", tuple(self.limitations))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fold_metrics"] = [dict(item) for item in self.fold_metrics]
        value["limitations"] = list(self.limitations)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExperimentResult":
        return cls(**value)
