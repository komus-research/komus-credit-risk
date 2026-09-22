"""Append-only local catalogue of fitted native models, separate from OOF reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import shutil
from typing import Any
from uuid import uuid4

from komus_risk.contracts import DatasetContract, ExperimentConfig, FeatureSpec, FeatureUsageStatus
from komus_risk.hashing import canonical_json, stable_hash
from komus_risk.models import CATBOOST_MODEL_SPEC, GBDT_MEAN_MODEL_SPEC, LIGHTGBM_MODEL_SPEC, XGBOOST_MODEL_SPEC
from komus_risk.models.gbdt.native import NativePredictor, load_native_predictor, native_file_names, save_fitted_native


_SCHEMA_VERSION = "1"
_DEPENDENCIES = {
    "catboost": ("catboost",),
    "xgboost": ("xgboost",),
    "lightgbm": ("lightgbm",),
    "gbdt_mean": ("catboost", "xgboost", "lightgbm"),
}
_MODEL_SPECS = {
    spec.model_id: spec for spec in (CATBOOST_MODEL_SPEC, XGBOOST_MODEL_SPEC, LIGHTGBM_MODEL_SPEC, GBDT_MEAN_MODEL_SPEC)
}


@dataclass(frozen=True, slots=True)
class ModelVersionSummary:
    version_id: str
    created_at: str
    dataset_name: str
    dataset_fingerprint: str
    model_id: str
    feature_count: int
    feature_set_hash: str
    experiment_artifact_id: str


@dataclass(frozen=True, slots=True)
class LoadedModelVersion:
    summary: ModelVersionSummary
    predictor: NativePredictor
    dataset_contract: DatasetContract
    experiment_config: ExperimentConfig
    feature_specs: tuple[FeatureSpec, ...]
    metadata: dict[str, Any]


class ModelVersionStore:
    """Writes immutable versions and checks metadata, native files and runtime on load."""

    def __init__(self, root: str | Path, *, code_version: str) -> None:
        if not code_version.strip():
            raise ValueError("Версия кода должна быть указана для хранилища моделей.")
        self.root = Path(root) / "models"
        self.code_version = code_version

    def save(
        self, *, adapter: Any, config: ExperimentConfig, dataset: DatasetContract,
        source_file_sha256: str, population_id: str, population_fingerprint: str,
        partition_role: str, population_size: int, feature_specs: tuple[FeatureSpec, ...],
        feature_dtypes: tuple[str, ...], experiment_artifact_id: str,
    ) -> ModelVersionSummary:
        if config.model_id not in _DEPENDENCIES:
            raise ValueError("Для выбранного алгоритма нет безопасного формата сохранения.")
        spec = _MODEL_SPECS[config.model_id]
        if config.model_version != spec.version or config.model_parameters != spec.default_profile:
            raise ValueError("Профиль или версия модели не совпадает с поддерживаемым рецептом.")
        self._validate_adapter_recipe(adapter, config)
        if len(feature_specs) != len(feature_dtypes) or not feature_specs:
            raise ValueError("Схема признаков для сохранения модели некорректна.")
        if tuple(spec.feature_id for spec in feature_specs) != config.feature_ids:
            raise ValueError("Порядок признаков не соответствует оценённой конфигурации.")
        if any(spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED for spec in feature_specs):
            raise ValueError("В модель нельзя сохранить запрещённые признаки.")
        if dataset.dataset_fingerprint != config.dataset_fingerprint or dataset.target_column != config.target:
            raise ValueError("Паспорт датасета не совпадает с оценённой конфигурацией.")
        if dataset.final_test_locked and partition_role != "working":
            raise ValueError("Закрытая контрольная выборка не может войти в итоговое обучение.")
        if not dataset.final_test_locked and partition_role != "full":
            raise ValueError("Новый датасет должен использовать подтверждённую полную популяцию.")
        if population_size < 1 or not source_file_sha256 or not population_id or not population_fingerprint:
            raise ValueError("Происхождение обучающей популяции неполно.")
        version_id = uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".tmp-{version_id}"
        target = self.root / version_id
        temporary.mkdir()
        try:
            best_iterations = save_fitted_native(adapter, config.model_id, temporary)
            metadata = {
                "version_id": version_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "code_version": self.code_version,
                "adapter_version": spec.adapter_version,
                "runtime_versions": self._runtime_versions(config.model_id),
                "experiment_artifact_id": experiment_artifact_id,
                "config": config.to_dict(),
                "dataset": dataset.to_dict(),
                "source_file_sha256": source_file_sha256,
                "population": {
                    "population_id": population_id,
                    "population_fingerprint": population_fingerprint,
                    "partition_role": partition_role,
                    "population_size": population_size,
                },
                "features": [spec.to_dict() for spec in feature_specs],
                "feature_dtypes": list(feature_dtypes),
                "input_policy": {"dtype": "float32", "allow_missing": False, "categorical_handling": "disabled"},
                "best_iterations": best_iterations,
            }
            (temporary / "metadata.json").write_text(canonical_json(metadata), encoding="utf-8")
            files = ("metadata.json", *native_file_names(config.model_id))
            manifest = {
                "artifact_type": "fitted_model", "schema_version": _SCHEMA_VERSION, "version_id": version_id,
                "metadata_hash": stable_hash(metadata),
                "files": {
                    name: {"size_bytes": (temporary / name).stat().st_size, "sha256": self._file_hash(temporary / name)}
                    for name in files
                },
            }
            (temporary / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
            summary, _ = self._inspect(temporary, version_id)
            load_native_predictor(config.model_id, temporary, tuple(spec.column_name for spec in feature_specs))
            if target.exists():
                raise ValueError("Версия модели уже существует; перезапись запрещена.")
            temporary.replace(target)
            return summary
        finally:
            if temporary.exists() and temporary.parent.resolve() == self.root.resolve() and not temporary.is_symlink():
                shutil.rmtree(temporary)

    def load(self, version_id: str) -> LoadedModelVersion:
        directory = self._version_path(version_id)
        summary, metadata = self._inspect(directory, version_id)
        if metadata["code_version"] != self.code_version:
            raise ValueError("Версия кода не совпадает с сохранённой моделью.")
        if metadata["runtime_versions"] != self._runtime_versions(summary.model_id):
            raise ValueError("Версии библиотек не совпадают с сохранённой моделью.")
        config = ExperimentConfig.from_dict(metadata["config"])
        dataset = DatasetContract.from_dict(metadata["dataset"])
        features = tuple(FeatureSpec.from_dict(value) for value in metadata["features"])
        columns = tuple(spec.column_name for spec in features)
        try:
            predictor = load_native_predictor(summary.model_id, directory, columns)
        except Exception as error:
            raise ValueError("Нативную модель не удалось безопасно восстановить.") from error
        return LoadedModelVersion(summary, predictor, dataset, config, features, metadata)

    def catalog(self) -> tuple[tuple[ModelVersionSummary, ...], tuple[str, ...]]:
        """List valid versions after restart; isolate corrupt entries without loading estimators."""
        if not self.root.exists():
            return (), ()
        valid: list[ModelVersionSummary] = []
        invalid: list[str] = []
        for directory in self.root.iterdir():
            if directory.name.startswith(".tmp-"):
                continue
            if not self._valid_id(directory.name) or not directory.is_dir() or directory.is_symlink():
                invalid.append(directory.name)
                continue
            try:
                summary, _ = self._inspect(directory, directory.name)
            except (OSError, ValueError, TypeError, KeyError):
                invalid.append(directory.name)
            else:
                valid.append(summary)
        valid.sort(key=lambda item: (item.created_at, item.version_id), reverse=True)
        return tuple(valid), tuple(invalid)

    def _inspect(self, directory: Path, version_id: str) -> tuple[ModelVersionSummary, dict[str, Any]]:
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Каталог версии модели отсутствует или недопустим.")
        manifest = self._read_json(directory / "manifest.json")
        metadata = self._read_json(directory / "metadata.json")
        if (
            manifest.get("artifact_type") != "fitted_model" or manifest.get("schema_version") != _SCHEMA_VERSION
            or manifest.get("version_id") != version_id or metadata.get("version_id") != version_id
            or manifest.get("metadata_hash") != stable_hash(metadata)
        ):
            raise ValueError("Манифест версии модели не согласован с метаданными.")
        config = ExperimentConfig.from_dict(metadata["config"])
        dataset = DatasetContract.from_dict(metadata["dataset"])
        features = tuple(FeatureSpec.from_dict(value) for value in metadata["features"])
        spec = _MODEL_SPECS[config.model_id]
        expected_files = {"metadata.json", *native_file_names(config.model_id)}
        if not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != expected_files:
            raise ValueError("Набор файлов модели не совпадает с манифестом.")
        for name in expected_files:
            path = directory / name
            entry = manifest["files"][name]
            if (
                not path.is_file() or path.is_symlink() or not isinstance(entry, dict)
                or entry.get("size_bytes") != path.stat().st_size or entry.get("sha256") != self._file_hash(path)
            ):
                raise ValueError("Проверка целостности файла модели не прошла.")
        if (
            config.dataset_id != dataset.dataset_id or config.dataset_fingerprint != dataset.dataset_fingerprint
            or config.target != dataset.target_column or tuple(spec.feature_id for spec in features) != config.feature_ids
            or config.model_version != spec.version or config.model_parameters != spec.default_profile
            or metadata.get("adapter_version") != spec.adapter_version
            or config.feature_set_hash is None or len(features) != len(metadata["feature_dtypes"])
            or any(spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED for spec in features)
            or dataset.target_column in {spec.column_name for spec in features}
            or dataset.identifier_column in {spec.column_name for spec in features}
            or len({spec.column_name for spec in features}) != len(features)
            or not isinstance(metadata.get("experiment_artifact_id"), str)
            or not isinstance(metadata.get("source_file_sha256"), str)
        ):
            raise ValueError("Схема версии модели противоречит оценённому эксперименту.")
        population = metadata["population"]
        if (
            not isinstance(population, dict) or population.get("population_size", 0) < 1
            or population.get("partition_role") != ("working" if dataset.final_test_locked else "full")
            or not population.get("population_id") or not population.get("population_fingerprint")
        ):
            raise ValueError("Происхождение обучающей популяции некорректно.")
        summary = ModelVersionSummary(
            version_id, metadata["created_at"], dataset.dataset_name, dataset.dataset_fingerprint,
            config.model_id, len(features), config.feature_set_hash, metadata["experiment_artifact_id"],
        )
        return summary, metadata

    def _version_path(self, version_id: str) -> Path:
        if not self._valid_id(version_id):
            raise ValueError("Недопустимый идентификатор версии модели.")
        return self.root / version_id

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 32 and all(character in "0123456789abcdef" for character in value)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file() or path.is_symlink():
            raise ValueError("Обязательный JSON-файл версии модели отсутствует.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("JSON-файл версии модели повреждён.") from error
        if not isinstance(value, dict):
            raise ValueError("JSON-файл версии модели должен содержать объект.")
        return value

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _runtime_versions(model_id: str) -> dict[str, str]:
        return {
            "python": platform.python_version(), "numpy": version("numpy"), "pandas": version("pandas"),
            "scikit-learn": version("scikit-learn"),
            **{package: version(package) for package in _DEPENDENCIES[model_id]},
        }

    @staticmethod
    def _validate_adapter_recipe(adapter: Any, config: ExperimentConfig) -> None:
        if config.model_id == "gbdt_mean":
            components = getattr(adapter, "_component_adapters", None)
            if not isinstance(components, dict) or set(components) != set(_DEPENDENCIES["gbdt_mean"]):
                raise ValueError("Набор компонентов итоговой модели не совпадает с профилем.")
            for model_id, component in components.items():
                profile = config.model_parameters["components"][model_id]["profile"]
                if getattr(component, "profile", None) != profile or getattr(component, "seed", None) != config.seed:
                    raise ValueError("Профиль компонента итоговой модели не совпадает с оценённым.")
        elif getattr(adapter, "profile", None) != config.model_parameters or getattr(adapter, "seed", None) != config.seed:
            raise ValueError("Профиль итоговой модели не совпадает с оценённым.")
