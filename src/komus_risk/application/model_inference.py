"""Inference against an immutable saved model version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_complex_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_timedelta64_dtype,
)

from komus_risk.artifacts import LoadedModelVersion
from komus_risk.data import TabularSnapshot


@dataclass(frozen=True, slots=True)
class PredictionRow:
    """One prediction, traceable to a single source-row position."""

    row_id: str
    source_row_position: int
    identifier_value: Any
    probability: float


@dataclass(frozen=True, slots=True)
class PredictionBatch:
    """Validated inference result and the precise values supplied to the model."""

    model_version_id: str
    source_sha256: str
    identifier_column: str
    required_feature_columns: tuple[str, ...]
    rows: tuple[PredictionRow, ...]
    ignored_columns: tuple[str, ...]
    validated_feature_values: tuple[tuple[float, ...], ...]


class ModelInferenceService:
    """Applies a loaded model to a new physical tabular snapshot."""

    def predict(self, *, loaded_model_version: LoadedModelVersion, snapshot: TabularSnapshot) -> PredictionBatch:
        metadata = loaded_model_version.metadata
        identifier_column, feature_columns = self._model_schema(metadata)
        dataframe = snapshot.dataframe
        headers = self._validate_headers(snapshot)

        if identifier_column not in headers:
            raise ValueError(f"Required identifier column {identifier_column!r} is absent from the inference source.")
        missing_features = [column for column in feature_columns if column not in headers]
        if missing_features:
            raise ValueError(f"Required model feature columns are absent from the inference source: {missing_features!r}.")

        identifier_values = tuple(dataframe.loc[:, identifier_column].tolist())
        self._validate_identifiers(identifier_values, identifier_column)
        feature_frame = self._validated_feature_frame(dataframe, feature_columns)
        probabilities = self._validated_probabilities(loaded_model_version.predictor.predict_positive_proba(feature_frame), len(feature_frame))
        values = tuple(tuple(float(value) for value in row) for row in feature_frame.to_numpy(copy=True))
        rows = tuple(
            PredictionRow(
                row_id=f"{snapshot.source_file_sha256}:{position}",
                source_row_position=position,
                identifier_value=identifier_values[position],
                probability=float(probabilities[position]),
            )
            for position in range(len(feature_frame))
        )
        ignored = tuple(column for column in headers if column not in {*feature_columns, identifier_column})
        return PredictionBatch(
            model_version_id=loaded_model_version.summary.model_version_id,
            source_sha256=snapshot.source_file_sha256,
            identifier_column=identifier_column,
            required_feature_columns=feature_columns,
            rows=rows,
            ignored_columns=ignored,
            validated_feature_values=values,
        )

    @staticmethod
    def _model_schema(metadata: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
        try:
            identifier_column = metadata["dataset_contract"]["identifier_column"]
            feature_columns = tuple(metadata["feature_columns"])
        except (KeyError, TypeError) as error:
            raise ValueError("Loaded model version has invalid inference metadata.") from error
        if (not isinstance(identifier_column, str) or not identifier_column.strip()
                or not feature_columns
                or any(not isinstance(column, str) or not column.strip() for column in feature_columns)
                or len(feature_columns) != len(set(feature_columns))
                or identifier_column in feature_columns):
            raise ValueError("Loaded model version has invalid inference schema metadata.")
        return identifier_column, feature_columns

    @staticmethod
    def _validate_headers(snapshot: TabularSnapshot) -> tuple[str, ...]:
        dataframe = snapshot.dataframe
        if not isinstance(dataframe, pd.DataFrame):
            raise ValueError("Inference snapshot must contain a dataframe.")
        headers = tuple(dataframe.columns)
        if (any(not isinstance(column, str) or not column.strip() for column in headers)
                or len(headers) != len(set(headers))):
            raise ValueError("Inference dataframe headers must be non-empty strings and unique.")
        # Older in-memory snapshots have no physical header record. When it is
        # available, it is authoritative and must be exactly the dataframe schema.
        if snapshot.physical_headers and tuple(snapshot.physical_headers) != headers:
            raise ValueError("Inference physical headers do not match dataframe headers.")
        if snapshot.physical_headers and (len(snapshot.physical_headers) != len(set(snapshot.physical_headers))
                                         or any(not isinstance(column, str) or not column.strip() for column in snapshot.physical_headers)):
            raise ValueError("Inference physical headers must be non-empty strings and unique.")
        return headers

    @staticmethod
    def _validate_identifiers(values: tuple[Any, ...], identifier_column: str) -> None:
        for position, value in enumerate(values):
            if value is None or (isinstance(value, str) and not value.strip()) or pd.isna(value):
                raise ValueError(f"Identifier column {identifier_column!r} has an empty value at source row {position}.")

    @staticmethod
    def _validated_feature_frame(dataframe: pd.DataFrame, feature_columns: tuple[str, ...]) -> pd.DataFrame:
        try:
            feature_frame = dataframe.loc[:, list(feature_columns)]
            for column in feature_columns:
                dtype = feature_frame.loc[:, column].dtype
                if (is_complex_dtype(dtype) or is_datetime64_any_dtype(dtype)
                        or is_timedelta64_dtype(dtype)
                        or not (is_numeric_dtype(dtype) or is_bool_dtype(dtype))):
                    raise ValueError(f"Inference predictor column {column!r} must have a real numeric or boolean dtype.")
            numeric = feature_frame.astype(float)
        except (TypeError, ValueError) as error:
            raise ValueError("Inference predictor values must all be numeric.") from error
        values = numeric.to_numpy(copy=False)
        if not np.isfinite(values).all():
            raise ValueError("Inference predictor values must be finite.")
        return numeric

    @staticmethod
    def _validated_probabilities(raw_probabilities: Any, row_count: int) -> np.ndarray:
        try:
            probabilities = np.asarray(raw_probabilities, dtype=float)
        except (TypeError, ValueError) as error:
            raise ValueError("Model predictor returned invalid positive probabilities.") from error
        if (probabilities.ndim != 1 or len(probabilities) != row_count
                or not np.isfinite(probabilities).all()
                or (probabilities < 0).any() or (probabilities > 1).any()):
            raise ValueError("Model predictor returned invalid positive probabilities.")
        return probabilities
