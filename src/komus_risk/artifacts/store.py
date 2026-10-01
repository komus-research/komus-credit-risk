"""Fail-closed, immutable filesystem persistence for completed experiment runs."""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput, OOFResultEvidence
from komus_risk.hashing import canonical_json, stable_hash
from komus_risk.model_platform import (
    ModelConfigurationRecord,
    SmokeEvidence,
    SmokeStatus,
)
from komus_risk.model_platform.contracts import ProviderDescriptor
from komus_risk.model_platform.persistence import ModelPersistenceProvider

from .contracts import ExperimentArtifactMetadata, LoadedExperimentArtifact, LoadedOOFFoldModel

_SCHEMA_VERSION_V1 = "1"
_SCHEMA_VERSION_V2 = "2"
_SCHEMA_VERSION_V3 = "3"
_PAYLOAD_FILES_V1 = (
    "config.json",
    "dataset.json",
    "population.json",
    "result.json",
    "evidence/oof_positive_proba.npy",
    "evidence/fold_assignments.npy",
    "evidence/row_positions.npy",
)
_PAYLOAD_FILES_V2 = _PAYLOAD_FILES_V1 + ("configuration.json", "smoke.json")
_PAYLOAD_FILES_V3 = _PAYLOAD_FILES_V2 + (
    "evidence/oof_y_true.npy",
    "evidence/identifier_display.npy",
    "evidence/model_input.npy",
    "evidence/feature_binding.json",
)


class ExperimentArtifactStore:
    """Publishes only fully validated content-addressed experiment artifacts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.experiments = self.root / "experiments"

    def save(
        self,
        *,
        config: ExperimentConfig,
        dataset_contract: DatasetContract,
        population: EvaluationPopulation,
        run_output: ExperimentRunOutput,
        configuration_record: ModelConfigurationRecord | None = None,
        smoke_evidence: SmokeEvidence | None = None,
        fold_model_provider: ModelPersistenceProvider | None = None,
    ) -> LoadedExperimentArtifact:
        if (configuration_record is None) != (smoke_evidence is None):
            raise ValueError(
                "MP-C artifacts require both configuration and smoke provenance."
            )
        if run_output.oof_evidence is not None:
            return self._save_v3(
                config=config,
                dataset_contract=dataset_contract,
                population=population,
                run_output=run_output,
                configuration_record=configuration_record,
                smoke_evidence=smoke_evidence,
                provider=fold_model_provider,
            )
        if fold_model_provider is not None:
            raise ValueError("Fold persistence provider is valid only for V3 evidence.")
        schema_version = (
            _SCHEMA_VERSION_V2
            if configuration_record is not None
            else _SCHEMA_VERSION_V1
        )
        if configuration_record is not None:
            self._validate_v2_provenance(
                config,
                dataset_contract,
                population,
                configuration_record,
                smoke_evidence,
            )
        arrays = self._canonical_arrays(run_output)
        self._validate_bundle(config, dataset_contract, population, run_output, arrays)
        payload = self._payload(
            config,
            dataset_contract,
            population,
            run_output.result,
            arrays,
            configuration_record,
            smoke_evidence,
        )
        content_hashes = self._content_hashes(payload, arrays)
        artifact_id = self._artifact_id(content_hashes, schema_version)
        target = self.experiments / artifact_id
        if target.exists():
            return self.load(artifact_id)

        self.experiments.mkdir(parents=True, exist_ok=True)
        temporary = self.experiments / f".tmp-{artifact_id}-{uuid4().hex}"
        try:
            (temporary / "evidence").mkdir(parents=True)
            self._write_payload(temporary, payload, arrays)
            manifest = self._manifest(
                artifact_id,
                config,
                dataset_contract,
                population,
                run_output.result,
                content_hashes,
                temporary,
                schema_version,
            )
            self._write_json(temporary / "manifest.json", manifest)
            loaded = self._load_directory(temporary, artifact_id, allow_temporary=True)
            if target.exists():
                return self.load(artifact_id)
            temporary.replace(target)
            return loaded
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _save_v3(
        self,
        *,
        config: ExperimentConfig,
        dataset_contract: DatasetContract,
        population: EvaluationPopulation,
        run_output: ExperimentRunOutput,
        configuration_record: ModelConfigurationRecord | None,
        smoke_evidence: SmokeEvidence | None,
        provider: ModelPersistenceProvider | None,
    ) -> LoadedExperimentArtifact:
        """Persist, reload and prove every fold before an artifact becomes visible."""
        if configuration_record is None or smoke_evidence is None or provider is None:
            raise ValueError("V3 evidence requires provenance and a trusted fold persistence provider.")
        self._validate_v2_provenance(config, dataset_contract, population, configuration_record, smoke_evidence)
        evidence = run_output.oof_evidence
        assert evidence is not None
        if (provider.model_id, provider.model_version, provider.adapter_version) != (
            config.model_id, config.model_version, configuration_record.adapter_version,
        ):
            raise ValueError("Fold persistence provider identity does not match experiment.")
        arrays = self._canonical_arrays(run_output)
        arrays.update(self._canonical_v3_arrays(evidence))
        self._validate_bundle(config, dataset_contract, population, run_output, arrays)
        self._validate_v3_evidence(config, population, evidence, arrays)
        payload = self._payload(config, dataset_contract, population, run_output.result, arrays, configuration_record, smoke_evidence)
        payload["feature_binding"] = self._feature_binding(evidence)

        self.experiments.mkdir(parents=True, exist_ok=True)
        temporary = self.experiments / f".tmp-v3-{uuid4().hex}"
        try:
            (temporary / "evidence").mkdir(parents=True)
            self._write_payload(temporary, payload, arrays)
            self._write_json(temporary / "evidence" / "feature_binding.json", payload["feature_binding"])
            self._write_fold_models(temporary, config, population, evidence, arrays, provider)
            fold_hash = self._fold_models_hash(temporary)
            self._validate_v3_canonical_result(run_output.result, arrays)
            content_hashes = self._content_hashes(payload, arrays)
            content_hashes["feature_binding"] = stable_hash(payload["feature_binding"])
            content_hashes["fold_models"] = fold_hash
            artifact_id = self._artifact_id(content_hashes, _SCHEMA_VERSION_V3)
            target = self.experiments / artifact_id
            if target.exists():
                return self.load(artifact_id)
            manifest = self._manifest(artifact_id, config, dataset_contract, population, run_output.result, content_hashes, temporary, _SCHEMA_VERSION_V3)
            self._write_json(temporary / "manifest.json", manifest)
            loaded = self._load_directory(temporary, artifact_id, allow_temporary=True)
            if target.exists():
                return self.load(artifact_id)
            temporary.replace(target)
            return loaded
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def load(self, artifact_id: str) -> LoadedExperimentArtifact:
        if not self._is_artifact_id(artifact_id):
            raise ValueError("Invalid experiment artifact identifier.")
        return self._load_directory(
            self.experiments / artifact_id, artifact_id, allow_temporary=False
        )

    def read_metadata(self, artifact_id: str) -> ExperimentArtifactMetadata:
        """Validate only the trusted JSON metadata needed by History catalogues."""
        if not self._is_artifact_id(artifact_id):
            raise ValueError("Invalid experiment artifact identifier.")
        directory = self.experiments / artifact_id
        if not directory.is_dir():
            raise ValueError("Experiment artifact directory is missing or incomplete.")
        if directory.name != artifact_id:
            raise ValueError("Artifact directory name does not match artifact_id.")
        manifest = self._read_json(directory / "manifest.json")
        schema_version = self._validate_manifest(manifest, artifact_id)
        expected_artifact_id = self._artifact_id(manifest["content_hashes"], schema_version)
        if expected_artifact_id != artifact_id:
            raise ValueError("Experiment artifact content-addressed identity is invalid.")
        metadata_files = ("config.json", "dataset.json", "population.json", "result.json")
        payload: dict[str, dict[str, Any]] = {}
        for name in metadata_files:
            path = directory / name
            info = manifest["files"].get(name)
            if not path.is_file() or not isinstance(info, dict):
                raise ValueError("Experiment artifact mandatory metadata file is missing.")
            if (
                info.get("size_bytes") != path.stat().st_size
                or info.get("sha256") != self._raw_hash(path)
            ):
                raise ValueError("Experiment artifact metadata integrity check failed.")
            payload[name] = self._read_json(path)
        config = ExperimentConfig.from_dict(payload["config.json"])
        dataset = DatasetContract.from_dict(payload["dataset.json"])
        result = ExperimentResult.from_dict(payload["result.json"])
        population = payload["population.json"]
        population_id = population.get("population_id")
        population_fingerprint = population.get("population_fingerprint")
        population_size = population.get("population_size")
        if (
            not isinstance(population_id, str) or not population_id.strip()
            or not isinstance(population_fingerprint, str) or not population_fingerprint.strip()
            or isinstance(population_size, bool) or not isinstance(population_size, int)
            or population_size < 1
        ):
            raise ValueError("Experiment artifact population metadata is invalid.")
        hashes = {
            "config": stable_hash(config.to_dict()),
            "dataset": stable_hash(dataset.to_dict()),
            "population": stable_hash(population),
            "result": stable_hash(result.to_dict()),
        }
        if any(manifest["content_hashes"].get(key) != value for key, value in hashes.items()):
            raise ValueError("Experiment artifact metadata semantic integrity check failed.")
        self._validate_metadata_identity(
            manifest["identity"], config, dataset, result, population_id, population_fingerprint
        )
        return ExperimentArtifactMetadata(
            artifact_id, schema_version, config, dataset, result,
            population_id, population_fingerprint, population_size,
        )

    def browse_metadata(self) -> tuple[ExperimentArtifactMetadata, ...]:
        """Browse canonical published artifacts without loading evidence arrays."""
        if not self.experiments.exists():
            return ()
        found: list[ExperimentArtifactMetadata] = []
        for child in self.experiments.iterdir():
            if not child.is_dir() or not self._is_artifact_id(child.name):
                continue
            found.append(self.read_metadata(child.name))
        return tuple(found)

    def load_oof_fold_model(
        self,
        artifact_id: str,
        fold_number: int,
        *,
        provider: ModelPersistenceProvider,
    ) -> LoadedOOFFoldModel:
        """Reload exactly one V3 fold through a registered trusted provider.

        Filesystem layout, hashes and declarative fold provenance are kept in
        this persistence boundary.  Callers receive only an ephemeral loaded
        predictor plus the immutable evidence needed to bind it.
        """
        artifact = self.load(artifact_id)
        if artifact.manifest.get("artifact_schema_version") != _SCHEMA_VERSION_V3:
            raise ValueError("OOF fold models require an Artifact V3 bundle.")
        if (
            isinstance(fold_number, bool)
            or not isinstance(fold_number, int)
            or not 1 <= fold_number <= artifact.config.folds
        ):
            raise ValueError("OOF fold number is invalid.")
        evidence = artifact.run_output.oof_evidence
        if evidence is None:
            raise ValueError("OOF fold model evidence is incomplete.")
        directory = self.experiments / artifact_id
        fold_dir = directory / "fold_models" / f"fold-{fold_number:03d}"
        native_dir = fold_dir / "native"
        metadata = self._read_json(fold_dir / "metadata.json")
        self._validate_oof_fold_load_metadata(
            artifact=artifact,
            fold_number=fold_number,
            metadata=metadata,
            provider=provider,
        )
        native_names = tuple(metadata["native_files"])
        if (
            tuple(provider.native_files()) != native_names
            or any(
                not (native_dir / name).is_file()
                or self._raw_hash(native_dir / name) != metadata["native_hashes"][name]
                for name in native_names
            )
        ):
            raise ValueError("OOF fold native model evidence is invalid.")
        try:
            predictor = provider.load(native_dir, tuple(evidence.feature_columns))
        except Exception as error:
            raise ValueError("OOF fold predictor could not be loaded.") from error
        if (
            predictor.model_id != artifact.config.model_id
            or tuple(predictor.feature_columns) != tuple(evidence.feature_columns)
        ):
            raise ValueError("OOF fold predictor does not match trusted evidence.")
        return LoadedOOFFoldModel(
            artifact_id=artifact.artifact_id,
            fold_number=fold_number,
            model_binding_id=self._oof_fold_binding_id(
                artifact_id=artifact.artifact_id, metadata=metadata
            ),
            metadata=metadata,
            predictor=predictor,
        )

    @staticmethod
    def _oof_fold_binding_id(*, artifact_id: str, metadata: dict[str, Any]) -> str:
        """Opaque deterministic identity for immutable persisted fold evidence."""
        return stable_hash(
            {
                "binding_schema": "oof_fold_model_binding_v1",
                "artifact_id": artifact_id,
                "fold_number": metadata["fold_number"],
                "provider": metadata["provider"],
                "model_id": metadata["model_id"],
                "model_version": metadata["model_version"],
                "adapter_version": metadata["adapter_version"],
                "feature_columns": metadata["feature_columns"],
                "validation_row_positions": metadata["validation_row_positions"],
                "native_hashes": metadata["native_hashes"],
                "population_id": metadata["population_id"],
                "population_fingerprint": metadata["population_fingerprint"],
            }
        )

    def _validate_oof_fold_load_metadata(
        self,
        *,
        artifact: LoadedExperimentArtifact,
        fold_number: int,
        metadata: dict[str, Any],
        provider: ModelPersistenceProvider,
    ) -> None:
        evidence = artifact.run_output.oof_evidence
        assert evidence is not None
        record = artifact.configuration_record
        expected_positions = np.asarray(artifact.run_output.row_positions)[
            np.asarray(artifact.run_output.fold_assignments) == fold_number
        ].tolist()
        required = {
            "fold_number", "fold_seed", "provider", "model_id", "model_version",
            "adapter_version", "feature_columns", "validation_row_positions",
            "native_files", "native_hashes", "population_id", "population_fingerprint",
        }
        try:
            descriptor_data = metadata["provider"]
            if not isinstance(descriptor_data, dict) or set(descriptor_data) != {
                "provider_id", "provider_version", "provider_kind", "metadata"
            }:
                raise ValueError("invalid descriptor shape")
            persisted_descriptor = ProviderDescriptor(**descriptor_data)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("OOF fold persistence provider descriptor is invalid.") from error
        if (
            set(metadata) != required
            or record is None
            or metadata["fold_number"] != fold_number
            or metadata["fold_seed"] != artifact.config.seed + fold_number
            or persisted_descriptor != provider.descriptor
            or (provider.model_id, provider.model_version, provider.adapter_version)
            != (artifact.config.model_id, artifact.config.model_version, record.adapter_version)
            or (metadata["model_id"], metadata["model_version"], metadata["adapter_version"])
            != (provider.model_id, provider.model_version, provider.adapter_version)
            or metadata["feature_columns"] != list(evidence.feature_columns)
            or metadata["validation_row_positions"] != expected_positions
            or metadata["population_id"] != artifact.population.population_id
            or metadata["population_fingerprint"] != artifact.population.population_fingerprint
            or not isinstance(metadata["native_files"], list)
            or tuple(metadata["native_files"]) != tuple(provider.native_files())
            or not isinstance(metadata["native_hashes"], dict)
            or set(metadata["native_hashes"]) != set(metadata["native_files"])
            or any(
                not isinstance(name, str)
                or not isinstance(digest, str)
                or len(digest) != 64
                for name, digest in metadata["native_hashes"].items()
            )
        ):
            raise ValueError("OOF fold model provenance is invalid.")

    def _load_directory(
        self, directory: Path, artifact_id: str, *, allow_temporary: bool
    ) -> LoadedExperimentArtifact:
        if not directory.is_dir():
            raise ValueError("Experiment artifact directory is missing or incomplete.")
        if not allow_temporary and directory.name != artifact_id:
            raise ValueError("Artifact directory name does not match artifact_id.")
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("Experiment artifact manifest is missing.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Experiment artifact manifest is invalid.") from error
        schema_version = self._validate_manifest(manifest, artifact_id)
        for relative in manifest["files"]:
            path = directory / relative
            info = manifest["files"].get(relative)
            if not path.is_file() or not isinstance(info, dict):
                raise ValueError("Experiment artifact mandatory file is missing.")
            if info.get("size_bytes") != path.stat().st_size or info.get(
                "sha256"
            ) != self._raw_hash(path):
                raise ValueError("Experiment artifact file integrity check failed.")
        try:
            config = ExperimentConfig.from_dict(
                self._read_json(directory / "config.json")
            )
            dataset_contract = DatasetContract.from_dict(
                self._read_json(directory / "dataset.json")
            )
            population_data = self._read_json(directory / "population.json")
            result = ExperimentResult.from_dict(
                self._read_json(directory / "result.json")
            )
            configuration_record = (
                ModelConfigurationRecord.from_dict(
                    self._read_json(directory / "configuration.json")
                )
                if schema_version in {_SCHEMA_VERSION_V2, _SCHEMA_VERSION_V3}
                else None
            )
            smoke_evidence = (
                SmokeEvidence.from_dict(self._read_json(directory / "smoke.json"))
                if schema_version in {_SCHEMA_VERSION_V2, _SCHEMA_VERSION_V3}
                else None
            )
            population = EvaluationPopulation(
                tuple(
                    np.load(
                        directory / "evidence/row_positions.npy", allow_pickle=False
                    ).tolist()
                ),
                population_data["population_id"],
                population_data["population_fingerprint"],
                population_data["partition_role"],
            )
            run_output = ExperimentRunOutput(
                result=result,
                oof_positive_proba=np.load(
                    directory / "evidence/oof_positive_proba.npy", allow_pickle=False
                ),
                fold_assignments=np.load(
                    directory / "evidence/fold_assignments.npy", allow_pickle=False
                ),
                row_positions=population.row_positions,
                population_id=population.population_id,
                population_fingerprint=population.population_fingerprint,
            )
            if schema_version == _SCHEMA_VERSION_V3:
                binding = self._read_json(directory / "evidence/feature_binding.json")["features"]
                run_output = ExperimentRunOutput(
                    result=run_output.result,
                    oof_positive_proba=run_output.oof_positive_proba,
                    fold_assignments=run_output.fold_assignments,
                    row_positions=run_output.row_positions,
                    population_id=run_output.population_id,
                    population_fingerprint=run_output.population_fingerprint,
                    oof_evidence=OOFResultEvidence(
                        y_true=np.load(directory / "evidence/oof_y_true.npy", allow_pickle=False),
                        identifier_display=tuple(np.load(directory / "evidence/identifier_display.npy", allow_pickle=False).tolist()),
                        model_input=np.load(directory / "evidence/model_input.npy", allow_pickle=False),
                        feature_ids=tuple(item["feature_id"] for item in binding),
                        feature_columns=tuple(item["column_name"] for item in binding),
                        fold_models=(),
                    ),
                )
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise ValueError("Experiment artifact typed payload is invalid.") from error
        if population_data.get("population_size") != len(population.row_positions):
            raise ValueError("Experiment artifact population size is invalid.")
        arrays = self._canonical_arrays(run_output)
        if schema_version == _SCHEMA_VERSION_V3:
            assert run_output.oof_evidence is not None
            arrays.update(self._canonical_v3_arrays(run_output.oof_evidence))
        self._validate_bundle(config, dataset_contract, population, run_output, arrays)
        if schema_version in {_SCHEMA_VERSION_V2, _SCHEMA_VERSION_V3}:
            self._validate_v2_provenance(
                config,
                dataset_contract,
                population,
                configuration_record,
                smoke_evidence,
            )
        payload = self._payload(
            config,
            dataset_contract,
            population,
            result,
            arrays,
            configuration_record,
            smoke_evidence,
        )
        if schema_version == _SCHEMA_VERSION_V3:
            assert run_output.oof_evidence is not None
            self._validate_v3_evidence(config, population, run_output.oof_evidence, arrays, require_models=False)
            self._validate_v3_canonical_result(result, arrays)
            self._validate_persisted_fold_models(directory, config, population, run_output.oof_evidence, arrays)
            payload["feature_binding"] = self._feature_binding(run_output.oof_evidence)
        hashes = self._content_hashes(payload, arrays)
        if schema_version == _SCHEMA_VERSION_V3:
            hashes["feature_binding"] = stable_hash(payload["feature_binding"])
            hashes["fold_models"] = self._fold_models_hash(directory)
        if (
            hashes != manifest["content_hashes"]
            or self._artifact_id(hashes, schema_version) != artifact_id
        ):
            raise ValueError("Experiment artifact semantic integrity check failed.")
        self._validate_identity(
            manifest["identity"], config, dataset_contract, population, result
        )
        return LoadedExperimentArtifact(
            artifact_id,
            config,
            dataset_contract,
            population,
            run_output,
            manifest,
            configuration_record,
            smoke_evidence,
        )

    @staticmethod
    def _canonical_arrays(run_output: ExperimentRunOutput) -> dict[str, np.ndarray]:
        def integer(values: Any, name: str) -> np.ndarray:
            source = np.asarray(values)
            if (
                source.ndim != 1
                or not np.issubdtype(source.dtype, np.integer)
                or np.issubdtype(source.dtype, np.bool_)
            ):
                raise ValueError(f"{name} must be a one-dimensional integer array.")
            return np.ascontiguousarray(source.astype("<i8", copy=False))

        source_oof = np.asarray(run_output.oof_positive_proba)
        if (
            source_oof.ndim != 1
            or not np.issubdtype(source_oof.dtype, np.number)
            or np.issubdtype(source_oof.dtype, np.bool_)
        ):
            raise ValueError(
                "OOF probabilities must be a one-dimensional numeric array."
            )
        return {
            "oof_positive_proba": np.ascontiguousarray(
                source_oof.astype("<f8", copy=False)
            ),
            "fold_assignments": integer(
                run_output.fold_assignments, "Fold assignments"
            ),
            "row_positions": integer(run_output.row_positions, "Row positions"),
        }

    @staticmethod
    def _canonical_v3_arrays(evidence: OOFResultEvidence) -> dict[str, np.ndarray]:
        y_true = np.asarray(evidence.y_true)
        input_matrix = np.asarray(evidence.model_input)
        identifiers = np.asarray(evidence.identifier_display, dtype=str)
        if y_true.ndim != 1 or not np.issubdtype(y_true.dtype, np.integer) or np.issubdtype(y_true.dtype, np.bool_):
            raise ValueError("OOF y_true must be a one-dimensional integer array.")
        if input_matrix.ndim != 2 or not np.issubdtype(input_matrix.dtype, np.number) or np.issubdtype(input_matrix.dtype, np.bool_):
            raise ValueError("OOF model input must be a two-dimensional numeric matrix.")
        if identifiers.ndim != 1:
            raise ValueError("OOF identifier display must be a one-dimensional string array.")
        return {
            "oof_y_true": np.ascontiguousarray(y_true.astype("<i8", copy=False)),
            "identifier_display": np.ascontiguousarray(identifiers),
            "model_input": np.ascontiguousarray(input_matrix),
        }

    @staticmethod
    def _feature_binding(evidence: OOFResultEvidence) -> dict[str, Any]:
        if (
            not evidence.feature_ids
            or len(evidence.feature_ids) != len(evidence.feature_columns)
            or len(set(evidence.feature_ids)) != len(evidence.feature_ids)
            or len(set(evidence.feature_columns)) != len(evidence.feature_columns)
            or any(not isinstance(value, str) or not value for value in (*evidence.feature_ids, *evidence.feature_columns))
        ):
            raise ValueError("OOF feature binding is invalid.")
        return {"features": [
            {"feature_id": feature_id, "column_name": column_name}
            for feature_id, column_name in zip(evidence.feature_ids, evidence.feature_columns, strict=True)
        ]}

    def _validate_v3_evidence(
        self,
        config: ExperimentConfig,
        population: EvaluationPopulation,
        evidence: OOFResultEvidence,
        arrays: dict[str, np.ndarray],
        *,
        require_models: bool = True,
    ) -> None:
        self._feature_binding(evidence)
        n_rows = len(population.row_positions)
        if (
            evidence.feature_ids != config.feature_ids
            or len(arrays["oof_y_true"]) != n_rows
            or len(arrays["identifier_display"]) != n_rows
            or arrays["model_input"].shape != (n_rows, len(evidence.feature_columns))
            or not np.isfinite(arrays["model_input"]).all()
            or not np.isin(arrays["oof_y_true"], (0, 1)).all()
        ):
            raise ValueError("OOF V3 row-aligned evidence is invalid.")
        if require_models:
            models = evidence.fold_models
            if len(models) != config.folds or {item.fold_number for item in models} != set(range(1, config.folds + 1)):
                raise ValueError("OOF V3 requires exactly one fitted model per fold.")
            if any(item.fold_seed != config.seed + item.fold_number for item in models):
                raise ValueError("OOF fold model seed provenance is invalid.")

    @staticmethod
    def _validate_v3_canonical_result(
        result: ExperimentResult, arrays: dict[str, np.ndarray]
    ) -> None:
        """Require saved OOF labels and scores to reproduce canonical Result V1 metrics."""
        threshold = 0.5
        if result.confusion.get("threshold") != threshold:
            raise ValueError("V3 canonical result threshold must equal 0.5.")

        y_true = arrays["oof_y_true"]
        predicted_positive = arrays["oof_positive_proba"] >= threshold
        actual_positive = y_true == 1
        tp = int(np.count_nonzero(actual_positive & predicted_positive))
        tn = int(np.count_nonzero(~actual_positive & ~predicted_positive))
        fp = int(np.count_nonzero(~actual_positive & predicted_positive))
        fn = int(np.count_nonzero(actual_positive & ~predicted_positive))
        expected_confusion = {"tp": tp, "tn": tn, "fp": fp, "fn": fn}
        if any(result.confusion.get(name) != value for name, value in expected_confusion.items()):
            raise ValueError("V3 OOF facts do not reproduce canonical ExperimentResult confusion.")

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        expected_metrics = {
            "precision_at_0_5": precision,
            "recall_at_0_5": recall,
            "f1_at_0_5": f1,
        }
        for name, expected in expected_metrics.items():
            actual = result.metrics.get(name)
            if (
                isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or not np.isfinite(actual)
                or not np.isclose(actual, expected, rtol=1e-12, atol=1e-12)
            ):
                raise ValueError(
                    f"V3 OOF facts do not reproduce canonical ExperimentResult metric {name}."
                )

    def _write_fold_models(
        self,
        directory: Path,
        config: ExperimentConfig,
        population: EvaluationPopulation,
        evidence: OOFResultEvidence,
        arrays: dict[str, np.ndarray],
        provider: ModelPersistenceProvider,
    ) -> None:
        for item in evidence.fold_models:
            provider.validate_fitted(item.adapter, parameters=dict(config.model_parameters), seed=item.fold_seed)
            fold_dir = directory / "fold_models" / f"fold-{item.fold_number:03d}"
            native_dir = fold_dir / "native"
            native_names = provider.save(item.adapter, native_dir)
            if tuple(native_names) != tuple(provider.native_files()):
                raise ValueError("Fold persistence provider wrote an undeclared native file set.")
            validation_mask = arrays["fold_assignments"] == item.fold_number
            validation_positions = arrays["row_positions"][validation_mask]
            if not len(validation_positions):
                raise ValueError("OOF fold has no validation rows.")
            metadata = {
                "fold_number": item.fold_number,
                "fold_seed": item.fold_seed,
                "provider": provider.descriptor.to_dict(),
                "model_id": config.model_id,
                "model_version": config.model_version,
                "adapter_version": provider.adapter_version,
                "feature_columns": list(evidence.feature_columns),
                "validation_row_positions": validation_positions.tolist(),
                "native_files": list(native_names),
                "native_hashes": {name: self._raw_hash(native_dir / name) for name in native_names},
                "population_id": population.population_id,
                "population_fingerprint": population.population_fingerprint,
            }
            self._write_json(fold_dir / "metadata.json", metadata)
            try:
                predictor = provider.load(native_dir, evidence.feature_columns)
                replay = np.asarray(predictor.predict_positive_proba(pd.DataFrame(arrays["model_input"][validation_mask], columns=evidence.feature_columns)), dtype=float)
            except Exception as error:
                raise ValueError("Persisted fold model could not be reloaded.") from error
            expected = arrays["oof_positive_proba"][validation_mask]
            if replay.shape != expected.shape or not np.isfinite(replay).all() or not np.allclose(replay, expected, rtol=1e-12, atol=1e-12):
                raise ValueError("Persisted fold model does not reproduce OOF probabilities.")

    def _fold_models_hash(self, directory: Path) -> str:
        base = directory / "fold_models"
        if not base.is_dir():
            raise ValueError("V3 fold model evidence is missing.")
        files = sorted(path for path in base.rglob("*") if path.is_file())
        if not files:
            raise ValueError("V3 fold model evidence is empty.")
        return stable_hash({path.relative_to(directory).as_posix(): self._raw_hash(path) for path in files})

    def _validate_persisted_fold_models(
        self,
        directory: Path,
        config: ExperimentConfig,
        population: EvaluationPopulation,
        evidence: OOFResultEvidence,
        arrays: dict[str, np.ndarray],
    ) -> None:
        base = directory / "fold_models"
        expected_names = {f"fold-{fold:03d}" for fold in range(1, config.folds + 1)}
        if not base.is_dir() or {path.name for path in base.iterdir() if path.is_dir()} != expected_names:
            raise ValueError("V3 fold model directories are invalid.")
        for fold_number in range(1, config.folds + 1):
            fold_dir = base / f"fold-{fold_number:03d}"
            metadata = self._read_json(fold_dir / "metadata.json")
            native_dir = fold_dir / "native"
            expected_positions = arrays["row_positions"][arrays["fold_assignments"] == fold_number].tolist()
            required = {"fold_number", "fold_seed", "provider", "model_id", "model_version", "adapter_version", "feature_columns", "validation_row_positions", "native_files", "native_hashes", "population_id", "population_fingerprint"}
            if (
                set(metadata) != required
                or metadata["fold_number"] != fold_number
                or metadata["fold_seed"] != config.seed + fold_number
                or metadata["model_id"] != config.model_id
                or metadata["model_version"] != config.model_version
                or metadata["feature_columns"] != list(evidence.feature_columns)
                or metadata["validation_row_positions"] != expected_positions
                or metadata["population_id"] != population.population_id
                or metadata["population_fingerprint"] != population.population_fingerprint
                or not isinstance(metadata["provider"], dict)
                or not isinstance(metadata["native_files"], list)
                or set(metadata["native_hashes"]) != set(metadata["native_files"])
                or any(self._raw_hash(native_dir / name) != digest for name, digest in metadata["native_hashes"].items())
            ):
                raise ValueError("V3 fold model provenance is invalid.")

    @staticmethod
    def _validate_bundle(
        config: ExperimentConfig,
        dataset: DatasetContract,
        population: EvaluationPopulation,
        output: ExperimentRunOutput,
        arrays: dict[str, np.ndarray],
    ) -> None:
        result = output.result
        pairs = (
            (result.experiment_config_id, config.experiment_id),
            (result.config_hash, config.config_hash),
            (dataset.dataset_id, config.dataset_id),
            (result.dataset_fingerprint, config.dataset_fingerprint),
            (dataset.dataset_fingerprint, config.dataset_fingerprint),
            (result.feature_set_hash, config.feature_set_hash),
            (result.model_id, config.model_id),
            (result.model_version, config.model_version),
            (result.evaluation_level, config.evaluation_level),
            (dataset.target_column, config.target),
            (population.population_id, output.population_id),
            (population.population_fingerprint, output.population_fingerprint),
            (population.row_positions, tuple(output.row_positions)),
        )
        if any(left != right for left, right in pairs):
            raise ValueError(
                "Completed experiment evidence is not mutually consistent."
            )
        if dataset.final_test_locked and population.partition_role != "working":
            raise ValueError("Locked final test requires a working population.")
        oof, folds, positions = (
            arrays["oof_positive_proba"],
            arrays["fold_assignments"],
            arrays["row_positions"],
        )
        if (
            len(oof) != len(folds)
            or len(oof) != len(positions)
            or len(oof) != len(population.row_positions)
        ):
            raise ValueError("Experiment evidence arrays have inconsistent lengths.")
        if not np.isfinite(oof).all() or (oof < 0).any() or (oof > 1).any():
            raise ValueError("OOF probabilities must be finite values in [0, 1].")
        if (folds < 1).any() or (folds > config.folds).any():
            raise ValueError(
                "Fold assignments must be labels from 1 through config.folds."
            )
        if (
            (positions < 0).any()
            or len(set(positions.tolist())) != len(positions)
            or (positions >= dataset.row_count).any()
        ):
            raise ValueError("Row positions are invalid for DatasetContract.")
        if len(result.fold_metrics) != config.folds:
            raise ValueError("Fold metrics count must equal config.folds.")

    @staticmethod
    def _payload(
        config: ExperimentConfig,
        dataset: DatasetContract,
        population: EvaluationPopulation,
        result: ExperimentResult,
        arrays: dict[str, np.ndarray],
        configuration_record: ModelConfigurationRecord | None = None,
        smoke_evidence: SmokeEvidence | None = None,
    ) -> dict[str, Any]:
        payload = {
            "config": config.to_dict(),
            "dataset": dataset.to_dict(),
            "result": result.to_dict(),
            "population": {
                "population_id": population.population_id,
                "population_fingerprint": population.population_fingerprint,
                "partition_role": population.partition_role,
                "population_size": len(arrays["row_positions"]),
            },
        }
        if configuration_record is not None:
            payload["configuration"] = configuration_record.to_dict()
            payload["smoke"] = smoke_evidence.to_dict()
        return payload

    @staticmethod
    def _content_hashes(
        payload: dict[str, Any], arrays: dict[str, np.ndarray]
    ) -> dict[str, str]:
        values = {
            "config": stable_hash(payload["config"]),
            "dataset": stable_hash(payload["dataset"]),
            "population": stable_hash(payload["population"]),
            "result": stable_hash(payload["result"]),
            **{
                name: ExperimentArtifactStore._array_hash(array)
                for name, array in arrays.items()
            },
        }
        if "configuration" in payload:
            values["configuration"] = stable_hash(payload["configuration"])
            values["smoke"] = stable_hash(payload["smoke"])
        return values

    @staticmethod
    def _array_hash(array: np.ndarray) -> str:
        return stable_hash(
            {
                "dtype": array.dtype.str,
                "shape": list(array.shape),
                "sha256": sha256(array.tobytes(order="C")).hexdigest(),
            }
        )

    @staticmethod
    def _artifact_id(content_hashes: dict[str, str], schema_version: str) -> str:
        return stable_hash(
            {
                "artifact_schema_version": schema_version,
                "content_hashes": content_hashes,
            }
        )

    def _write_payload(
        self, directory: Path, payload: dict[str, Any], arrays: dict[str, np.ndarray]
    ) -> None:
        self._write_json(directory / "config.json", payload["config"])
        self._write_json(directory / "dataset.json", payload["dataset"])
        self._write_json(directory / "population.json", payload["population"])
        self._write_json(directory / "result.json", payload["result"])
        if "configuration" in payload:
            self._write_json(directory / "configuration.json", payload["configuration"])
            self._write_json(directory / "smoke.json", payload["smoke"])
        for name, array in arrays.items():
            np.save(directory / "evidence" / f"{name}.npy", array, allow_pickle=False)

    def _manifest(
        self,
        artifact_id: str,
        config: ExperimentConfig,
        dataset: DatasetContract,
        population: EvaluationPopulation,
        result: ExperimentResult,
        content_hashes: dict[str, str],
        directory: Path,
        schema_version: str,
    ) -> dict[str, Any]:
        return {
            "artifact_type": "experiment",
            "artifact_schema_version": schema_version,
            "artifact_id": artifact_id,
            "identity": {
                "experiment_id": config.experiment_id,
                "result_id": result.result_id,
                "config_hash": config.config_hash,
                "dataset_id": dataset.dataset_id,
                "dataset_fingerprint": dataset.dataset_fingerprint,
                "population_id": population.population_id,
                "population_fingerprint": population.population_fingerprint,
                "model_id": config.model_id,
                "model_version": config.model_version,
                "evaluation_level": config.evaluation_level,
            },
            "content_hashes": content_hashes,
            "files": {
                relative: {
                    "sha256": self._raw_hash(directory / relative),
                    "size_bytes": (directory / relative).stat().st_size,
                }
                for relative in (
                    sorted(
                        path.relative_to(directory).as_posix()
                        for path in directory.rglob("*")
                        if path.is_file() and path.name != "manifest.json"
                    )
                    if schema_version == _SCHEMA_VERSION_V3
                    else _PAYLOAD_FILES_V2
                    if schema_version == _SCHEMA_VERSION_V2
                    else _PAYLOAD_FILES_V1
                )
            },
        }

    @staticmethod
    def _validate_manifest(manifest: Any, artifact_id: str) -> str:
        required = {
            "artifact_type",
            "artifact_schema_version",
            "artifact_id",
            "identity",
            "content_hashes",
            "files",
        }
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise ValueError("Experiment artifact manifest structure is invalid.")
        schema_version = manifest.get("artifact_schema_version")
        if manifest["artifact_type"] != "experiment" or schema_version not in {
            _SCHEMA_VERSION_V1,
            _SCHEMA_VERSION_V2,
            _SCHEMA_VERSION_V3,
        }:
            raise ValueError("Unsupported experiment artifact schema.")
        if manifest["artifact_id"] != artifact_id or not isinstance(
            manifest["identity"], dict
        ):
            raise ValueError("Experiment artifact manifest identity is invalid.")
        expected_hashes = {
            "config",
            "dataset",
            "population",
            "result",
            "oof_positive_proba",
            "fold_assignments",
            "row_positions",
        }
        if schema_version in {_SCHEMA_VERSION_V2, _SCHEMA_VERSION_V3}:
            expected_hashes |= {"configuration", "smoke"}
        if schema_version == _SCHEMA_VERSION_V3:
            expected_hashes |= {"oof_y_true", "identifier_display", "model_input", "feature_binding", "fold_models"}
        if (
            not isinstance(manifest["content_hashes"], dict)
            or set(manifest["content_hashes"]) != expected_hashes
            or not isinstance(manifest["files"], dict)
        ):
            raise ValueError("Experiment artifact manifest hashes are invalid.")
        required_files = (
            _PAYLOAD_FILES_V3 if schema_version == _SCHEMA_VERSION_V3
            else _PAYLOAD_FILES_V2 if schema_version == _SCHEMA_VERSION_V2
            else _PAYLOAD_FILES_V1
        )
        if not set(required_files).issubset(manifest["files"]):
            raise ValueError("Experiment artifact mandatory file list is invalid.")
        if schema_version == _SCHEMA_VERSION_V3:
            fold_files = [name for name in manifest["files"] if name.startswith("fold_models/")]
            if not fold_files or any(not isinstance(name, str) for name in manifest["files"]):
                raise ValueError("Experiment artifact fold model file list is invalid.")
        return schema_version

    @staticmethod
    def _validate_v2_provenance(
        config: ExperimentConfig,
        dataset: DatasetContract,
        population: EvaluationPopulation,
        record: ModelConfigurationRecord | None,
        smoke: SmokeEvidence | None,
    ) -> None:
        if not isinstance(record, ModelConfigurationRecord) or not isinstance(
            smoke, SmokeEvidence
        ):
            raise ValueError("MP-C artifact provenance is invalid.")
        if (
            record.model_id != config.model_id
            or record.model_version != config.model_version
        ):
            raise ValueError("MP-C configuration provenance does not match experiment.")
        if record.resolved_parameters != config.model_parameters:
            raise ValueError("MP-C resolved parameters do not match experiment.")
        if (
            smoke.status is not SmokeStatus.PASS
            or smoke.configuration_record_id != record.configuration_record_id
        ):
            raise ValueError("MP-C smoke provenance does not authorize configuration.")
        if (
            smoke.plugin_contract_hash != record.plugin_contract_hash
            or smoke.resolved_configuration_hash != record.resolved_configuration_hash
        ):
            raise ValueError("MP-C smoke provenance identity is inconsistent.")
        if (
            smoke.dataset_id != dataset.dataset_id
            or smoke.dataset_fingerprint != dataset.dataset_fingerprint
            or smoke.feature_registry_id != dataset.feature_registry_id
            or smoke.feature_registry_hash != dataset.feature_registry_hash
            or smoke.population_id != population.population_id
            or smoke.population_fingerprint != population.population_fingerprint
            or smoke.population_row_positions_hash
            != stable_hash({"row_positions": list(population.row_positions)})
            or smoke.selected_feature_ids != config.feature_ids
            or smoke.seed != config.seed
        ):
            raise ValueError(
                "MP-C smoke provenance does not match experiment identity."
            )

    @staticmethod
    def _validate_identity(
        identity: dict[str, Any],
        config: ExperimentConfig,
        dataset: DatasetContract,
        population: EvaluationPopulation,
        result: ExperimentResult,
    ) -> None:
        expected = {
            "experiment_id": config.experiment_id,
            "result_id": result.result_id,
            "config_hash": config.config_hash,
            "dataset_id": dataset.dataset_id,
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "population_id": population.population_id,
            "population_fingerprint": population.population_fingerprint,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "evaluation_level": config.evaluation_level,
        }
        if identity != expected:
            raise ValueError(
                "Experiment artifact manifest identity does not match payload."
            )

    @staticmethod
    def _validate_metadata_identity(
        identity: Any,
        config: ExperimentConfig,
        dataset: DatasetContract,
        result: ExperimentResult,
        population_id: str,
        population_fingerprint: str,
    ) -> None:
        expected = {
            "experiment_id": config.experiment_id,
            "result_id": result.result_id,
            "config_hash": config.config_hash,
            "dataset_id": dataset.dataset_id,
            "dataset_fingerprint": dataset.dataset_fingerprint,
            "population_id": population_id,
            "population_fingerprint": population_fingerprint,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "evaluation_level": config.evaluation_level,
        }
        if identity != expected:
            raise ValueError("Experiment artifact manifest identity does not match metadata.")

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(canonical_json(value), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Experiment artifact JSON payload is invalid.") from error
        if not isinstance(value, dict):
            raise ValueError("Experiment artifact JSON payload must be an object.")
        return value

    @staticmethod
    def _raw_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _is_artifact_id(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )
