"""Shared technical compatibility rule for raw predictor columns."""
from __future__ import annotations

import numpy as np
import pandas as pd


def predictor_compatibility_error(series: pd.Series) -> str | None:
    """Return the materialization error code, or ``None`` when a series is usable.

    This is deliberately technical: it does not make any recommendation about
    usefulness, leakage, or a column's business meaning.
    """
    if pd.api.types.is_complex_dtype(series) or not (
        pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)
    ):
        return "UNSUPPORTED_PREDICTOR_REPRESENTATION"
    try:
        values = series.to_numpy(dtype=np.float32)
    except (TypeError, ValueError, OverflowError):
        return "UNSUPPORTED_PREDICTOR_REPRESENTATION"
    if not np.isfinite(values).all():
        return "NON_FINITE_PREDICTOR"
    return None
