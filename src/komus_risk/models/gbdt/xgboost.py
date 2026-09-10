"""Frozen XGBoost adapter, эквивалентный accepted Stage 1 V2 recipe."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

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


XGBOOST_ESTIMATOR_PARAMS = {
    "n_estimators": 900, "learning_rate": 0.06, "max_depth": 6, "min_child_weight": 3,
    "subsample": 0.85, "colsample_bytree": 0.85, "reg_alpha": 0.05, "reg_lambda": 1.0,
    "objective": "binary:logistic", "eval_metric": "logloss", "n_jobs": -1, "tree_method": "hist",
}
XGBOOST_PROFILE = build_profile(XGBOOST_ESTIMATOR_PARAMS)
XGBOOST_MODEL_SPEC = ModelSpec(
    "xgboost", "XGBoost", "accepted_stage1_v2", ("binary",),
    "CPU XGBoost по зафиксированному Stage 1 V2 recipe.",
    deepcopy(XGBOOST_PROFILE),
    {"library": {"package": "xgboost", "version": "3.4.1"}, "cpu_policy": {"device": "cpu", "gpu_allowed": False}},
    "1",
)


class XGBoostAdapter(BinaryClassifierAdapter):
    def __init__(self, profile: dict[str, Any], seed: int) -> None:
        self.profile = validate_locked_profile(profile, XGBOOST_PROFILE)
        self.seed = seed
        self.search_estimator: XGBClassifier | None = None
        self.refit_estimator: XGBClassifier | None = None
        self.best_iteration: int | None = None

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        X_prepared = prepare_numeric_input(X_train)
        y_prepared = prepare_binary_target(y_train, len(X_prepared))
        X_fit, X_early, y_fit, y_early = inner_stratified_split(X_prepared, y_prepared, self.seed)
        search_params = deepcopy(self.profile["estimator_params"])
        self.search_estimator = XGBClassifier(
            **search_params, random_state=self.seed,
            early_stopping_rounds=self.profile["fit_recipe"]["early_stopping_rounds"],
        )
        self.search_estimator.fit(X_fit, y_fit, eval_set=[(X_early, y_early)], verbose=False)
        best = getattr(self.search_estimator, "best_iteration", None)
        self.best_iteration = int(best) + 1 if best is not None else search_params["n_estimators"]
        refit_params = deepcopy(search_params)
        refit_params["n_estimators"] = self.best_iteration
        self.refit_estimator = XGBClassifier(**refit_params, random_state=self.seed)
        self.refit_estimator.fit(X_prepared, y_prepared)

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        if self.refit_estimator is None:
            raise RuntimeError("XGBoost adapter должен быть обучен до predict_positive_proba.")
        return np.asarray(self.refit_estimator.predict_proba(prepare_numeric_input(X_valid))[:, 1], dtype=float)


class XGBoostFactory(ModelAdapterFactory):
    model_id = "xgboost"
    model_version = "accepted_stage1_v2"
    adapter_version = "1"

    @property
    def model_spec(self) -> ModelSpec:
        return XGBOOST_MODEL_SPEC

    def create(self, parameters: dict[str, Any], seed: int) -> BinaryClassifierAdapter:
        ensure_library_version("xgboost", "3.4.1")
        return XGBoostAdapter(validate_locked_profile(parameters, XGBOOST_PROFILE), seed)
