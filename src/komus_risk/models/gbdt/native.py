"""Native, pickle-free persistence for the frozen GBDT adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from lightgbm import Booster
from xgboost import DMatrix, XGBClassifier

from komus_risk.models.base import BinaryClassifierAdapter

from .catboost import CatBoostAdapter
from .common import prepare_numeric_input
from .lightgbm import LightGBMAdapter
from .mean import GBDTMeanAdapter
from .xgboost import XGBoostAdapter


class NativePredictor:
    """A reloadable predictor which admits exactly the persisted feature order."""

    def __init__(
        self,
        model_id: str,
        feature_columns: tuple[str, ...],
        predict: Callable[[pd.DataFrame], Any],
        *,
        local_shap: Callable[[pd.DataFrame], Any] | None = None,
        raw_predict: Callable[[pd.DataFrame], Any] | None = None,
        component_predict: Mapping[str, Callable[[pd.DataFrame], Any]] | None = None,
    ) -> None:
        self.model_id = model_id
        self.feature_columns = tuple(feature_columns)
        self._predict = predict
        self._local_shap = local_shap
        self._raw_predict = raw_predict
        self._component_predict = dict(component_predict or {})

    def predict_positive_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not isinstance(X, pd.DataFrame) or tuple(X.columns) != self.feature_columns:
            raise ValueError("NativePredictor requires the exact persisted ordered feature columns.")
        values = np.asarray(self._predict(X), dtype=float)
        if values.ndim != 1 or len(values) != len(X) or not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
            raise ValueError("Native model returned invalid positive probabilities.")
        return values

    def local_shap(self, X: pd.DataFrame) -> tuple[np.ndarray, float, float]:
        """Return native additive TreeSHAP values and raw margin for one exact row."""
        if not isinstance(X, pd.DataFrame) or len(X) != 1:
            raise ValueError("Native local SHAP requires exactly one DataFrame row.")
        shap_values, base_values, raw_values = self.native_shap_batch(X)
        return shap_values[0].copy(), float(base_values[0]), float(raw_values[0])

    def native_shap_batch(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return native TreeSHAP values, base values, and raw outputs for exact rows."""
        if self.model_id not in {"catboost", "xgboost", "lightgbm"} or self._local_shap is None or self._raw_predict is None:
            raise ValueError("Native batch explanations are unsupported for this model.")
        if not isinstance(X, pd.DataFrame) or tuple(X.columns) != self.feature_columns or len(X) < 1:
            raise ValueError("Native batch SHAP requires rows with exact persisted feature columns.")
        try:
            raw_shap = self._local_shap(X)
            if hasattr(raw_shap, "toarray"):
                raw_shap = raw_shap.toarray()
            shap_matrix = np.asarray(raw_shap, dtype=float)
            raw_values = np.asarray(self._raw_predict(X), dtype=float)
        except Exception as error:
            raise ValueError("Native local SHAP returned invalid values.") from error
        row_count = len(X)
        expected_shape = (row_count, len(self.feature_columns) + 1)
        if (shap_matrix.shape != expected_shape or raw_values.shape not in {(row_count,), (row_count, 1)}
                or not np.isfinite(shap_matrix).all() or not np.isfinite(raw_values).all()):
            raise ValueError("Native batch SHAP returned invalid values.")
        return shap_matrix[:, :-1].copy(), shap_matrix[:, -1].copy(), raw_values.reshape(-1).copy()

    def catboost_local_shap(self, X: pd.DataFrame) -> tuple[np.ndarray, float, float]:
        """Backward-compatible CatBoost-only local-SHAP entry point."""
        if self.model_id != "catboost":
            raise ValueError("Local explanations are unsupported for this native model.")
        return self.local_shap(X)

    def component_positive_probabilities(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return the fixed GBDT Mean component probabilities in saved order."""
        if self.model_id != "gbdt_mean" or set(self._component_predict) != {
            "catboost", "xgboost", "lightgbm"
        }:
            raise ValueError("Component probabilities are unsupported for this native model.")
        if not isinstance(X, pd.DataFrame) or tuple(X.columns) != self.feature_columns:
            raise ValueError("NativePredictor requires the exact persisted ordered feature columns.")
        result: dict[str, np.ndarray] = {}
        for model_id in ("catboost", "xgboost", "lightgbm"):
            values = np.asarray(self._component_predict[model_id](X), dtype=float)
            if (
                values.ndim != 1
                or len(values) != len(X)
                or not np.isfinite(values).all()
                or (values < 0).any()
                or (values > 1).any()
            ):
                raise ValueError("Native component returned invalid positive probabilities.")
            result[model_id] = values
        return result


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
            return NativePredictor(
                model_id,
                feature_columns,
                lambda X: model.predict_proba(prepare_numeric_input(X))[:, 1],
                local_shap=lambda X: model.get_feature_importance(
                    Pool(prepare_numeric_input(X), feature_names=list(feature_columns)),
                    type="ShapValues",
                ),
                raw_predict=lambda X: model.predict(prepare_numeric_input(X), prediction_type="RawFormulaVal"),
            )
        if model_id == "xgboost":
            model = XGBClassifier()
            model.load_model(path / "model.json")
            booster = model.get_booster()

            def matrix(X: pd.DataFrame) -> DMatrix:
                return DMatrix(prepare_numeric_input(X), feature_names=list(feature_columns))

            return NativePredictor(
                model_id, feature_columns,
                lambda X: model.predict_proba(prepare_numeric_input(X))[:, 1],
                local_shap=lambda X: booster.predict(matrix(X), pred_contribs=True),
                raw_predict=lambda X: booster.predict(matrix(X), output_margin=True),
            )
        if model_id == "lightgbm":
            model = Booster(model_file=str(path / "model.txt"))
            return NativePredictor(
                model_id, feature_columns,
                lambda X: model.predict(prepare_numeric_input(X)),
                local_shap=lambda X: model.predict(prepare_numeric_input(X), pred_contrib=True),
                raw_predict=lambda X: model.predict(prepare_numeric_input(X), raw_score=True),
            )
        catboost = CatBoostClassifier(); catboost.load_model(path / "catboost.cbm")
        xgboost = XGBClassifier(); xgboost.load_model(path / "xgboost.json")
        lightgbm = Booster(model_file=str(path / "lightgbm.txt"))
        components = {
            "catboost": lambda X: catboost.predict_proba(prepare_numeric_input(X))[:, 1],
            "xgboost": lambda X: xgboost.predict_proba(prepare_numeric_input(X))[:, 1],
            "lightgbm": lambda X: lightgbm.predict(prepare_numeric_input(X)),
        }
        return NativePredictor(
            model_id,
            feature_columns,
            lambda X: sum(
                np.asarray(components[component](X), dtype=float)
                for component in ("catboost", "xgboost", "lightgbm")
            ) / 3,
            component_predict=components,
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
