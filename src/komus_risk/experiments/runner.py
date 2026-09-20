"""Строго ограниченный runner бинарного stratified OOF-эксперимента."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold

from komus_risk.contracts import ExperimentConfig, ExperimentResult, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.hashing import stable_hash
from komus_risk.models import ModelAdapterFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry


@dataclass(frozen=True, slots=True)
class EvaluationPopulation:
    """Явно заданные строки датасета для оценки эксперимента."""

    row_positions: tuple[int, ...]
    population_id: str
    population_fingerprint: str
    partition_role: str

    def __post_init__(self) -> None:
        positions = tuple(self.row_positions)
        if not positions:
            raise ValueError("Популяция оценки не может быть пустой.")
        if any(not isinstance(position, int) or isinstance(position, bool) or position < 0 for position in positions):
            raise ValueError("Позиции строк должны быть неотрицательными целыми числами.")
        if len(positions) != len(set(positions)):
            raise ValueError("Позиции строк популяции не должны повторяться.")
        if self.partition_role not in {"full", "working"}:
            raise ValueError("Роль популяции должна быть «full» или «working».")
        if not isinstance(self.population_id, str) or not self.population_id.strip():
            raise ValueError("Идентификатор популяции должен быть непустой строкой.")
        if not isinstance(self.population_fingerprint, str) or not self.population_fingerprint.strip():
            raise ValueError("Fingerprint популяции должен быть непустой строкой.")
        object.__setattr__(self, "row_positions", positions)


@dataclass(frozen=True, slots=True)
class ExperimentRunOutput:
    """Result с вынесенными OOF evidence, которые не входят в контракт результата."""

    result: ExperimentResult
    oof_positive_proba: np.ndarray
    fold_assignments: np.ndarray
    row_positions: tuple[int, ...]
    population_id: str
    population_fingerprint: str


@dataclass(frozen=True, slots=True)
class ExperimentProgressEvent:
    """Observational progress emitted by an experiment run; it never changes evidence."""

    stage: str
    fold_number: int | None
    folds_total: int | None


class ExperimentRunner:
    """Запускает только разрешённый stratified K-fold OOF path."""

    def __init__(
        self,
        *,
        feature_registry: FeatureRegistry,
        model_registry: ModelRegistry,
        adapter_factory: ModelAdapterFactory,
        code_version: str,
    ) -> None:
        if not isinstance(code_version, str) or not code_version.strip():
            raise ValueError("Версия кода должна быть передана runner явной непустой строкой.")
        self.feature_registry = feature_registry
        self.model_registry = model_registry
        self.adapter_factory = adapter_factory
        self.code_version = code_version

    def run(
        self,
        loaded_dataset: LoadedDataset,
        config: ExperimentConfig,
        population: EvaluationPopulation,
        progress_listener: Callable[[ExperimentProgressEvent], None] | None = None,
    ) -> ExperimentRunOutput:
        """Выполняет OOF без full-data обучения и без доступа adapter к y_valid."""
        self._notify(progress_listener, ExperimentProgressEvent("run_started", None, config.folds))
        contract = loaded_dataset.contract
        dataframe = loaded_dataset.dataframe
        feature_specs = self._validate_before_fit(contract, dataframe, config, population)
        predictor_columns = [spec.column_name for spec in feature_specs]
        population_frame = dataframe.iloc[list(population.row_positions)]
        y_binary = self._binary_target(population_frame[contract.target_column], contract.positive_class)
        self._validate_oof_feasibility(config, y_binary)

        X = population_frame.loc[:, predictor_columns]
        splitter = StratifiedKFold(
            n_splits=config.folds,
            shuffle=True,
            random_state=config.seed,
        )
        oof_positive_proba = np.full(len(population_frame), np.nan, dtype=float)
        fold_assignments = np.full(len(population_frame), -1, dtype=int)
        fold_metrics: list[dict[str, Any]] = []
        started_at = perf_counter()
        progress_overhead_seconds = 0.0

        for fold_number, (train_indices, valid_indices) in enumerate(splitter.split(X, y_binary), start=1):
            progress_overhead_seconds += self._notify(
                progress_listener, ExperimentProgressEvent("fold_started", fold_number, config.folds)
            )
            fold_seed = config.seed + fold_number
            adapter = self.adapter_factory.create(dict(config.model_parameters), fold_seed)
            fold_started_at = perf_counter()
            adapter.fit(X.iloc[train_indices], y_binary.iloc[train_indices])
            probabilities = self._validate_probabilities(
                adapter.predict_positive_proba(X.iloc[valid_indices]),
                expected_length=len(valid_indices),
            )
            fold_runtime = perf_counter() - fold_started_at
            oof_positive_proba[valid_indices] = probabilities
            fold_assignments[valid_indices] = fold_number
            metrics = self._metrics(y_binary.iloc[valid_indices], probabilities)
            fold_metrics.append(
                {
                    "fold": fold_number,
                    "fold_seed": fold_seed,
                    "n_train": len(train_indices),
                    "n_valid": len(valid_indices),
                    **metrics,
                    "runtime_seconds": fold_runtime,
                }
            )
            progress_overhead_seconds += self._notify(
                progress_listener, ExperimentProgressEvent("fold_completed", fold_number, config.folds)
            )

        if np.isnan(oof_positive_proba).any() or (fold_assignments < 1).any():
            raise RuntimeError("Не каждая строка популяции получила OOF prediction и fold assignment.")

        progress_overhead_seconds += self._notify(
            progress_listener, ExperimentProgressEvent("aggregate_metrics_started", None, config.folds)
        )
        global_metrics = self._metrics(y_binary, oof_positive_proba)
        confusion = self._confusion(y_binary, oof_positive_proba)
        result = ExperimentResult(
            result_id=stable_hash(
                {
                    "experiment_config_id": config.experiment_id,
                    "config_hash": config.config_hash,
                    "population_id": population.population_id,
                    "population_fingerprint": population.population_fingerprint,
                }
            ),
            experiment_config_id=config.experiment_id,
            config_hash=config.config_hash,
            dataset_fingerprint=contract.dataset_fingerprint,
            feature_set_hash=config.feature_set_hash,
            model_id=config.model_id,
            model_version=config.model_version,
            evaluation_level=config.evaluation_level,
            metrics=global_metrics,
            confusion=confusion,
            fold_metrics=tuple(fold_metrics),
            runtime_seconds=perf_counter() - started_at - progress_overhead_seconds,
            comparison={},
            code_version=self.code_version,
            created_at=datetime.now(timezone.utc).isoformat(),
            limitations=(
                "Результат получен на случайной стратифицированной OOF-кросс-валидации.",
                "OOF-оценка не доказывает временную стабильность модели.",
                (
                    "Защищённый final test существует и не использован."
                    if contract.final_test_locked
                    else "Защищённый final test для этого датасета не определён."
                ),
            ),
        )
        return ExperimentRunOutput(
            result=result,
            oof_positive_proba=oof_positive_proba,
            fold_assignments=fold_assignments,
            row_positions=population.row_positions,
            population_id=population.population_id,
            population_fingerprint=population.population_fingerprint,
        )

    @staticmethod
    def _notify(
        listener: Callable[[ExperimentProgressEvent], None] | None,
        event: ExperimentProgressEvent,
    ) -> float:
        if listener is None:
            return 0.0
        started_at = perf_counter()
        try:
            listener(event)
        except Exception:
            # Progress is observational: a presentation failure must not alter a run.
            pass
        return perf_counter() - started_at

    def _validate_before_fit(self, contract, dataframe: pd.DataFrame, config: ExperimentConfig, population: EvaluationPopulation):
        if contract.validation_status != "validated":
            raise ValueError("DatasetContract должен иметь статус «validated» до запуска эксперимента.")
        if contract.dataset_id != config.dataset_id or contract.dataset_fingerprint != config.dataset_fingerprint:
            raise ValueError("Идентичность датасета не совпадает с ExperimentConfig.")
        if contract.target_column != config.target:
            raise ValueError("Целевая колонка DatasetContract не совпадает с ExperimentConfig.")
        if len(dataframe) != contract.row_count:
            raise ValueError("Число строк dataframe не совпадает с DatasetContract.")
        if contract.feature_registry_id != self.feature_registry.registry_id:
            raise ValueError("Идентификатор FeatureRegistry не совпадает с DatasetContract.")
        if contract.feature_registry_hash != self.feature_registry.registry_hash:
            raise ValueError("Хеш FeatureRegistry не совпадает с DatasetContract.")
        if any(position >= len(dataframe) for position in population.row_positions):
            raise ValueError("Позиции строк популяции выходят за границы датасета.")
        if contract.final_test_locked:
            if population.partition_role != "working":
                raise ValueError("Для датасета с закрытым final test разрешена только working-популяция.")
            if not population.population_fingerprint:
                raise ValueError("Для working-популяции требуется непустой fingerprint.")
        if config.protocol_id != "stratified_kfold_oof" or config.protocol_version != "1":
            raise ValueError("Runner поддерживает только протокол «stratified_kfold_oof» версии «1».")
        if config.evaluation_level != "oof":
            raise ValueError("Runner поддерживает только evaluation_level «oof».")
        if config.folds < 2:
            raise ValueError("Для OOF требуется не менее двух фолдов.")

        feature_specs = self.feature_registry.resolve(config.feature_ids)
        for spec in feature_specs:
            if spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED:
                raise ValueError(f"Признак «{spec.feature_id}» не разрешён для predictor-использования.")
        predictor_columns = [spec.column_name for spec in feature_specs]
        missing_columns = [column for column in predictor_columns if column not in dataframe.columns]
        if missing_columns:
            raise ValueError(f"Колонки predictor отсутствуют в dataframe: {', '.join(missing_columns)}.")
        if contract.target_column in predictor_columns or contract.identifier_column in predictor_columns:
            raise ValueError("Целевая колонка и идентификатор не могут входить в predictor columns.")
        if len(predictor_columns) != len(set(predictor_columns)):
            raise ValueError("Итоговые имена predictor columns не должны повторяться.")

        model_spec = self.model_registry.get(config.model_id)
        if model_spec.version != config.model_version:
            raise ValueError("Версия модели ModelSpec не совпадает с ExperimentConfig.")
        if "binary" not in model_spec.task_types:
            raise ValueError("ModelSpec не поддерживает задачу «binary».")
        if (
            self.adapter_factory.model_id != config.model_id
            or self.adapter_factory.model_version != config.model_version
            or self.adapter_factory.adapter_version != model_spec.adapter_version
        ):
            raise ValueError("Identity ModelAdapterFactory не согласована с ModelSpec и ExperimentConfig.")
        return feature_specs

    @staticmethod
    def _binary_target(target: pd.Series, positive_class: str | int | float | bool) -> pd.Series:
        if target.isna().any():
            raise ValueError("Целевая колонка не должна содержать пропущенные значения.")
        if not target.eq(positive_class).any():
            raise ValueError("Положительный класс отсутствует в целевой колонке популяции.")
        if target.nunique(dropna=False) != 2:
            raise ValueError("Целевая колонка должна содержать ровно два класса.")
        return target.eq(positive_class).astype(int)

    @staticmethod
    def _validate_oof_feasibility(config: ExperimentConfig, y_binary: pd.Series) -> None:
        class_counts = y_binary.value_counts()
        if class_counts.min() < config.folds:
            raise ValueError("Для каждого класса требуется не меньше наблюдений, чем число фолдов.")

    @staticmethod
    def _validate_probabilities(values: Any, *, expected_length: int) -> np.ndarray:
        probabilities = np.asarray(values, dtype=float)
        if probabilities.ndim != 1:
            raise ValueError("Adapter должен вернуть одномерные вероятности положительного класса.")
        if len(probabilities) != expected_length:
            raise ValueError("Длина вероятностей adapter не совпадает с размером validation-fold.")
        if not np.isfinite(probabilities).all():
            raise ValueError("Вероятности adapter должны быть конечными числами.")
        if (probabilities < 0).any() or (probabilities > 1).any():
            raise ValueError("Вероятности adapter должны лежать в диапазоне [0, 1].")
        return probabilities

    @staticmethod
    def _metrics(y_true: pd.Series, probabilities: np.ndarray) -> dict[str, float]:
        predicted = probabilities >= 0.5
        roc_auc = float(roc_auc_score(y_true, probabilities))
        return {
            "roc_auc": roc_auc,
            "gini": 2 * roc_auc - 1,
            "pr_auc": float(average_precision_score(y_true, probabilities)),
            "precision_at_0_5": float(precision_score(y_true, predicted, zero_division=0)),
            "recall_at_0_5": float(recall_score(y_true, predicted, zero_division=0)),
            "f1_at_0_5": float(f1_score(y_true, predicted, zero_division=0)),
        }

    @staticmethod
    def _confusion(y_true: pd.Series, probabilities: np.ndarray) -> dict[str, int | float]:
        predicted = probabilities >= 0.5
        return {
            "threshold": 0.5,
            "tp": int(((y_true == 1) & predicted).sum()),
            "tn": int(((y_true == 0) & ~predicted).sum()),
            "fp": int(((y_true == 0) & predicted).sum()),
            "fn": int(((y_true == 1) & ~predicted).sum()),
        }
