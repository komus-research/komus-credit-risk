"""Local, row-level TreeSHAP evidence from an exact persisted GBDT model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import catboost
import lightgbm
import numpy as np
import pandas as pd
import xgboost

from komus_risk.artifacts import LoadedModelVersion
from komus_risk.hashing import stable_hash

from .model_inference import PredictionBatch, PredictionRow

_EVIDENCE_VERSION = "local_explanation_v1"
_SUPPORTED_MODEL_IDS = frozenset({"catboost", "xgboost", "lightgbm"})
_EXPLAINER_IDS = {model_id: f"{model_id}_native_shap" for model_id in _SUPPORTED_MODEL_IDS}
_EXPLAINER_VERSIONS = {
    "catboost": catboost.__version__,
    "xgboost": xgboost.__version__,
    "lightgbm": lightgbm.__version__,
}
_ADDITIVITY_TOLERANCES = {
    "catboost": (1e-7, 1e-8),
    "xgboost": (1e-6, 1e-6),
    "lightgbm": (1e-7, 1e-8),
}


@dataclass(frozen=True, slots=True)
class LocalFeatureContribution:
    feature_id: str
    column_name: str
    raw_value: float
    shap_value: float
    abs_rank: int


@dataclass(frozen=True, slots=True)
class LocalExplanationEvidence:
    evidence_version: str
    model_version_id: str
    experiment_artifact_id: str
    dataset_id: str
    dataset_fingerprint: str
    feature_set_hash: str
    model_id: str
    model_version: str
    row_id: str
    identifier_column: str
    identifier_value: Any
    probability: float
    shap_output_space: str
    raw_model_output: float
    base_value: float
    features: tuple[LocalFeatureContribution, ...]
    explainer_id: str
    explainer_version: str
    created_at: str
    evidence_hash: str


class LocalExplanationService:
    """Builds fail-closed native TreeSHAP evidence for a predicted row."""

    def explain(
        self,
        *,
        loaded_model_version: LoadedModelVersion,
        prediction_batch: PredictionBatch,
        row_id: str,
    ) -> LocalExplanationEvidence:
        metadata = loaded_model_version.metadata
        model_id, feature_ids, columns, dataset = self._validate_binding(
            loaded_model_version, prediction_batch, metadata
        )
        row, values = self._locate_row(prediction_batch, row_id, len(columns))
        frame = pd.DataFrame([values], columns=columns, dtype=float)
        probability = float(loaded_model_version.predictor.predict_positive_proba(frame)[0])
        if not np.isclose(probability, row.probability, rtol=1e-9, atol=1e-12):
            raise ValueError("Recomputed probability does not match the displayed PredictionBatch probability.")
        shap_values, base_value, raw_model_output = loaded_model_version.predictor.local_shap(frame)
        relative_tolerance, absolute_tolerance = _ADDITIVITY_TOLERANCES[model_id]
        if not np.isclose(
            base_value + float(np.sum(shap_values)), raw_model_output,
            rtol=relative_tolerance, atol=absolute_tolerance,
        ):
            raise ValueError("Native SHAP values fail the raw-margin additivity check.")
        if not np.isclose(self._margin_probability(raw_model_output), probability, rtol=1e-7, atol=1e-9):
            raise ValueError("Native SHAP raw margin does not reproduce the model probability.")

        contributions = [
            LocalFeatureContribution(
                feature_id=feature_ids[index],
                column_name=column,
                raw_value=float(values[index]),
                shap_value=float(shap_values[index]),
                abs_rank=0,
            )
            for index, column in enumerate(columns)
        ]
        contributions.sort(key=lambda item: (-abs(item.shap_value), columns.index(item.column_name)))
        ranked = tuple(
            LocalFeatureContribution(item.feature_id, item.column_name, item.raw_value, item.shap_value, rank)
            for rank, item in enumerate(contributions, start=1)
        )
        payload = {
            "evidence_version": _EVIDENCE_VERSION,
            "model_version_id": loaded_model_version.summary.model_version_id,
            "experiment_artifact_id": metadata["experiment_artifact_id"],
            "dataset_id": dataset["dataset_id"],
            "dataset_fingerprint": dataset["dataset_fingerprint"],
            "feature_set_hash": metadata["feature_set_hash"],
            "model_id": model_id,
            "model_version": metadata["model_version"],
            "row_id": row.row_id,
            "identifier_column": prediction_batch.identifier_column,
            "identifier_value": row.identifier_value,
            "probability": float(row.probability),
            "shap_output_space": "raw_margin",
            "raw_model_output": raw_model_output,
            "base_value": base_value,
            "features": ranked,
            "explainer_id": _EXPLAINER_IDS[model_id],
            "explainer_version": _EXPLAINER_VERSIONS[model_id],
        }
        return LocalExplanationEvidence(
            **payload,
            created_at=datetime.now(timezone.utc).isoformat(),
            evidence_hash=stable_hash(payload),
        )

    @staticmethod
    def _validate_binding(
        loaded: LoadedModelVersion,
        batch: PredictionBatch,
        metadata: dict[str, Any],
    ) -> tuple[str, tuple[str, ...], tuple[str, ...], dict[str, Any]]:
        if batch.model_version_id != loaded.summary.model_version_id:
            raise ValueError("PredictionBatch model_version_id does not match the loaded model version.")
        model_id = loaded.summary.model_id
        if (model_id not in _SUPPORTED_MODEL_IDS or metadata.get("model_id") != model_id
                or loaded.predictor.model_id != model_id):
            raise ValueError("Local explanations are unsupported for this model version.")
        try:
            columns = tuple(metadata["feature_columns"])
            feature_ids = tuple(metadata["feature_ids"])
            specs = tuple(metadata["feature_specs"])
            dataset = metadata["dataset_contract"]
            expected_identifier = dataset["identifier_column"]
        except (KeyError, TypeError) as error:
            raise ValueError("Loaded model version has invalid local-explanation metadata.") from error
        if (not columns or tuple(batch.required_feature_columns) != columns
                or tuple(loaded.predictor.feature_columns) != columns
                or len(columns) != len(set(columns))
                or len(feature_ids) != len(columns) or len(specs) != len(columns)
                or batch.identifier_column != expected_identifier):
            raise ValueError("PredictionBatch schema does not exactly match the saved model version.")
        if any(
            not isinstance(feature_id, str) or not feature_id.strip()
            or not isinstance(spec, dict)
            or spec.get("feature_id") != feature_id
            or spec.get("column_name") != columns[index]
            for index, (feature_id, spec) in enumerate(zip(feature_ids, specs, strict=True))
        ):
            raise ValueError("Saved model feature identity metadata is invalid.")
        if (loaded.summary.experiment_artifact_id != metadata["experiment_artifact_id"]
                or loaded.summary.model_version != metadata["model_version"]
                or loaded.summary.feature_ids != feature_ids):
            raise ValueError("Loaded model version summary does not match immutable metadata.")
        required_metadata = ("experiment_artifact_id", "feature_set_hash", "model_version")
        if (not isinstance(dataset, dict)
                or any(not isinstance(dataset.get(key), str) or not dataset[key].strip() for key in ("dataset_id", "dataset_fingerprint"))
                or any(not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in required_metadata)):
            raise ValueError("Loaded model version has invalid local-explanation provenance.")
        return model_id, feature_ids, columns, dataset

    @staticmethod
    def _margin_probability(raw_margin: float) -> float:
        if not np.isfinite(raw_margin):
            raise ValueError("Native SHAP raw margin must be finite.")
        if raw_margin >= 0:
            return float(1.0 / (1.0 + np.exp(-raw_margin)))
        exp_margin = float(np.exp(raw_margin))
        return exp_margin / (1.0 + exp_margin)

    @staticmethod
    def _locate_row(batch: PredictionBatch, row_id: str, feature_count: int) -> tuple[PredictionRow, tuple[float, ...]]:
        if not isinstance(row_id, str) or not row_id:
            raise ValueError("row_id must be a non-empty string.")
        if len(batch.rows) != len(batch.validated_feature_values):
            raise ValueError("PredictionBatch rows and validated feature values are inconsistent.")
        matches = [(row, values) for row, values in zip(batch.rows, batch.validated_feature_values, strict=True) if row.row_id == row_id]
        if len(matches) != 1:
            raise ValueError("row_id must exist exactly once in the PredictionBatch.")
        row, values = matches[0]
        try:
            numeric_values = tuple(float(value) for value in values)
        except (TypeError, ValueError) as error:
            raise ValueError("PredictionBatch validated feature values are invalid.") from error
        if (len(numeric_values) != feature_count or not np.isfinite(numeric_values).all()
                or not isinstance(row.probability, (int, float)) or not np.isfinite(float(row.probability))
                or not 0 <= float(row.probability) <= 1):
            raise ValueError("PredictionBatch selected row is invalid.")
        return row, numeric_values
