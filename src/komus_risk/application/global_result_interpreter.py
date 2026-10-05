"""Safe aggregate LLM interpretation of one completed OOF model result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from numbers import Real
import json
from typing import Any, Mapping

from komus_risk.hashing import canonical_json, stable_hash

from .interpreter_policy import ProviderDispatch, ProviderDispatchReceipt
from .oof_explanation import GlobalOOFExplanation
from .oof_result import OOFResultSummary, OOFThresholdMetrics
from .result_interpreter import RESULT_INTERPRETER_ROLES, ResultInterpreterClient
from .result_interpreter_prompts import ResultInterpreterPromptLoader, ResultInterpreterPromptsError


GLOBAL_RESULT_INTERPRETER_REQUEST_VERSION = "global_result_interpreter_v1"
GLOBAL_RESULT_INTERPRETER_TOP_FEATURES = 10


@dataclass(frozen=True, slots=True)
class GlobalInterpreterFoldFact:
    fold: int
    gini: float
    roc_auc: float
    pr_auc: float
    recall_at_0_5: float


@dataclass(frozen=True, slots=True)
class GlobalInterpreterFeatureFact:
    feature_id: str
    column_name: str
    mean_abs_shap: float
    rank: int


@dataclass(frozen=True, slots=True)
class GlobalResultInterpreterRequest:
    request_version: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    recipient_role: str
    artifact_id: str
    global_evidence_hash: str
    model_id: str
    model_version: str
    object_count: int
    feature_count: int
    folds: int
    evaluation_level: str
    gini: float
    roc_auc: float
    pr_auc: float
    fold_metrics: tuple[GlobalInterpreterFoldFact, ...]
    threshold: float
    tp: int
    tn: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    above_threshold_count: int
    above_threshold_share: float
    capture_object_share: float | None
    capture_event_share: float | None
    top_features: tuple[GlobalInterpreterFeatureFact, ...]
    limitations: tuple[str, ...]
    request_hash: str


@dataclass(frozen=True, slots=True)
class GlobalResultInterpreterResponse:
    request_hash: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    interpreter_id: str
    interpreter_model: str
    text: str
    created_at: str
    response_hash: str


@dataclass(frozen=True, slots=True)
class GlobalResultInterpretationOutcome:
    response: GlobalResultInterpreterResponse
    dispatch_receipt: ProviderDispatchReceipt


class GlobalResultInterpreterService:
    """Build one aggregate request from trusted OOF/SHAP evidence only."""

    def __init__(self, prompt_loader: ResultInterpreterPromptLoader) -> None:
        self._prompt_loader = prompt_loader

    def build_request(
        self,
        *,
        summary: OOFResultSummary,
        threshold: OOFThresholdMetrics,
        global_explanation: GlobalOOFExplanation,
        recipient_role: str,
    ) -> GlobalResultInterpreterRequest:
        self._validate_role(recipient_role)
        self._validate_binding(summary, threshold, global_explanation)
        prompt = self._load_prompt(recipient_role)
        fold_metrics = tuple(self._fold_fact(item) for item in summary.fold_metrics)
        top_features = tuple(
            GlobalInterpreterFeatureFact(
                feature_id=item.feature_id,
                column_name=item.column_name,
                mean_abs_shap=self._finite(item.mean_abs_shap, "mean_abs_shap"),
                rank=item.rank,
            )
            for item in global_explanation.features[:GLOBAL_RESULT_INTERPRETER_TOP_FEATURES]
        )
        marker = summary.capture.marker
        payload = {
            "request_version": GLOBAL_RESULT_INTERPRETER_REQUEST_VERSION,
            "prompt_id": prompt.prompt_id,
            "prompt_version": prompt.prompt_version,
            "prompt_hash": prompt.prompt_hash,
            "recipient_role": recipient_role,
            "artifact_id": summary.artifact_id,
            "global_evidence_hash": global_explanation.evidence_hash,
            "model_id": summary.model_id,
            "model_version": summary.model_version,
            "object_count": summary.object_count,
            "feature_count": summary.feature_count,
            "folds": summary.folds,
            "evaluation_level": summary.evaluation_level,
            "gini": self._finite(summary.gini, "gini"),
            "roc_auc": self._finite(summary.roc_auc, "roc_auc"),
            "pr_auc": self._finite(summary.pr_auc, "pr_auc"),
            "fold_metrics": fold_metrics,
            "threshold": self._finite(threshold.threshold, "threshold"),
            "tp": threshold.tp,
            "tn": threshold.tn,
            "fp": threshold.fp,
            "fn": threshold.fn,
            "precision": self._finite(threshold.precision, "precision"),
            "recall": self._finite(threshold.recall, "recall"),
            "f1": self._finite(threshold.f1, "f1"),
            "above_threshold_count": threshold.above_threshold_count,
            "above_threshold_share": self._finite(threshold.above_threshold_share, "above_threshold_share"),
            "capture_object_share": None if marker is None else self._finite(marker.object_share, "capture_object_share"),
            "capture_event_share": None if marker is None else self._finite(marker.event_share, "capture_event_share"),
            "top_features": top_features,
            "limitations": tuple(summary.limitations),
        }
        self._require_json_compatible(payload)
        return GlobalResultInterpreterRequest(**payload, request_hash=stable_hash(payload))

    def validate_request(self, request: GlobalResultInterpreterRequest) -> None:
        if not isinstance(request, GlobalResultInterpreterRequest):
            raise ValueError("Global result interpreter requires a typed request.")
        self._validate_role(request.recipient_role)
        semantic = {
            field: getattr(request, field)
            for field in GlobalResultInterpreterRequest.__dataclass_fields__
            if field != "request_hash"
        }
        self._require_json_compatible(semantic)
        if (
            request.request_version != GLOBAL_RESULT_INTERPRETER_REQUEST_VERSION
            or stable_hash(semantic) != request.request_hash
        ):
            raise ValueError("Global result interpreter request hash integrity check failed.")

    def interpret_request(
        self,
        *,
        request: GlobalResultInterpreterRequest,
        client: ResultInterpreterClient,
    ) -> GlobalResultInterpreterResponse:
        self.validate_request(request)
        prompt = self._load_prompt(request.recipient_role)
        if (
            prompt.prompt_id,
            prompt.prompt_version,
            prompt.prompt_hash,
        ) != (
            request.prompt_id,
            request.prompt_version,
            request.prompt_hash,
        ):
            raise ResultInterpreterPromptsError(
                "RESULT_INTERPRETER_PROMPTS_INVALID: prompt identity changed after request creation."
            )
        try:
            interpreter_id = client.interpreter_id
            interpreter_model = client.interpreter_model
            text = client.interpret(
                system_instruction=prompt.system_instruction,
                payload=self._internal_client_payload(request),
            )
        except ResultInterpreterPromptsError:
            raise
        except Exception as error:
            raise RuntimeError("Global result interpreter client failed.") from error
        if not isinstance(interpreter_id, str) or not interpreter_id.strip():
            raise ValueError("Global result interpreter client interpreter_id is invalid.")
        if not isinstance(interpreter_model, str) or not interpreter_model.strip():
            raise ValueError("Global result interpreter client interpreter_model is invalid.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Global result interpreter client returned invalid text.")
        semantic_response = {
            "request_hash": request.request_hash,
            "prompt_id": request.prompt_id,
            "prompt_version": request.prompt_version,
            "prompt_hash": request.prompt_hash,
            "interpreter_id": interpreter_id,
            "interpreter_model": interpreter_model,
            "text": text.strip(),
        }
        return GlobalResultInterpreterResponse(
            **semantic_response,
            created_at=datetime.now(timezone.utc).isoformat(),
            response_hash=stable_hash(semantic_response),
        )

    def _load_prompt(self, recipient_role: str):
        try:
            return self._prompt_loader.load(recipient_role)
        except ResultInterpreterPromptsError:
            raise
        except Exception as error:
            raise ResultInterpreterPromptsError("RESULT_INTERPRETER_PROMPTS_INVALID") from error

    @staticmethod
    def _validate_role(recipient_role: str) -> None:
        if recipient_role not in RESULT_INTERPRETER_ROLES:
            raise ValueError("Unknown global result interpreter recipient role.")

    @staticmethod
    def _validate_binding(
        summary: OOFResultSummary,
        threshold: OOFThresholdMetrics,
        global_explanation: GlobalOOFExplanation,
    ) -> None:
        if (
            threshold.artifact_id != summary.artifact_id
            or global_explanation.artifact_id != summary.artifact_id
            or global_explanation.model_id != summary.model_id
            or global_explanation.model_version != summary.model_version
            or global_explanation.row_count != summary.object_count
            or global_explanation.feature_count != summary.feature_count
        ):
            raise ValueError("Global result interpreter evidence binding mismatch.")

    @classmethod
    def _fold_fact(cls, item: Mapping[str, object]) -> GlobalInterpreterFoldFact:
        try:
            fold = item["fold"]
            if isinstance(fold, bool) or not isinstance(fold, int):
                raise TypeError
            return GlobalInterpreterFoldFact(
                fold=fold,
                gini=cls._finite(item["gini"], "fold.gini"),
                roc_auc=cls._finite(item["roc_auc"], "fold.roc_auc"),
                pr_auc=cls._finite(item["pr_auc"], "fold.pr_auc"),
                recall_at_0_5=cls._finite(item["recall_at_0_5"], "fold.recall_at_0_5"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Global result interpreter fold metrics are invalid.") from error

    @staticmethod
    def _finite(value: object, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{label} must be finite.")
        number = float(value)
        if not isfinite(number):
            raise ValueError(f"{label} must be finite.")
        return number

    @staticmethod
    def _require_json_compatible(value: Any) -> None:
        try:
            canonical_json(value)
        except ValueError as error:
            raise ValueError("Global result interpreter request must contain JSON-compatible facts.") from error

    @staticmethod
    def _internal_client_payload(request: GlobalResultInterpreterRequest) -> dict[str, Any]:
        """Full internal payload; an outbound policy must still project it before provider dispatch."""
        return {
            field: getattr(request, field)
            for field in GlobalResultInterpreterRequest.__dataclass_fields__
            if field not in {"request_hash", "artifact_id", "global_evidence_hash"}
        }


class GlobalRedactedV1OutboundPolicy:
    """Allowlist aggregate facts only; never emit row/object identity or raw records."""

    policy_id = "GLOBAL_REDACTED_V1"
    policy_version = 1

    def project(self, request: GlobalResultInterpreterRequest) -> ProviderDispatch:
        features = [
            {
                "feature_id": item.feature_id,
                "column_name": item.column_name,
                "mean_abs_shap": item.mean_abs_shap,
                "rank": item.rank,
            }
            for item in request.top_features
        ]
        fold_metrics = [
            {
                "fold": item.fold,
                "gini": item.gini,
                "roc_auc": item.roc_auc,
                "pr_auc": item.pr_auc,
                "recall_at_0_5": item.recall_at_0_5,
            }
            for item in request.fold_metrics
        ]
        payload = {
            "recipient_role": request.recipient_role,
            "model": {
                "model_id": request.model_id,
                "model_version": request.model_version,
            },
            "evaluation": {
                "level": request.evaluation_level,
                "object_count": request.object_count,
                "feature_count": request.feature_count,
                "folds": request.folds,
            },
            "quality": {
                "gini": request.gini,
                "roc_auc": request.roc_auc,
                "pr_auc": request.pr_auc,
                "fold_metrics": fold_metrics,
            },
            "operating_point": {
                "threshold": request.threshold,
                "tp": request.tp,
                "tn": request.tn,
                "fp": request.fp,
                "fn": request.fn,
                "precision": request.precision,
                "recall": request.recall,
                "f1": request.f1,
                "above_threshold_count": request.above_threshold_count,
                "above_threshold_share": request.above_threshold_share,
            },
            "capture": None if request.capture_object_share is None else {
                "object_share": request.capture_object_share,
                "event_share": request.capture_event_share,
            },
            "global_feature_importance": {
                "method": "mean_abs_oof_shap",
                "features": features,
            },
            "limitations": list(request.limitations),
        }
        provider_payload = json.loads(canonical_json(payload))
        return ProviderDispatch(
            payload=provider_payload,
            receipt=ProviderDispatchReceipt(
                source_request_hash=request.request_hash,
                prompt_id=request.prompt_id,
                prompt_version=request.prompt_version,
                prompt_hash=request.prompt_hash,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                provider_payload_hash=stable_hash(provider_payload),
            ),
        )
