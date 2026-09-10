"""Детерминированная сериализация и идентификаторы содержимого."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any


def _json_value(value: Any) -> Any:
    """Преобразует поддерживаемые значения в форму для канонического JSON."""
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_json_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def canonical_json(value: Any) -> str:
    """Возвращает UTF-8-совместимое каноническое JSON-представление значения.

    Несериализуемые и нечисловые значения ``NaN``/``Infinity`` намеренно
    отклоняются: они не могут быть частью воспроизводимого контракта.
    """
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Значение нельзя канонически сериализовать в JSON.") from error


def stable_hash(value: Any) -> str:
    """Возвращает SHA-256 канонического JSON-представления значения."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
