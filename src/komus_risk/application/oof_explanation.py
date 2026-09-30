"""Local explanations bound to the exact persisted OOF fold predictor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from komus_risk.artifacts import ExperimentArtifactStore, LoadedOOFFoldModel
from komus_risk.model_platform import ModelPluginRegistry, TrustedExplanationContext

from .local_explanation import LocalExplanationEvidence
from .model_inference import PredictionBatch, PredictionRow
from .oof_result import OOFResultError, _load_oof_object


class OOFExplanationError(ValueError):
    """Stable fail-closed errors for the OOF local-explanation boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
