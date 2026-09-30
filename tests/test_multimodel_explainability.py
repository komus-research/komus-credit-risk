from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from komus_risk.application import (
    IntegrationWorkflowService, ModelInferenceService,
    RedactedV1OutboundPolicy, RESULT_INTERPRETER_ROLES,
    ResultInterpreterRuntimeConfiguration, ResultInterpreterService,
)
from komus_risk.artifacts import ModelVersionStore
from komus_risk.contracts import DatasetContract, ExperimentConfig, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import TabularSnapshot
from komus_risk.experiments import EvaluationPopulation
from komus_risk.hashing import canonical_json
from komus_risk.model_platform import ModelConfigurationMode, ModelConfigurationRecord, ModelConfigurationService, build_builtin_model_plugin_registry
from komus_risk.registries import FeatureRegistry


class _RecordingInterpreterClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    @property
    def interpreter_id(self) -> str:
        return "recording-interpreter"

    @property
    def interpreter_model(self) -> str:
        return "recording-model"

    def interpret(self, *, system_instruction: str, payload: dict) -> str:
        self.calls.append({"system_instruction": system_instruction, "payload": payload})
        return f"Explanation for {payload['recipient_role']}."


class MultiModelExplainabilityPathTests(unittest.TestCase):
    """Exercise current trusted plugin through V2 persistence and redacted interpretation."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        rows = 60
        self.frame = pd.DataFrame({
            "company_id": [f"company-{index}" for index in range(rows)],
            "f_a": np.linspace(-1.0, 1.0, rows),
            "f_b": np.tile([0.0, 1.0], rows // 2),
            "target": np.tile([0, 1], rows // 2),
        })
        self.registry = FeatureRegistry(
            "features-multimodel-v1",
            (
                FeatureSpec("feature-a", "f_a", "Показатель A", "Синтетический показатель A.", "base", "float64", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 0),
                FeatureSpec("feature-b", "f_b", "Показатель B", "Синтетический показатель B.", "base", "float64", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 1),
            ),
            (FeatureGroup("base", "Базовые", "Тестовые признаки.", 0, "test", ("feature-a", "feature-b")),),
        )
        self.contract = DatasetContract("dataset-multimodel", "v1", "Synthetic", "ready_csv", "dataset-fingerprint", rows, 4, "target", 1, "company_id", self.registry.registry_id, self.registry.registry_hash, "validated", False)
        self.population = EvaluationPopulation(tuple(range(rows)), "full-v1", "full-fingerprint", "full")
        self.source_hash = sha256(self.frame.to_csv(index=False).encode("utf-8")).hexdigest()
        self.plugins = build_builtin_model_plugin_registry()
        self.model_ids = ("catboost", "xgboost", "lightgbm")
        self.store = ModelVersionStore(
            Path(self.temp.name) / "models", code_version="multimodel-test-v1",
            model_specs={model_id: self.plugins.get(model_id).spec for model_id in self.model_ids},
            model_plugin_registry=self.plugins,
        )
        self.client = _RecordingInterpreterClient()
        self.workflow = IntegrationWorkflowService(
            final_model_training_service=SimpleNamespace(model_version_store=self.store),
            model_version_store=self.store, model_inference_service=ModelInferenceService(),
            model_plugin_registry=self.plugins,
            result_interpreter_service=ResultInterpreterService(), result_interpreter_client=self.client,
            outbound_interpreter_policy=RedactedV1OutboundPolicy(),
            result_interpreter_runtime=ResultInterpreterRuntimeConfiguration(
                policy_mode="REDACTED_V1", provider_configured=True, provider_registered=True,
                model_configured=True, credentials_configured=True,
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_current_model_version_v2_to_interpreter_for_all_supported_models(self) -> None:
        for model_id in self.model_ids:
            with self.subTest(model_id=model_id):
                plugin = self.plugins.get(model_id)
                resolved = ModelConfigurationService(self.plugins).resolve(model_id=model_id, mode=ModelConfigurationMode.RECOMMENDED)
                record = ModelConfigurationRecord.from_resolved(resolved, plugin)
                config = ExperimentConfig(
                    f"experiment-{model_id}", self.contract.dataset_id, self.contract.dataset_fingerprint,
                    self.contract.target_column, ("feature-a", "feature-b"), None, ("base",), model_id,
                    plugin.spec.version, resolved.resolved_parameters_dict(), "stratified_kfold_oof", "1", 17, 3, "oof", None, None, (),
                )
                adapter = plugin.factory.create(config.model_parameters, config.seed)
                adapter.fit(self.frame.loc[:, ["f_a", "f_b"]], self.frame["target"])
                summary = self.store.save(
                    experiment_artifact_id=f"artifact-{model_id}", dataset_contract=self.contract, config=config,
                    feature_specs=self.registry.resolve(config.feature_ids), feature_registry=self.registry,
                    population=self.population, adapter=adapter, source_file_sha256=self.source_hash,
                    configuration_record=record,
                )
                loaded = self.store.load(summary.model_version_id, dataset_contract=self.contract, config=config, feature_registry=self.registry, population=self.population)
                self.assertEqual(2, loaded.metadata["schema_version"])
                self.assertEqual(summary.model_version_id, loaded.summary.model_version_id)
                self.assertEqual(tuple(loaded.metadata["feature_columns"]), loaded.predictor.feature_columns)
                self.assertEqual(("f_a", "f_b"), loaded.predictor.feature_columns)

                prediction = self.workflow.predict(loaded_model_version=loaded, snapshot=self._snapshot(model_id))
                evidence = self.workflow.explain(loaded_model_version=loaded, prediction_batch=prediction, row_id=prediction.rows[0].row_id)
                repeated = self.workflow.explain(loaded_model_version=loaded, prediction_batch=prediction, row_id=prediction.rows[0].row_id)
                self.assertEqual(model_id, evidence.model_id)
                self.assertEqual(plugin.local_explanation_provider.provider_id, evidence.provider_id)
                self.assertEqual(plugin.local_explanation_provider.provider_id, evidence.explainer_id)
                self.assertEqual(evidence.evidence_hash, repeated.evidence_hash)
                self.assertAlmostEqual(prediction.rows[0].probability, evidence.probability, places=9)
                self.assertAlmostEqual(evidence.raw_model_output, evidence.base_value + sum(item.shap_value for item in evidence.features), places=5)
                sigmoid = 1 / (1 + np.exp(-evidence.raw_model_output))
                self.assertAlmostEqual(sigmoid, evidence.probability, places=7)

                for role in RESULT_INTERPRETER_ROLES:
                    request = self.workflow.prepare_interpretation(evidence=evidence, loaded_model_version=loaded, recipient_role=role)
                    outcome = self.workflow.interpret(request=request)
                    self.assertEqual((f"result_interpreter/{role}", "1", request.prompt_hash), (outcome.response.prompt_id, outcome.response.prompt_version, outcome.response.prompt_hash))
                    self.assertEqual((request.prompt_id, request.prompt_version, request.prompt_hash), (outcome.dispatch_receipt.prompt_id, outcome.dispatch_receipt.prompt_version, outcome.dispatch_receipt.prompt_hash))
                    payload = self.client.calls[-1]["payload"]
                    self.assertEqual({"recipient_role", "prediction", "explanation", "top_features"}, set(payload))
                    serialized = canonical_json(payload)
                    for forbidden in ("identifier", "company_id", "row_id", "raw_value", "raw_model_output", "base_value", "provenance", "evidence_hash", "model_version_id", "dataset_id", "experiment_artifact_id"):
                        self.assertNotIn(forbidden, serialized)

        self.assertEqual(12, len(self.client.calls))

    def test_gbdt_mean_local_explanation_uses_registered_provider(self) -> None:
        mean = SimpleNamespace(summary=SimpleNamespace(model_id="gbdt_mean"))
        capability = self.workflow.capabilities(loaded_model_version=mean, prediction_batch=object(), selected_row_id="row-1")["local_explanation"]
        self.assertEqual(("AVAILABLE", "LOCAL_EXPLAINER_READY"), (capability.state, capability.reason_code))

    def _snapshot(self, model_id: str) -> TabularSnapshot:
        dataframe = pd.DataFrame({"company_id": ["secret-company", "second-company"], "f_a": [-0.35, 0.65], "f_b": [1.0, 0.0], "ignored_note": [10, 20]})
        digest = sha256(dataframe.to_csv(index=False).encode("utf-8")).hexdigest()
        return TabularSnapshot(Path(self.temp.name) / f"inference-{model_id}.csv", "csv", {"separator": ",", "encoding": "utf-8"}, digest, f"inference-{model_id}", len(dataframe), len(dataframe.columns), dataframe, tuple(dataframe.columns))


if __name__ == "__main__":
    unittest.main()
