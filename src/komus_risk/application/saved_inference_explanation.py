"""Trusted local explanations for immutable saved inference Results."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from threading import RLock
from typing import Any

import numpy as np
import pandas as pd

from komus_risk.artifacts import (
    InferenceResultIntegrityError,
    InferenceResultNotFoundError,
    SavedInferenceObjectEvidence,
    SavedModelInferenceResultStore,
)
from komus_risk.hashing import stable_hash
from komus_risk.model_platform import TrustedExplanationContext

from .model_inference import PredictionBatch, PredictionRow
from .model_library_errors import (
    ModelSourceResultUnavailable,
    ModelVersionIntegrityError,
    ModelVersionNotFound,
)
from .saved_model_inference import SavedModelInferenceError


_REPLAY_RTOL = 1e-12
_REPLAY_ATOL = 1e-12
_CACHE_MAX_ENTRIES = 128


@dataclass(frozen=True, slots=True)
class SavedInferenceFeature:
    feature_id: str
    column_name: str
    display_name_ru: str | None
    description_ru: str | None
    raw_value: float


@dataclass(frozen=True, slots=True)
class SavedInferenceObjectDetail:
    inference_result_id: str
    model_version_id: str
    row_id: str
    source_row_position: int
    identifier_column: str
    identifier_display: str
    score: float
    threshold: float
    position: str
    features: tuple[SavedInferenceFeature, ...]
    capabilities: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SavedInferenceExplanation:
    inference_result_id: str
    model_version_id: str
    row_id: str
    explanation_id: str
    evidence_hash: str
    prediction_probability: float
    base_value: float
    explained_output_value: float
    output_space: str
    explanation_method_id: str
    explanation_method_version: str
    explanation_provider_id: str
    explanation_provider_version: str
    features: tuple[Any, ...]
    remainder: Any | None
    result_interpretation_capability: Any


class SavedInferenceExplanationService:
    """One-row orchestrator; it neither predicts a new Result nor reads uploads."""

    def __init__(
        self, *, result_store: SavedModelInferenceResultStore, model_library_service: Any,
        integration_workflow_service: Any, experiment_artifact_store: Any | None = None,
    ) -> None:
        self.result_store = result_store
        self.model_library_service = model_library_service
        self.integration_workflow_service = integration_workflow_service
        self.experiment_artifact_store = experiment_artifact_store
        self._cache: OrderedDict[tuple[str, str, str, str, str, str], Any] = OrderedDict()
        self._cache_lock = RLock()

    def detail(
        self, inference_result_id: str, row_id: str, *, threshold: object,
    ) -> SavedInferenceObjectDetail:
        value = self._threshold(threshold)
        evidence, loaded = self._trusted_row_and_model(inference_result_id, row_id)
        features = self._features(loaded, evidence)
        batch = self._batch(evidence)
        capabilities = self.integration_workflow_service.capabilities(
            loaded_model_version=loaded, prediction_batch=batch, selected_row_id=evidence.row_id,
        )
        return SavedInferenceObjectDetail(
            inference_result_id=evidence.inference_result_id,
            model_version_id=evidence.model_version_id,
            row_id=evidence.row_id,
            source_row_position=evidence.source_row_position,
            identifier_column=evidence.identifier_column,
            identifier_display=evidence.identifier_display,
            score=evidence.probability,
            threshold=value,
            position="ABOVE" if evidence.probability >= value else "BELOW",
            features=features,
            capabilities=capabilities,
        )

    def explain(self, inference_result_id: str, row_id: str) -> SavedInferenceExplanation:
        evidence, loaded = self._trusted_row_and_model(inference_result_id, row_id)
        batch = self._batch(evidence)
        self._verify_score_replay(loaded, evidence)
        context = self._context(loaded, evidence)
        try:
            explanation_capability = self.integration_workflow_service.capabilities(
                loaded_model_version=loaded, prediction_batch=batch, selected_row_id=evidence.row_id,
            )["local_explanation"]
        except Exception as error:
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_INTERNAL_ERROR") from error
        if explanation_capability.state == "UNSUPPORTED":
            raise SavedModelInferenceError("INFERENCE_LOCAL_EXPLANATION_UNSUPPORTED")
        provider_identity = self._provider_identity(loaded)
        cached = self._cached(evidence, provider_identity, context)
        if cached is None:
            try:
                local = self.integration_workflow_service.explain(
                    loaded_model_version=loaded, prediction_batch=batch, row_id=evidence.row_id,
                    explanation_context=context,
                )
            except ValueError as error:
                raise SavedModelInferenceError("INFERENCE_LOCAL_EXPLANATION_FAILED") from error
            except Exception as error:
                raise SavedModelInferenceError("INFERENCE_LOCAL_EXPLANATION_FAILED") from error
            self._validate_explanation(local, evidence, loaded)
            self._put_cached(evidence, local, provider_identity, context)
        else:
            local = cached
        try:
            capability = self.integration_workflow_service.capabilities(
                loaded_model_version=loaded, prediction_batch=batch,
                selected_row_id=evidence.row_id, local_explanation_evidence=local,
            )["result_interpretation"]
        except Exception as error:
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_INTERNAL_ERROR") from error
        return SavedInferenceExplanation(
            inference_result_id=evidence.inference_result_id,
            model_version_id=evidence.model_version_id,
            row_id=evidence.row_id,
            explanation_id=stable_hash({
                "inference_result_id": evidence.inference_result_id,
                "model_version_id": evidence.model_version_id,
                "row_id": evidence.row_id,
                "evidence_hash": local.evidence_hash,
            }),
            evidence_hash=local.evidence_hash,
            prediction_probability=local.prediction_probability,
            base_value=local.base_value,
            explained_output_value=local.explained_output_value,
            output_space=local.output_space,
            explanation_method_id=local.explanation_method_id,
            explanation_method_version=local.explanation_method_version,
            explanation_provider_id=local.provider_id,
            explanation_provider_version=local.provider_version,
            features=local.features,
            remainder=getattr(local, "remainder", None),
            result_interpretation_capability=capability,
        )

    def _trusted_row_and_model(
        self, inference_result_id: str, row_id: str,
    ) -> tuple[SavedInferenceObjectEvidence, Any]:
        try:
            evidence = self.result_store.read_object_evidence(inference_result_id, row_id)
        except InferenceResultNotFoundError as error:
            # Result and row identifiers deliberately have distinct public codes.
            try:
                self.result_store.read(inference_result_id)
            except InferenceResultNotFoundError:
                raise SavedModelInferenceError("INFERENCE_RESULT_NOT_FOUND") from error
            except InferenceResultIntegrityError:
                raise SavedModelInferenceError("INFERENCE_RESULT_INTEGRITY_ERROR") from error
            raise SavedModelInferenceError("INFERENCE_OBJECT_NOT_FOUND") from error
        except InferenceResultIntegrityError as error:
            raise SavedModelInferenceError("INFERENCE_RESULT_INTEGRITY_ERROR") from error
        try:
            _record, loaded = self.model_library_service.load_for_inference(evidence.model_version_id)
        except ModelVersionNotFound as error:
            raise SavedModelInferenceError("MODEL_VERSION_NOT_FOUND") from error
        except ModelSourceResultUnavailable as error:
            raise SavedModelInferenceError("MODEL_SOURCE_RESULT_UNAVAILABLE") from error
        except ModelVersionIntegrityError as error:
            raise SavedModelInferenceError("MODEL_VERSION_INTEGRITY_ERROR") from error
        except Exception as error:
            raise SavedModelInferenceError("MODEL_VERSION_INTEGRITY_ERROR") from error
        metadata = getattr(loaded, "metadata", None)
        if (
            loaded.summary.model_version_id != evidence.model_version_id
            or loaded.summary.experiment_artifact_id != evidence.experiment_artifact_id
            or not isinstance(metadata, dict)
            or metadata.get("experiment_artifact_id") != evidence.experiment_artifact_id
            or tuple(metadata.get("feature_columns", ())) != evidence.required_feature_columns
            or stable_hash({"identifier_column": evidence.identifier_column,
                            "required_feature_columns": evidence.required_feature_columns})
            != evidence.feature_binding_hash
        ):
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_EVIDENCE_MISMATCH")
        return evidence, loaded

    @staticmethod
    def _batch(evidence: SavedInferenceObjectEvidence) -> PredictionBatch:
        return PredictionBatch(
            model_version_id=evidence.model_version_id,
            source_sha256=evidence.source_file_sha256,
            identifier_column=evidence.identifier_column,
            required_feature_columns=evidence.required_feature_columns,
            rows=(PredictionRow(evidence.row_id, evidence.source_row_position,
                                evidence.identifier_display, evidence.probability),),
            ignored_columns=(),
            validated_feature_values=(evidence.feature_values,),
        )

    def _features(self, loaded: Any, evidence: SavedInferenceObjectEvidence) -> tuple[SavedInferenceFeature, ...]:
        specs = loaded.metadata.get("feature_specs")
        if not isinstance(specs, list) or len(specs) != len(evidence.required_feature_columns):
            raise SavedModelInferenceError("MODEL_VERSION_INTEGRITY_ERROR")
        features = []
        for column, raw_value, spec in zip(evidence.required_feature_columns, evidence.feature_values, specs, strict=True):
            if not isinstance(spec, dict) or spec.get("column_name") != column or not isinstance(spec.get("feature_id"), str):
                raise SavedModelInferenceError("MODEL_VERSION_INTEGRITY_ERROR")
            features.append(SavedInferenceFeature(spec["feature_id"], column, spec.get("display_name_ru"), spec.get("description_ru"), raw_value))
        return tuple(features)

    def _verify_score_replay(self, loaded: Any, evidence: SavedInferenceObjectEvidence) -> None:
        try:
            frame = pd.DataFrame((evidence.feature_values,), columns=evidence.required_feature_columns, dtype=float)
            replay = np.asarray(loaded.predictor.predict_positive_proba(frame), dtype=float)
            if (replay.shape != (1,) or not np.isfinite(replay).all() or not 0 <= replay[0] <= 1
                    or not np.isclose(replay[0], evidence.probability, rtol=_REPLAY_RTOL, atol=_REPLAY_ATOL)):
                raise ValueError
        except Exception as error:
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_EVIDENCE_MISMATCH") from error

    def _context(self, loaded: Any, evidence: SavedInferenceObjectEvidence) -> TrustedExplanationContext | None:
        if loaded.summary.model_id != "gbdt_mean":
            return None
        if self.experiment_artifact_store is None:
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_BACKGROUND_UNAVAILABLE")
        try:
            artifact = self.experiment_artifact_store.load(evidence.experiment_artifact_id)
            oof = artifact.run_output.oof_evidence
            if (
                oof is None or artifact.artifact_id != evidence.experiment_artifact_id
                or tuple(oof.feature_columns) != evidence.required_feature_columns
                or oof.model_input.shape != (len(oof.identifier_display), len(oof.feature_columns))
            ):
                raise ValueError
            return TrustedExplanationContext.from_model_version_evidence(
                source_artifact_id=evidence.experiment_artifact_id,
                model_binding_id=evidence.model_version_id,
                feature_columns=evidence.required_feature_columns,
                model_input_values=tuple(tuple(float(value) for value in row) for row in oof.model_input),
                row_positions=tuple(int(value) for value in artifact.run_output.row_positions),
            )
        except SavedModelInferenceError:
            raise
        except Exception as error:
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_BACKGROUND_UNAVAILABLE") from error

    def _provider_identity(self, loaded: Any) -> tuple[str, str] | None:
        """Resolve cache identity only from the workflow's trusted registry."""
        resolver = getattr(self.integration_workflow_service, "_explanation_provider", None)
        if not callable(resolver):
            return None
        try:
            provider = resolver(loaded.summary.model_id)
            descriptor = getattr(provider, "descriptor", None)
            if descriptor is None:
                return None
            return descriptor.provider_id, descriptor.provider_version
        except (AttributeError, KeyError, ValueError):
            return None

    def _cached(self, evidence: SavedInferenceObjectEvidence, provider_identity: tuple[str, str] | None, context: TrustedExplanationContext | None) -> Any | None:
        if provider_identity is None:
            return None
        background_hash = context.background_hash if context is not None else "no_background"
        key = (*self._cache_prefix(evidence), *provider_identity, background_hash)
        with self._cache_lock:
            try:
                value = self._cache.pop(key)
            except KeyError:
                return None
            self._cache[key] = value
            return value

    def _put_cached(self, evidence: SavedInferenceObjectEvidence, local: Any, provider_identity: tuple[str, str] | None, context: TrustedExplanationContext | None) -> None:
        if provider_identity is None or provider_identity != (local.provider_id, local.provider_version):
            return
        key = (*self._cache_prefix(evidence), *provider_identity, context.background_hash if context is not None else "no_background")
        with self._cache_lock:
            self._cache.pop(key, None)
            self._cache[key] = local
            while len(self._cache) > _CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)

    @staticmethod
    def _cache_prefix(evidence: SavedInferenceObjectEvidence) -> tuple[str, str, str]:
        return evidence.inference_result_id, evidence.model_version_id, evidence.row_id

    def _validate_explanation(self, local: Any, evidence: SavedInferenceObjectEvidence, loaded: Any) -> None:
        try:
            if (
                local.model_version_id != evidence.model_version_id
                or local.row_id != evidence.row_id
                or local.experiment_artifact_id != evidence.experiment_artifact_id
                or len(local.features) != len(evidence.required_feature_columns)
                or tuple(item.column_name for item in sorted(local.features, key=lambda item: evidence.required_feature_columns.index(item.column_name))) != evidence.required_feature_columns
                or not np.isclose(local.prediction_probability, evidence.probability, rtol=_REPLAY_RTOL, atol=_REPLAY_ATOL)
                or not local.evidence_hash
            ):
                raise ValueError
        except Exception as error:
            raise SavedModelInferenceError("INFERENCE_EXPLANATION_EVIDENCE_MISMATCH") from error

    @staticmethod
    def _threshold(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(float(value)) or not 0 <= float(value) <= 1:
            raise SavedModelInferenceError("INVALID_INFERENCE_RESULT_QUERY")
        return float(value)
