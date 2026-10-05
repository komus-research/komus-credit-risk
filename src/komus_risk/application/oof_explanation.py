"""Local explanations bound to the exact persisted OOF fold predictor."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any

import numpy as np
import pandas as pd

from komus_risk.artifacts import ExperimentArtifactStore, LoadedOOFFoldModel
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import ModelPluginRegistry, TrustedExplanationContext
from komus_risk.model_platform.explainability import OOFPredictionReplayMismatch

from .local_explanation import LocalExplanationEvidence
from .local_explanation import NATIVE_SHAP_NUMERICAL_PROFILES
from .global_oof_operation import (
    GlobalOOFDerivedStore,
    GlobalOOFOperationFailed,
    GlobalOOFOperationService,
)
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
        global_operation_service: GlobalOOFOperationService | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.model_plugin_registry = model_plugin_registry
        self.global_operation_service = global_operation_service or GlobalOOFOperationService(
            GlobalOOFDerivedStore(artifact_store.root)
        )
        self._global_operation_identity_lock = threading.RLock()
        self._global_operation_identity_cache: dict[str, tuple[str, dict[str, Any], int, int]] = {}

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
        """Return exact, persisted row-weighted SHAP aggregation for every OOF row."""
        spec = self._global_operation_spec(artifact_id)
        _, context, identity, derivation_key, folds, compute = spec
        self._remember_global_operation_identity(artifact_id, derivation_key, identity, len(context.scores), len(folds))
        try:
            return self.global_operation_service.get_or_run(
                artifact_id=artifact_id, derivation_key=derivation_key, identity=identity,
                total_rows=len(context.scores), total_folds=len(folds), compute=compute,
            )
        except OOFExplanationError:
            raise
        except GlobalOOFOperationFailed as error:
            raise OOFExplanationError(error.code) from error
        except ValueError as error:
            code = str(error)
            safe_code = code if code.startswith("GLOBAL_OOF_") or code == "OOF_PREDICTION_MISMATCH" else "GLOBAL_OOF_EXPLANATION_FAILED"
            raise OOFExplanationError(safe_code) from error

    def start_global_oof(self, artifact_id: str):
        """Start or join one asynchronous derivation attempt for future run APIs."""
        _, context, identity, key, folds, compute = self._global_operation_spec(artifact_id)
        self._remember_global_operation_identity(artifact_id, key, identity, len(context.scores), len(folds))
        return self.global_operation_service.start(
            artifact_id=artifact_id, derivation_key=key, identity=identity,
            total_rows=len(context.scores), total_folds=len(folds), compute=compute,
        )

    def retry_global_oof(self, artifact_id: str):
        """Explicitly create one successor attempt for a failed derivation."""
        _, context, identity, key, folds, compute = self._global_operation_spec(artifact_id)
        self._remember_global_operation_identity(artifact_id, key, identity, len(context.scores), len(folds))
        with self._global_operation_identity_lock:
            snapshot = self.global_operation_service.status(
                key, artifact_id=artifact_id, identity=identity,
                total_rows=len(context.scores), total_folds=len(folds),
            )
            if snapshot.status == "FAILED":
                self.global_operation_service.retry(key)
                return self.global_operation_service.start(
                    artifact_id=artifact_id, derivation_key=key, identity=identity,
                    total_rows=len(context.scores), total_folds=len(folds), compute=compute,
                )
            if snapshot.status == "NOT_STARTED":
                return self.global_operation_service.start(
                    artifact_id=artifact_id, derivation_key=key, identity=identity,
                    total_rows=len(context.scores), total_folds=len(folds), compute=compute,
                )
            return snapshot

    def global_oof_status(self, artifact_id: str):
        """Read process-local progress or persisted READY state without starting work."""
        key, identity, total_rows, total_folds = self._resolved_global_operation_identity(artifact_id)
        return self.global_operation_service.status(
            key, artifact_id=artifact_id, identity=identity,
            total_rows=total_rows, total_folds=total_folds,
        )

    def global_oof_ready_result(self, artifact_id: str) -> GlobalOOFExplanation:
        """Read a validated READY result; fail when the derivation has not completed."""
        key, identity, total_rows, total_folds = self._resolved_global_operation_identity(artifact_id)
        status = self.global_operation_service.status(
            key, artifact_id=artifact_id, identity=identity,
            total_rows=total_rows, total_folds=total_folds,
        )
        if status.status != "READY":
            raise OOFExplanationError("GLOBAL_OOF_RESULT_NOT_READY")
        try:
            return self.global_operation_service.wait_result(key, timeout=0)
        except (ValueError, TimeoutError) as error:
            raise OOFExplanationError(str(error)) from error

    def _resolved_global_operation_identity(self, artifact_id):
        with self._global_operation_identity_lock:
            cached = self._global_operation_identity_cache.get(artifact_id)
            if cached is not None:
                return cached
            _, context, identity, key, folds, _ = self._global_operation_spec(artifact_id)
            resolved = (key, identity, len(context.scores), len(folds))
            self._global_operation_identity_cache[artifact_id] = resolved
            return resolved

    def _remember_global_operation_identity(self, artifact_id, key, identity, total_rows, total_folds):
        with self._global_operation_identity_lock:
            self._global_operation_identity_cache[artifact_id] = (key, identity, total_rows, total_folds)

    def _global_operation_spec(self, artifact_id):
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
            plugin, persistence_provider, explanation_provider = self._providers(artifact)
        except OOFExplanationError as error:
            if error.code == "LOCAL_OOF_EXPLANATION_UNSUPPORTED":
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_UNSUPPORTED") from error
            raise

        configured_folds = tuple(range(1, artifact.config.folds + 1))
        present_folds = tuple(sorted({int(value) for value in context.folds}))
        if present_folds != configured_folds:
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        aggregate = getattr(explanation_provider, "aggregate_oof_chunk", None)
        if not callable(aggregate) or artifact.config.model_id not in NATIVE_SHAP_NUMERICAL_PROFILES:
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_UNSUPPORTED")
        binding_ids = self._fold_binding_ids(artifact, configured_folds)
        background_contexts = {
            fold_number: self._trusted_background(artifact, context, fold_number, binding_id)
            for fold_number, binding_id in zip(configured_folds, binding_ids, strict=True)
        }
        fold_background_hashes = [
            [fold_number, background_contexts[fold_number].background_hash]
            for fold_number in configured_folds
        ]
        descriptor = explanation_provider.descriptor
        profile = NATIVE_SHAP_NUMERICAL_PROFILES[artifact.config.model_id]
        identity = {
            "artifact_id": artifact.artifact_id,
            "row_count": len(context.scores),
            "aggregation_method_id": "sum_absolute_shap",
            "aggregation_method_version": "1",
            "provider_id": descriptor.provider_id,
            "provider_version": descriptor.provider_version,
            "explanation_method_id": descriptor.provider_id,
            "explanation_method_version": descriptor.provider_version,
            "feature_binding_hash": artifact.config.feature_set_hash,
            "feature_count": len(evidence.feature_ids),
            "feature_ids": list(evidence.feature_ids),
            "feature_columns": list(evidence.feature_columns),
            "fold_model_binding_ids": list(binding_ids),
            "fold_background_hashes": fold_background_hashes,
            "output_space": "raw_margin",
            "background_policy_id": "outer_train_hash_top128_v1",
            "numerical_validation_profile_id": profile.profile_id,
            "numerical_validation_profile_version": profile.version,
            "chunk_implementation_policy": "global_oof_chunk_2048_v1",
        }
        derivation_key = stable_hash(identity)

        def compute(attempt_token, progress):
            try:
                return self._compute_global_chunks(
                    artifact=artifact, context=context, folds=configured_folds,
                    persistence_provider=persistence_provider,
                    explanation_provider=explanation_provider,
                    background_contexts=background_contexts, progress=progress,
                )
            except OOFExplanationError as error:
                raise GlobalOOFOperationFailed(error.code) from error

        return artifact, context, identity, derivation_key, configured_folds, compute

    def _fold_binding_ids(self, artifact, folds):
        result = []
        try:
            for fold in folds:
                fold_dir = self.artifact_store.experiments / artifact.artifact_id / "fold_models" / f"fold-{fold:03d}"
                metadata = self.artifact_store._read_json(fold_dir / "metadata.json")
                result.append(self.artifact_store._oof_fold_binding_id(artifact_id=artifact.artifact_id, metadata=metadata))
        except Exception as error:
            raise OOFExplanationError("FOLD_MODEL_UNAVAILABLE") from error
        return tuple(result)

    def _compute_global_chunks(self, *, artifact, context, folds, persistence_provider,
                               explanation_provider, background_contexts, progress):
        evidence = artifact.run_output.oof_evidence
        assert evidence is not None
        feature_count = len(evidence.feature_ids)
        totals = np.zeros(feature_count, dtype=np.float64)
        covered = np.zeros(len(context.scores), dtype=np.uint8)
        binding_ids = []
        common = None
        processed = 0
        for fold_number in folds:
            indices = np.flatnonzero(context.folds == fold_number)
            if len(indices) == 0:
                raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
            progress(fold_number, processed)
            try:
                fold_model = self.artifact_store.load_oof_fold_model(artifact.artifact_id, fold_number, provider=persistence_provider)
            except (OSError, ValueError) as error:
                raise OOFExplanationError("FOLD_MODEL_UNAVAILABLE") from error
            if fold_model.fold_number != fold_number or not fold_model.model_binding_id:
                raise OOFExplanationError("PROVENANCE_MISMATCH")
            binding_ids.append(fold_model.model_binding_id)
            if tuple(binding_ids) != tuple(self._fold_binding_ids(artifact, folds)[:len(binding_ids)]):
                raise OOFExplanationError("PROVENANCE_MISMATCH")
            runtime = self._runtime(artifact, fold_model)
            background = background_contexts[fold_number]
            if background.model_binding_id != fold_model.model_binding_id:
                raise OOFExplanationError("PROVENANCE_MISMATCH")
            for offset in range(0, len(indices), 2048):
                chunk_indices = indices[offset:offset + 2048]
                positions = tuple(int(context.row_positions[index]) for index in chunk_indices)
                matrix = np.asarray(evidence.model_input[chunk_indices], dtype=float)
                frame = pd.DataFrame(matrix, columns=evidence.feature_columns, dtype=float)
                values = tuple(tuple(float(value) for value in row) for row in matrix)
                batch = PredictionBatch(
                    model_version_id=runtime.summary.model_version_id,
                    source_sha256=artifact.artifact_id,
                    identifier_column=artifact.dataset_contract.identifier_column,
                    required_feature_columns=tuple(evidence.feature_columns),
                    rows=tuple(PredictionRow(
                        row_id=OOFResultService._object_id(context, int(index)),
                        source_row_position=int(context.row_positions[index]),
                        identifier_value=context.identifiers[index],
                        probability=float(context.scores[index]),
                    ) for index in chunk_indices),
                    ignored_columns=(), validated_feature_values=values,
                )
                try:
                    aggregate = explanation_provider.aggregate_oof_chunk(
                        loaded_model_version=runtime, prediction_batch=batch,
                        feature_matrix=frame, persisted_oof_probabilities=context.scores[chunk_indices],
                        row_positions=positions, explanation_context=background,
                    )
                except OOFPredictionReplayMismatch as error:
                    raise OOFExplanationError("OOF_PREDICTION_MISMATCH") from error
                except (TypeError, ValueError, KeyError, AttributeError) as error:
                    raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE") from error
                signature = (aggregate.provider_id, aggregate.provider_version, aggregate.explanation_method_id,
                    aggregate.explanation_method_version, aggregate.output_space, aggregate.aggregation_method_id,
                    aggregate.aggregation_method_version, aggregate.numerical_validation_profile_id,
                    aggregate.numerical_validation_profile_version)
                if (aggregate.row_count != len(chunk_indices) or len(aggregate.sum_abs_shap) != feature_count
                        or aggregate.model_binding_id != fold_model.model_binding_id
                        or aggregate.feature_binding_hash != artifact.config.feature_set_hash
                        or aggregate.background_policy_id != background.background_policy_id
                        or aggregate.background_hash != background.background_hash
                        or any(not np.isfinite(value) or value < 0 for value in aggregate.sum_abs_shap)
                        or (common is not None and signature != common)):
                    raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
                common = signature
                totals += np.asarray(aggregate.sum_abs_shap, dtype=np.float64)
                if np.any(covered[chunk_indices]):
                    raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
                covered[chunk_indices] = 1
                processed += aggregate.row_count
                progress(fold_number, processed)
                del frame, matrix, values, batch, aggregate
        if (not np.all(covered == 1) or processed != len(context.scores) or common is None):
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        means = totals / len(context.scores)
        order = sorted(range(feature_count), key=lambda index: (-float(means[index]), index))
        features = tuple(GlobalOOFFeatureImportance(evidence.feature_ids[i], evidence.feature_columns[i], float(means[i]), rank)
                         for rank, i in enumerate(order, 1))
        (provider_id, provider_version, method_id, method_version, output_space,
         aggregation_id, aggregation_version, profile_id, profile_version) = common
        payload = {
            "artifact_id": artifact.artifact_id, "model_id": artifact.config.model_id,
            "model_version": artifact.config.model_version, "row_count": len(context.scores),
            "feature_count": feature_count, "output_space": output_space,
            "provider_id": provider_id, "provider_version": provider_version,
            "explanation_method_id": method_id, "explanation_method_version": method_version,
            "background_policy_id": background.background_policy_id,
            "feature_binding_hash": artifact.config.feature_set_hash,
            "fold_model_binding_ids": binding_ids,
            "fold_background_hashes": [
                [fold, background_contexts[fold].background_hash] for fold in folds
            ],
            "aggregation_method_id": aggregation_id, "aggregation_method_version": aggregation_version,
            "numerical_validation_profile_id": profile_id, "numerical_validation_profile_version": profile_version,
            "features": [(item.feature_id, item.column_name, item.mean_abs_shap, item.rank) for item in features],
        }
        return GlobalOOFExplanation(
            artifact_id=artifact.artifact_id, model_id=artifact.config.model_id,
            model_version=artifact.config.model_version, row_count=len(context.scores), feature_count=feature_count,
            output_space=output_space, provider_id=provider_id, provider_version=provider_version,
            explanation_method_id=method_id, explanation_method_version=method_version,
            background_policy_id="outer_train_hash_top128_v1", feature_binding_hash=artifact.config.feature_set_hash,
            fold_model_binding_ids=tuple(binding_ids), features=features, evidence_hash=stable_hash(payload),
        )

    @staticmethod
    def _trusted_background(artifact, context, fold_number, binding_id):
        evidence = artifact.run_output.oof_evidence
        assert evidence is not None
        policy = "outer_train_hash_top128_v1"
        final_test: set[int] = set()
        candidates = []
        for index, (position, fold) in enumerate(zip(context.row_positions, context.folds, strict=True)):
            position = int(position)
            if int(fold) != fold_number and position not in final_test:
                digest = stable_hash({"policy_id": policy, "source_artifact_id": artifact.artifact_id,
                    "model_binding_id": binding_id, "fold_id": str(fold_number), "row_position": position})
                candidates.append((digest, index, position))
        selected = sorted(candidates)[:128]
        if not selected:
            raise OOFExplanationError("GLOBAL_OOF_EXPLANATION_INCOMPATIBLE")
        from komus_risk.model_platform import TrustedExplanationContext
        return TrustedExplanationContext(
            source_kind="oof_fold", source_artifact_id=artifact.artifact_id, model_binding_id=binding_id,
            feature_columns=tuple(evidence.feature_columns),
            background_values=tuple(tuple(float(value) for value in evidence.model_input[index]) for _, index, _ in selected),
            background_row_positions=tuple(position for _, _, position in selected),
            background_policy_id=policy, validation_row_positions=tuple(int(context.row_positions[i]) for i in np.flatnonzero(context.folds == fold_number)),
            final_test_row_positions=tuple(final_test), fold_id=str(fold_number),
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
