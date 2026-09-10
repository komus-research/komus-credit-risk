"""Минимальные интерфейсы бинарного классификатора без concrete adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class BinaryClassifierAdapter(ABC):
    """Адаптер, которому runner передаёт только train target."""

    @abstractmethod
    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> None:
        """Обучает экземпляр адаптера только на train-fold."""

    @abstractmethod
    def predict_positive_proba(self, X_valid: pd.DataFrame) -> np.ndarray:
        """Возвращает одномерные вероятности положительного класса."""


class ModelAdapterFactory(ABC):
    """Создаёт новый adapter для каждого fold и объявляет его identity."""

    model_id: str
    model_version: str
    adapter_version: str

    @abstractmethod
    def create(self, parameters: dict[str, Any], seed: int) -> BinaryClassifierAdapter:
        """Создаёт новый, ещё не обученный adapter."""
