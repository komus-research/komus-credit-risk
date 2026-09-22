"""Native, non-pickle serialization of the four supported fitted predictors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import Booster
from xgboost import XGBClassifier

from .catboost import CatBoostAdapter
from .common import prepare_numeric_input
from .lightgbm import LightGBMAdapter
from .mean import GBDTMeanAdapter
from .xgboost import XGBoostAdapter


_NATIVE_FILES = {
    "catboost": "catboost.cbm",
    "xgboost": "xgboost.json",
    "lightgbm": "lightgbm.txt",
}


def native_file_names(model_id: str) -> tuple[str, ...]:
    if model_id == "gbdt_mean":
        return tuple(_NATIVE_FILES[key] for key in sorted(_NATIVE_FILES))
    if model_id not in _NATIVE_FILES:
        raise ValueError("Неподдерживаемый алгоритм для сохранения модели.")
    return (_NATIVE_FILES[model_id],)


def save_fitted_native(adapter: Any, model_id: str, directory: Path) -> dict[str, int]:
    """Save only native estimator formats; never serialize Python objects."""
    components = adapter._component_adapters if isinstance(adapter, GBDTMeanAdapter) and adapter._fitted else None
    if model_id == "gbdt_mean":
        if components is None or set(components) != set(_NATIVE_FILES):
            raise ValueError("GBDT mean ещё не обучен полностью.")
    else:
        components = {model_id: adapter}
    iterations: dict[str, int] = {}
    for component_id in sorted(components):
        component = components[component_id]
        estimator = getattr(component, "refit_estimator", None)
        expected_type = {"catboost": CatBoostAdapter, "xgboost": XGBoostAdapter, "lightgbm": LightGBMAdapter}[component_id]
        if not isinstance(component, expected_type) or estimator is None:
            raise ValueError(f"Component «{component_id}» не является обученной поддерживаемой моделью.")
        destination = directory / _NATIVE_FILES[component_id]
        if component_id == "catboost":
            estimator.save_model(str(destination), format="cbm")
        elif component_id == "xgboost":
            estimator.save_model(str(destination))
        else:
            estimator.booster_.save_model(str(destination))
        if not destination.is_file() or destination.stat().st_size == 0:
            raise ValueError(f"Нативный файл «{component_id}» не был сохранён.")
        iterations[component_id] = int(component.best_iteration)
    return iterations


class NativePredictor:
    """Inference-only wrapper restored from trusted native model files."""

    def __init__(self, model_id: str, components: dict[str, Any], feature_columns: tuple[str, ...]) -> None:
        self.model_id = model_id
        self.components = components
        self.feature_columns = feature_columns

    def predict_positive_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != self.feature_columns:
            raise ValueError("Колонки прогноза должны точно совпадать с сохранённой схемой и порядком.")
        prepared = prepare_numeric_input(frame)
        predictions: list[np.ndarray] = []
        for component_id in sorted(self.components):
            estimator = self.components[component_id]
            if component_id == "lightgbm":
                values = estimator.predict(prepared)
            else:
                values = estimator.predict_proba(prepared)[:, 1]
            probabilities = np.asarray(values, dtype=float)
            if probabilities.ndim != 1 or len(probabilities) != len(prepared):
                raise ValueError("Нативная модель вернула вероятности неверной формы.")
            if not np.isfinite(probabilities).all() or (probabilities < 0).any() or (probabilities > 1).any():
                raise ValueError("Нативная модель вернула некорректные вероятности.")
            predictions.append(probabilities)
        return np.mean(np.stack(predictions), axis=0)


def load_native_predictor(model_id: str, directory: Path, feature_columns: tuple[str, ...]) -> NativePredictor:
    components: dict[str, Any] = {}
    component_ids = sorted(_NATIVE_FILES) if model_id == "gbdt_mean" else (model_id,)
    for component_id in component_ids:
        source = directory / _NATIVE_FILES[component_id]
        if component_id == "catboost":
            estimator = CatBoostClassifier()
            estimator.load_model(str(source), format="cbm")
        elif component_id == "xgboost":
            estimator = XGBClassifier()
            estimator.load_model(str(source))
        else:
            estimator = Booster(model_file=str(source))
        components[component_id] = estimator
    return NativePredictor(model_id, components, feature_columns)
