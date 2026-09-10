"""Fail-closed, immutable filesystem persistence for completed experiment runs."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

import numpy as np

from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput
from komus_risk.hashing import canonical_json, stable_hash

from .contracts import LoadedExperimentArtifact


_SCHEMA_VERSION = "1"
_PAYLOAD_FILES = (
    "config.json", "dataset.json", "population.json", "result.json",
    "evidence/oof_positive_proba.npy", "evidence/fold_assignments.npy", "evidence/row_positions.npy",
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
    ) -> LoadedExperimentArtifact:
        arrays = self._canonical_arrays(run_output)
        self._validate_bundle(config, dataset_contract, population, run_output, arrays)
        payload = self._payload(config, dataset_contract, population, run_output.result, arrays)
        content_hashes = self._content_hashes(payload, arrays)
        artifact_id = self._artifact_id(content_hashes)
        target = self.experiments / artifact_id
        if target.exists():
            return self.load(artifact_id)

        self.experiments.mkdir(parents=True, exist_ok=True)
        temporary = self.experiments / f".tmp-{artifact_id}-{uuid4().hex}"
        try:
            (temporary / "evidence").mkdir(parents=True)
            self._write_payload(temporary, payload, arrays)
            manifest = self._manifest(artifact_id, config, dataset_contract, population, run_output.result, content_hashes, temporary)
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
        return self._load_directory(self.experiments / artifact_id, artifact_id, allow_temporary=False)

    def _load_directory(self, directory: Path, artifact_id: str, *, allow_temporary: bool) -> LoadedExperimentArtifact:
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
        self._validate_manifest(manifest, artifact_id)
        for relative in _PAYLOAD_FILES:
            path = directory / relative
            info = manifest["files"].get(relative)
            if not path.is_file() or not isinstance(info, dict):
                raise ValueError("Experiment artifact mandatory file is missing.")
            if info.get("size_bytes") != path.stat().st_size or info.get("sha256") != self._raw_hash(path):
                raise ValueError("Experiment artifact file integrity check failed.")
        try:
            config = ExperimentConfig.from_dict(self._read_json(directory / "config.json"))
            dataset_contract = DatasetContract.from_dict(self._read_json(directory / "dataset.json"))
            population_data = self._read_json(directory / "population.json")
            result = ExperimentResult.from_dict(self._read_json(directory / "result.json"))
            population = EvaluationPopulation(
                tuple(np.load(directory / "evidence/row_positions.npy", allow_pickle=False).tolist()),
                population_data["population_id"], population_data["population_fingerprint"], population_data["partition_role"],
            )
            run_output = ExperimentRunOutput(
                result=result,
                oof_positive_proba=np.load(directory / "evidence/oof_positive_proba.npy", allow_pickle=False),
                fold_assignments=np.load(directory / "evidence/fold_assignments.npy", allow_pickle=False),
                row_positions=population.row_positions,
                population_id=population.population_id,
                population_fingerprint=population.population_fingerprint,
            )
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise ValueError("Experiment artifact typed payload is invalid.") from error
        if population_data.get("population_size") != len(population.row_positions):
            raise ValueError("Experiment artifact population size is invalid.")
        arrays = self._canonical_arrays(run_output)
        self._validate_bundle(config, dataset_contract, population, run_output, arrays)
        payload = self._payload(config, dataset_contract, population, result, arrays)
        hashes = self._content_hashes(payload, arrays)
        if hashes != manifest["content_hashes"] or self._artifact_id(hashes) != artifact_id:
            raise ValueError("Experiment artifact semantic integrity check failed.")
        self._validate_identity(manifest["identity"], config, dataset_contract, population, result)
        return LoadedExperimentArtifact(artifact_id, config, dataset_contract, population, run_output, manifest)

    @staticmethod
    def _canonical_arrays(run_output: ExperimentRunOutput) -> dict[str, np.ndarray]:
        def integer(values: Any, name: str) -> np.ndarray:
            source = np.asarray(values)
            if source.ndim != 1 or not np.issubdtype(source.dtype, np.integer) or np.issubdtype(source.dtype, np.bool_):
                raise ValueError(f"{name} must be a one-dimensional integer array.")
            return np.ascontiguousarray(source.astype("<i8", copy=False))

        source_oof = np.asarray(run_output.oof_positive_proba)
        if source_oof.ndim != 1 or not np.issubdtype(source_oof.dtype, np.number) or np.issubdtype(source_oof.dtype, np.bool_):
            raise ValueError("OOF probabilities must be a one-dimensional numeric array.")
        return {
            "oof_positive_proba": np.ascontiguousarray(source_oof.astype("<f8", copy=False)),
            "fold_assignments": integer(run_output.fold_assignments, "Fold assignments"),
            "row_positions": integer(run_output.row_positions, "Row positions"),
        }

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
            (result.experiment_config_id, config.experiment_id), (result.config_hash, config.config_hash),
            (dataset.dataset_id, config.dataset_id),
            (result.dataset_fingerprint, config.dataset_fingerprint), (dataset.dataset_fingerprint, config.dataset_fingerprint),
            (result.feature_set_hash, config.feature_set_hash), (result.model_id, config.model_id),
            (result.model_version, config.model_version), (result.evaluation_level, config.evaluation_level),
            (dataset.target_column, config.target), (population.population_id, output.population_id),
            (population.population_fingerprint, output.population_fingerprint),
            (population.row_positions, tuple(output.row_positions)),
        )
        if any(left != right for left, right in pairs):
            raise ValueError("Completed experiment evidence is not mutually consistent.")
        if dataset.final_test_locked and population.partition_role != "working":
            raise ValueError("Locked final test requires a working population.")
        oof, folds, positions = arrays["oof_positive_proba"], arrays["fold_assignments"], arrays["row_positions"]
        if len(oof) != len(folds) or len(oof) != len(positions) or len(oof) != len(population.row_positions):
            raise ValueError("Experiment evidence arrays have inconsistent lengths.")
        if not np.isfinite(oof).all() or (oof < 0).any() or (oof > 1).any():
            raise ValueError("OOF probabilities must be finite values in [0, 1].")
        if (folds < 1).any() or (folds > config.folds).any():
            raise ValueError("Fold assignments must be labels from 1 through config.folds.")
        if (positions < 0).any() or len(set(positions.tolist())) != len(positions) or (positions >= dataset.row_count).any():
            raise ValueError("Row positions are invalid for DatasetContract.")
        if len(result.fold_metrics) != config.folds:
            raise ValueError("Fold metrics count must equal config.folds.")

    @staticmethod
    def _payload(
        config: ExperimentConfig, dataset: DatasetContract, population: EvaluationPopulation,
        result: ExperimentResult, arrays: dict[str, np.ndarray],
    ) -> dict[str, Any]:
        return {
            "config": config.to_dict(), "dataset": dataset.to_dict(), "result": result.to_dict(),
            "population": {
                "population_id": population.population_id,
                "population_fingerprint": population.population_fingerprint,
                "partition_role": population.partition_role,
                "population_size": len(arrays["row_positions"]),
            },
        }

    @staticmethod
    def _content_hashes(payload: dict[str, Any], arrays: dict[str, np.ndarray]) -> dict[str, str]:
        return {
            "config": stable_hash(payload["config"]), "dataset": stable_hash(payload["dataset"]),
            "population": stable_hash(payload["population"]), "result": stable_hash(payload["result"]),
            **{name: ExperimentArtifactStore._array_hash(array) for name, array in arrays.items()},
        }

    @staticmethod
    def _array_hash(array: np.ndarray) -> str:
        return stable_hash({
            "dtype": array.dtype.str, "shape": list(array.shape),
            "sha256": sha256(array.tobytes(order="C")).hexdigest(),
        })

    @staticmethod
    def _artifact_id(content_hashes: dict[str, str]) -> str:
        return stable_hash({"artifact_schema_version": _SCHEMA_VERSION, "content_hashes": content_hashes})

    def _write_payload(self, directory: Path, payload: dict[str, Any], arrays: dict[str, np.ndarray]) -> None:
        self._write_json(directory / "config.json", payload["config"])
        self._write_json(directory / "dataset.json", payload["dataset"])
        self._write_json(directory / "population.json", payload["population"])
        self._write_json(directory / "result.json", payload["result"])
        for name, array in arrays.items():
            np.save(directory / "evidence" / f"{name}.npy", array, allow_pickle=False)

    def _manifest(
        self, artifact_id: str, config: ExperimentConfig, dataset: DatasetContract, population: EvaluationPopulation,
        result: ExperimentResult, content_hashes: dict[str, str], directory: Path,
    ) -> dict[str, Any]:
        return {
            "artifact_type": "experiment", "artifact_schema_version": _SCHEMA_VERSION, "artifact_id": artifact_id,
            "identity": {
                "experiment_id": config.experiment_id, "result_id": result.result_id, "config_hash": config.config_hash,
                "dataset_id": dataset.dataset_id, "dataset_fingerprint": dataset.dataset_fingerprint,
                "population_id": population.population_id, "population_fingerprint": population.population_fingerprint,
                "model_id": config.model_id, "model_version": config.model_version,
                "evaluation_level": config.evaluation_level,
            },
            "content_hashes": content_hashes,
            "files": {relative: {"sha256": self._raw_hash(directory / relative), "size_bytes": (directory / relative).stat().st_size} for relative in _PAYLOAD_FILES},
        }

    @staticmethod
    def _validate_manifest(manifest: Any, artifact_id: str) -> None:
        required = {"artifact_type", "artifact_schema_version", "artifact_id", "identity", "content_hashes", "files"}
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise ValueError("Experiment artifact manifest structure is invalid.")
        if manifest["artifact_type"] != "experiment" or manifest["artifact_schema_version"] != _SCHEMA_VERSION:
            raise ValueError("Unsupported experiment artifact schema.")
        if manifest["artifact_id"] != artifact_id or not isinstance(manifest["identity"], dict):
            raise ValueError("Experiment artifact manifest identity is invalid.")
        expected_hashes = {"config", "dataset", "population", "result", "oof_positive_proba", "fold_assignments", "row_positions"}
        if (
            not isinstance(manifest["content_hashes"], dict)
            or set(manifest["content_hashes"]) != expected_hashes
            or not isinstance(manifest["files"], dict)
        ):
            raise ValueError("Experiment artifact manifest hashes are invalid.")

    @staticmethod
    def _validate_identity(identity: dict[str, Any], config: ExperimentConfig, dataset: DatasetContract, population: EvaluationPopulation, result: ExperimentResult) -> None:
        expected = {
            "experiment_id": config.experiment_id, "result_id": result.result_id, "config_hash": config.config_hash,
            "dataset_id": dataset.dataset_id, "dataset_fingerprint": dataset.dataset_fingerprint,
            "population_id": population.population_id, "population_fingerprint": population.population_fingerprint,
            "model_id": config.model_id, "model_version": config.model_version,
            "evaluation_level": config.evaluation_level,
        }
        if identity != expected:
            raise ValueError("Experiment artifact manifest identity does not match payload.")

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
        return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
