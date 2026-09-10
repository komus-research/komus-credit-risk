"""Контракт метаданных датасета без хранения самих данных."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле «{name}» должно быть непустой строкой.")


@dataclass(frozen=True, slots=True)
class DatasetContract:
    """Паспорт датасета; dataframe и исходные байты в нём не хранятся."""

    dataset_id: str
    dataset_version: str
    dataset_name: str
    source_type: str
    dataset_fingerprint: str
    row_count: int
    column_count: int
    target_column: str
    positive_class: str | int | float | bool
    identifier_column: str
    feature_registry_id: str
    feature_registry_hash: str
    validation_status: str
    final_test_locked: bool

    def __post_init__(self) -> None:
        for name in (
            "dataset_id", "dataset_version", "dataset_name", "source_type",
            "dataset_fingerprint", "target_column", "identifier_column",
            "feature_registry_id", "feature_registry_hash", "validation_status",
        ):
            _required_text(name, getattr(self, name))
        if self.row_count < 0 or self.column_count < 0:
            raise ValueError("Количество строк и столбцов не может быть отрицательным.")

    def to_dict(self) -> dict[str, Any]:
        """Сериализует паспорт в обычные JSON-совместимые типы."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DatasetContract":
        """Восстанавливает паспорт из результата :meth:`to_dict`."""
        return cls(**value)
