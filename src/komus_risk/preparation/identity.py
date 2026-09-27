"""Typed deterministic identities for Dataset Preparation V1."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any


class CanonicalValueError(ValueError):
    code = "UNSUPPORTED_CANONICAL_VALUE"


def canonical_value(value: Any) -> Any:
    """Return a type-tagged, JSON-safe canonical V1 representation."""
    if hasattr(value, "item") and value.__class__.__module__.startswith("numpy"):
        value = value.item()
    if is_dataclass(value) and not isinstance(value, type):
        return canonical_value(asdict(value))
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if value is None:
        return {"type": "none"}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalValueError("UNSUPPORTED_CANONICAL_VALUE")
        return {"type": "float", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalValueError("UNSUPPORTED_CANONICAL_VALUE")
        sign, digits, exponent = value.as_tuple()
        if not any(digits):
            sign, digits, exponent = 0, (0,), 0
        else:
            digits = tuple(digits)
            while len(digits) > 1 and digits[0] == 0:
                digits = digits[1:]
            while len(digits) > 1 and digits[-1] == 0:
                digits = digits[:-1]
                exponent += 1
        return {"type": "decimal", "sign": sign, "digits": "".join(map(str, digits)), "exponent": exponent}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, (list, tuple)):
        return {"type": "list" if isinstance(value, list) else "tuple", "items": [canonical_value(item) for item in value]}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalValueError("UNSUPPORTED_CANONICAL_VALUE")
        return {"type": "dict", "items": [[key, canonical_value(value[key])] for key in sorted(value)]}
    raise CanonicalValueError("UNSUPPORTED_CANONICAL_VALUE")


def canonical_json(value: Any) -> str:
    return json.dumps(canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
