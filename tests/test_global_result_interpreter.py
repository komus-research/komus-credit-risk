from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from komus_risk.application import (
    GlobalOOFExplanation,
    GlobalOOFFeatureImportance,
    GlobalRedactedV1OutboundPolicy,
    GlobalResultInterpreterService,
    OOFResultSummary,
    OOFThresholdMetrics,
    ResultInterpreterPromptLoader,
)
from komus_risk.application.interpreter_policy import PolicyBoundResultInterpreterClient
from komus_risk.application.oof_result import OOFResultCapture, OOFResultCapturePoint


class _FakeInterpreter:
    interpreter_id = "fake"
    interpreter_model = "fake-model"

    def __init__(self) -> None:
        self.instruction: str | None = None
        self.payload: dict | None = None

    def interpret(self, *, system_instruction: str, payload: dict) -> str:
        self.instruction = system_instruction
        self.payload = payload
        return "Подтверждённое общее объяснение."


def _service() -> GlobalResultInterpreterService:
    root = Path(__file__).resolve().parents[1] / "resources" / "prompts" / "global_result_interpreter"
    return GlobalResultInterpreterService(ResultInterpreterPromptLoader(root))


def _summary() -> OOFResultSummary:
    return OOFResultSummary(
        artifact_id="artifact-1",
        result_id="result-1",
        model_id="catboost",
        model_version="1",
        object_count=120,
        feature_count=3,
        folds=2,
        evaluation_level="OOF",
        runtime_seconds=12.0,
        gini=0.82,
        roc_auc=0.91,
        pr_auc=0.54,
        fold_metrics=(
            {"fold": 1, "gini": 0.80, "roc_auc": 0.90, "pr_auc": 0.52, "recall_at_0_5": 0.68},
            {"fold": 2, "gini": 0.84, "roc_auc": 0.92, "pr_auc": 0.56, "recall_at_0_5": 0.70},
        ),
        limitations=("Random OOF does not prove temporal stability.",),
        capture=OOFResultCapture(
            total_positive_events=20,
            points=(
                OOFResultCapturePoint(0.0, 0.0),
                OOFResultCapturePoint(0.15, 0.60),
                OOFResultCapturePoint(1.0, 1.0),
            ),
            marker=OOFResultCapturePoint(0.15, 0.60),
        ),
    )


def _threshold() -> OOFThresholdMetrics:
    return OOFThresholdMetrics(
        artifact_id="artifact-1",
        threshold=0.61,
        tp=13,
        tn=95,
        fp=5,
        fn=7,
        precision=13 / 18,
        recall=13 / 20,
        f1=0.6842105263,
        above_threshold_count=18,
        above_threshold_share=0.15,
    )


def _global_explanation() -> GlobalOOFExplanation:
    return GlobalOOFExplanation(
        artifact_id="artifact-1",
        model_id="catboost",
        model_version="1",
        row_count=120,
        feature_count=3,
        output_space="raw_margin",
        provider_id="catboost_native_shap",
        provider_version="1",
        explanation_method_id="catboost_native_shap",
        explanation_method_version="1",
        background_policy_id="outer_train_hash_top128_v1",
        feature_binding_hash="feature-binding",
        fold_model_binding_ids=("fold-1", "fold-2"),
        features=(
            GlobalOOFFeatureImportance("feature-1", "Q_A", 0.8, 1),
            GlobalOOFFeatureImportance("feature-2", "Q_B", 0.5, 2),
            GlobalOOFFeatureImportance("feature-3", "Q_C", 0.2, 3),
        ),
        evidence_hash="global-evidence-hash",
    )


def test_global_request_uses_only_bound_aggregate_evidence() -> None:
    service = _service()
    request = service.build_request(
        summary=_summary(),
        threshold=_threshold(),
        global_explanation=_global_explanation(),
        recipient_role="credit_controller",
    )

    assert request.artifact_id == "artifact-1"
    assert request.threshold == 0.61
    assert request.fn == 7
    assert request.capture_event_share == 0.60
    assert [item.column_name for item in request.top_features] == ["Q_A", "Q_B", "Q_C"]
    assert request.limitations == ("Random OOF does not prove temporal stability.",)


def test_global_redacted_payload_excludes_row_identity_and_internal_provenance() -> None:
    service = _service()
    request = service.build_request(
        summary=_summary(),
        threshold=_threshold(),
        global_explanation=_global_explanation(),
        recipient_role="sales_manager",
    )
    dispatch = GlobalRedactedV1OutboundPolicy().project(request)

    assert set(dispatch.payload) == {
        "recipient_role",
        "model",
        "evaluation",
        "quality",
        "operating_point",
        "capture",
        "global_feature_importance",
        "limitations",
    }
    serialized = str(dispatch.payload)
    assert "artifact-1" not in serialized
    assert "global-evidence-hash" not in serialized
    assert "identifier" not in serialized.lower()
    assert "row_id" not in serialized.lower()


def test_global_policy_bound_provider_receives_only_redacted_payload() -> None:
    service = _service()
    request = service.build_request(
        summary=_summary(),
        threshold=_threshold(),
        global_explanation=_global_explanation(),
        recipient_role="lawyer",
    )
    dispatch = GlobalRedactedV1OutboundPolicy().project(request)
    fake = _FakeInterpreter()

    response = service.interpret_request(
        request=request,
        client=PolicyBoundResultInterpreterClient(
            underlying_client=fake,
            dispatch=dispatch,
        ),
    )

    assert fake.payload == dispatch.payload
    assert response.text == "Подтверждённое общее объяснение."
    assert "юрист" in (fake.instruction or "").lower()
    assert "не доказывает" in (fake.instruction or "").lower()


def test_global_request_fails_closed_on_mixed_artifacts() -> None:
    service = _service()
    with pytest.raises(ValueError, match="binding mismatch"):
        service.build_request(
            summary=_summary(),
            threshold=replace(_threshold(), artifact_id="other-artifact"),
            global_explanation=_global_explanation(),
            recipient_role="credit_controller",
        )


def test_global_prompt_rejects_invalid_role() -> None:
    service = _service()
    with pytest.raises(ValueError, match="recipient role"):
        service.build_request(
            summary=_summary(),
            threshold=_threshold(),
            global_explanation=_global_explanation(),
            recipient_role="administrator",
        )
