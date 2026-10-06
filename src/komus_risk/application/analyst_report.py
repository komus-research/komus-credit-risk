"""Resolve an editable inference report draft into one immutable report artifact."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from numbers import Real
from typing import Any

from komus_risk.artifacts.analyst_report_store import (
    AnalystReportIntegrityError,
    AnalystReportNotFoundError,
    AnalystReportPersistenceError,
    AnalystReportStore,
    SavedInferenceInterpretationStore,
    SavedInterpretationIntegrityError,
)
from komus_risk.artifacts.inference_result_store import (
    InferenceResultIntegrityError,
    InferenceResultNotFoundError,
    SavedModelInferenceResultStore,
)
from komus_risk.artifacts.inference_view_store import (
    InferenceReportDraftIntegrityError,
    InferenceReportDraftPersistenceError,
    SavedInferenceReportDraftStore,
)
from komus_risk.hashing import stable_hash

from .saved_model_inference import SavedModelInferenceError


class AnalystReportError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AnalystReportService:
    """The sole semantic resolver between a report draft and renderable content."""

    def __init__(
        self, *, result_store: SavedModelInferenceResultStore,
        draft_store: SavedInferenceReportDraftStore,
        explanation_service: Any,
        model_library_service: Any,
        interpretation_store: SavedInferenceInterpretationStore,
        report_store: AnalystReportStore,
    ) -> None:
        self.result_store = result_store
        self.draft_store = draft_store
        self.explanation_service = explanation_service
        self.model_library_service = model_library_service
        self.interpretation_store = interpretation_store
        self.report_store = report_store

    def generate(self, inference_result_id: str) -> tuple[dict[str, Any], str]:
        draft = self._draft(inference_result_id)
        if not draft.selected_row_ids:
            raise AnalystReportError("ANALYST_REPORT_DRAFT_EMPTY")
        result = self._result(inference_result_id)
        if result.inference_result_id != draft.inference_result_id:
            raise AnalystReportError("ANALYST_REPORT_DRAFT_INTEGRITY_ERROR")
        threshold, threshold_source, record, loaded = self._decision_context(result)
        companies = [self._company(result, row_id, threshold) for row_id in draft.selected_row_ids]
        snapshot = {
            "schema_version": 1,
            "source": {
                "inference_result_id": result.inference_result_id,
                "model_version_id": result.model_version_id,
                "experiment_artifact_id": result.experiment_artifact_id,
                "model_id": getattr(getattr(loaded, "summary", None), "model_id", None),
                "model_version": getattr(getattr(loaded, "summary", None), "model_version", None),
                "source_file_sha256": result.source_file_sha256,
                "inference_recipe_key": result.inference_recipe_key,
            },
            "decision_context": {"threshold": threshold, "threshold_source": threshold_source},
            "model_summary": self._model_summary(result.model_version_id, record),
            "selection": {
                "inference_result_id": draft.inference_result_id,
                "selected_row_ids": list(draft.selected_row_ids),
                "selection_hash": stable_hash(list(draft.selected_row_ids)),
            },
            "companies": companies,
        }
        content_hash = stable_hash(snapshot)
        report = {
            "schema_version": 1, "report_id": content_hash, "content_hash": content_hash,
            "created_at": datetime.now(UTC).isoformat(), **snapshot,
        }
        try:
            # The store boundary rebuilds this exact snapshot before both
            # publishing and every subsequent read.
            self.report_store.semantic_snapshot(report)
            return self.report_store.publish(report)
        except AnalystReportIntegrityError as error:
            raise AnalystReportError("ANALYST_REPORT_INTEGRITY_ERROR") from error
        except AnalystReportPersistenceError as error:
            raise AnalystReportError("ANALYST_REPORT_PERSISTENCE_ERROR") from error

    def get(self, report_id: str) -> dict[str, Any]:
        try:
            return self.report_store.read(report_id)
        except AnalystReportNotFoundError as error:
            raise AnalystReportError("ANALYST_REPORT_NOT_FOUND") from error
        except AnalystReportIntegrityError as error:
            raise AnalystReportError("ANALYST_REPORT_INTEGRITY_ERROR") from error

    def _draft(self, inference_result_id: str) -> Any:
        try:
            draft = self.draft_store.read(inference_result_id)
        except InferenceReportDraftIntegrityError as error:
            raise AnalystReportError("ANALYST_REPORT_DRAFT_INTEGRITY_ERROR") from error
        except InferenceReportDraftPersistenceError as error:
            raise AnalystReportError("ANALYST_REPORT_PERSISTENCE_ERROR") from error
        if draft is None:
            raise AnalystReportError("ANALYST_REPORT_DRAFT_NOT_FOUND")
        return draft

    def _result(self, inference_result_id: str) -> Any:
        try:
            return self.result_store.read(inference_result_id)
        except InferenceResultNotFoundError as error:
            raise AnalystReportError("ANALYST_REPORT_SOURCE_UNAVAILABLE") from error
        except InferenceResultIntegrityError as error:
            raise AnalystReportError("ANALYST_REPORT_SOURCE_INTEGRITY_ERROR") from error

    def _decision_context(self, result: Any) -> tuple[float, str, Any, Any]:
        try:
            record, loaded = self.model_library_service.load_for_inference(result.model_version_id)
            if record.model_version_id != result.model_version_id or record.experiment_artifact_id != result.experiment_artifact_id:
                raise ValueError
            if record.decision_threshold_state == "USER_APPLIED":
                value = record.decision_threshold
                source = "MODEL_DECISION"
            elif record.decision_threshold_state == "NOT_SET":
                value = 0.50
                source = "TECHNICAL_DEFAULT"
            else:
                raise ValueError
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(float(value)) or not 0 <= float(value) <= 1:
                raise ValueError
            return float(value), source, record, loaded
        except Exception as error:
            raise AnalystReportError("ANALYST_REPORT_SOURCE_INTEGRITY_ERROR") from error

    def _model_summary(self, model_version_id: str, record: Any) -> dict[str, Any]:
        """Freeze trusted ModelLibrary detail in a newly generated report only."""
        try:
            detail = self.model_library_service.detail(model_version_id)
            value = getattr(detail, "value", detail)
            if not isinstance(value, dict) or value.get("model_version_id") != model_version_id:
                raise ValueError
            algorithm = value["algorithm"]
            dataset = value["dataset"]
            configuration = value["configuration"]
            quality = value["oof_quality"]
            summary = {
                "display_name": value["display_name"],
                "model_display_name": algorithm["model_display_name"],
                "dataset_name": dataset["dataset_name"],
                "feature_count": len(value["features"]),
                "folds": configuration["folds"],
                "oof_gini": quality["gini"],
                "oof_roc_auc": quality["roc_auc"],
                "oof_pr_auc": quality["pr_auc"],
            }
            if summary["display_name"] != record.display_name:
                raise ValueError
            AnalystReportStore._model_summary(summary)
            return summary
        except Exception as error:
            raise AnalystReportError("ANALYST_REPORT_SOURCE_INTEGRITY_ERROR") from error

    def _company(self, result: Any, row_id: str, threshold: float) -> dict[str, Any]:
        try:
            evidence = self.result_store.read_object_evidence(result.inference_result_id, row_id)
        except InferenceResultNotFoundError as error:
            raise AnalystReportError("ANALYST_REPORT_SELECTED_OBJECT_UNAVAILABLE") from error
        except InferenceResultIntegrityError as error:
            raise AnalystReportError("ANALYST_REPORT_SOURCE_INTEGRITY_ERROR") from error
        try:
            explanation = self.explanation_service.explain(result.inference_result_id, row_id)
        except SavedModelInferenceError as error:
            raise AnalystReportError("ANALYST_REPORT_LOCAL_EXPLANATION_UNAVAILABLE") from error
        except Exception as error:
            raise AnalystReportError("ANALYST_REPORT_LOCAL_EXPLANATION_UNAVAILABLE") from error
        if (
            explanation.inference_result_id != result.inference_result_id
            or explanation.model_version_id != result.model_version_id
            or explanation.row_id != row_id
            or explanation.prediction_probability != evidence.probability
            or not isinstance(explanation.evidence_hash, str) or not explanation.evidence_hash
        ):
            raise AnalystReportError("ANALYST_REPORT_LOCAL_EXPLANATION_INTEGRITY_ERROR")
        contributions = [self._contribution(feature) for feature in explanation.features]
        if not contributions or len({item["abs_rank"] for item in contributions}) != len(contributions):
            raise AnalystReportError("ANALYST_REPORT_LOCAL_EXPLANATION_INTEGRITY_ERROR")
        local_snapshot = {
            "explanation_id": explanation.explanation_id,
            "evidence_hash": explanation.evidence_hash,
            "prediction_probability": explanation.prediction_probability,
            "base_value": explanation.base_value,
            "explained_output_value": explanation.explained_output_value,
            "output_space": explanation.output_space,
            "method": {"id": explanation.explanation_method_id, "version": explanation.explanation_method_version},
            "provider": {"id": explanation.explanation_provider_id, "version": explanation.explanation_provider_version},
            "features": contributions,
            "remainder": self._remainder(explanation.remainder),
        }
        try:
            interpretations = self.interpretation_store.list_for_evidence(
                result.inference_result_id, row_id,
                model_version_id=result.model_version_id,
                explanation_id=explanation.explanation_id, evidence_hash=explanation.evidence_hash,
            )
        except SavedInterpretationIntegrityError as error:
            raise AnalystReportError("ANALYST_REPORT_INTERPRETATION_INTEGRITY_ERROR") from error
        except AnalystReportPersistenceError as error:
            raise AnalystReportError("ANALYST_REPORT_PERSISTENCE_ERROR") from error
        visible = [item for item in local_snapshot["features"] if item["abs_rank"] <= 10]
        return {
            "row_id": evidence.row_id, "identifier": evidence.identifier_display, "subject_name": None,
            "score": evidence.probability, "threshold": threshold,
            "position": "ABOVE" if evidence.probability >= threshold else "BELOW",
            "local_shap": local_snapshot, "report_visible_contributions": visible,
            "role_interpretations": [
                {"role": item.role, "text": item.text, "created_at": item.created_at,
                 "response_hash": item.response_hash, "evidence_hash": item.evidence_hash,
                 "explanation_id": item.explanation_id, "record_hash": item.record_hash,
                 "response_content": item.response_content}
                for item in interpretations
            ],
            "evidence": {
                "source_file_sha256": evidence.source_file_sha256,
                "feature_binding_hash": evidence.feature_binding_hash,
                "local_explanation_hash": explanation.evidence_hash,
            },
        }

    @staticmethod
    def _contribution(item: Any) -> dict[str, Any]:
        value = {
            "feature_id": item.feature_id, "column_name": item.column_name,
            "display_name_ru": item.display_name_ru, "description_ru": item.description_ru,
            "raw_value": item.raw_value, "shap_value": item.shap_value,
            "abs_rank": item.abs_rank, "direction": item.direction,
        }
        if (
            not isinstance(value["abs_rank"], int) or value["abs_rank"] < 1
            or any(isinstance(value[key], bool) or not isinstance(value[key], Real) or not isfinite(float(value[key])) for key in ("raw_value", "shap_value"))
        ):
            raise AnalystReportError("ANALYST_REPORT_LOCAL_EXPLANATION_INTEGRITY_ERROR")
        return value

    @staticmethod
    def _remainder(value: Any) -> Any:
        if value is None:
            return None
        try:
            return {
                "feature_count": value.feature_count, "shap_value": value.shap_value,
                "direction": value.direction,
            }
        except AttributeError as error:
            raise AnalystReportError("ANALYST_REPORT_LOCAL_EXPLANATION_INTEGRITY_ERROR") from error
