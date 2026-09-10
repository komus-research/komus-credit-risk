"""Frozen LightGBM adapter, эквивалентный accepted Stage 1 V2 recipe."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping

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


LIGHTGBM_ESTIMATOR_PARAMS = {
    "n_estimators": 900, "learning_rate": 0.05, "num_leaves": 31, "max_depth": -1,
    "min_child_samples": 40, "subsample": 0.85, "subsample_freq": 1,
    "colsample_bytree": 0.85, "reg_alpha": 0.05, "reg_lambda": 1.0, "n_jobs": -1, "verbosity": -1,
}
LIGHTGBM_PROFILE = build_profile(LIGHTGBM_ESTIMATOR_PARAMS)
LIGHTGBM_MODEL_SPEC = ModelSpec(
    "lightgbm", "LightGBM", "accepted_stage1_v2", ("binary",),
    "CPU LightGBM по зафиксированному Stage 1 V2 recipe.",
    deepcopy(LIGHTGBM_PROFILE),
    {"library": {"package": "lightgbm", "version": "4.7.0"}, "cpu_policy": {"device": "cpu", "gpu_allowed": False}},
    "1",
)


class LightGBMAdapter(BinaryClassifierAdapter):
    def __init__(self, profile: dict[str, Any], seed: int) -> None:
        self.profile = validate_locked_profile(profile, LIGHTGBM_PROFILE)
        self.seed = seed
        self.search_estimator: LGBMClassifier | None = None
        self.refit_estimator: LGBMClassifier | None = None
        self.best_iteration: int | None = None

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        X_prepared = prepare_numeric_input(X_train)
        y_prepared = prepare_binary_target(y_train, len(X_prepared))
        X_fit, X_early, y_fit, y_early = inner_stratified_split(X_prepared, y_prepared, self.seed)
        search_params = deepcopy(self.profile["estimator_params"])
        self.search_estimator = LGBMClassifier(**search_params, random_state=self.seed)
        self.search_estimator.fit(
            X_fit, y_fit, eval_X=X_early, eval_y=y_early,
            callbacks=[early_stopping(self.profile["fit_recipe"]["early_stopping_rounds"], verbose=False)],
        )
        best = getattr(self.search_estimator, "best_iteration_", None)
        self.best_iteration = int(best) if best is not None and int(best) > 0 else search_params["n_estimators"]
        refit_params = deepcopy(search_params)
        refit_params["n_estimators"] = self.best_iteration
        self.refit_estimator = LGBMClassifier(**refit_params, random_state=self.seed)
        self.refit_estimator.fit(X_prepared, y_prepared)

    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        if self.refit_estimator is None:
            raise RuntimeError("LightGBM adapter должен быть обучен до predict_positive_proba.")
        return np.asarray(self.refit_estimator.predict_proba(prepare_numeric_input(X_valid))[:, 1], dtype=float)


class LightGBMFactory(ModelAdapterFactory):
    model_id = "lightgbm"
    model_version = "accepted_stage1_v2"
    adapter_version = "1"

    @property
    def model_spec(self) -> ModelSpec:
        return LIGHTGBM_MODEL_SPEC

    def create(self, parameters: dict[str, Any], seed: int) -> BinaryClassifierAdapter:
        ensure_library_version("lightgbm", "4.7.0")
        return LightGBMAdapter(validate_locked_profile(parameters, LIGHTGBM_PROFILE), seed)
