"""Immutable, content-addressed saved-model inference evidence."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import numpy as np

from komus_risk.hashing import stable_hash

_SCHEMA_VERSION = 1
_CONTRACT_VERSION = "saved-model-inference-v1"


class InferenceResultPersistenceError(RuntimeError):
    """Typed boundary for write, publish, and post-publish verification failures."""


class InferenceResultNotFoundError(ValueError):
    """Requested immutable inference result does not exist."""


class InferenceResultIntegrityError(ValueError):
    """Published immutable inference result failed trusted verification."""


@dataclass(frozen=True, slots=True)
class SavedInferenceRow:
    row_id: str
    source_row_position: int
    identifier_display: str
    probability: float


@dataclass(frozen=True, slots=True)
class SavedModelInferenceResult:
    schema_version: int
    inference_result_id: str
    inference_recipe_key: str
    inference_contract_version: str
    model_version_id: str
    experiment_artifact_id: str
    source_display_name: str
    source_format: str
    source_file_sha256: str
    source_fingerprint: str
    physical_headers_hash: str
    identifier_column: str
    required_feature_columns: tuple[str, ...]
    feature_binding_hash: str
    ignored_columns: tuple[str, ...]
    row_count: int
    column_count: int
    created_at: str
    rows: tuple[SavedInferenceRow, ...]
    model_input_hash: str
    scores_hash: str


@dataclass(frozen=True, slots=True)
class SavedInferenceObjectEvidence:
    """One validated immutable row, read only from saved inference evidence."""

    inference_result_id: str
    model_version_id: str
    experiment_artifact_id: str
    source_file_sha256: str
    row_id: str
    source_row_position: int
    identifier_column: str
    identifier_display: str
    probability: float
    required_feature_columns: tuple[str, ...]
    feature_values: tuple[float, ...]
    feature_binding_hash: str


class SavedModelInferenceResultStore:
    """Directory-per-result evidence store; only validated published directories read."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def recipe_key(*, model_version_id: str, prepared: Any) -> str:
        return stable_hash({
            "model_version_id": model_version_id,
            "source_file_sha256": prepared.source_sha256,
            "source_fingerprint": prepared.source_fingerprint,
            "physical_headers_hash": prepared.physical_headers_hash,
            "identifier_column": prepared.identifier_column,
            "required_feature_columns": prepared.required_feature_columns,
            "feature_binding_hash": prepared.feature_binding_hash,
            "inference_contract_version": _CONTRACT_VERSION,
        })

    def find_by_recipe_key(self, inference_recipe_key: str) -> SavedModelInferenceResult | None:
        for directory in sorted(self.root.iterdir()) if self.root.is_dir() else ():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                result = self.read(directory.name)
            except ValueError:
                continue
            if result.inference_recipe_key == inference_recipe_key:
                return result
        return None

    def create(
        self, *, model_version_id: str, experiment_artifact_id: str, source_display_name: str,
        source_format: str, prepared: Any, prediction_batch: Any,
    ) -> SavedModelInferenceResult:
        matrix = np.asarray(prepared.validated_feature_values, dtype=np.float64)
        scores = np.asarray([row.probability for row in prediction_batch.rows], dtype=np.float64)
        positions = np.asarray(prepared.source_row_positions, dtype=np.int64)
        if matrix.shape != (prepared.row_count, len(prepared.required_feature_columns)) or scores.shape != (prepared.row_count,):
            raise ValueError("INFERENCE_RESULT_PERSISTENCE_FAILED")
        recipe = self.recipe_key(model_version_id=model_version_id, prepared=prepared)
        model_input_hash = self._array_hash(matrix)
        scores_hash = self._array_hash(scores)
        rows = tuple(
            SavedInferenceRow(
                row_id=row.row_id, source_row_position=row.source_row_position,
                identifier_display=str(row.identifier_value), probability=float(row.probability),
            ) for row in prediction_batch.rows
        )
        object_identity_hash = stable_hash([
            {"row_id": row.row_id, "source_row_position": row.source_row_position,
             "identifier_display": row.identifier_display} for row in rows
        ])
        result_id = self._result_identity({
            "inference_recipe_key": recipe, "experiment_artifact_id": experiment_artifact_id,
            "object_identity_hash": object_identity_hash,
            "model_input_hash": model_input_hash, "scores_hash": scores_hash,
        })
        existing = self._read_if_present(result_id)
        if existing is not None:
            return existing
        result = SavedModelInferenceResult(
            schema_version=_SCHEMA_VERSION, inference_result_id=result_id,
            inference_recipe_key=recipe, inference_contract_version=_CONTRACT_VERSION,
            model_version_id=model_version_id, experiment_artifact_id=experiment_artifact_id,
            source_display_name=source_display_name, source_format=source_format,
            source_file_sha256=prepared.source_sha256, source_fingerprint=prepared.source_fingerprint,
            physical_headers_hash=prepared.physical_headers_hash, identifier_column=prepared.identifier_column,
            required_feature_columns=tuple(prepared.required_feature_columns),
            feature_binding_hash=prepared.feature_binding_hash, ignored_columns=tuple(prepared.ignored_columns),
            row_count=prepared.row_count, column_count=prepared.column_count,
            created_at=datetime.now(UTC).isoformat(), rows=rows,
            model_input_hash=model_input_hash, scores_hash=scores_hash,
        )
        try:
            temporary = Path(mkdtemp(prefix=".inference-result-", dir=self.root))
        except OSError as error:
            raise InferenceResultPersistenceError() from error
        try:
            evidence = temporary / "evidence"
            evidence.mkdir()
            self._write_json(temporary / "result.json", self._result_payload(result))
            np.save(evidence / "scores.npy", scores, allow_pickle=False)
            np.save(evidence / "model_input.npy", matrix, allow_pickle=False)
            np.save(evidence / "source_row_positions.npy", positions, allow_pickle=False)
            manifest = self._manifest(temporary, result)
            self._write_json(temporary / "manifest.json", manifest)
            self._verify_directory(temporary, result_id)
            destination = self.root / result_id
            try:
                os.replace(temporary, destination)
            except (FileExistsError, PermissionError, OSError) as error:
                try:
                    return self.read(result_id)
                except ValueError:
                    raise InferenceResultPersistenceError() from error
            try:
                return self.read(result_id)
            except ValueError as error:
                raise InferenceResultPersistenceError() from error
        except InferenceResultPersistenceError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise InferenceResultPersistenceError() from error
        finally:
            if temporary.exists():
                try:
                    shutil.rmtree(temporary, ignore_errors=True)
                except OSError:
                    pass

    def read(self, inference_result_id: str) -> SavedModelInferenceResult:
        if not self._valid_id(inference_result_id):
            raise InferenceResultNotFoundError()
        directory = self.root / inference_result_id
        if not directory.is_dir():
            raise InferenceResultNotFoundError()
        try:
            return self._verify_directory(directory, inference_result_id)
        except InferenceResultNotFoundError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise InferenceResultIntegrityError() from error

    def read_object_evidence(
        self, inference_result_id: str, row_id: str,
    ) -> SavedInferenceObjectEvidence:
        """Return exactly one row after validating the complete published Result.

        The full Result validation is intentionally retained before the mmap row
        slice: a row can never be trusted independently of its content-addressed
        Result and feature binding.
        """
        result = self.read(inference_result_id)
        matches = [index for index, row in enumerate(result.rows) if row.row_id == row_id]
        if len(matches) != 1:
            raise InferenceResultNotFoundError()
        index = matches[0]
        try:
            directory = self.root / result.inference_result_id / "evidence"
            matrix = np.load(directory / "model_input.npy", allow_pickle=False, mmap_mode="r")
            scores = np.load(directory / "scores.npy", allow_pickle=False, mmap_mode="r")
            positions = np.load(directory / "source_row_positions.npy", allow_pickle=False, mmap_mode="r")
            row = result.rows[index]
            values = np.asarray(matrix[index], dtype=np.float64)
            score = float(scores[index])
            position = int(positions[index])
            if (
                matrix.shape != (result.row_count, len(result.required_feature_columns))
                or scores.shape != (result.row_count,) or positions.shape != (result.row_count,)
                or values.shape != (len(result.required_feature_columns),)
                or not np.isfinite(values).all() or not np.isfinite(score)
                or position != row.source_row_position or score != row.probability
            ):
                raise ValueError("Saved inference row evidence is invalid.")
        except (OSError, TypeError, ValueError, IndexError) as error:
            raise InferenceResultIntegrityError() from error
        return SavedInferenceObjectEvidence(
            inference_result_id=result.inference_result_id,
            model_version_id=result.model_version_id,
            experiment_artifact_id=result.experiment_artifact_id,
            source_file_sha256=result.source_file_sha256,
            row_id=row.row_id,
            source_row_position=row.source_row_position,
            identifier_column=result.identifier_column,
            identifier_display=row.identifier_display,
            probability=row.probability,
            required_feature_columns=result.required_feature_columns,
            feature_values=tuple(float(value) for value in values),
            feature_binding_hash=result.feature_binding_hash,
        )

    def _read_if_present(self, inference_result_id: str) -> SavedModelInferenceResult | None:
        try:
            return self.read(inference_result_id)
        except InferenceResultNotFoundError:
            return None

    def _verify_directory(self, directory: Path, expected_id: str) -> SavedModelInferenceResult:
        manifest = self._read_json(directory / "manifest.json")
        payload = self._read_json(directory / "result.json")
        expected_manifest_keys = {"artifact_type", "schema_version", "inference_result_id", "result_hash", "files"}
        if (not isinstance(manifest, dict) or set(manifest) != expected_manifest_keys
                or manifest.get("artifact_type") != "saved_model_inference_result"
                or manifest.get("schema_version") != _SCHEMA_VERSION
                or manifest.get("inference_result_id") != expected_id):
            raise ValueError("Invalid inference result manifest.")
        if manifest.get("result_hash") != stable_hash(payload) or not isinstance(manifest.get("files"), dict):
            raise ValueError("Inference result manifest hash is invalid.")
        expected_files = {"result.json", "evidence/scores.npy", "evidence/model_input.npy", "evidence/source_row_positions.npy"}
        if set(manifest["files"]) != expected_files:
            raise ValueError("Inference result manifest files are invalid.")
        for name, details in manifest["files"].items():
            path = directory / name
            if not path.is_file() or details != {"sha256": self._file_hash(path), "size_bytes": path.stat().st_size}:
                raise ValueError("Inference result evidence integrity is invalid.")
        result = self._from_payload(payload)
        if result.inference_result_id != expected_id:
            raise ValueError("Inference result identity mismatch.")
        matrix = np.load(directory / "evidence" / "model_input.npy", allow_pickle=False, mmap_mode="r")
        scores = np.load(directory / "evidence" / "scores.npy", allow_pickle=False, mmap_mode="r")
        positions = np.load(directory / "evidence" / "source_row_positions.npy", allow_pickle=False, mmap_mode="r")
        expected_positions = [row.source_row_position for row in result.rows]
        row_scores = np.asarray([row.probability for row in result.rows], dtype=np.float64)
        feature_binding_hash = stable_hash({
            "identifier_column": result.identifier_column,
            "required_feature_columns": result.required_feature_columns,
        })
        recipe_key = stable_hash({
            "model_version_id": result.model_version_id,
            "source_file_sha256": result.source_file_sha256,
            "source_fingerprint": result.source_fingerprint,
            "physical_headers_hash": result.physical_headers_hash,
            "identifier_column": result.identifier_column,
            "required_feature_columns": result.required_feature_columns,
            "feature_binding_hash": result.feature_binding_hash,
            "inference_contract_version": result.inference_contract_version,
        })
        object_identity_hash = stable_hash([
            {"row_id": row.row_id, "source_row_position": row.source_row_position,
             "identifier_display": row.identifier_display} for row in result.rows
        ])
        expected_result_id = self._result_identity({
            "inference_recipe_key": result.inference_recipe_key,
            "experiment_artifact_id": result.experiment_artifact_id,
            "object_identity_hash": object_identity_hash,
            "model_input_hash": result.model_input_hash,
            "scores_hash": result.scores_hash,
        })
        if (
            matrix.shape != (result.row_count, len(result.required_feature_columns))
            or scores.shape != (result.row_count,)
            or positions.tolist() != expected_positions
            or len({row.row_id for row in result.rows}) != result.row_count
            or not np.isfinite(scores).all()
            or (scores < 0).any() or (scores > 1).any()
            or not np.array_equal(scores, row_scores)
            or self._array_hash(matrix) != result.model_input_hash
            or self._array_hash(scores) != result.scores_hash
            or feature_binding_hash != result.feature_binding_hash
            or recipe_key != result.inference_recipe_key
            or expected_result_id != expected_id
        ):
            raise ValueError("Inference result evidence does not match result metadata.")
        return result

    @staticmethod
    def _result_payload(result: SavedModelInferenceResult) -> dict[str, Any]:
        return {
            "schema_version": result.schema_version, "inference_result_id": result.inference_result_id,
            "inference_recipe_key": result.inference_recipe_key,
            "inference_contract_version": result.inference_contract_version,
            "model_version_id": result.model_version_id, "experiment_artifact_id": result.experiment_artifact_id,
            "source_display_name": result.source_display_name, "source_format": result.source_format,
            "source_file_sha256": result.source_file_sha256, "source_fingerprint": result.source_fingerprint,
            "physical_headers_hash": result.physical_headers_hash, "identifier_column": result.identifier_column,
            "required_feature_columns": list(result.required_feature_columns),
            "feature_binding_hash": result.feature_binding_hash, "ignored_columns": list(result.ignored_columns),
            "row_count": result.row_count, "column_count": result.column_count, "created_at": result.created_at,
            "rows": [row.__dict__ if hasattr(row, "__dict__") else {"row_id": row.row_id, "source_row_position": row.source_row_position, "identifier_display": row.identifier_display, "probability": row.probability} for row in result.rows],
            "model_input_hash": result.model_input_hash, "scores_hash": result.scores_hash,
        }

    @staticmethod
    def _from_payload(payload: Any) -> SavedModelInferenceResult:
        try:
            value = dict(payload)
            rows = tuple(SavedInferenceRow(**row) for row in value.pop("rows"))
            value["required_feature_columns"] = tuple(value["required_feature_columns"])
            value["ignored_columns"] = tuple(value["ignored_columns"])
            result = SavedModelInferenceResult(**value, rows=rows)
        except (AttributeError, TypeError, KeyError) as error:
            raise ValueError("Invalid inference result payload.") from error
        if (result.schema_version != _SCHEMA_VERSION or result.inference_contract_version != _CONTRACT_VERSION
                or not SavedModelInferenceResultStore._valid_id(result.inference_result_id)
                or result.row_count < 1 or result.column_count < 1 or len(result.rows) != result.row_count
                or not result.required_feature_columns):
            raise ValueError("Invalid inference result payload.")
        return result

    def _manifest(self, directory: Path, result: SavedModelInferenceResult) -> dict[str, Any]:
        files = ["result.json", "evidence/scores.npy", "evidence/model_input.npy", "evidence/source_row_positions.npy"]
        return {"artifact_type": "saved_model_inference_result", "schema_version": _SCHEMA_VERSION,
                "inference_result_id": result.inference_result_id,
                "result_hash": stable_hash(self._read_json(directory / "result.json")),
                "files": {name: {"sha256": self._file_hash(directory / name), "size_bytes": (directory / name).stat().st_size} for name in files}}

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _file_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _array_hash(value: np.ndarray) -> str:
        return sha256(np.ascontiguousarray(value).tobytes()).hexdigest()

    @staticmethod
    def _result_identity(value: dict[str, str]) -> str:
        return stable_hash(value)

    @staticmethod
    def _valid_id(value: str) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(item in "0123456789abcdef" for item in value)
