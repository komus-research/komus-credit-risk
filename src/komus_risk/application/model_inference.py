"""Inference against an immutable saved model version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_bool_dtype, is_complex_dtype, is_datetime64_any_dtype, is_numeric_dtype,
    is_timedelta64_dtype,
)

from komus_risk.artifacts import LoadedModelVersion
from komus_risk.data import TabularSnapshot
from komus_risk.hashing import stable_hash


class InferenceInputError(ValueError):
    """A typed compatibility failure while preserving the legacy diagnostic text."""

    _MESSAGES = {
        "INFERENCE_SOURCE_EMPTY": "Inference source must contain at least one row.",
        "INFERENCE_IDENTIFIER_MISSING": "Identifier column has an empty value in the inference source.",
        "INFERENCE_REQUIRED_FEATURE_MISSING": "Required model feature columns are absent from the inference source.",
        "INFERENCE_DTYPE_INCOMPATIBLE": "Inference predictor values must all be numeric.",
        "INFERENCE_VALUES_INVALID": "Inference predictor values must be finite.",
        "INFERENCE_PHYSICAL_HEADERS_INVALID": "Inference physical headers do not match dataframe headers.",
        "INFERENCE_PREPARATION_STALE": "Prepared inference input does not match the active ModelVersion.",
        "INFERENCE_INTERNAL_ERROR": "Loaded model version has invalid inference metadata.",
        "INFERENCE_FAILED": "Model predictor returned invalid positive probabilities.",
        "MODEL_INFERENCE_UNSUPPORTED": "Saved model does not support targetless positive-probability inference.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._MESSAGES.get(code, code))


@dataclass(frozen=True, slots=True)
class PreparedInferenceInput:
    """Validated, targetless input in the exact saved feature order."""

    model_version_id: str
    source_sha256: str
    source_fingerprint: str
    physical_headers_hash: str
    row_count: int
    column_count: int
    identifier_column: str
    identifier_values: tuple[Any, ...]
    source_row_positions: tuple[int, ...]
    required_feature_columns: tuple[str, ...]
    validated_feature_values: tuple[tuple[float, ...], ...]
    ignored_columns: tuple[str, ...]

    @property
    def feature_binding_hash(self) -> str:
        return stable_hash({
            "identifier_column": self.identifier_column,
            "required_feature_columns": self.required_feature_columns,
        })

    def feature_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            self.validated_feature_values, columns=list(self.required_feature_columns), dtype=float,
        )


@dataclass(frozen=True, slots=True)
class InferenceCompatibility:
    model_version_id: str
    source_sha256: str
    source_fingerprint: str
    row_count: int
    column_count: int
    identifier_column: str
    required_feature_columns: tuple[str, ...]
    ignored_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PredictionRow:
    row_id: str
    source_row_position: int
    identifier_value: Any
    probability: float


@dataclass(frozen=True, slots=True)
class PredictionBatch:
    model_version_id: str
    source_sha256: str
    identifier_column: str
    required_feature_columns: tuple[str, ...]
    rows: tuple[PredictionRow, ...]
    ignored_columns: tuple[str, ...]
    validated_feature_values: tuple[tuple[float, ...], ...]


class ModelInferenceService:
    """The sole prediction engine for loaded saved models."""

    def prepare(self, *, loaded_model_version: LoadedModelVersion, snapshot: TabularSnapshot) -> PreparedInferenceInput:
        if not callable(getattr(loaded_model_version.predictor, "predict_positive_proba", None)):
            raise InferenceInputError("MODEL_INFERENCE_UNSUPPORTED")
        identifier_column, feature_columns = self._model_schema(loaded_model_version.metadata)
        dataframe = snapshot.dataframe
        headers = self._validate_headers(snapshot)
        if snapshot.row_count < 1 or len(dataframe.index) < 1:
            raise InferenceInputError("INFERENCE_SOURCE_EMPTY")
        if identifier_column not in headers:
            raise InferenceInputError("INFERENCE_IDENTIFIER_MISSING")
        missing = [column for column in feature_columns if column not in headers]
        if missing:
            raise InferenceInputError("INFERENCE_REQUIRED_FEATURE_MISSING")
        identifiers = tuple(dataframe.loc[:, identifier_column].tolist())
        self._validate_identifiers(identifiers, identifier_column)
        feature_frame = self._validated_feature_frame(dataframe, feature_columns)
        values = tuple(tuple(float(value) for value in row) for row in feature_frame.to_numpy(copy=True))
        ignored = tuple(column for column in headers if column not in {*feature_columns, identifier_column})
        return PreparedInferenceInput(
            model_version_id=loaded_model_version.summary.model_version_id,
            source_sha256=snapshot.source_file_sha256,
            source_fingerprint=snapshot.fingerprint,
            physical_headers_hash=stable_hash(headers),
            row_count=snapshot.row_count,
            column_count=snapshot.column_count,
            identifier_column=identifier_column,
            identifier_values=identifiers,
            source_row_positions=tuple(range(snapshot.row_count)),
            required_feature_columns=feature_columns,
            validated_feature_values=values,
            ignored_columns=ignored,
        )

    def inspect(self, *, loaded_model_version: LoadedModelVersion, snapshot: TabularSnapshot) -> InferenceCompatibility:
        prepared = self.prepare(loaded_model_version=loaded_model_version, snapshot=snapshot)
        return InferenceCompatibility(
            model_version_id=prepared.model_version_id, source_sha256=prepared.source_sha256,
            source_fingerprint=prepared.source_fingerprint, row_count=prepared.row_count,
            column_count=prepared.column_count, identifier_column=prepared.identifier_column,
            required_feature_columns=prepared.required_feature_columns,
            ignored_columns=prepared.ignored_columns,
        )

    def predict(self, *, loaded_model_version: LoadedModelVersion, snapshot: TabularSnapshot) -> PredictionBatch:
        return self.predict_prepared(
            loaded_model_version=loaded_model_version,
            prepared=self.prepare(loaded_model_version=loaded_model_version, snapshot=snapshot),
        )

    def predict_prepared(self, *, loaded_model_version: LoadedModelVersion, prepared: PreparedInferenceInput) -> PredictionBatch:
        if prepared.model_version_id != loaded_model_version.summary.model_version_id:
            raise InferenceInputError("INFERENCE_PREPARATION_STALE")
        probabilities = self._validated_probabilities(
            loaded_model_version.predictor.predict_positive_proba(prepared.feature_frame()), prepared.row_count,
        )
        rows = tuple(
            PredictionRow(
                row_id=f"{prepared.source_sha256}:{position}", source_row_position=position,
                identifier_value=prepared.identifier_values[position], probability=float(probabilities[position]),
            )
            for position in prepared.source_row_positions
        )
        return PredictionBatch(
            model_version_id=prepared.model_version_id, source_sha256=prepared.source_sha256,
            identifier_column=prepared.identifier_column,
            required_feature_columns=prepared.required_feature_columns, rows=rows,
            ignored_columns=prepared.ignored_columns,
            validated_feature_values=prepared.validated_feature_values,
        )

    @staticmethod
    def _model_schema(metadata: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
        try:
            identifier_column = metadata["dataset_contract"]["identifier_column"]
            feature_columns = tuple(metadata["feature_columns"])
        except (KeyError, TypeError) as error:
            raise InferenceInputError("INFERENCE_INTERNAL_ERROR") from error
        if (not isinstance(identifier_column, str) or not identifier_column.strip() or not feature_columns
                or any(not isinstance(column, str) or not column.strip() for column in feature_columns)
                or len(feature_columns) != len(set(feature_columns)) or identifier_column in feature_columns):
            raise InferenceInputError("INFERENCE_INTERNAL_ERROR")
        return identifier_column, feature_columns

    @staticmethod
    def _validate_headers(snapshot: TabularSnapshot) -> tuple[str, ...]:
        dataframe = snapshot.dataframe
        if not isinstance(dataframe, pd.DataFrame):
            raise InferenceInputError("INFERENCE_PHYSICAL_HEADERS_INVALID")
        headers = tuple(dataframe.columns)
        if (any(not isinstance(column, str) or not column.strip() for column in headers)
                or len(headers) != len(set(headers))
                or (snapshot.physical_headers and tuple(snapshot.physical_headers) != headers)
                or (snapshot.physical_headers and (len(snapshot.physical_headers) != len(set(snapshot.physical_headers))
                    or any(not isinstance(column, str) or not column.strip() for column in snapshot.physical_headers)))):
            raise InferenceInputError("INFERENCE_PHYSICAL_HEADERS_INVALID")
        return headers

    @staticmethod
    def _validate_identifiers(values: tuple[Any, ...], identifier_column: str) -> None:
        for value in values:
            if value is None or (isinstance(value, str) and not value.strip()) or pd.isna(value):
                raise InferenceInputError("INFERENCE_IDENTIFIER_MISSING")

    @staticmethod
    def _validated_feature_frame(dataframe: pd.DataFrame, feature_columns: tuple[str, ...]) -> pd.DataFrame:
        try:
            frame = dataframe.loc[:, list(feature_columns)]
            for column in feature_columns:
                dtype = frame.loc[:, column].dtype
                if (is_complex_dtype(dtype) or is_datetime64_any_dtype(dtype) or is_timedelta64_dtype(dtype)
                        or not (is_numeric_dtype(dtype) or is_bool_dtype(dtype))):
                    raise InferenceInputError("INFERENCE_DTYPE_INCOMPATIBLE")
            numeric = frame.astype(float)
        except InferenceInputError:
            raise
        except (TypeError, ValueError) as error:
            raise InferenceInputError("INFERENCE_DTYPE_INCOMPATIBLE") from error
        if not np.isfinite(numeric.to_numpy(copy=False)).all():
            raise InferenceInputError("INFERENCE_VALUES_INVALID")
        return numeric

    @staticmethod
    def _validated_probabilities(raw_probabilities: Any, row_count: int) -> np.ndarray:
        try:
            probabilities = np.asarray(raw_probabilities, dtype=float)
        except (TypeError, ValueError) as error:
            raise InferenceInputError("INFERENCE_FAILED") from error
        if (probabilities.ndim != 1 or len(probabilities) != row_count or not np.isfinite(probabilities).all()
                or (probabilities < 0).any() or (probabilities > 1).any()):
            raise InferenceInputError("INFERENCE_FAILED")
        return probabilities
