from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from komus_risk.application import (
    IntegrationWorkflowService,
    LocalExplanationEvidence,
    LocalFeatureContribution,
    RedactedV1OutboundPolicy,
    ResultInterpreterService,
)
from komus_risk.artifacts import ModelVersionSummary


class _TrainingService:
    def __init__(self, summary) -> None:
        self.summary = summary
        self.calls = []

    def train(self, **kwargs):
        self.calls.append(kwargs)
        return self.summary


class _VersionStore:
    def __init__(self, loaded) -> None:
        self.loaded = loaded
        self.calls = []

    def load(self, model_version_id):
        self.calls.append(model_version_id)
        return self.loaded


class _InferenceService:
    def __init__(self, batch) -> None:
        self.batch = batch
        self.calls = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return self.batch


class _Explainer:
    def __init__(self, evidence) -> None:
        self.evidence = evidence
        self.calls = []

    def explain(self, **kwargs):
        self.calls.append(kwargs)
        return self.evidence


class _InterpreterClient:
    def __init__(self) -> None:
        self.calls = []

    @property
    def interpreter_id(self):
        return "fake-interpreter"

    @property
    def interpreter_model(self):
        return "fake-model"

    def interpret(self, *, system_instruction, payload):
        self.calls.append({"system_instruction": system_instruction, "payload": payload})
        return "Текст интерпретации."


class _CountingPolicy(RedactedV1OutboundPolicy):
    def __init__(self) -> None:
        self.project_calls = 0

    def project(self, request):
        self.project_calls += 1
        return super().project(request)


class IntegrationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = ModelVersionSummary("version-1", "experiment-1", "future-model", "v1", ("feature-a",))
        self.loaded = SimpleNamespace(summary=self.summary)
        self.batch = SimpleNamespace(model_version_id="version-1")
        self.snapshot = SimpleNamespace(fingerprint="new-file")
        self.evidence = SimpleNamespace(row_id="row-1")
        self.training = _TrainingService(self.summary)
        self.store = _VersionStore(self.loaded)
        self.inference = _InferenceService(self.batch)
        self.explainer = _Explainer(self.evidence)
        self.context = SimpleNamespace(
            loaded_dataset=object(), feature_registry=object(), population=object(),
        )
        self.workflow = IntegrationWorkflowService(
            final_model_training_service=self.training,
            model_version_store=self.store,
            model_inference_service=self.inference,
            local_explainers={"future-model": self.explainer},
        )

    def test_save_model_uses_final_fit_then_model_store_load_boundary(self) -> None:
        loaded = self.workflow.save_model(
            experiment_artifact_id="experiment-1", prepared_dataset_context=self.context,
        )

        self.assertIs(loaded, self.loaded)
        self.assertEqual(self.store.calls, ["version-1"])
        self.assertEqual(self.training.calls, [{
            "experiment_artifact_id": "experiment-1",
            "loaded_dataset": self.context.loaded_dataset,
            "feature_registry": self.context.feature_registry,
            "population": self.context.population,
        }])

    def test_predict_delegates_to_the_existing_inference_service(self) -> None:
        result = self.workflow.predict(loaded_model_version=self.loaded, snapshot=self.snapshot)

        self.assertIs(result, self.batch)
        self.assertEqual(self.inference.calls, [{"loaded_model_version": self.loaded, "snapshot": self.snapshot}])

    def test_registered_future_model_explainer_is_available_and_delegated(self) -> None:
        capability = self.workflow.capabilities(
            loaded_model_version=self.loaded, prediction_batch=self.batch, selected_row_id="row-1",
        )["local_explanation"]
        evidence = self.workflow.explain(
            loaded_model_version=self.loaded, prediction_batch=self.batch, row_id="row-1",
        )

        self.assertEqual((capability.state, capability.reason_code), ("AVAILABLE", "LOCAL_EXPLAINER_READY"))
        self.assertIs(evidence, self.evidence)
        self.assertEqual(self.explainer.calls, [{
            "loaded_model_version": self.loaded,
            "prediction_batch": self.batch,
            "row_id": "row-1",
        }])

    def test_missing_explainer_does_not_block_prediction(self) -> None:
        unsupported = SimpleNamespace(summary=ModelVersionSummary("version-2", "experiment-1", "unregistered", "v1", ("feature-a",)))
        workflow = IntegrationWorkflowService(
            final_model_training_service=self.training,
            model_version_store=self.store,
            model_inference_service=self.inference,
            local_explainers={},
        )

        capability = workflow.capabilities(
            loaded_model_version=unsupported, prediction_batch=self.batch, selected_row_id="row-1",
        )["local_explanation"]
        result = workflow.predict(loaded_model_version=unsupported, snapshot=self.snapshot)

        self.assertEqual((capability.state, capability.reason_code), ("UNSUPPORTED", "LOCAL_EXPLAINER_NOT_REGISTERED"))
        self.assertIs(result, self.batch)

    def test_workflow_has_no_fallback_predictor_or_explainer(self) -> None:
        self.assertFalse(hasattr(self.workflow, "fallback_predictor"))
        self.assertFalse(hasattr(self.workflow, "fallback_explainer"))

    def test_interpretation_is_opt_in_and_prepare_makes_no_provider_call(self) -> None:
        evidence = LocalExplanationEvidence(
            evidence_version="v1", evidence_hash="evidence", model_version_id="version-1",
            experiment_artifact_id="experiment", dataset_id="dataset", dataset_fingerprint="fingerprint",
            feature_set_hash="features", model_id="future-model", model_version="v1", row_id="row-1",
            identifier_column="client_id", identifier_value="secret", probability=0.7,
            shap_output_space="raw_margin", raw_model_output=1.0, base_value=0.2,
            features=(LocalFeatureContribution("feature", "technical", 9.0, 0.5, 1),),
            explainer_id="local", explainer_version="v1", created_at="2026-09-24T00:00:00+00:00",
        )
        client = _InterpreterClient()
        configured = IntegrationWorkflowService(
            final_model_training_service=self.training, model_version_store=self.store,
            model_inference_service=self.inference, local_explainers={"future-model": self.explainer},
            result_interpreter_service=ResultInterpreterService(), result_interpreter_client=client,
            outbound_interpreter_policy=RedactedV1OutboundPolicy(),
        )
        request = configured.prepare_interpretation(evidence=evidence)
        self.assertEqual(client.calls, [])

        outcome = configured.interpret(request=request)
        self.assertEqual(outcome.dispatch_receipt.source_request_hash, request.request_hash)
        self.assertEqual(set(client.calls[0]["payload"]), {"prediction", "explanation", "top_features"})

    def test_interpretation_validates_before_policy_or_provider_access(self) -> None:
        client = _InterpreterClient()
        policy = _CountingPolicy()
        workflow = IntegrationWorkflowService(
            final_model_training_service=self.training, model_version_store=self.store,
            model_inference_service=self.inference, local_explainers={},
            result_interpreter_service=ResultInterpreterService(), result_interpreter_client=client,
            outbound_interpreter_policy=policy,
        )
        valid = ResultInterpreterService().build_request(evidence=LocalExplanationEvidence(
            evidence_version="v1", evidence_hash="evidence", model_version_id="version-1",
            experiment_artifact_id="experiment", dataset_id="dataset", dataset_fingerprint="fingerprint",
            feature_set_hash="features", model_id="future-model", model_version="v1", row_id="row-1",
            identifier_column="client_id", identifier_value="secret", probability=0.7,
            shap_output_space="raw_margin", raw_model_output=1.0, base_value=0.2,
            features=(LocalFeatureContribution("feature", "technical", 9.0, 0.5, 1),),
            explainer_id="local", explainer_version="v1", created_at="2026-09-24T00:00:00+00:00",
        ))
        for tampered in (
            replace(valid, probability=0.8),
            replace(valid, features=(replace(valid.features[0], shap_value=0.8),)),
        ):
            with self.subTest(tampered=tampered):
                with self.assertRaisesRegex(ValueError, "hash integrity"):
                    workflow.interpret(request=tampered)
        self.assertEqual(policy.project_calls, 0)
        self.assertEqual(client.calls, [])

    def test_interpretation_without_dependencies_fails_before_provider_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "not configured"):
            self.workflow.interpret(request=object())


if __name__ == "__main__":
    unittest.main()
