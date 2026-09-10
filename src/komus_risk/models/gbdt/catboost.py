"""Frozen CatBoost adapter, эквивалентный accepted Stage 1 V2 recipe."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier

from komus_risk.models.base import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.registries import ModelSpec

from .common import (
    build_profile,
    ensure_library_version,
    inner_stratified_split,
    prepare_binary_target,
    prepare_numeric_input,
    validate_locked_profile,
)


CATBOOST_ESTIMATOR_PARAMS = {
    "iterations": 900, "learning_rate": 0.06, "depth": 7,
    "loss_function": "Logloss", "eval_metric": "AUC", "thread_count": -1,
    "verbose": False, "allow_writing_files": False,
}
CATBOOST_PROFILE = build_profile(CATBOOST_ESTIMATOR_PARAMS)
CATBOOST_MODEL_SPEC = ModelSpec(
    "catboost", "CatBoost", "accepted_stage1_v2", ("binary",),
    "CPU CatBoost по зафиксированному Stage 1 V2 recipe.",
    deepcopy(CATBOOST_PROFILE),
    {"library": {"package": "catboost", "version": "1.2.10"}, "cpu_policy": {"device": "cpu", "gpu_allowed": False}},
    "1",
)


class CatBoostAdapter(BinaryClassifierAdapter):
    """Search на inner split и refit на 100% outer-train."""

    def __init__(self, profile: dict[str, Any], seed: int) -> None:
        self.profile = validate_locked_profile(profile, CATBOOST_PROFILE)
        self.seed = seed
        self.search_estimator: CatBoostClassifier | None = None
        self.refit_estimator: CatBoostClassifier | None = None
        self.best_iteration: int | None = None

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        X_prepared = prepare_numeric_input(X_train)
        y_prepared = prepare_binary_target(y_train, len(X_prepared))
        X_fit, X_early, y_fit, y_early = inner_stratified_split(X_prepared, y_prepared, self.seed)
        search_params = deepcopy(self.profile["estimator_params"])
        self.search_estimator = CatBoostClassifier(**search_params, random_seed=self.seed)
        self.search_estimator.fit(
            X_fit, y_fit, eval_set=(X_early, y_early),
            early_stopping_rounds=self.profile["fit_recipe"]["early_stopping_rounds"], verbose=False,
        )
        best = self.search_estimator.get_best_iteration()
        self.best_iteration = int(best) + 1 if best is not None and int(best) >= 0 else search_params["iterations"]
        refit_params = deepcopy(search_params)
        refit_params["iterations"] = self.best_iteration
        self.refit_estimator = CatBoostClassifier(**refit_params, random_seed=self.seed)
        self.refit_estimator.fit(X_prepared, y_prepared)

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        if self.refit_estimator is None:
            raise RuntimeError("CatBoost adapter должен быть обучен до predict_positive_proba.")
        return np.asarray(self.refit_estimator.predict_proba(prepare_numeric_input(X_valid))[:, 1], dtype=float)


class CatBoostFactory(ModelAdapterFactory):
    model_id = "catboost"
    model_version = "accepted_stage1_v2"
    adapter_version = "1"

    @property
    def model_spec(self) -> ModelSpec:
        return CATBOOST_MODEL_SPEC

    def create(self, parameters: dict[str, Any], seed: int) -> BinaryClassifierAdapter:
        ensure_library_version("catboost", "1.2.10")
        return CatBoostAdapter(validate_locked_profile(parameters, CATBOOST_PROFILE), seed)
