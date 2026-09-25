from __future__ import annotations

from types import SimpleNamespace
import unittest

from komus_risk.application import IntegrationWorkflowService
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


if __name__ == "__main__":
    unittest.main()
