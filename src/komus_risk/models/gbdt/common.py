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


def validate_locked_profile(profile: dict[str, Any], expected_profile: dict[str, Any]) -> dict[str, Any]:
    """Отклоняет неполный или изменённый preset до создания estimator."""
    if not isinstance(profile, dict) or profile != expected_profile:
        raise ValueError("Для GBDT требуется полная неизменённая frozen Stage 1 profile.")
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
