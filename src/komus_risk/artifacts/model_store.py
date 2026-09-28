"""Immutable store for operational fitted-model versions, separate from OOF evidence."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from typing import Any
from uuid import uuid4

import catboost
import lightgbm
import xgboost

from komus_risk.contracts import DatasetContract, ExperimentConfig, FeatureSpec
from komus_risk.experiments import EvaluationPopulation
from komus_risk.hashing import canonical_json, stable_hash
from komus_risk.model_platform import (
    ModelConfigurationRecord,
    ModelPersistenceProviderRegistry,
    ModelPluginRegistry,
)
from komus_risk.models.base import BinaryClassifierAdapter
from komus_risk.models.gbdt.native import (
    NativePredictor,
    load_native_predictor,
    native_model_files,
    save_native_model,
    validate_fitted_adapter_recipe,
)
from komus_risk.registries import FeatureRegistry, ModelSpec

_SCHEMA_VERSION = 1
_SCHEMA_VERSION_V2 = 2


@dataclass(frozen=True, slots=True)
class ModelVersionSummary:
    model_version_id: str
    experiment_artifact_id: str
    model_id: str
    model_version: str
    feature_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedModelVersion:
    summary: ModelVersionSummary
    metadata: dict[str, Any]
    manifest: dict[str, Any]
    predictor: NativePredictor


@dataclass(frozen=True, slots=True)
class _MetadataFeatureRegistry:
    """Minimal immutable registry view used only for self-validating V2 metadata."""

    identity: dict[str, str]
    specs: tuple[FeatureSpec, ...]

    @property
    def registry_id(self) -> str:
        return self.identity["registry_id"]

    @property
    def registry_hash(self) -> str:
        return self.identity["registry_hash"]

    def resolve(self, feature_ids: tuple[str, ...]) -> tuple[FeatureSpec, ...]:
        if tuple(spec.feature_id for spec in self.specs) != tuple(feature_ids):
            raise ValueError("ModelVersion V2 feature order is invalid.")
        return self.specs


class ModelVersionStore:
    """Persists a fresh version directory per final fit and never overwrites it."""

    def __init__(
        self,
        root: str | Path,
        *,
        code_version: str,
        model_specs: Mapping[str, ModelSpec],
        model_plugin_registry: ModelPluginRegistry | None = None,
        persistence_provider_registry: ModelPersistenceProviderRegistry | None = None,
    ) -> None:
        if not isinstance(code_version, str) or not code_version.strip():
            raise ValueError("code_version must be a non-empty string.")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._code_version = code_version
        if not model_specs or any(
            not isinstance(spec, ModelSpec) or model_id != spec.model_id
            for model_id, spec in model_specs.items()
        ):
            raise ValueError(
                "Trusted ModelSpec mapping must be non-empty and keyed by model_id."
            )
        self._model_specs = {
            model_id: ModelSpec.from_dict(spec.to_dict())
            for model_id, spec in model_specs.items()
        }
        if model_plugin_registry is not None and persistence_provider_registry is None:
            persistence_provider_registry = model_plugin_registry.persistence_providers
        if (model_plugin_registry is None) != (persistence_provider_registry is None):
            raise ValueError(
                "ModelVersion V2 requires both trusted plugin and persistence provider registries."
            )
        self._model_plugin_registry = model_plugin_registry
        self._persistence_provider_registry = persistence_provider_registry

    @property
    def code_version(self) -> str:
        return self._code_version

    def save(
        self,
        *,
        experiment_artifact_id: str,
        dataset_contract: DatasetContract,
        config: ExperimentConfig,
        feature_specs: tuple[FeatureSpec, ...],
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
        adapter: BinaryClassifierAdapter,
        source_file_sha256: str,
        configuration_record: ModelConfigurationRecord | None = None,
    ) -> ModelVersionSummary:
        if configuration_record is not None:
            return self._save_v2(
                experiment_artifact_id=experiment_artifact_id,
                dataset_contract=dataset_contract,
                config=config,
                feature_specs=feature_specs,
                feature_registry=feature_registry,
                population=population,
                adapter=adapter,
                source_file_sha256=source_file_sha256,
                configuration_record=configuration_record,
            )
        self._validate_inputs(
            experiment_artifact_id,
            dataset_contract,
            config,
            feature_specs,
            feature_registry,
            population,
        )
        if not isinstance(source_file_sha256, str) or len(source_file_sha256) != 64:
            raise ValueError(
                "Source file SHA-256 must be supplied for a model version."
            )
        validate_fitted_adapter_recipe(
            config.model_id,
            adapter,
            self._model_specs[config.model_id].default_profile,
            config.seed,
        )
        nonce = uuid4().hex
        stage = Path(mkdtemp(prefix=f".{nonce}.", dir=self.root))
        try:
            native_dir = stage / "native"
            native_names = save_native_model(config.model_id, adapter, native_dir)
            metadata = self._metadata(
                experiment_artifact_id,
                dataset_contract,
                config,
                feature_specs,
                population,
                source_file_sha256,
                native_dir,
                native_names,
                nonce,
            )
            version_id = self._version_id(metadata)
            self._write_json(stage / "metadata.json", metadata)
            manifest = self._manifest(version_id, stage, metadata)
            self._write_json(stage / "manifest.json", manifest)
            # Verify the actual persisted artifact before it becomes visible.
            self._load_directory(stage, version_id, allow_temporary=True)
            target = self.root / version_id
            if target.exists():
                raise FileExistsError("Model version id unexpectedly already exists.")
            os.replace(stage, target)
            return ModelVersionSummary(
                version_id,
                experiment_artifact_id,
                config.model_id,
                config.model_version,
                config.feature_ids,
            )
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def load(
        self,
        model_version_id: str,
        *,
        dataset_contract: DatasetContract | None = None,
        config: ExperimentConfig | None = None,
        feature_registry: FeatureRegistry | None = None,
        population: EvaluationPopulation | None = None,
    ) -> LoadedModelVersion:
        loaded = self._load_directory(
            self.root / model_version_id, model_version_id, allow_temporary=False
        )
        metadata = loaded.metadata
        if (
            dataset_contract is not None
            and metadata["dataset_contract"] != dataset_contract.to_dict()
        ):
            raise ValueError(
                "Model version dataset contract does not match current dataset."
            )
        if config is not None and metadata["config"] != config.to_dict():
            raise ValueError(
                "Model version experiment config does not match expected config."
            )
        if feature_registry is not None:
            if metadata["feature_registry"] != {
                "registry_id": feature_registry.registry_id,
                "registry_hash": feature_registry.registry_hash,
            }:
                raise ValueError(
                    "Model version FeatureRegistry does not match current registry."
                )
            expected = tuple(feature_registry.resolve(metadata["feature_ids"]))
            if [spec.to_dict() for spec in expected] != metadata["feature_specs"]:
                raise ValueError(
                    "Model version FeatureSpec payload does not match current registry."
                )
        if population is not None and metadata["population"] != self._population_dict(
            population
        ):
            raise ValueError(
                "Model version population provenance does not match current population."
            )
        return loaded

    def _load_directory(
        self, directory: Path, version_id: str, *, allow_temporary: bool
    ) -> LoadedModelVersion:
        if not directory.is_dir() or (
            not allow_temporary and directory.name != version_id
        ):
            raise ValueError("Model version directory is missing or invalid.")
        try:
            metadata = self._read_json(directory / "metadata.json")
            if metadata.get("schema_version") == _SCHEMA_VERSION_V2:
                return self._load_directory_v2(
                    directory,
                    version_id,
                    allow_temporary=allow_temporary,
                    metadata=metadata,
                )
            manifest = self._read_json(directory / "manifest.json")
        except ValueError as error:
            raise ValueError(
                "Model version metadata or manifest is invalid."
            ) from error
        self._validate_manifest(manifest, version_id)
        expected_files = {
            "metadata.json",
            *[
                f"native/{name}"
                for name in native_model_files(metadata.get("model_id"))
            ],
        }
        if set(manifest["files"]) != expected_files:
            raise ValueError("Model version manifest file list is invalid.")
        for name, details in manifest["files"].items():
            path = directory / name
            if (
                not path.is_file()
                or not isinstance(details, dict)
                or details.get("sha256") != self._raw_hash(path)
                or details.get("size_bytes") != path.stat().st_size
            ):
                raise ValueError("Model version file integrity check failed.")
        self._validate_metadata(metadata)
        if manifest["metadata_hash"] != stable_hash(metadata):
            raise ValueError("Model version semantic metadata integrity check failed.")
        if self._version_id(metadata) != version_id:
            raise ValueError(
                "Model version identity does not match its immutable metadata."
            )
        for name, digest in metadata["native_hashes"].items():
            if self._raw_hash(directory / "native" / name) != digest:
                raise ValueError(
                    "Model version native payload does not match immutable metadata."
                )
        current_runtime = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "catboost": catboost.__version__,
            "xgboost": xgboost.__version__,
            "lightgbm": lightgbm.__version__,
        }
        if metadata["runtime"] != current_runtime:
            raise ValueError("Model version runtime/library identity is incompatible.")
        if metadata["code_version"] != self.code_version:
            raise ValueError("Model version code identity is incompatible.")
        predictor = load_native_predictor(
            metadata["model_id"],
            directory / "native",
            tuple(metadata["feature_columns"]),
        )
        summary = ModelVersionSummary(
            version_id,
            metadata["experiment_artifact_id"],
            metadata["model_id"],
            metadata["model_version"],
            tuple(metadata["feature_ids"]),
        )
        return LoadedModelVersion(summary, metadata, manifest, predictor)

    def _save_v2(
        self,
        *,
        experiment_artifact_id: str,
        dataset_contract: DatasetContract,
        config: ExperimentConfig,
        feature_specs: tuple[FeatureSpec, ...],
        feature_registry: FeatureRegistry,
        population: EvaluationPopulation,
        adapter: BinaryClassifierAdapter,
        source_file_sha256: str,
        configuration_record: ModelConfigurationRecord,
    ) -> ModelVersionSummary:
        provider = self._validate_v2_inputs(
            experiment_artifact_id,
            dataset_contract,
            config,
            feature_specs,
            feature_registry,
            population,
            source_file_sha256,
            configuration_record,
        )
        provider.validate_fitted(
            adapter, parameters=dict(config.model_parameters), seed=config.seed
        )
        nonce = uuid4().hex
        stage = Path(mkdtemp(prefix=f".{nonce}.", dir=self.root))
        try:
            native_dir = stage / "native"
            native_names = provider.save(adapter, native_dir)
            if native_names != provider.native_files():
                raise ValueError(
                    "Persistence provider native file declaration is inconsistent."
                )
            metadata = self._metadata_v2(
                experiment_artifact_id,
                dataset_contract,
                config,
                feature_specs,
                population,
                source_file_sha256,
                native_dir,
                native_names,
                nonce,
                configuration_record,
                provider,
            )
            version_id = self._version_id(metadata)
            self._write_json(stage / "metadata.json", metadata)
            manifest = self._manifest_v2(version_id, stage, metadata)
            self._write_json(stage / "manifest.json", manifest)
            self._load_directory(stage, version_id, allow_temporary=True)
            target = self.root / version_id
            if target.exists():
                raise FileExistsError("Model version id unexpectedly already exists.")
            os.replace(stage, target)
            return ModelVersionSummary(
                version_id,
                experiment_artifact_id,
                config.model_id,
                config.model_version,
                config.feature_ids,
            )
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def _validate_v2_inputs(
        self,
        experiment_artifact_id,
        dataset,
        config,
        specs,
        registry,
        population,
        source_file_sha256,
        record,
    ):
        if (
            self._model_plugin_registry is None
            or self._persistence_provider_registry is None
        ):
            raise ValueError("Trusted ModelVersion V2 providers are not configured.")
        if not isinstance(record, ModelConfigurationRecord):
            raise ValueError(
                "ModelVersion V2 requires trusted configuration provenance."
            )
        if not isinstance(source_file_sha256, str) or len(source_file_sha256) != 64:
            raise ValueError(
                "Source file SHA-256 must be supplied for a model version."
            )
        self._validate_common_inputs(
            experiment_artifact_id, dataset, config, specs, registry, population
        )
        try:
            plugin = self._model_plugin_registry.get(config.model_id)
            provider = self._persistence_provider_registry.validate_plugin_provider(
                plugin
            )
        except (KeyError, ValueError) as error:
            raise ValueError(
                "Trusted persistence provider is unavailable or incompatible."
            ) from error
        identity = (config.model_id, config.model_version, plugin.spec.adapter_version)
        if (
            plugin.spec.model_id,
            plugin.spec.version,
            plugin.spec.adapter_version,
        ) != identity:
            raise ValueError(
                "Experiment configuration is incompatible with trusted plugin."
            )
        if (
            record.model_id,
            record.model_version,
            record.adapter_version,
            record.plugin_contract_hash,
        ) != (*identity, plugin.plugin_contract_hash):
            raise ValueError("Configuration provenance does not match trusted plugin.")
        if record.resolved_parameters != config.model_parameters:
            raise ValueError(
                "Configuration provenance parameters do not match experiment."
            )
        if record.resolved_configuration_hash != stable_hash(
            {
                "model_id": plugin.spec.model_id,
                "model_version": plugin.spec.version,
                "adapter_version": plugin.spec.adapter_version,
                "schema_hash": plugin.parameter_schema.schema_hash,
                "resolved_parameters": dict(config.model_parameters),
            }
        ):
            raise ValueError("Configuration provenance resolved hash is invalid.")
        if (
            record.schema_id,
            record.schema_version,
            record.schema_hash,
            record.recommended_profile_id,
            record.recommended_profile_hash,
        ) != (
            plugin.parameter_schema.schema_id,
            plugin.parameter_schema.schema_version,
            plugin.parameter_schema.schema_hash,
            plugin.recommended_profile.profile_id,
            plugin.recommended_profile.profile_hash,
        ):
            raise ValueError(
                "Configuration provenance schema/profile is incompatible with trusted plugin."
            )
        return provider

    def _validate_common_inputs(
        self, experiment_artifact_id, dataset, config, specs, registry, population
    ) -> None:
        if (
            not isinstance(experiment_artifact_id, str)
            or not experiment_artifact_id.strip()
        ):
            raise ValueError("Experiment artifact identity must be non-empty.")
        if (
            dataset.dataset_id != config.dataset_id
            or dataset.dataset_fingerprint != config.dataset_fingerprint
            or dataset.target_column != config.target
        ):
            raise ValueError("DatasetContract and ExperimentConfig are inconsistent.")
        if (
            dataset.feature_registry_id != registry.registry_id
            or dataset.feature_registry_hash != registry.registry_hash
        ):
            raise ValueError(
                "DatasetContract is not bound to the supplied FeatureRegistry."
            )
        if tuple(registry.resolve(config.feature_ids)) != specs:
            raise ValueError(
                "Feature specs do not exactly match the supplied FeatureRegistry."
            )
        self._validate_feature_specs(dataset, config, specs)
        if dataset.final_test_locked and population.partition_role != "working":
            raise ValueError(
                "Locked final test permits only a working final-fit population."
            )
        if not dataset.final_test_locked and population.partition_role != "full":
            raise ValueError(
                "Generic dataset final fit requires the confirmed full population."
            )

    def _metadata_v2(
        self,
        experiment_artifact_id,
        dataset,
        config,
        specs,
        population,
        source_file_sha256,
        native_dir,
        native_names,
        nonce,
        record,
        provider,
    ) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION_V2,
            "version_nonce": nonce,
            "experiment_artifact_id": experiment_artifact_id,
            "dataset_contract": dataset.to_dict(),
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "config": config.to_dict(),
            "config_hash": config.config_hash,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "adapter_version": record.adapter_version,
            "feature_ids": list(config.feature_ids),
            "feature_set_hash": config.feature_set_hash,
            "feature_columns": [spec.column_name for spec in specs],
            "feature_specs": [spec.to_dict() for spec in specs],
            "feature_registry": {
                "registry_id": dataset.feature_registry_id,
                "registry_hash": dataset.feature_registry_hash,
            },
            "population": self._population_dict(population),
            "partition_role": population.partition_role,
            "source_file_sha256": source_file_sha256,
            "code_version": self.code_version,
            "runtime": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "catboost": catboost.__version__,
                "xgboost": xgboost.__version__,
                "lightgbm": lightgbm.__version__,
            },
            "configuration_record": record.to_dict(),
            "persistence_provider": provider.descriptor.to_dict(),
            "native_files": list(native_names),
            "native_hashes": {
                name: self._raw_hash(native_dir / name) for name in native_names
            },
        }

    @staticmethod
    def _manifest_v2(
        version_id: str, directory: Path, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        files = [
            "metadata.json",
            *[f"native/{name}" for name in metadata["native_files"]],
        ]
        return {
            "artifact_type": "model_version",
            "schema_version": _SCHEMA_VERSION_V2,
            "model_version_id": version_id,
            "metadata_hash": stable_hash(metadata),
            "files": {
                name: {
                    "sha256": ModelVersionStore._raw_hash(directory / name),
                    "size_bytes": (directory / name).stat().st_size,
                }
                for name in files
            },
        }

    def _load_directory_v2(
        self,
        directory: Path,
        version_id: str,
        *,
        allow_temporary: bool,
        metadata: dict[str, Any],
    ) -> LoadedModelVersion:
        if (
            self._model_plugin_registry is None
            or self._persistence_provider_registry is None
        ):
            raise ValueError("Trusted ModelVersion V2 providers are not configured.")
        manifest = self._read_json(directory / "manifest.json")
        self._validate_manifest_v2(manifest, version_id)
        self._validate_metadata_v2(metadata)
        expected_files = {
            "metadata.json",
            *[f"native/{name}" for name in metadata["native_files"]],
        }
        if set(manifest["files"]) != expected_files:
            raise ValueError("Model version manifest file list is invalid.")
        for name, details in manifest["files"].items():
            path = directory / name
            if (
                not path.is_file()
                or not isinstance(details, dict)
                or details.get("sha256") != self._raw_hash(path)
                or details.get("size_bytes") != path.stat().st_size
            ):
                raise ValueError("Model version file integrity check failed.")
        if (
            manifest["metadata_hash"] != stable_hash(metadata)
            or self._version_id(metadata) != version_id
        ):
            raise ValueError("Model version metadata integrity is invalid.")
        if metadata["code_version"] != self.code_version or metadata["runtime"] != {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "catboost": catboost.__version__,
            "xgboost": xgboost.__version__,
            "lightgbm": lightgbm.__version__,
        }:
            raise ValueError("Model version runtime/code identity is incompatible.")
        record = ModelConfigurationRecord.from_dict(metadata["configuration_record"])
        config = ExperimentConfig.from_dict(metadata["config"])
        dataset = DatasetContract.from_dict(metadata["dataset_contract"])
        specs = tuple(FeatureSpec.from_dict(item) for item in metadata["feature_specs"])
        population_data = metadata["population"]
        population = EvaluationPopulation(
            tuple(population_data["row_positions"]),
            population_data["population_id"],
            population_data["population_fingerprint"],
            population_data["partition_role"],
        )
        provider = self._validate_v2_inputs(
            metadata["experiment_artifact_id"],
            dataset,
            config,
            specs,
            _MetadataFeatureRegistry(metadata["feature_registry"], specs),
            population,
            metadata["source_file_sha256"],
            record,
        )
        if (
            metadata["persistence_provider"] != provider.descriptor.to_dict()
            or tuple(metadata["native_files"]) != provider.native_files()
        ):
            raise ValueError(
                "Model version persistence provider provenance is invalid."
            )
        for name, digest in metadata["native_hashes"].items():
            if self._raw_hash(directory / "native" / name) != digest:
                raise ValueError(
                    "Model version native payload does not match immutable metadata."
                )
        predictor = provider.load(
            directory / "native", tuple(metadata["feature_columns"])
        )
        summary = ModelVersionSummary(
            version_id,
            metadata["experiment_artifact_id"],
            metadata["model_id"],
            metadata["model_version"],
            tuple(metadata["feature_ids"]),
        )
        return LoadedModelVersion(summary, metadata, manifest, predictor)

    def _validate_metadata_v2(self, value: Any) -> None:
        required = {
            "schema_version",
            "version_nonce",
            "experiment_artifact_id",
            "dataset_contract",
            "dataset_fingerprint",
            "config",
            "config_hash",
            "model_id",
            "model_version",
            "adapter_version",
            "feature_ids",
            "feature_set_hash",
            "feature_columns",
            "feature_specs",
            "feature_registry",
            "population",
            "partition_role",
            "source_file_sha256",
            "code_version",
            "runtime",
            "configuration_record",
            "persistence_provider",
            "native_files",
            "native_hashes",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or value["schema_version"] != _SCHEMA_VERSION_V2
        ):
            raise ValueError("ModelVersion V2 metadata structure is invalid.")
        if (
            not isinstance(value["version_nonce"], str)
            or len(value["version_nonce"]) != 32
            or not isinstance(value["native_files"], list)
            or set(value["native_hashes"]) != set(value["native_files"])
        ):
            raise ValueError("ModelVersion V2 immutable identity is invalid.")
        if any(
            not isinstance(digest, str) or len(digest) != 64
            for digest in value["native_hashes"].values()
        ):
            raise ValueError("ModelVersion V2 native hashes are invalid.")
        config = ExperimentConfig.from_dict(value["config"])
        dataset = DatasetContract.from_dict(value["dataset_contract"])
        specs = tuple(FeatureSpec.from_dict(item) for item in value["feature_specs"])
        record = ModelConfigurationRecord.from_dict(value["configuration_record"])
        population_data = value["population"]
        population = EvaluationPopulation(
            tuple(population_data["row_positions"]),
            population_data["population_id"],
            population_data["population_fingerprint"],
            population_data["partition_role"],
        )
        if (
            value["dataset_fingerprint"] != dataset.dataset_fingerprint
            or value["config_hash"] != config.config_hash
            or value["model_id"] != config.model_id
            or value["model_version"] != config.model_version
            or value["model_id"] != record.model_id
            or value["model_version"] != record.model_version
            or value["adapter_version"] != record.adapter_version
            or value["feature_ids"] != list(config.feature_ids)
            or value["feature_ids"] != [spec.feature_id for spec in specs]
            or value["feature_set_hash"] != config.feature_set_hash
            or value["feature_columns"] != [spec.column_name for spec in specs]
            or value["feature_registry"]
            != {
                "registry_id": dataset.feature_registry_id,
                "registry_hash": dataset.feature_registry_hash,
            }
            or value["partition_role"] != population.partition_role
        ):
            raise ValueError("ModelVersion V2 metadata is internally inconsistent.")

    @staticmethod
    def _validate_manifest_v2(value: Any, version_id: str) -> None:
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "artifact_type",
                "schema_version",
                "model_version_id",
                "metadata_hash",
                "files",
            }
            or value["artifact_type"] != "model_version"
            or value["schema_version"] != _SCHEMA_VERSION_V2
            or value["model_version_id"] != version_id
            or not isinstance(value["files"], dict)
        ):
            raise ValueError("ModelVersion V2 manifest structure is invalid.")

    def _validate_inputs(
        self,
        experiment_artifact_id: str,
        dataset: DatasetContract,
        config: ExperimentConfig,
        specs: tuple[FeatureSpec, ...],
        registry: FeatureRegistry,
        population: EvaluationPopulation,
    ) -> None:
        if (
            not isinstance(experiment_artifact_id, str)
            or not experiment_artifact_id.strip()
        ):
            raise ValueError("Experiment artifact identity must be non-empty.")
        if (
            dataset.dataset_id != config.dataset_id
            or dataset.dataset_fingerprint != config.dataset_fingerprint
            or dataset.target_column != config.target
        ):
            raise ValueError("DatasetContract and ExperimentConfig are inconsistent.")
        self._validate_current_recipe(config)
        if (
            dataset.feature_registry_id != registry.registry_id
            or dataset.feature_registry_hash != registry.registry_hash
        ):
            raise ValueError(
                "DatasetContract is not bound to the supplied FeatureRegistry."
            )
        if tuple(registry.resolve(config.feature_ids)) != specs:
            raise ValueError(
                "Feature specs do not exactly match the supplied FeatureRegistry."
            )
        self._validate_feature_specs(dataset, config, specs)
        if dataset.final_test_locked and population.partition_role != "working":
            raise ValueError(
                "Locked final test permits only a working final-fit population."
            )
        if not dataset.final_test_locked and population.partition_role != "full":
            raise ValueError(
                "Generic dataset final fit requires the confirmed full population."
            )

    def _metadata(
        self,
        experiment_artifact_id: str,
        dataset: DatasetContract,
        config: ExperimentConfig,
        specs: tuple[FeatureSpec, ...],
        population: EvaluationPopulation,
        source_file_sha256: str,
        native_dir: Path,
        native_names: tuple[str, ...],
        nonce: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "version_nonce": nonce,
            "experiment_artifact_id": experiment_artifact_id,
            "dataset_contract": dataset.to_dict(),
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "config": config.to_dict(),
            "config_hash": config.config_hash,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "model_recipe": self._recipe(self._model_specs[config.model_id]),
            "feature_ids": list(config.feature_ids),
            "feature_set_hash": config.feature_set_hash,
            "feature_columns": [spec.column_name for spec in specs],
            "feature_specs": [spec.to_dict() for spec in specs],
            "feature_registry": {
                "registry_id": dataset.feature_registry_id,
                "registry_hash": dataset.feature_registry_hash,
            },
            "population": ModelVersionStore._population_dict(population),
            "partition_role": population.partition_role,
            "source_file_sha256": source_file_sha256,
            "code_version": self.code_version,
            "runtime": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "catboost": catboost.__version__,
                "xgboost": xgboost.__version__,
                "lightgbm": lightgbm.__version__,
            },
            "native_files": list(native_names),
            "native_hashes": {
                name: ModelVersionStore._raw_hash(native_dir / name)
                for name in native_names
            },
        }

    @staticmethod
    def _population_dict(population: EvaluationPopulation) -> dict[str, Any]:
        return {
            "population_id": population.population_id,
            "population_fingerprint": population.population_fingerprint,
            "partition_role": population.partition_role,
            "row_positions": list(population.row_positions),
        }

    @staticmethod
    def _recipe(spec: ModelSpec) -> dict[str, Any]:
        return {
            "model_id": spec.model_id,
            "model_version": spec.version,
            "parameters": spec.default_profile,
            "adapter_version": spec.adapter_version,
        }

    @staticmethod
    def _manifest(
        version_id: str, directory: Path, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        files = [
            "metadata.json",
            *[f"native/{name}" for name in metadata["native_files"]],
        ]
        return {
            "artifact_type": "model_version",
            "schema_version": _SCHEMA_VERSION,
            "model_version_id": version_id,
            "metadata_hash": stable_hash(metadata),
            "files": {
                name: {
                    "sha256": ModelVersionStore._raw_hash(directory / name),
                    "size_bytes": (directory / name).stat().st_size,
                }
                for name in files
            },
        }

    def _validate_metadata(self, value: Any) -> None:
        required = {
            "schema_version",
            "version_nonce",
            "experiment_artifact_id",
            "dataset_contract",
            "dataset_fingerprint",
            "config",
            "config_hash",
            "model_id",
            "model_version",
            "model_recipe",
            "feature_ids",
            "feature_set_hash",
            "feature_columns",
            "feature_specs",
            "feature_registry",
            "population",
            "partition_role",
            "source_file_sha256",
            "code_version",
            "runtime",
            "native_files",
            "native_hashes",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or value["schema_version"] != _SCHEMA_VERSION
        ):
            raise ValueError("Model version metadata structure is invalid.")
        dataset, config = (
            DatasetContract.from_dict(value["dataset_contract"]),
            ExperimentConfig.from_dict(value["config"]),
        )
        specs = tuple(FeatureSpec.from_dict(item) for item in value["feature_specs"])
        population_data = value["population"]
        population = EvaluationPopulation(
            tuple(population_data["row_positions"]),
            population_data["population_id"],
            population_data["population_fingerprint"],
            population_data["partition_role"],
        )
        if (
            not isinstance(value["experiment_artifact_id"], str)
            or not value["experiment_artifact_id"].strip()
        ):
            raise ValueError("Model version experiment artifact identity is invalid.")
        self._validate_current_recipe(config)
        self._validate_feature_specs(dataset, config, specs)
        if dataset.final_test_locked and population.partition_role != "working":
            raise ValueError(
                "Locked final test permits only a working final-fit population."
            )
        if not dataset.final_test_locked and population.partition_role != "full":
            raise ValueError(
                "Generic dataset final fit requires the confirmed full population."
            )
        if (
            value["dataset_fingerprint"] != dataset.dataset_fingerprint
            or value["config_hash"] != config.config_hash
            or value["model_id"] != config.model_id
            or value["model_version"] != config.model_version
            or value["feature_set_hash"] != config.feature_set_hash
            or value["feature_columns"] != [spec.column_name for spec in specs]
            or value["feature_registry"]
            != {
                "registry_id": dataset.feature_registry_id,
                "registry_hash": dataset.feature_registry_hash,
            }
            or value["partition_role"] != population.partition_role
            or value["model_recipe"] != self._recipe(self._model_specs[config.model_id])
            or tuple(value["native_files"]) != native_model_files(config.model_id)
        ):
            raise ValueError("Model version metadata is internally inconsistent.")
        if (
            not isinstance(value["source_file_sha256"], str)
            or len(value["source_file_sha256"]) != 64
        ):
            raise ValueError("Model version source identity is invalid.")
        if (
            not isinstance(value["version_nonce"], str)
            or len(value["version_nonce"]) != 32
            or set(value["native_hashes"]) != set(value["native_files"])
            or any(
                not isinstance(digest, str) or len(digest) != 64
                for digest in value["native_hashes"].values()
            )
        ):
            raise ValueError("Model version immutable identity is invalid.")

    def _validate_current_recipe(self, config: ExperimentConfig) -> None:
        try:
            spec = self._model_specs[config.model_id]
        except KeyError as error:
            raise ValueError(
                "Model version uses an unknown current ModelSpec."
            ) from error
        if (
            config.model_version != spec.version
            or config.model_parameters != spec.default_profile
        ):
            raise ValueError(
                "Model version recipe does not match current frozen ModelSpec."
            )

    @staticmethod
    def _validate_feature_specs(
        dataset: DatasetContract,
        config: ExperimentConfig,
        specs: tuple[FeatureSpec, ...],
    ) -> None:
        if (
            not specs
            or tuple(spec.feature_id for spec in specs) != config.feature_ids
            or len(config.feature_ids) != len(set(config.feature_ids))
        ):
            raise ValueError(
                "Feature specs must be non-empty and exactly preserve unique ExperimentConfig feature order."
            )
        columns = [spec.column_name for spec in specs]
        if any(spec.usage_status.value != "model_allowed" for spec in specs):
            raise ValueError("Every model-version feature must be MODEL_ALLOWED.")
        if (
            dataset.target_column in columns
            or dataset.identifier_column in columns
            or len(columns) != len(set(columns))
        ):
            raise ValueError(
                "Model-version predictor columns must be unique and exclude target and identifier."
            )

    @staticmethod
    def _version_id(metadata: dict[str, Any]) -> str:
        return stable_hash(
            {"model_version_schema": _SCHEMA_VERSION, "metadata": metadata}
        )

    @staticmethod
    def _validate_manifest(value: Any, version_id: str) -> None:
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "artifact_type",
                "schema_version",
                "model_version_id",
                "metadata_hash",
                "files",
            }
            or value["artifact_type"] != "model_version"
            or value["schema_version"] != _SCHEMA_VERSION
            or value["model_version_id"] != version_id
            or not isinstance(value["files"], dict)
        ):
            raise ValueError("Model version manifest structure is invalid.")

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(canonical_json(value), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Model version JSON is invalid.") from error
        if not isinstance(value, dict):
            raise ValueError("Model version JSON must be an object.")
        return value

    @staticmethod
    def _raw_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()
