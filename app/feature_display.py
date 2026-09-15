"""Display-only grouping helpers for feature-selection controls."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
from collections.abc import Iterable


_FAMILY_PATTERN = re.compile(r"^(?P<family>(?:[A-Za-z]+_)*[A-Za-z]+)\d+$")


@dataclass(frozen=True, slots=True)
class FeatureFamily:
    """A UI family while preserving the registry's feature order."""

    family_id: str
    feature_ids: tuple[str, ...]


def feature_family_id(feature_id: str) -> str:
    """Derive a display family from a numbered feature identifier.

    The optional ``_norm`` suffix is presentation-neutral only for identifiers
    that follow the numbered convention. Other identifiers remain unchanged so
    distinct feature IDs cannot be merged by display grouping.
    """
    base_id = feature_id.removesuffix("_norm")
    match = _FAMILY_PATTERN.fullmatch(base_id)
    return match.group("family") if match else feature_id


def group_feature_ids_by_family(feature_ids: Iterable[str]) -> tuple[FeatureFamily, ...]:
    """Group identifiers by display family in first-appearance order."""
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for feature_id in feature_ids:
        grouped.setdefault(feature_family_id(feature_id), []).append(feature_id)
    return tuple(
        FeatureFamily(family_id=family_id, feature_ids=tuple(ids))
        for family_id, ids in grouped.items()
    )
