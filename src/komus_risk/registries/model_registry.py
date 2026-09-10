"""Независимый от ML-библиотек реестр метаданных моделей."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле «{name}» должно быть непустой строкой.")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Метаданные модели, не содержащие adapter или реализацию estimator."""

    model_id: str
    display_name_ru: str
    version: str
    task_types: tuple[str, ...]
    description_ru: str
    default_profile: dict[str, Any]
    runtime_requirements: dict[str, Any]
    adapter_version: str

    def __post_init__(self) -> None:
        for name in (
            "model_id", "display_name_ru", "version", "description_ru", "adapter_version",
        ):
            _required_text(name, getattr(self, name))
        task_types = tuple(self.task_types)
        if not task_types or any(not isinstance(item, str) or not item.strip() for item in task_types):
            raise ValueError("Для модели требуется хотя бы один тип задачи.")
        if not isinstance(self.default_profile, dict) or not isinstance(self.runtime_requirements, dict):
            raise ValueError("Профиль и требования запуска должны быть словарями.")
        object.__setattr__(self, "task_types", task_types)
        object.__setattr__(self, "default_profile", dict(self.default_profile))
        object.__setattr__(self, "runtime_requirements", dict(self.runtime_requirements))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_types"] = list(self.task_types)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelSpec":
        return cls(**value)


class ModelRegistry:
    """Хранит model spec и не допускает конфликтующих описаний одного ID."""

    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}

    def register(self, spec: ModelSpec) -> ModelSpec:
        """Регистрирует model spec или безопасно повторяет идентичную регистрацию."""
        if not isinstance(spec, ModelSpec):
            raise TypeError("В реестр можно зарегистрировать только ModelSpec.")
        existing = self._models.get(spec.model_id)
        if existing is None:
            self._models[spec.model_id] = spec
            return spec
        if existing != spec:
            raise ValueError(
                f"Модель с идентификатором «{spec.model_id}» уже зарегистрирована "
                "с несовместимым описанием."
            )
        return existing

    def get(self, model_id: str) -> ModelSpec:
        """Возвращает spec по ID или сообщает по-русски об отсутствии модели."""
        try:
            return self._models[model_id]
        except KeyError as error:
            raise KeyError(f"Модель с идентификатором «{model_id}» не зарегистрирована.") from error

    def list(self) -> tuple[ModelSpec, ...]:
        """Возвращает модели в стабильном порядке идентификаторов."""
        return tuple(self._models[model_id] for model_id in sorted(self._models))
