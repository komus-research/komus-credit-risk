"""Trusted executable local-explanation providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Protocol

from komus_risk.hashing import stable_hash

from .contracts import ProviderDescriptor

_GBDT_MEAN_PERMUTATION_SEED = 20260930
_GBDT_MEAN_PERMUTATIONS = 1
_BACKGROUND_POLICY_ID = "outer_train_hash_top128_v1"
_MAX_BACKGROUND_ROWS = 128
_COMPONENT_IDS = ("catboost", "xgboost", "lightgbm")


@dataclass(frozen=True, slots=True)
class TrustedExplanationContext:
    """Source-neutral, application-created explanation background binding."""

    source_kind: str
    source_artifact_id: str
    model_binding_id: str
    feature_columns: tuple[str, ...]
    background_values: tuple[tuple[float, ...], ...]
    background_row_positions: tuple[int, ...]
    background_policy_id: str
    validation_row_position: int | None = None
    validation_row_positions: tuple[int, ...] = ()
    final_test_row_positions: tuple[int, ...] = ()
    fold_id: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.source_kind, self.source_artifact_id, self.model_binding_id, self.background_policy_id)):
            raise ValueError("Trusted explanation context identity is invalid.")
        columns = tuple(self.feature_columns)
        rows = tuple(tuple(float(value) for value in row) for row in self.background_values)
        positions = tuple(self.background_row_positions)
        final_test = tuple(self.final_test_row_positions)
        validation = tuple(self.validation_row_positions)
        if self.validation_row_position is not None and self.validation_row_position not in validation:
            validation = (*validation, self.validation_row_position)
        if (not columns or len(columns) != len(set(columns)) or any(not isinstance(column, str) or not column.strip() for column in columns) or not rows or len(rows) != len(positions) or len(rows) > _MAX_BACKGROUND_ROWS or any(len(row) != len(columns) for row in rows) or len(positions) != len(set(positions)) or len(validation) != len(set(validation)) or set(positions) & set(final_test) or set(positions) & set(validation)):
            raise ValueError("Trusted explanation background binding is invalid.")
        object.__setattr__(self, "feature_columns", columns)
        object.__setattr__(self, "background_values", rows)
        object.__setattr__(self, "background_row_positions", positions)
        object.__setattr__(self, "validation_row_positions", validation)
        object.__setattr__(self, "final_test_row_positions", final_test)

    @property
    def background_hash(self) -> str:
        return stable_hash({"policy_id": self.background_policy_id, "feature_columns": self.feature_columns, "row_positions": self.background_row_positions, "values": self.background_values, "final_test_row_positions": self.final_test_row_positions, "fold_id": self.fold_id})

    @classmethod
    def from_oof_evidence(cls, *, source_artifact_id: str, model_binding_id: str, feature_columns: Sequence[str], model_input_values: Sequence[Sequence[float]], row_positions: Sequence[int], fold_assignments: Sequence[str | int], validation_fold: str | int, validation_row_position: int, final_test_row_positions: Sequence[int] = (), background_policy_id: str = _BACKGROUND_POLICY_ID) -> "TrustedExplanationContext":
        if not (len(model_input_values) == len(row_positions) == len(fold_assignments)):
            raise ValueError("OOF explanation facts are not canonically aligned.")
        final_test = tuple(final_test_row_positions)
        candidates = tuple((tuple(values), position) for values, position, fold in zip(model_input_values, row_positions, fold_assignments, strict=True) if fold != validation_fold and position not in final_test)
        ranked = sorted(candidates, key=lambda item: stable_hash({"policy_id": background_policy_id, "source_artifact_id": source_artifact_id, "model_binding_id": model_binding_id, "fold_id": str(validation_fold), "row_position": item[1]}))
        selected = tuple(ranked[:_MAX_BACKGROUND_ROWS])
        validation_positions = tuple(position for position, fold in zip(row_positions, fold_assignments, strict=True) if fold == validation_fold)
        return cls("oof_fold", source_artifact_id, model_binding_id, tuple(feature_columns), tuple(values for values, _ in selected), tuple(position for _, position in selected), background_policy_id, validation_row_position, validation_positions, final_test, str(validation_fold))

    @classmethod
    def from_model_version_evidence(
        cls, *, source_artifact_id: str, model_binding_id: str,
        feature_columns: Sequence[str], model_input_values: Sequence[Sequence[float]],
        row_positions: Sequence[int],
        background_policy_id: str = "model_version_training_hash_top128_v1",
    ) -> "TrustedExplanationContext":
        """Build a deterministic final-model background without OOF semantics."""
        if len(model_input_values) != len(row_positions) or not model_input_values:
            raise ValueError("ModelVersion explanation evidence is not canonically aligned.")
        candidates = tuple((tuple(values), int(position)) for values, position in zip(model_input_values, row_positions, strict=True))
        ranked = sorted(candidates, key=lambda item: stable_hash({
            "policy_id": background_policy_id,
            "source_artifact_id": source_artifact_id,
            "model_binding_id": model_binding_id,
            "row_position": item[1],
        }))
        selected = tuple(ranked[:_MAX_BACKGROUND_ROWS])
        return cls(
            "model_version", source_artifact_id, model_binding_id,
            tuple(feature_columns), tuple(values for values, _ in selected),
            tuple(position for _, position in selected), background_policy_id,
        )


class ModelExplanationProvider(Protocol):
    descriptor: ProviderDescriptor
    model_id: str
    model_version: str
    adapter_version: str

    def explain(self, *, loaded_model_version: Any, prediction_batch: Any, row_id: str, explanation_context: TrustedExplanationContext | None = None) -> Any: ...
    def explain_batch(self, *, loaded_model_version: Any, prediction_batch: Any, row_ids: tuple[str, ...], explanation_context: TrustedExplanationContext) -> tuple[Any, ...]: ...


@dataclass(frozen=True, slots=True)
class OOFShapChunkAggregate:
    row_count: int
    sum_abs_shap: tuple[float, ...]
    provider_id: str
    provider_version: str
    explanation_method_id: str
    explanation_method_version: str
    aggregation_method_id: str
    aggregation_method_version: str
    numerical_validation_profile_id: str
    numerical_validation_profile_version: str
    output_space: str
    model_binding_id: str
    feature_binding_hash: str
    background_policy_id: str
    background_hash: str

    def __post_init__(self) -> None:
        values = tuple(float(value) for value in self.sum_abs_shap)
        if (self.row_count < 1 or not values or any(not math.isfinite(value) or value < 0 for value in values)
                or any(not isinstance(getattr(self, field), str) or not getattr(self, field).strip() for field in (
                    "provider_id", "provider_version", "explanation_method_id", "explanation_method_version",
                    "aggregation_method_id", "aggregation_method_version", "numerical_validation_profile_id",
                    "numerical_validation_profile_version", "output_space", "model_binding_id",
                    "feature_binding_hash", "background_policy_id", "background_hash"))):
            raise ValueError("OOF SHAP chunk aggregate is invalid.")
        object.__setattr__(self, "sum_abs_shap", values)


class OOFPredictionReplayMismatch(ValueError):
    """Stable typed failure when a persisted OOF score does not replay."""


class ModelExplanationProviderRegistry:
    """Fail-closed mapping from reviewed provider IDs to executable code."""

    def __init__(self, providers: Iterable[ModelExplanationProvider] = ()) -> None:
        self._providers: dict[str, ModelExplanationProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ModelExplanationProvider) -> ModelExplanationProvider:
        descriptor = getattr(provider, "descriptor", None)
        if not isinstance(descriptor, ProviderDescriptor) or descriptor.provider_kind != "local_explanation":
            raise TypeError("Only a trusted local explanation provider can be registered.")
        identity = (getattr(provider, "model_id", None), getattr(provider, "model_version", None), getattr(provider, "adapter_version", None))
        if not all(isinstance(value, str) and value.strip() for value in identity):
            raise ValueError("Explanation provider has an invalid model identity.")
        if not callable(getattr(provider, "explain", None)) or not callable(getattr(provider, "explain_batch", None)):
            raise TypeError("Explanation provider has no executable batch explanation method.")
        existing = self._providers.get(descriptor.provider_id)
        if existing is not None:
            if existing.descriptor != descriptor or (existing.model_id, existing.model_version, existing.adapter_version) != identity:
                raise ValueError("Explanation provider is already registered incompatibly.")
            return existing
        self._providers[descriptor.provider_id] = provider
        return provider

    def get(self, provider_id: str) -> ModelExplanationProvider:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("Explanation provider ID must be a non-empty string.")
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError("Trusted explanation provider is not registered.") from error

    def validate_plugin_provider(self, plugin: Any) -> ModelExplanationProvider:
        descriptor = plugin.local_explanation_provider
        if descriptor is None:
            raise ValueError("Plugin has no local explanation provider descriptor.")
        provider = self.get(descriptor.provider_id)
        if provider.descriptor != descriptor:
            raise ValueError("Plugin explanation provider identity does not match executable provider.")
        if (provider.model_id, provider.model_version, provider.adapter_version) != (plugin.spec.model_id, plugin.spec.version, plugin.spec.adapter_version):
            raise ValueError("Plugin model identity is incompatible with explanation provider.")
        return provider


def _validate_oof_context_binding(
    *,
    metadata: Mapping[str, Any],
    context: TrustedExplanationContext,
    prediction_batch: Any,
    selected_rows: Sequence[Any],
    expected_model_version_id: str,
) -> None:
    """Validate the shared trusted artifact/fold/schema/row OOF binding."""
    columns = tuple(metadata.get("feature_columns", ()))
    artifact_id = metadata.get("experiment_artifact_id")
    fold_model_binding_id = metadata.get("fold_model_binding_id")
    fold_id = metadata.get("fold_id")
    if (
        context.source_kind != "oof_fold"
        or not isinstance(artifact_id, str)
        or not artifact_id.strip()
        or context.source_artifact_id != artifact_id
        or not isinstance(fold_model_binding_id, str)
        or not fold_model_binding_id.strip()
        or context.model_binding_id != fold_model_binding_id
        or fold_id is None
        or not context.fold_id
        or context.fold_id != str(fold_id)
        or not columns
        or context.feature_columns != columns
        or tuple(prediction_batch.required_feature_columns) != context.feature_columns
        or prediction_batch.model_version_id != expected_model_version_id
        or not context.validation_row_positions
        or any(row.source_row_position not in context.validation_row_positions for row in selected_rows)
    ):
        raise ValueError("Trusted OOF context does not match the exact artifact, fold model, feature binding, or validation rows.")


def _validate_model_version_context_binding(
    *, metadata: Mapping[str, Any], context: TrustedExplanationContext,
    prediction_batch: Any, expected_model_version_id: str,
) -> None:
    """Validate final-ModelVersion background; it deliberately has no OOF rule."""
    columns = tuple(metadata.get("feature_columns", ()))
    artifact_id = metadata.get("experiment_artifact_id")
    if (
        context.source_kind != "model_version" or context.source_artifact_id != artifact_id
        or context.model_binding_id != expected_model_version_id
        or context.feature_columns != columns
        or tuple(prediction_batch.required_feature_columns) != columns
        or prediction_batch.model_version_id != expected_model_version_id
        or context.validation_row_positions or context.fold_id is not None
    ):
        raise ValueError("Trusted ModelVersion context does not match final model evidence.")


@dataclass(frozen=True, slots=True)
class BuiltinNativeExplanationProvider:
    descriptor: ProviderDescriptor
    model_id: str
    model_version: str
    adapter_version: str

    def __post_init__(self) -> None:
        if self.descriptor.provider_kind != "local_explanation":
            raise ValueError("Explanation provider has an invalid provider kind.")

    def explain(self, *, loaded_model_version: Any, prediction_batch: Any, row_id: str, explanation_context: TrustedExplanationContext | None = None) -> Any:
        from komus_risk.application.local_explanation import LocalExplanationService
        return LocalExplanationService(provider_descriptor=self.descriptor, expected_model_id=self.model_id).explain(loaded_model_version=loaded_model_version, prediction_batch=prediction_batch, row_id=row_id)

    def aggregate_oof_chunk(
        self, *, loaded_model_version: Any, prediction_batch: Any, feature_matrix: Any,
        persisted_oof_probabilities: Any, row_positions: Sequence[int],
        explanation_context: TrustedExplanationContext,
    ) -> OOFShapChunkAggregate:
        """Validate and aggregate exact OOF rows without constructing row evidence."""
        import numpy as np
        import pandas as pd
        from komus_risk.application.local_explanation import (
            NATIVE_SHAP_NUMERICAL_PROFILES, validate_native_shap_numerics,
        )

        metadata = loaded_model_version.metadata
        summary = loaded_model_version.summary
        if (self.model_id not in {"catboost", "xgboost", "lightgbm"}
                or metadata.get("model_id") != self.model_id or summary.model_id != self.model_id
                or loaded_model_version.predictor.model_id != self.model_id
                or summary.experiment_artifact_id != metadata.get("experiment_artifact_id")
                or summary.model_version != metadata.get("model_version")):
            raise ValueError("Native OOF aggregate model binding is invalid.")
        if not isinstance(feature_matrix, pd.DataFrame) or len(feature_matrix) < 1:
            raise ValueError("OOF aggregate feature matrix must be a non-empty DataFrame.")
        columns = tuple(metadata.get("feature_columns", ()))
        feature_binding_hash = metadata.get("feature_set_hash")
        if (tuple(feature_matrix.columns) != columns or tuple(loaded_model_version.predictor.feature_columns) != columns
                or not isinstance(feature_binding_hash, str) or not feature_binding_hash.strip()):
            raise ValueError("OOF aggregate feature columns/order do not match the persisted model.")
        if not isinstance(explanation_context, TrustedExplanationContext):
            raise ValueError("Native OOF aggregate requires trusted fold context.")
        if len(prediction_batch.rows) != len(feature_matrix) or len(prediction_batch.validated_feature_values) != len(feature_matrix):
            raise ValueError("OOF aggregate chunk does not match its PredictionBatch.")
        values = np.asarray(feature_matrix, dtype=float)
        batch_values = np.asarray(prediction_batch.validated_feature_values, dtype=float)
        positions = tuple(row_positions)
        batch_positions = tuple(row.source_row_position for row in prediction_batch.rows)
        if (values.shape != (len(prediction_batch.rows), len(columns)) or not np.isfinite(values).all()
                or batch_values.shape != values.shape or not np.array_equal(values, batch_values)
                or len(positions) != len(values) or positions != batch_positions
                or len(set(positions)) != len(positions)
                or len({row.row_id for row in prediction_batch.rows}) != len(prediction_batch.rows)):
            raise ValueError("OOF aggregate chunk row binding or feature values are invalid.")
        _validate_oof_context_binding(
            metadata=metadata, context=explanation_context, prediction_batch=prediction_batch,
            selected_rows=prediction_batch.rows, expected_model_version_id=summary.model_version_id,
        )
        expected_specs = metadata.get("feature_specs")
        if (not isinstance(expected_specs, list) or len(expected_specs) != len(columns)
                or any(not isinstance(spec, Mapping) or spec.get("column_name") != columns[index]
                       for index, spec in enumerate(expected_specs))):
            raise ValueError("OOF aggregate feature binding metadata is invalid.")
        persisted = np.asarray(persisted_oof_probabilities, dtype=float)
        if persisted.shape != (len(values),) or not np.isfinite(persisted).all() or ((persisted < 0) | (persisted > 1)).any():
            raise ValueError("Persisted OOF probabilities have invalid shape or values.")
        replayed = np.asarray(loaded_model_version.predictor.predict_positive_proba(feature_matrix), dtype=float)
        displayed = np.asarray([row.probability for row in prediction_batch.rows], dtype=float)
        if (replayed.shape != persisted.shape or not np.isfinite(replayed).all()
                or not np.isclose(replayed, persisted, rtol=1e-12, atol=1e-12).all()
                or not np.isclose(persisted, displayed, rtol=1e-12, atol=1e-12).all()):
            raise OOFPredictionReplayMismatch("Fold probability replay does not match persisted OOF probabilities.")
        shap_values, bases, margins = loaded_model_version.predictor.native_shap_batch(feature_matrix)
        profile = validate_native_shap_numerics(self.model_id, shap_values, bases, margins, replayed)
        return OOFShapChunkAggregate(
            row_count=len(values),
            sum_abs_shap=tuple(np.sum(np.abs(shap_values), axis=0, dtype=np.float64).tolist()),
            provider_id=self.descriptor.provider_id,
            provider_version=self.descriptor.provider_version,
            explanation_method_id=self.descriptor.provider_id,
            explanation_method_version=self.descriptor.provider_version,
            aggregation_method_id="sum_absolute_shap",
            aggregation_method_version="1",
            numerical_validation_profile_id=profile.profile_id,
            numerical_validation_profile_version=profile.version,
            output_space="raw_margin",
            model_binding_id=explanation_context.model_binding_id,
            feature_binding_hash=feature_binding_hash,
            background_policy_id=explanation_context.background_policy_id,
            background_hash=explanation_context.background_hash,
        )

    def explain_batch(self, *, loaded_model_version: Any, prediction_batch: Any, row_ids: tuple[str, ...], explanation_context: TrustedExplanationContext) -> tuple[Any, ...]:
        if not isinstance(explanation_context, TrustedExplanationContext):
            raise ValueError("Native explanation batch requires trusted background context.")
        if not row_ids or len(row_ids) != len(set(row_ids)):
            raise ValueError("Explanation batch row IDs are invalid.")
        from dataclasses import replace
        from komus_risk.application.local_explanation import LocalExplanationEvidence

        metadata = loaded_model_version.metadata
        summary = loaded_model_version.summary
        records = {row.row_id: (row, values) for row, values in zip(prediction_batch.rows, prediction_batch.validated_feature_values, strict=True)}
        if len(records) != len(prediction_batch.rows) or set(row_ids) - set(records):
            raise ValueError("Native OOF explanation rows do not match the PredictionBatch.")
        selected = tuple(records[row_id][0] for row_id in row_ids)
        _validate_oof_context_binding(
            metadata=metadata,
            context=explanation_context,
            prediction_batch=prediction_batch,
            selected_rows=selected,
            expected_model_version_id=summary.model_version_id,
        )
        result = []
        for row_id in row_ids:
            evidence = self.explain(loaded_model_version=loaded_model_version, prediction_batch=prediction_batch, row_id=row_id)
            provenance = dict(evidence.provenance or {})
            provenance.update({
                "source_kind": "oof_fold",
                "source_artifact_id": explanation_context.source_artifact_id,
                "model_binding_id": explanation_context.model_binding_id,
                "fold_id": explanation_context.fold_id,
                "validation_row_positions": list(explanation_context.validation_row_positions),
                "feature_binding_hash": metadata["feature_set_hash"],
            })
            changes = {
                "source_kind": "oof_fold",
                "source_artifact_id": explanation_context.source_artifact_id,
                "model_binding_id": explanation_context.model_binding_id,
                "provenance": provenance,
            }
            semantic = {field: getattr(evidence, field) for field in evidence.__dataclass_fields__ if field not in {"evidence_hash", "created_at"}}
            semantic.update(changes)
            result.append(replace(evidence, **changes, evidence_hash=stable_hash(semantic)))
        return tuple(result)


@dataclass(frozen=True, slots=True)
class GBDTMeanProbabilityExplanationProvider:
    """Component-wise probability SHAP for the fixed equal-weight ensemble."""

    descriptor: ProviderDescriptor
    model_id: str
    model_version: str
    adapter_version: str

    def __post_init__(self) -> None:
        if self.descriptor.provider_kind != "local_explanation" or self.model_id != "gbdt_mean":
            raise ValueError("GBDT Mean explanation provider identity is invalid.")

    def explain(self, *, loaded_model_version: Any, prediction_batch: Any, row_id: str, explanation_context: TrustedExplanationContext | None = None) -> Any:
        if not isinstance(explanation_context, TrustedExplanationContext):
            raise ValueError("GBDT Mean probability explanation requires trusted background context.")
        return self.explain_batch(loaded_model_version=loaded_model_version, prediction_batch=prediction_batch, row_ids=(row_id,), explanation_context=explanation_context)[0]

    def explain_batch(self, *, loaded_model_version: Any, prediction_batch: Any, row_ids: tuple[str, ...], explanation_context: TrustedExplanationContext) -> tuple[Any, ...]:
        import numpy as np
        import pandas as pd
        import shap
        from komus_risk.application.local_explanation import LocalExplanationEvidence, LocalFeatureContribution

        metadata = loaded_model_version.metadata
        if not isinstance(explanation_context, TrustedExplanationContext):
            raise ValueError("GBDT Mean probability explanation requires trusted background context.")
        summary = loaded_model_version.summary
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("model_id") != self.model_id
            or summary.model_id != self.model_id
            or metadata.get("model_version") != summary.model_version
            or metadata.get("experiment_artifact_id") != summary.experiment_artifact_id
        ):
            raise ValueError("GBDT Mean explanation model identity is invalid.")
        columns, specs, dataset = tuple(metadata.get("feature_columns", ())), metadata.get("feature_specs"), metadata.get("dataset_contract")
        if (not row_ids or len(row_ids) != len(set(row_ids)) or not columns or not isinstance(specs, list) or len(specs) != len(columns) or not isinstance(dataset, Mapping)):
            raise ValueError("GBDT Mean trusted explanation context does not match model binding.")
        records = {row.row_id: (row, values) for row, values in zip(prediction_batch.rows, prediction_batch.validated_feature_values, strict=True)}
        if len(records) != len(prediction_batch.rows) or set(row_ids) - set(records):
            raise ValueError("Explanation batch row IDs do not match the prediction batch.")
        selected = tuple(records[row_id] for row_id in row_ids)
        if explanation_context.source_kind == "oof_fold":
            _validate_oof_context_binding(
                metadata=metadata, context=explanation_context,
                prediction_batch=prediction_batch,
                selected_rows=tuple(row for row, _ in selected),
                expected_model_version_id=summary.model_version_id,
            )
        else:
            _validate_model_version_context_binding(
                metadata=metadata, context=explanation_context,
                prediction_batch=prediction_batch,
                expected_model_version_id=summary.model_version_id,
            )
        x = np.asarray([values for _, values in selected], dtype=float)
        background = np.asarray(explanation_context.background_values, dtype=float)
        if x.shape != (len(selected), len(columns)) or background.shape != (len(explanation_context.background_values), len(columns)) or not np.isfinite(x).all() or not np.isfinite(background).all():
            raise ValueError("GBDT Mean trusted background values are invalid.")

        def component_model(component_id: str):
            def predict(matrix: np.ndarray) -> np.ndarray:
                frame = pd.DataFrame(np.asarray(matrix, dtype=float), columns=columns)
                return np.asarray(loaded_model_version.predictor.component_positive_probabilities(frame)[component_id], dtype=float)
            return predict

        frame = pd.DataFrame(x, columns=columns)
        component_probabilities = loaded_model_version.predictor.component_positive_probabilities(frame)
        ensemble = np.asarray(loaded_model_version.predictor.predict_positive_proba(frame), dtype=float)
        stacked = np.asarray([component_probabilities[component] for component in _COMPONENT_IDS], dtype=float)
        displayed = np.asarray([row.probability for row, _ in selected], dtype=float)
        if not np.isclose(stacked.mean(axis=0), ensemble, rtol=1e-9, atol=1e-12).all() or not np.isclose(ensemble, displayed, rtol=1e-9, atol=1e-12).all():
            raise ValueError("GBDT Mean predictor does not reproduce displayed probability.")
        component_bases, component_shap = [], []
        for component in _COMPONENT_IDS:
            explained = shap.Explainer(component_model(component), background, algorithm="permutation", seed=_GBDT_MEAN_PERMUTATION_SEED)(x, max_evals=2 * len(columns) * _GBDT_MEAN_PERMUTATIONS + 1, silent=True)
            values = np.asarray(explained.values, dtype=float)
            bases = np.asarray(explained.base_values, dtype=float).reshape(-1)
            if values.shape != x.shape or bases.shape != (len(selected),) or not np.isfinite(values).all() or not np.isfinite(bases).all() or not np.isclose(bases + values.sum(axis=1), component_probabilities[component], rtol=1e-8, atol=1e-10).all():
                raise ValueError("GBDT Mean component probability SHAP reconstruction failed.")
            component_bases.append(bases)
            component_shap.append(values)
        bases = np.mean(np.asarray(component_bases), axis=0)
        shap_values = np.mean(np.asarray(component_shap), axis=0)
        if not np.isclose(bases + shap_values.sum(axis=1), ensemble, rtol=1e-8, atol=1e-10).all():
            raise ValueError("GBDT Mean probability SHAP does not reconstruct displayed probability.")
        provenance = {"source_kind": explanation_context.source_kind, "source_artifact_id": explanation_context.source_artifact_id, "model_binding_id": explanation_context.model_binding_id, "background_policy_id": explanation_context.background_policy_id, "background_hash": explanation_context.background_hash, "background_row_positions": list(explanation_context.background_row_positions), "validation_row_positions": list(explanation_context.validation_row_positions), "final_test_row_positions": list(explanation_context.final_test_row_positions), "fold_id": explanation_context.fold_id, "feature_binding_hash": metadata.get("feature_set_hash"), "output_space": "probability", "method": "component_shap_permutation_probability_mean", "method_version": shap.__version__, "permutation_count": _GBDT_MEAN_PERMUTATIONS, "seed": _GBDT_MEAN_PERMUTATION_SEED, "component_model_ids": list(_COMPONENT_IDS), "weights": [1 / 3, 1 / 3, 1 / 3]}
        evidence = []
        for row_index, (row, _) in enumerate(selected):
            contributions = []
            for index, column in enumerate(columns):
                spec = specs[index]
                if not isinstance(spec, Mapping) or spec.get("column_name") != column or not isinstance(spec.get("feature_id"), str):
                    raise ValueError("GBDT Mean feature binding is invalid.")
                value = float(shap_values[row_index, index])
                contributions.append(LocalFeatureContribution(spec["feature_id"], column, float(x[row_index, index]), value, 0, spec.get("display_name_ru"), spec.get("description_ru"), "increases_output" if value > 0 else "decreases_output" if value < 0 else "neutral"))
            contributions.sort(key=lambda item: (-abs(item.shap_value), columns.index(item.column_name)))
            features = tuple(LocalFeatureContribution(item.feature_id, item.column_name, item.raw_value, item.shap_value, rank, item.display_name_ru, item.description_ru, item.direction) for rank, item in enumerate(contributions, 1))
            payload = {"evidence_version": "local_explanation_v2", "model_version_id": loaded_model_version.summary.model_version_id, "experiment_artifact_id": metadata["experiment_artifact_id"], "dataset_id": dataset["dataset_id"], "dataset_fingerprint": dataset["dataset_fingerprint"], "feature_set_hash": metadata["feature_set_hash"], "model_id": self.model_id, "model_version": metadata["model_version"], "row_id": row.row_id, "identifier_column": prediction_batch.identifier_column, "identifier_value": row.identifier_value, "probability": float(ensemble[row_index]), "shap_output_space": "probability", "raw_model_output": float(ensemble[row_index]), "base_value": float(bases[row_index]), "features": features, "explainer_id": self.descriptor.provider_id, "explainer_version": self.descriptor.provider_version, "source_kind": explanation_context.source_kind, "source_artifact_id": explanation_context.source_artifact_id, "model_binding_id": explanation_context.model_binding_id, "object_id": row.row_id, "prediction_probability": float(ensemble[row_index]), "explanation_method_id": "component_shap_permutation_probability_mean", "explanation_method_version": shap.__version__, "output_space": "probability", "explained_output_value": float(ensemble[row_index]), "provider_id": self.descriptor.provider_id, "provider_version": self.descriptor.provider_version, "provenance": provenance}
            evidence.append(LocalExplanationEvidence(**payload, created_at=datetime.now(timezone.utc).isoformat(), evidence_hash=stable_hash(payload)))
        return tuple(evidence)
