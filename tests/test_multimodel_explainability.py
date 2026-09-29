from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from komus_risk.application import (
    IntegrationWorkflowService,
    LocalExplanationService,
    ModelInferenceService,
    RedactedV1OutboundPolicy,
    RESULT_INTERPRETER_ROLES,
    ResultInterpreterRuntimeConfiguration,
    ResultInterpreterService,
)
from komus_risk.artifacts import ModelVersionStore, ModelVersionSummary
from komus_risk.contracts import (
    DatasetContract,
    ExperimentConfig,
    FeatureGroup,
    FeatureSpec,
    FeatureUsageStatus,
)
from komus_risk.data import TabularSnapshot
from komus_risk.experiments import EvaluationPopulation
from komus_risk.hashing import canonical_json
from komus_risk.models.gbdt import (
    CATBOOST_MODEL_SPEC,
    CATBOOST_PROFILE,
    LIGHTGBM_MODEL_SPEC,
    LIGHTGBM_PROFILE,
    XGBOOST_MODEL_SPEC,
    XGBOOST_PROFILE,
    CatBoostFactory,
    LightGBMFactory,
    XGBoostFactory,
)
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
    """Exercise the persisted-model path without replacing the external privacy boundary."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
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
                FeatureSpec(
                    "feature-a", "f_a", "Показатель A", "Синтетический показатель A.",
                    "base", "float64", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED,
                    None, None, None, 0,
                ),
                FeatureSpec(
                    "feature-b", "f_b", "Показатель B", "Синтетический показатель B.",
                    "base", "float64", "numeric", "test", FeatureUsageStatus.MODEL_ALLOWED,
                    None, None, None, 1,
                ),
            ),
            (FeatureGroup("base", "Базовые", "Тестовые признаки.", 0, "test", ("feature-a", "feature-b")),),
        )
        self.contract = DatasetContract(
            "dataset-multimodel", "v1", "Synthetic", "ready_csv", "dataset-fingerprint",
            rows, 4, "target", 1, "company_id", self.registry.registry_id,
            self.registry.registry_hash, "validated", False,
        )
        self.population = EvaluationPopulation(tuple(range(rows)), "full-v1", "full-fingerprint", "full")
        self.source_hash = sha256(self.frame.to_csv(index=False).encode("utf-8")).hexdigest()
        self.specs = {
            spec.model_id: spec
            for spec in (CATBOOST_MODEL_SPEC, XGBOOST_MODEL_SPEC, LIGHTGBM_MODEL_SPEC)
        }
        self.store = ModelVersionStore(root / "models", code_version="multimodel-test-v1", model_specs=self.specs)
        self.client = _RecordingInterpreterClient()
        self.workflow = IntegrationWorkflowService(
            final_model_training_service=SimpleNamespace(model_version_store=self.store),
            model_version_store=self.store,
            model_inference_service=ModelInferenceService(),
            local_explainers={
                model_id: LocalExplanationService()
                for model_id in ("catboost", "xgboost", "lightgbm")
            },
            result_interpreter_service=ResultInterpreterService(),
            result_interpreter_client=self.client,
            outbound_interpreter_policy=RedactedV1OutboundPolicy(),
            result_interpreter_runtime=ResultInterpreterRuntimeConfiguration(
                policy_mode="REDACTED_V1",
                provider_configured=True,
                provider_registered=True,
                model_configured=True,
                credentials_configured=True,
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_save_load_inference_shap_and_llm_for_each_supported_model(self) -> None:
        X = self.frame.loc[:, ["f_a", "f_b"]]
        y = self.frame.loc[:, "target"]
        cases = (
            ("catboost", CatBoostFactory(), CATBOOST_PROFILE),
            ("xgboost", XGBoostFactory(), XGBOOST_PROFILE),
            ("lightgbm", LightGBMFactory(), LIGHTGBM_PROFILE),
        )

        for model_id, factory, profile in cases:
            with self.subTest(model_id=model_id):
                config = ExperimentConfig(
                    f"experiment-{model_id}", self.contract.dataset_id,
                    self.contract.dataset_fingerprint, self.contract.target_column,
                    ("feature-a", "feature-b"), None, ("base",), model_id,
                    self.specs[model_id].version, profile, "stratified_kfold_oof", "1",
                    17, 3, "oof", None, None, (),
                )
                adapter = factory.create(profile, config.seed)
                adapter.fit(X, y)
                summary = self.store.save(
                    experiment_artifact_id=f"artifact-{model_id}",
                    dataset_contract=self.contract,
                    config=config,
                    feature_specs=self.registry.resolve(config.feature_ids),
                    feature_registry=self.registry,
                    population=self.population,
                    adapter=adapter,
                    source_file_sha256=self.source_hash,
                )
                loaded = self.store.load(
                    summary.model_version_id,
                    dataset_contract=self.contract,
                    config=config,
                    feature_registry=self.registry,
                    population=self.population,
                )
                snapshot = self._inference_snapshot(model_id)
                prediction = self.workflow.predict(loaded_model_version=loaded, snapshot=snapshot)
                evidence = self.workflow.explain(
                    loaded_model_version=loaded,
                    prediction_batch=prediction,
                    row_id=prediction.rows[0].row_id,
                )

                self.assertEqual(model_id, loaded.summary.model_id)
                self.assertEqual(model_id, evidence.model_id)
                self.assertAlmostEqual(prediction.rows[0].probability, evidence.probability, places=7)
                self.assertAlmostEqual(
                    evidence.raw_model_output,
                    evidence.base_value + sum(item.shap_value for item in evidence.features),
                    places=6,
                )

                for role in RESULT_INTERPRETER_ROLES:
                    request = self.workflow.prepare_interpretation(
                        evidence=evidence,
                        loaded_model_version=loaded,
                        recipient_role=role,
                    )
                    outcome = self.workflow.interpret(request=request)
                    self.assertIn(role, outcome.response.text)
                    self.assertEqual("REDACTED_V1", outcome.dispatch_receipt.policy_id)

        self.assertEqual(12, len(self.client.calls))
        for call in self.client.calls:
            payload = call["payload"]
            self.assertEqual(
                {"recipient_role", "prediction", "explanation", "top_features"},
                set(payload),
            )
            self.assertEqual({"shap_output_space"}, set(payload["explanation"]))
            for feature in payload["top_features"]:
                self.assertNotIn("raw_value", feature)
            serialized = canonical_json(payload)
            self.assertNotIn("secret-company", serialized)
            self.assertNotIn("row_id", serialized)
            self.assertNotIn("raw_model_output", serialized)
            self.assertNotIn("base_value", serialized)

    def test_probability_mean_ensemble_remains_explicitly_unsupported(self) -> None:
        ensemble = SimpleNamespace(
            summary=ModelVersionSummary(
                "mean-version", "mean-artifact", "gbdt_mean", "accepted_stage1_v2",
                ("feature-a", "feature-b"),
            ),
        )
        capability = self.workflow.capabilities(
            loaded_model_version=ensemble,
            prediction_batch=object(),
            selected_row_id="row-1",
        )["local_explanation"]

        self.assertEqual("UNSUPPORTED", capability.state)
        self.assertEqual("LOCAL_EXPLAINER_NOT_REGISTERED", capability.reason_code)

    def _inference_snapshot(self, model_id: str) -> TabularSnapshot:
        dataframe = pd.DataFrame({
            "company_id": ["secret-company", "second-company"],
            "f_a": [-0.35, 0.65],
            "f_b": [1.0, 0.0],
            "ignored_note": [10, 20],
        })
        digest = sha256(dataframe.to_csv(index=False).encode("utf-8")).hexdigest()
        return TabularSnapshot(
            source_path=Path(self.temp.name) / f"inference-{model_id}.csv",
            source_format="csv",
            read_options={"separator": ",", "encoding": "utf-8"},
            source_file_sha256=digest,
            fingerprint=f"inference-{model_id}",
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            dataframe=dataframe,
            physical_headers=tuple(dataframe.columns),
        )


if __name__ == "__main__":
    unittest.main()
