"""Final fit after a verified OOF experiment, without touching a locked final test."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256

import numpy as np

from komus_risk.artifacts.model_store import ModelVersionStore, ModelVersionSummary
from komus_risk.artifacts.store import ExperimentArtifactStore
from komus_risk.contracts import FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentRunner
from komus_risk.models import ModelAdapterFactory
from komus_risk.registries import FeatureRegistry, ModelRegistry


class FinalModelTrainingService:
    """Re-fits exactly the evaluated recipe on its allowed population and publishes it."""

    def __init__(
        self, *, experiment_store: ExperimentArtifactStore, model_store: ModelVersionStore,
        model_registry: ModelRegistry, model_factories: Mapping[str, ModelAdapterFactory], code_version: str,
    ) -> None:
        self.experiment_store = experiment_store
        self.model_store = model_store
        self.model_registry = model_registry
        self.model_factories = dict(model_factories)
        self.code_version = code_version

    def train_and_save(
        self, *, experiment_artifact_id: str, loaded_dataset: LoadedDataset,
        feature_registry: FeatureRegistry, population: EvaluationPopulation,
        progress_listener: Callable[[str], None] | None = None,
    ) -> ModelVersionSummary:
        artifact = self.experiment_store.load(experiment_artifact_id)
        config = artifact.config
        contract = loaded_dataset.contract
        if (
            contract != artifact.dataset_contract or population != artifact.population
            or config.dataset_fingerprint != contract.dataset_fingerprint
            or contract.feature_registry_id != feature_registry.registry_id
            or contract.feature_registry_hash != feature_registry.registry_hash
            or artifact.run_output.result.code_version != self.code_version
        ):
            raise ValueError("Текущий датасет, популяция или код не совпадают с сохранённой OOF-оценкой.")
        if contract.final_test_locked and population.partition_role != "working":
            raise ValueError("Закрытая финальная выборка не может использоваться для обучения.")
        if not contract.final_test_locked and population.partition_role != "full":
            raise ValueError("Новый датасет должен использовать утверждённую полную популяцию.")
        self._notify(progress_listener, "verifying_source")
        if not loaded_dataset.source_path.is_file() or self._file_hash(loaded_dataset.source_path) != loaded_dataset.source_file_sha256:
            raise ValueError("Исходный файл изменился после оценки; переобучение запрещено.")
        try:
            factory = self.model_factories[config.model_id]
        except KeyError as error:
            raise ValueError("Фабрика выбранного алгоритма недоступна.") from error
        runner = ExperimentRunner(
            feature_registry=feature_registry, model_registry=self.model_registry,
            adapter_factory=factory, code_version=self.code_version,
        )
        specs = runner._validate_before_fit(contract, loaded_dataset.dataframe, config, population)
        if any(spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED for spec in specs):
            raise ValueError("Не все признаки разрешены для итоговой модели.")
        frame = loaded_dataset.dataframe.iloc[list(population.row_positions)]
        target = runner._binary_target(frame[contract.target_column], contract.positive_class)
        predictor_columns = tuple(spec.column_name for spec in specs)
        X = frame.loc[:, list(predictor_columns)]
        feature_dtypes = tuple(str(X[column].dtype) for column in predictor_columns)
        self._notify(progress_listener, "fitting_final_model")
        adapter = factory.create(dict(config.model_parameters), config.seed)
        adapter.fit(X, target)
        probabilities = runner._validate_probabilities(
            adapter.predict_positive_proba(X.iloc[: min(16, len(X))]),
            expected_length=min(16, len(X)),
        )
        if not np.isfinite(probabilities).all():
            raise ValueError("Итоговая модель не прошла проверку прогнозов.")
        self._notify(progress_listener, "saving_model")
        summary = self.model_store.save(
            adapter=adapter, config=config, dataset=contract,
            source_file_sha256=loaded_dataset.source_file_sha256,
            population_id=population.population_id, population_fingerprint=population.population_fingerprint,
            partition_role=population.partition_role, population_size=len(population.row_positions),
            feature_specs=specs, feature_dtypes=feature_dtypes,
            experiment_artifact_id=experiment_artifact_id,
        )
        self._notify(progress_listener, "completed")
        return summary

    @staticmethod
    def _file_hash(path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _notify(listener: Callable[[str], None] | None, stage: str) -> None:
        if listener is not None:
            try:
                listener(stage)
            except Exception:
                pass
