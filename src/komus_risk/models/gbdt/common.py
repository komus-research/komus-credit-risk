"""Общие guards для frozen GBDT fit recipe."""

from __future__ import annotations

from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype
from sklearn.model_selection import train_test_split


FIT_RECIPE = {
    "inner_validation_fraction": 0.10,
    "early_stopping_rounds": 40,
    "refit_outer_train": True,
    "inner_split": "stratified",
}
INPUT_POLICY = {
    "dtype": "float32",
    "allow_missing": False,
    "categorical_handling": "disabled",
}
RUNTIME_POLICY = {"device": "cpu"}


def build_profile(estimator_params: dict[str, Any]) -> dict[str, Any]:
    """Создаёт полную неизменяемую по смыслу конфигурацию Stage 1."""
    return {
        "estimator_params": deepcopy(estimator_params),
        "fit_recipe": deepcopy(FIT_RECIPE),
        "input_policy": deepcopy(INPUT_POLICY),
        "runtime_policy": deepcopy(RUNTIME_POLICY),
    }


def validate_configurable_profile(
    profile: dict[str, Any],
    expected_profile: dict[str, Any],
    editable_parameters: dict[str, tuple[type, int | float | None, int | float | None]],
) -> dict[str, Any]:
    """Admit only complete profiles with explicitly approved estimator deltas.

    This is deliberately a second guard behind ModelConfigurationService: callers
    cannot smuggle new keys or alter the fit, input, or runtime recipe directly
    into an adapter factory.
    """
    if not isinstance(profile, dict) or set(profile) != set(expected_profile):
        raise ValueError("GBDT factory requires a complete trusted resolved profile.")
    for section in ("fit_recipe", "input_policy", "runtime_policy"):
        if profile.get(section) != expected_profile[section]:
            raise ValueError("GBDT factory rejects changes outside editable estimator parameters.")
    candidate = profile.get("estimator_params")
    expected = expected_profile["estimator_params"]
    if not isinstance(candidate, dict) or set(candidate) != set(expected):
        raise ValueError("GBDT factory requires the exact trusted estimator parameter set.")
    for name, value in candidate.items():
        if name not in editable_parameters:
            if value != expected[name]:
                raise ValueError("GBDT factory rejects changes to locked estimator parameters.")
            continue
        expected_type, minimum, maximum = editable_parameters[name]
        valid_type = (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            if expected_type is float
            else isinstance(value, expected_type) and not isinstance(value, bool)
        )
        if not valid_type:
            raise ValueError("GBDT factory received an invalid editable parameter type.")
        if minimum is not None and value < minimum:
            raise ValueError("GBDT factory received an editable parameter below its allowed range.")
        if maximum is not None and value > maximum:
            raise ValueError("GBDT factory received an editable parameter above its allowed range.")
    return deepcopy(profile)


def ensure_library_version(package_name: str, expected_version: str) -> None:
    """Проверяет exact version библиотеки до model fit."""
    try:
        installed_version = version(package_name)
    except PackageNotFoundError as error:
        raise ValueError(f"Библиотека «{package_name}» не установлена.") from error
    if installed_version != expected_version:
        raise ValueError(
            f"Для «{package_name}» требуется версия {expected_version}, "
            f"установлена {installed_version}."
        )


def prepare_numeric_input(X: pd.DataFrame) -> pd.DataFrame:
    """Применяет locked input policy без imputation, encoding или mutation входа."""
    if not isinstance(X, pd.DataFrame):
        raise ValueError("GBDT adapter ожидает pandas DataFrame с predictor columns.")
    unsupported = [
        str(column)
        for column, dtype in X.dtypes.items()
        if not (is_numeric_dtype(dtype) or is_bool_dtype(dtype)) or is_complex_dtype(dtype)
    ]
    if unsupported:
        raise ValueError(f"Поддерживаются только numeric и boolean колонки: {', '.join(unsupported)}.")
    prepared = X.astype(np.float32).copy()
    if not np.isfinite(prepared.to_numpy(dtype=np.float32)).all():
        raise ValueError("Predictor columns не должны содержать NaN, +Inf или -Inf.")
    return prepared


def prepare_binary_target(y_train: pd.Series, expected_length: int) -> pd.Series:
    """Проверяет train target, необходимый для stratified inner split."""
    if not isinstance(y_train, pd.Series) or len(y_train) != expected_length:
        raise ValueError("Train target должен быть pandas Series той же длины, что и X_train.")
    if y_train.isna().any() or y_train.nunique(dropna=False) != 2:
        raise ValueError("Train target должен содержать ровно два класса без пропусков.")
    return y_train


def inner_stratified_split(X_train: pd.DataFrame, y_train: pd.Series, seed: int):
    """Делит outer-train на Stage 1 fit и early-stop части."""
    positions = np.arange(len(X_train))
    fit_positions, early_stop_positions = train_test_split(
        positions,
        test_size=FIT_RECIPE["inner_validation_fraction"],
        stratify=y_train,
        random_state=seed,
    )
    return (
        X_train.iloc[fit_positions],
        X_train.iloc[early_stop_positions],
        y_train.iloc[fit_positions],
        y_train.iloc[early_stop_positions],
    )
