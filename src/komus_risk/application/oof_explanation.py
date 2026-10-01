"""Local explanations bound to the exact persisted OOF fold predictor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from komus_risk.artifacts import ExperimentArtifactStore, LoadedOOFFoldModel
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import ModelPluginRegistry, TrustedExplanationContext

from .local_explanation import LocalExplanationEvidence
from .model_inference import PredictionBatch, PredictionRow
from .oof_result import OOFResultError, OOFResultService, _load_oof_context, _load_oof_object


class OOFExplanationError(ValueError):
    """Stable fail-closed errors for the OOF local-explanation boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class GlobalOOFFeatureImportance:
    """One canonical predictor's row-weighted OOF SHAP magnitude."""

    feature_id: str
    column_name: str
    mean_abs_shap: float
    rank: int


@dataclass(frozen=True, slots=True)
class GlobalOOFExplanation:
    """Deterministic aggregate of validated local OOF explanations."""

    artifact_id: str
    model_id: str
    model_version: str
    row_count: int
    feature_count: int
    output_space: str
    provider_id: str
    provider_version: str
    explanation_method_id: str
    explanation_method_version: str
    background_policy_id: str
    feature_binding_hash: str
    fold_model_binding_ids: tuple[str, ...]
    features: tuple[GlobalOOFFeatureImportance, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class _OOFFoldRuntimeSummary:
    """Private, non-persisted carrier accepted by explanation providers."""

    model_version_id: str
    experiment_artifact_id: str
    model_id: str
    model_version: str
    feature_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OOFFoldRuntime:
    """Structural runtime adapter; it is never a ModelVersion."""

    summary: _OOFFoldRuntimeSummary
    metadata: dict[str, Any]
    predictor: Any


class OOFExplanationService:
    """Recovers, replays and explains the exact fold that scored one OOF row."""

    def __init__(
        self,
        artifact_store: ExperimentArtifactStore,
        model_plugin_registry: ModelPluginRegistry,
    ) -> None:
        self.artifact_store = artifact_store
        self.model_plugin_registry = model_plugin_registry

    def local(self, artifact_id: str, object_id: str) -> LocalExplanationEvidence:
        """Return V2 evidence for one canonical Result V2 object identity."""
        try:
            resolved = _load_oof_object(self.artifact_store, artifact_id, object_id)
        except OOFResultError as error:
            raise OOFExplanationError(error.code) from error

        context = resolved.context
        artifact = context.artifact
        evidence = artifact.run_output.oof_evidence
        if (
            artifact.manifest.get("artifact_schema_version") != "3"
            or evidence is None
            or evidence.model_input.shape != (len(context.scores), len(evidence.feature_columns))
        ):
            raise OOFExplanationError("OOF_RESULT_EVIDENCE_INCOMPLETE")

        fold_number = int(context.folds[resolved.index])
        plugin, persistence_provider, explanation_provider = self._providers(artifact)
        try:
            fold_model = self.artifact_store.load_oof_fold_model(
                artifact.artifact_id, fold_number, provider=persistence_provider
            )
        except (OSError, ValueError) as error:
            raise OOFExplanationError("FOLD_MODEL_UNAVAILABLE") from error

        if fold_model.fold_number != fold_number:
            raise OOFExplanationError("PROVENANCE_MISMATCH")
        runtime = self._runtime(artifact, fold_model)
        batch = self._prediction_batch(resolved.index, resolved.object_id, context, runtime)
        self._replay(runtime, batch, float(context.scores[resolved.index]))

        try:
            explanation_context = TrustedExplanationContext.from_oof_evidence(
                source_artifact_id=artifact.artifact_id,
                model_binding_id=fold_model.model_binding_id,
                feature_columns=evidence.feature_columns,
                model_input_values=tuple(
                    tuple(float(value) for value in row)
                    for row in evidence.model_input
                ),
                row_positions=tuple(int(value) for value in context.row_positions),
                fold_assignments=tuple(int(value) for value in context.folds),
                validation_fold=fold_number,
                validation_row_position=int(context.row_positions[resolved.index]),
            )
            returned = explanation_provider.explain_batch(
                loaded_model_version=runtime,
                prediction_batch=batch,
                row_ids=(resolved.object_id,),
                explanation_context=explanation_context,
            )
        except (TypeError, ValueError, KeyError) as error:
            raise OOFExplanationError("PROVENANCE_MISMATCH") from error
        if not isinstance(returned, tuple) or len(returned) != 1:
            raise OOFExplanationError("PROVENANCE_MISMATCH")
        local = returned[0]
        if not isinstance(local, LocalExplanationEvidence) or not self._matches(
            local=local,
            artifact_id=artifact.artifact_id,
            object_id=resolved.object_id,
            probability=float(context.scores[resolved.index]),
            binding_id=fold_model.model_binding_id,
            fold_number=fold_number,
        ):
            raise OOFExplanationError("PROVENANCE_MISMATCH")
        return local

    def global_oof(self, artifact_id: str) -> GlobalOOFExplanation:
        """Explain every OOF row with its persisted fold predictor and aggregate.

        The result is exactly ``sum(abs(local_shap)) / OOF row count`` for
        each saved predictor feature; folds are never averaged as units.
        """
        try:
            context = _load_oof_context(self.artifact_store, artifact_id)
        except OOFResultError as error:
            raise OOFExplanationError(error.code) from error
        artifact, evidence = context.artifact, context.artifact.run_output.oof_evidence
        if (
            artifact.manifest.get("artifact_schema_version") != "3"
            or evidence is None
            or evidence.model_input.shape != (len(context.scores), len(evidence.feature_columns))
            or tuple(evidence.feature_ids) != tuple(artifact.config.feature_ids)
            or len(evidence.feature_ids) != len(set(evidence.feature_ids))
            or len(evidence.feature_columns) != len(set(evidence.feature_columns))
            or len(evidence.feature_ids) != len(evidence.feature_columns)
        ):
            raise OOFExplanationError("OOF_RESULT_EVIDENCE_INCOMPLETE")
        try:
            _, persistence_provider, explanation_provider = self._providers(artifact)
        except OOFExplanationError as error:
            if error.code == "LOCAL_OOF_EXPLANATION_UNSUPPORTED":
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_UNSUPPORTED") from error
            raise

        configured_folds = tuple(range(1, artifact.config.folds + 1))
        present_folds = tuple(sorted({int(value) for value in context.folds}))
        if present_folds != configured_folds:
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")

        totals = np.zeros(len(evidence.feature_columns), dtype=float)
        explained_indices: set[int] = set()
        binding_ids: list[str] = []
        background_hashes: list[tuple[int, str]] = []
        common: tuple[str, str, str, str, str] | None = None
        for fold_number in configured_folds:
            indices = tuple(int(index) for index in np.flatnonzero(context.folds == fold_number))
            if not indices:
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
            try:
                fold_model = self.artifact_store.load_oof_fold_model(
                    artifact.artifact_id, fold_number, provider=persistence_provider
                )
            except (OSError, ValueError) as error:
                raise OOFExplanationError("FOLD_MODEL_UNAVAILABLE") from error
            if fold_model.fold_number != fold_number or not fold_model.model_binding_id:
                raise OOFExplanationError("PROVENANCE_MISMATCH")
            runtime = self._runtime(artifact, fold_model)
            batch = self._prediction_batch_for_indices(indices, context, runtime)
            self._replay_batch(runtime, batch, context.scores[list(indices)])
            try:
                explanation_context = TrustedExplanationContext.from_oof_evidence(
                    source_artifact_id=artifact.artifact_id,
                    model_binding_id=fold_model.model_binding_id,
                    feature_columns=evidence.feature_columns,
                    model_input_values=tuple(tuple(float(value) for value in row) for row in evidence.model_input),
                    row_positions=tuple(int(value) for value in context.row_positions),
                    fold_assignments=tuple(int(value) for value in context.folds),
                    validation_fold=fold_number,
                    validation_row_position=int(context.row_positions[indices[0]]),
                )
                row_ids = tuple(batch_row.row_id for batch_row in batch.rows)
                returned = explanation_provider.explain_batch(
                    loaded_model_version=runtime,
                    prediction_batch=batch,
                    row_ids=row_ids,
                    explanation_context=explanation_context,
                )
            except (TypeError, ValueError, KeyError) as error:
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE") from error
            if not isinstance(returned, tuple) or len(returned) != len(indices):
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
            returned_by_id = {getattr(item, "object_id", None): item for item in returned}
            if len(returned_by_id) != len(returned) or set(returned_by_id) != set(row_ids):
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
            for index, row_id in zip(indices, row_ids, strict=True):
                local = returned_by_id[row_id]
                identity = self._validate_global_local(
                    local=local,
                    artifact=artifact,
                    object_id=row_id,
                    probability=float(context.scores[index]),
                    binding_id=fold_model.model_binding_id,
                    fold_number=fold_number,
                    feature_ids=tuple(evidence.feature_ids),
                    feature_columns=tuple(evidence.feature_columns),
                    background_policy_id=explanation_context.background_policy_id,
                )
                if common is None:
                    common = identity
                elif common != identity:
                    raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
                by_feature = {item.feature_id: item for item in local.features}
                totals += np.asarray(
                    [abs(float(by_feature[feature_id].shap_value)) for feature_id in evidence.feature_ids],
                    dtype=float,
                )
                if index in explained_indices:
                    raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
                explained_indices.add(index)
            binding_ids.append(fold_model.model_binding_id)
            background_hashes.append((fold_number, explanation_context.background_hash))

        if (
            len(explained_indices) != len(context.scores)
            or len(binding_ids) != len(configured_folds)
            or len(set(binding_ids)) != len(binding_ids)
            or common is None
        ):
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        provider_id, provider_version, method_id, method_version, output_space = common
        values = totals / len(context.scores)
        ordered = sorted(range(len(values)), key=lambda index: (-float(values[index]), index))
        ranks = {index: rank for rank, index in enumerate(ordered, start=1)}
        features = tuple(
            GlobalOOFFeatureImportance(
                feature_id=evidence.feature_ids[index],
                column_name=evidence.feature_columns[index],
                mean_abs_shap=float(values[index]),
                rank=ranks[index],
            )
            for index in ordered
        )
        semantic = {
            "artifact_id": artifact.artifact_id,
            "model_id": artifact.config.model_id,
            "model_version": artifact.config.model_version,
            "row_count": len(context.scores),
            "feature_count": len(features),
            "output_space": output_space,
            "provider_id": provider_id,
            "provider_version": provider_version,
            "explanation_method_id": method_id,
            "explanation_method_version": method_version,
            "background_policy_id": "outer_train_hash_top128_v1",
            "feature_binding_hash": artifact.config.feature_set_hash,
            "fold_model_binding_ids": binding_ids,
            "fold_background_hashes": background_hashes,
            "features": [(item.feature_id, item.column_name, item.mean_abs_shap, item.rank) for item in features],
        }
        return GlobalOOFExplanation(
            artifact_id=artifact.artifact_id, model_id=artifact.config.model_id,
            model_version=artifact.config.model_version, row_count=len(context.scores),
            feature_count=len(features), output_space=output_space, provider_id=provider_id,
            provider_version=provider_version, explanation_method_id=method_id,
            explanation_method_version=method_version,
            background_policy_id="outer_train_hash_top128_v1",
            feature_binding_hash=artifact.config.feature_set_hash,
            fold_model_binding_ids=tuple(binding_ids), features=features,
            evidence_hash=stable_hash(semantic),
        )

    def _providers(self, artifact):
        try:
            plugin = self.model_plugin_registry.get(artifact.config.model_id)
        except (KeyError, ValueError) as error:
            raise OOFExplanationError("LOCAL_OOF_EXPLANATION_UNSUPPORTED") from error
        if (
            plugin.spec.model_id != artifact.config.model_id
            or plugin.spec.version != artifact.config.model_version
            or artifact.configuration_record is None
            or plugin.spec.adapter_version != artifact.configuration_record.adapter_version
        ):
            raise OOFExplanationError("PROVENANCE_MISMATCH")
        explanation_registry = self.model_plugin_registry.explanation_providers
        if explanation_registry is None or plugin.local_explanation_provider is None:
            raise OOFExplanationError("LOCAL_OOF_EXPLANATION_UNSUPPORTED")
        persistence_registry = self.model_plugin_registry.persistence_providers
        if persistence_registry is None or plugin.persistence_provider is None:
            raise OOFExplanationError("FOLD_MODEL_UNAVAILABLE")
        try:
            return (
                plugin,
                persistence_registry.validate_plugin_provider(plugin),
                explanation_registry.validate_plugin_provider(plugin),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise OOFExplanationError("PROVENANCE_MISMATCH") from error

    @staticmethod
    def _runtime(artifact, fold_model: LoadedOOFFoldModel) -> _OOFFoldRuntime:
        evidence = artifact.run_output.oof_evidence
        assert evidence is not None
        metadata = {
            "model_id": artifact.config.model_id,
            "model_version": artifact.config.model_version,
            "experiment_artifact_id": artifact.artifact_id,
            "feature_set_hash": artifact.config.feature_set_hash,
            "feature_columns": list(evidence.feature_columns),
            "feature_ids": list(evidence.feature_ids),
            # V3 binding owns only these fields.  No current registry/display
            # metadata is permitted to enrich an immutable OOF explanation.
            "feature_specs": [
                {"feature_id": feature_id, "column_name": column}
                for feature_id, column in zip(
                    evidence.feature_ids, evidence.feature_columns, strict=True
                )
            ],
            "dataset_contract": artifact.dataset_contract.to_dict(),
            "fold_model_binding_id": fold_model.model_binding_id,
            "fold_id": str(fold_model.fold_number),
        }
        return _OOFFoldRuntime(
            _OOFFoldRuntimeSummary(
                model_version_id=fold_model.model_binding_id,
                experiment_artifact_id=artifact.artifact_id,
                model_id=artifact.config.model_id,
                model_version=artifact.config.model_version,
                feature_ids=tuple(evidence.feature_ids),
            ),
            metadata,
            fold_model.predictor,
        )

    @staticmethod
    def _prediction_batch(index, object_id, context, runtime) -> PredictionBatch:
        evidence = context.artifact.run_output.oof_evidence
        assert evidence is not None
        values = tuple(float(value) for value in evidence.model_input[index])
        return PredictionBatch(
            model_version_id=runtime.summary.model_version_id,
            source_sha256=context.artifact.artifact_id,
            identifier_column=context.artifact.dataset_contract.identifier_column,
            required_feature_columns=tuple(evidence.feature_columns),
            rows=(
                PredictionRow(
                    row_id=object_id,
                    source_row_position=int(context.row_positions[index]),
                    identifier_value=context.identifiers[index],
                    probability=float(context.scores[index]),
                ),
            ),
            ignored_columns=(),
            validated_feature_values=(values,),
        )

    @staticmethod
    def _prediction_batch_for_indices(indices, context, runtime) -> PredictionBatch:
        evidence = context.artifact.run_output.oof_evidence
        assert evidence is not None
        return PredictionBatch(
            model_version_id=runtime.summary.model_version_id,
            source_sha256=context.artifact.artifact_id,
            identifier_column=context.artifact.dataset_contract.identifier_column,
            required_feature_columns=tuple(evidence.feature_columns),
            rows=tuple(
                PredictionRow(
                    row_id=OOFResultService._object_id(context, index),
                    source_row_position=int(context.row_positions[index]),
                    identifier_value=context.identifiers[index],
                    probability=float(context.scores[index]),
                ) for index in indices
            ),
            ignored_columns=(),
            validated_feature_values=tuple(
                tuple(float(value) for value in evidence.model_input[index]) for index in indices
            ),
        )

    @staticmethod
    def _replay(runtime, batch: PredictionBatch, expected: float) -> None:
        try:
            frame = pd.DataFrame(
                [batch.validated_feature_values[0]],
                columns=batch.required_feature_columns,
                dtype=float,
            )
            actual = np.asarray(runtime.predictor.predict_positive_proba(frame), dtype=float)
        except Exception as error:
            raise OOFExplanationError("OOF_PREDICTION_MISMATCH") from error
        if (
            actual.shape != (1,)
            or not np.isfinite(actual).all()
            or not np.isclose(float(actual[0]), expected, rtol=1e-12, atol=1e-12)
        ):
            raise OOFExplanationError("OOF_PREDICTION_MISMATCH")

    @staticmethod
    def _replay_batch(runtime, batch: PredictionBatch, expected) -> None:
        try:
            frame = pd.DataFrame(batch.validated_feature_values, columns=batch.required_feature_columns, dtype=float)
            actual = np.asarray(runtime.predictor.predict_positive_proba(frame), dtype=float)
            expected_values = np.asarray(expected, dtype=float)
        except Exception as error:
            raise OOFExplanationError("OOF_PREDICTION_MISMATCH") from error
        if (actual.shape != expected_values.shape or not np.isfinite(actual).all()
                or not np.isclose(actual, expected_values, rtol=1e-12, atol=1e-12).all()):
            raise OOFExplanationError("OOF_PREDICTION_MISMATCH")

    @staticmethod
    def _validate_global_local(*, local, artifact, object_id, probability, binding_id,
                               fold_number, feature_ids, feature_columns,
                               background_policy_id) -> tuple[str, str, str, str, str]:
        if (not isinstance(local, LocalExplanationEvidence)
                or not OOFExplanationService._matches(local=local, artifact_id=artifact.artifact_id,
                    object_id=object_id, probability=probability, binding_id=binding_id,
                    fold_number=fold_number)
                or local.model_id != artifact.config.model_id
                or local.model_version != artifact.config.model_version
                or local.feature_set_hash != artifact.config.feature_set_hash
                or not isinstance(local.provenance, Mapping)
                or local.provenance.get("feature_binding_hash", artifact.config.feature_set_hash)
                   != artifact.config.feature_set_hash
                or local.provenance.get("background_policy_id", background_policy_id)
                   != background_policy_id):
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        features = tuple(local.features)
        returned_ids = tuple(item.feature_id for item in features)
        returned_columns = tuple(item.column_name for item in features)
        canonical_bindings = dict(zip(feature_ids, feature_columns, strict=True))
        returned_bindings = {
            item.feature_id: item.column_name for item in features
        }
        if (
            len(features) != len(feature_ids)
            or len(set(returned_ids)) != len(returned_ids)
            or len(set(returned_columns)) != len(returned_columns)
            or set(returned_ids) != set(feature_ids)
            or set(returned_columns) != set(feature_columns)
            or returned_bindings != canonical_bindings
            or any(not np.isfinite(float(item.shap_value)) for item in features)
        ):
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        identity = (local.provider_id, local.provider_version,
                    local.explanation_method_id, local.explanation_method_version,
                    local.output_space)
        if any(not isinstance(value, str) or not value.strip() for value in identity):
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        return identity

    @staticmethod
    def _matches(
        *, local: LocalExplanationEvidence, artifact_id: str, object_id: str,
        probability: float, binding_id: str, fold_number: int,
    ) -> bool:
        provenance = local.provenance
        return (
            local.source_kind == "oof_fold"
            and local.source_artifact_id == artifact_id
            and local.object_id == object_id
            and local.row_id == object_id
            and local.model_binding_id == binding_id
            and np.isclose(local.prediction_probability, probability, rtol=1e-12, atol=1e-12)
            and np.isclose(local.probability, probability, rtol=1e-12, atol=1e-12)
            and isinstance(provenance, dict)
            and provenance.get("fold_id") == str(fold_number)
        )
