"""Ephemeral OOF evidence retained until its immutable artifact is published."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from komus_risk.models.base import BinaryClassifierAdapter


@dataclass(frozen=True, slots=True)
class FoldModelEvidence:
    """One fitted evaluation adapter and its deterministic fold provenance."""

    fold_number: int
    fold_seed: int
    adapter: BinaryClassifierAdapter


@dataclass(frozen=True, slots=True)
class OOFResultEvidence:
    """Canonical row-aligned facts required to prove an OOF prediction."""

    y_true: np.ndarray
    identifier_display: tuple[str, ...]
    model_input: np.ndarray
    feature_ids: tuple[str, ...]
    feature_columns: tuple[str, ...]
    fold_models: tuple[FoldModelEvidence, ...]
