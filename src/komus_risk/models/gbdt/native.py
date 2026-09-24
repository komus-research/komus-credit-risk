"""Native, pickle-free persistence for the frozen GBDT adapters."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import Booster
from xgboost import XGBClassifier

from komus_risk.models.base import BinaryClassifierAdapter

from .catboost import CatBoostAdapter
from .common import prepare_numeric_input
from .lightgbm import LightGBMAdapter
from .mean import GBDTMeanAdapter
from .xgboost import XGBoostAdapter


class NativePredictor:
    """A reloadable predictor which admits exactly the persisted feature order."""

    def __init__(self, model_id: str, feature_columns: tuple[str, ...], predict: Callable[[pd.DataFrame], Any]) -> None:
        self.model_id = model_id
        self.feature_columns = tuple(feature_columns)
        self._predict = predict

    def predict_positive_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not isinstance(X, pd.DataFrame) or tuple(X.columns) != self.feature_columns:
            raise ValueError("NativePredictor requires the exact persisted ordered feature columns.")
        values = np.asarray(self._predict(X), dtype=float)
        if values.ndim != 1 or len(values) != len(X) or not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
            raise ValueError("Native model returned invalid positive probabilities.")
        return values


def native_model_files(model_id: str) -> tuple[str, ...]:
    files = {
        "catboost": ("model.cbm",),
        "xgboost": ("model.json",),
        "lightgbm": ("model.txt",),
        "gbdt_mean": ("catboost.cbm", "xgboost.json", "lightgbm.txt"),
    }
    try:
        return files[model_id]
    except KeyError as error:
        raise ValueError(f"Unsupported native model_id: {model_id!r}.") from error


def save_native_model(model_id: str, adapter: BinaryClassifierAdapter, directory: str | Path) -> tuple[str, ...]:
    """Write native library artifacts only; callers must persist metadata separately."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    if model_id == "catboost":
        _catboost_estimator(adapter).save_model(path / "model.cbm")
    elif model_id == "xgboost":
        _xgboost_estimator(adapter).get_booster().save_model(path / "model.json")
    elif model_id == "lightgbm":
        _lightgbm_estimator(adapter).booster_.save_model(str(path / "model.txt"))
    elif model_id == "gbdt_mean":
        components = getattr(adapter, "_component_adapters", None)
        if not isinstance(adapter, GBDTMeanAdapter) or not getattr(adapter, "_fitted", False) or not isinstance(components, dict):
            raise ValueError("GBDT mean adapter must be fully fitted before native persistence.")
        _catboost_estimator(components["catboost"]).save_model(path / "catboost.cbm")
        _xgboost_estimator(components["xgboost"]).get_booster().save_model(path / "xgboost.json")
        _lightgbm_estimator(components["lightgbm"]).booster_.save_model(str(path / "lightgbm.txt"))
    else:
        native_model_files(model_id)
    files = native_model_files(model_id)
    if any(not (path / name).is_file() for name in files):
        raise RuntimeError("Native model persistence did not create every required file.")
    return files


def validate_fitted_adapter_recipe(
    model_id: str,
    adapter: BinaryClassifierAdapter,
    expected_profile: dict[str, Any],
    expected_seed: int,
) -> None:
    """Fail closed unless the actual fitted adapter is the trusted frozen recipe."""
    if model_id == "catboost":
        _validate_component(adapter, CatBoostAdapter, expected_profile, expected_seed, "CatBoost")
        return
    if model_id == "xgboost":
        _validate_component(adapter, XGBoostAdapter, expected_profile, expected_seed, "XGBoost")
        return
    if model_id == "lightgbm":
        _validate_component(adapter, LightGBMAdapter, expected_profile, expected_seed, "LightGBM")
        return
    if model_id != "gbdt_mean" or type(adapter) is not GBDTMeanAdapter or not getattr(adapter, "_fitted", False):
        raise ValueError("Actual fitted adapter does not match the trusted GBDT mean recipe.")
    components = getattr(adapter, "_component_adapters", None)
    expected_components = expected_profile.get("components") if isinstance(expected_profile, dict) else None
    if not isinstance(components, dict) or set(components) != {"catboost", "xgboost", "lightgbm"} or not isinstance(expected_components, dict):
        raise ValueError("GBDT mean components do not match the trusted frozen recipe.")
    _validate_component(components["catboost"], CatBoostAdapter, expected_components["catboost"].get("profile"), expected_seed, "CatBoost")
    _validate_component(components["xgboost"], XGBoostAdapter, expected_components["xgboost"].get("profile"), expected_seed, "XGBoost")
    _validate_component(components["lightgbm"], LightGBMAdapter, expected_components["lightgbm"].get("profile"), expected_seed, "LightGBM")


def _validate_component(adapter: Any, adapter_type: type[Any], expected_profile: Any, expected_seed: int, label: str) -> None:
    if type(adapter) is not adapter_type:
        raise ValueError(f"Actual fitted adapter is not the trusted {label} adapter type.")
    if adapter.profile != expected_profile or adapter.seed != expected_seed:
        raise ValueError(f"Actual {label} adapter profile or seed does not match the trusted recipe.")
    estimator = getattr(adapter, "refit_estimator", None)
    best_iteration = getattr(adapter, "best_iteration", None)
    if estimator is None or not isinstance(best_iteration, int) or isinstance(best_iteration, bool) or best_iteration < 1:
        raise ValueError(f"Actual {label} adapter is not completely fitted.")
    if adapter_type is LightGBMAdapter and getattr(estimator, "booster_", None) is None:
        raise ValueError("Actual LightGBM adapter has no fitted booster.")


def load_native_predictor(model_id: str, directory: str | Path, feature_columns: tuple[str, ...]) -> NativePredictor:
    """Reload a native artifact into a feature-order enforcing predictor."""
    path = Path(directory)
    files = native_model_files(model_id)
    if any(not (path / name).is_file() for name in files):
        raise ValueError("Native model files are missing.")
    try:
        if model_id == "catboost":
            model = CatBoostClassifier()
            model.load_model(path / "model.cbm")
            return NativePredictor(model_id, feature_columns, lambda X: model.predict_proba(prepare_numeric_input(X))[:, 1])
        if model_id == "xgboost":
            model = XGBClassifier()
            model.load_model(path / "model.json")
            return NativePredictor(model_id, feature_columns, lambda X: model.predict_proba(prepare_numeric_input(X))[:, 1])
        if model_id == "lightgbm":
            model = Booster(model_file=str(path / "model.txt"))
            return NativePredictor(model_id, feature_columns, lambda X: model.predict(prepare_numeric_input(X)))
        catboost = CatBoostClassifier(); catboost.load_model(path / "catboost.cbm")
        xgboost = XGBClassifier(); xgboost.load_model(path / "xgboost.json")
        lightgbm = Booster(model_file=str(path / "lightgbm.txt"))
        return NativePredictor(
            model_id, feature_columns,
            lambda X: (
                np.asarray(catboost.predict_proba(prepare_numeric_input(X))[:, 1], dtype=float)
                + np.asarray(xgboost.predict_proba(prepare_numeric_input(X))[:, 1], dtype=float)
                + np.asarray(lightgbm.predict(prepare_numeric_input(X)), dtype=float)
            ) / 3,
        )
    except Exception as error:
        raise ValueError("Native model could not be reloaded.") from error


def _catboost_estimator(adapter: Any) -> Any:
    estimator = getattr(adapter, "refit_estimator", None)
    if estimator is None:
        raise ValueError("CatBoost adapter must be fitted before native persistence.")
    return estimator


def _xgboost_estimator(adapter: Any) -> Any:
    estimator = getattr(adapter, "refit_estimator", None)
    if estimator is None:
        raise ValueError("XGBoost adapter must be fitted before native persistence.")
    return estimator


def _lightgbm_estimator(adapter: Any) -> Any:
    estimator = getattr(adapter, "refit_estimator", None)
    if estimator is None or getattr(estimator, "booster_", None) is None:
        raise ValueError("LightGBM adapter must be fitted before native persistence.")
    return estimator
