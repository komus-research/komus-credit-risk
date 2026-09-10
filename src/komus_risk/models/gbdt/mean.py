"""Зафиксированный equal-weight GBDT mean без собственной CV-логики."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from komus_risk.models.base import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.registries import ModelSpec

from .catboost import CATBOOST_PROFILE
from .lightgbm import LIGHTGBM_PROFILE
from .xgboost import XGBOOST_PROFILE


_COMPONENT_IDENTITIES = {
    "catboost": ("catboost", "accepted_stage1_v2", "1"),
    "xgboost": ("xgboost", "accepted_stage1_v2", "1"),
    "lightgbm": ("lightgbm", "accepted_stage1_v2", "1"),
}
GBDT_MEAN_PROFILE = {
    "aggregation": {"method": "arithmetic_mean_positive_probability"},
    "seed_policy": {"method": "shared_fold_seed"},
    "components": {
        "catboost": {"model_version": "accepted_stage1_v2", "adapter_version": "1", "profile": deepcopy(CATBOOST_PROFILE)},
        "xgboost": {"model_version": "accepted_stage1_v2", "adapter_version": "1", "profile": deepcopy(XGBOOST_PROFILE)},
        "lightgbm": {"model_version": "accepted_stage1_v2", "adapter_version": "1", "profile": deepcopy(LIGHTGBM_PROFILE)},
    },
}
GBDT_MEAN_MODEL_SPEC = ModelSpec(
    "gbdt_mean", "GBDT mean", "accepted_stage1_v2_equal_mean", ("binary",),
    "Равное среднее positive probabilities CatBoost, XGBoost и LightGBM.",
    deepcopy(GBDT_MEAN_PROFILE),
    {
        "device": "cpu",
        "components": {
            "catboost": {"package": "catboost", "version": "1.2.10"},
            "xgboost": {"package": "xgboost", "version": "3.4.1"},
            "lightgbm": {"package": "lightgbm", "version": "4.7.0"},
        },
    },
    "1",
)


class GBDTMeanAdapter(BinaryClassifierAdapter):
    """Composite adapter, не выполняющий собственных split или fit recipe."""

    def __init__(self, component_adapters: Mapping[str, BinaryClassifierAdapter]) -> None:
        self._component_adapters = dict(component_adapters)
        self._fitted = False

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        for model_id in sorted(self._component_adapters):
            try:
                self._component_adapters[model_id].fit(X_train, y_train)
            except Exception as error:
                self._component_adapters = {}
                self._fitted = False
                raise RuntimeError(f"Не удалось обучить component «{model_id}» GBDT mean.") from error
        self._fitted = True

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("GBDT mean должен быть полностью обучен до predict_positive_proba.")
        predictions: list[np.ndarray] = []
        for model_id in sorted(self._component_adapters):
            try:
                probabilities = self._validate_component_probabilities(
                    self._component_adapters[model_id].predict_positive_proba(X_valid),
                    expected_length=len(X_valid),
                    model_id=model_id,
                )
            except Exception as error:
                raise ValueError(f"Некорректные вероятности component «{model_id}» GBDT mean.") from error
            predictions.append(probabilities)
        return (predictions[0] + predictions[1] + predictions[2]) / 3

    @staticmethod
    def _validate_component_probabilities(values: Any, *, expected_length: int, model_id: str) -> np.ndarray:
        probabilities = np.asarray(values, dtype=float)
        if probabilities.ndim != 1:
            raise ValueError(f"Component «{model_id}» вернул не одномерные вероятности.")
        if len(probabilities) != expected_length:
            raise ValueError(f"Длина вероятностей component «{model_id}» не совпадает с X_valid.")
        if not np.isfinite(probabilities).all():
            raise ValueError(f"Вероятности component «{model_id}» должны быть конечными.")
        if (probabilities < 0).any() or (probabilities > 1).any():
            raise ValueError(f"Вероятности component «{model_id}» должны лежать в [0, 1].")
        return probabilities


class GBDTMeanFactory(ModelAdapterFactory):
    """Создаёт fresh composite и fresh adapters трёх locked components."""

    model_id = "gbdt_mean"
    model_version = "accepted_stage1_v2_equal_mean"
    adapter_version = "1"

    def __init__(self, component_factories: Mapping[str, ModelAdapterFactory]) -> None:
        self._component_factories = dict(component_factories)
        self._validate_component_factories()

    @property
    def model_spec(self) -> ModelSpec:
        return GBDT_MEAN_MODEL_SPEC

    def create(self, parameters: dict[str, Any], seed: int) -> BinaryClassifierAdapter:
        if not isinstance(parameters, dict) or parameters != GBDT_MEAN_PROFILE:
            raise ValueError("Для GBDT mean требуется полная неизменённая frozen composite profile.")
        adapters: dict[str, BinaryClassifierAdapter] = {}
        for model_id in sorted(self._component_factories):
            profile = deepcopy(parameters["components"][model_id]["profile"])
            adapters[model_id] = self._component_factories[model_id].create(profile, seed)
        return GBDTMeanAdapter(adapters)

    def _validate_component_factories(self) -> None:
        expected_ids = set(_COMPONENT_IDENTITIES)
        actual_ids = set(self._component_factories)
        if actual_ids != expected_ids:
            raise ValueError("GBDT mean требует ровно components: catboost, xgboost, lightgbm.")
        for key in sorted(expected_ids):
            factory = self._component_factories[key]
            expected_identity = _COMPONENT_IDENTITIES[key]
            actual_identity = (
                getattr(factory, "model_id", None),
                getattr(factory, "model_version", None),
                getattr(factory, "adapter_version", None),
            )
            if actual_identity != expected_identity:
                raise ValueError(
                    f"Component «{key}» имеет несовместимый identity: {actual_identity}."
                )
