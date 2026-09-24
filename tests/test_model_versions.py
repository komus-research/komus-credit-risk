from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from komus_risk.application import FinalModelTrainingService
from komus_risk.artifacts import ExperimentArtifactStore, ModelVersionStore
from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput
from komus_risk.models.gbdt import (
    CATBOOST_MODEL_SPEC, CATBOOST_PROFILE, GBDT_MEAN_PROFILE, LIGHTGBM_PROFILE,
    XGBOOST_PROFILE, CatBoostAdapter, CatBoostFactory, GBDTMeanAdapter, GBDTMeanFactory, LightGBMFactory, XGBoostFactory,
)
from komus_risk.models.gbdt.native import load_native_predictor, save_native_model, validate_fitted_adapter_recipe
from komus_risk.registries import FeatureRegistry, ModelRegistry


class ModelVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "dataset.csv"
        rows = 40
        self.frame = pd.DataFrame({"id": range(rows), "f_a": np.linspace(0, 1, rows), "f_b": np.tile([0.0, 1.0], rows // 2), "target": np.tile([0, 1], rows // 2)})
        self.frame.to_csv(self.source, index=False)
        self.registry = FeatureRegistry(
            "features-v1",
            (
                FeatureSpec("f_a", "f_a", "A", "A", "base", "float64", "numeric", "source", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 0),
                FeatureSpec("f_b", "f_b", "B", "B", "base", "float64", "numeric", "source", FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 1),
            ),
            (FeatureGroup("base", "Base", "Base", 0, "source", ("f_a", "f_b")),),
        )
        self.contract = DatasetContract("dataset", "v1", "Synthetic", "ready_csv", "fingerprint", rows, 4, "target", 1, "id", self.registry.registry_id, self.registry.registry_hash, "validated", True)
        self.loaded = LoadedDataset(self.frame, self.contract, self.source, "csv", sha256(self.source.read_bytes()).hexdigest())
        self.population = EvaluationPopulation(tuple(range(rows)), "working-v1", "population-sha", "working")
        self.config = ExperimentConfig("experiment-v1", "dataset", "fingerprint", "target", ("f_a", "f_b"), None, ("base",), "catboost", "accepted_stage1_v2", CATBOOST_PROFILE, "stratified_kfold_oof", "1", 7, 2, "oof", None, None, ())
        result = ExperimentResult("result-v1", self.config.experiment_id, self.config.config_hash, "fingerprint", self.config.feature_set_hash, "catboost", "accepted_stage1_v2", "oof", {"roc_auc": 0.5}, {"threshold": 0.5}, ({"fold": 1}, {"fold": 2}), 0.0, {}, "code-v1", datetime.now(timezone.utc).isoformat(), ())
        self.output = ExperimentRunOutput(result, np.full(rows, 0.5), np.tile([1, 2], rows // 2), self.population.row_positions, self.population.population_id, self.population.population_fingerprint)
        self.experiments = ExperimentArtifactStore(root / "experiments")
        self.artifact = self.experiments.save(config=self.config, dataset_contract=self.contract, population=self.population, run_output=self.output)
        registry = ModelRegistry(); registry.register(CATBOOST_MODEL_SPEC)
        self.versions = ModelVersionStore(root / "models", code_version="code-v1", model_specs={"catboost": CATBOOST_MODEL_SPEC})
        self.service = FinalModelTrainingService(experiment_artifact_store=self.experiments, model_version_store=self.versions, model_registry=registry, model_factories={"catboost": CatBoostFactory()}, code_version="code-v1")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_final_fit_persists_and_native_reload_preserves_prediction(self) -> None:
        saved = self.service.train(experiment_artifact_id=self.artifact.artifact_id, loaded_dataset=self.loaded, feature_registry=self.registry, population=self.population)
        X = self.frame.loc[:, ["f_a", "f_b"]]
        loaded = self.versions.load(saved.model_version_id, dataset_contract=self.contract, config=self.config, feature_registry=self.registry, population=self.population)
        expected = CatBoostFactory().create(CATBOOST_PROFILE, self.config.seed)
        expected.fit(X, self.frame["target"])
        np.testing.assert_allclose(expected.predict_positive_proba(X), loaded.predictor.predict_positive_proba(X), rtol=1e-10, atol=1e-12)
        self.assertEqual(loaded.metadata["experiment_artifact_id"], self.artifact.artifact_id)
        self.assertEqual(loaded.metadata["feature_ids"], ["f_a", "f_b"])
        with self.assertRaisesRegex(ValueError, "exact persisted"):
            loaded.predictor.predict_positive_proba(X.loc[:, ["f_b", "f_a"]])

    def test_mismatches_and_locked_final_test_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires the working"):
            self.service.train(experiment_artifact_id=self.artifact.artifact_id, loaded_dataset=self.loaded, feature_registry=self.registry, population=EvaluationPopulation(self.population.row_positions, "full-v1", "full-sha", "full"))
        with self.assertRaisesRegex(ValueError, "changed"):
            self.source.write_text("changed", encoding="utf-8")
            self.service.train(experiment_artifact_id=self.artifact.artifact_id, loaded_dataset=self.loaded, feature_registry=self.registry, population=self.population)

    def test_generic_dataset_requires_and_allows_full_population(self) -> None:
        generic_contract = DatasetContract("dataset", "v1", "Synthetic", "ready_csv", "fingerprint", len(self.frame), 4, "target", 1, "id", self.registry.registry_id, self.registry.registry_hash, "validated", False)
        generic_population = EvaluationPopulation(tuple(range(len(self.frame))), "full-v1", "full-sha", "full")
        generic_output = ExperimentRunOutput(self.output.result, self.output.oof_positive_proba, self.output.fold_assignments, generic_population.row_positions, generic_population.population_id, generic_population.population_fingerprint)
        artifact = self.experiments.save(config=self.config, dataset_contract=generic_contract, population=generic_population, run_output=generic_output)
        loaded = LoadedDataset(self.frame, generic_contract, self.source, "csv", self.loaded.source_file_sha256)
        saved = self.service.train(experiment_artifact_id=artifact.artifact_id, loaded_dataset=loaded, feature_registry=self.registry, population=generic_population)
        self.assertEqual(saved.model_id, "catboost")

    def test_corrupt_native_file_or_manifest_is_rejected(self) -> None:
        saved = self.service.train(experiment_artifact_id=self.artifact.artifact_id, loaded_dataset=self.loaded, feature_registry=self.registry, population=self.population)
        version_dir = Path(self.temp.name) / "models" / saved.model_version_id
        native = version_dir / "native" / "model.cbm"
        native.write_bytes(native.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.versions.load(saved.model_version_id)

    def test_corrupt_manifest_is_rejected(self) -> None:
        saved = self.service.train(experiment_artifact_id=self.artifact.artifact_id, loaded_dataset=self.loaded, feature_registry=self.registry, population=self.population)
        manifest = Path(self.temp.name) / "models" / saved.model_version_id / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.versions.load(saved.model_version_id)

    def test_native_roundtrip_for_xgboost_lightgbm_and_gbdt_mean(self) -> None:
        X = self.frame.loc[:, ["f_a", "f_b"]]
        y = self.frame["target"]
        mean_factory = GBDTMeanFactory({"catboost": CatBoostFactory(), "xgboost": XGBoostFactory(), "lightgbm": LightGBMFactory()})
        for model_id, factory, profile in (
            ("xgboost", XGBoostFactory(), XGBOOST_PROFILE),
            ("lightgbm", LightGBMFactory(), LIGHTGBM_PROFILE),
            ("gbdt_mean", mean_factory, GBDT_MEAN_PROFILE),
        ):
            with self.subTest(model_id=model_id):
                adapter = factory.create(profile, seed=19)
                adapter.fit(X, y)
                directory = Path(self.temp.name) / f"native-{model_id}"
                save_native_model(model_id, adapter, directory)
                restored = load_native_predictor(model_id, directory, ("f_a", "f_b"))
                np.testing.assert_allclose(adapter.predict_positive_proba(X), restored.predict_positive_proba(X), rtol=1e-8, atol=1e-10)

    def test_store_enforces_current_code_recipe_and_feature_registry_boundaries(self) -> None:
        saved = self.service.train(experiment_artifact_id=self.artifact.artifact_id, loaded_dataset=self.loaded, feature_registry=self.registry, population=self.population)
        root = Path(self.temp.name) / "models"
        with self.assertRaisesRegex(ValueError, "code identity"):
            ModelVersionStore(root, code_version="other-code", model_specs={"catboost": CATBOOST_MODEL_SPEC}).load(saved.model_version_id)
        with self.assertRaises(ValueError):
            ModelVersionStore(root, code_version="code-v1", model_specs={"catboost": replace(CATBOOST_MODEL_SPEC, default_profile={})}).load(saved.model_version_id)
        with self.assertRaises(ValueError):
            ModelVersionStore(root, code_version="code-v1", model_specs={"catboost": replace(CATBOOST_MODEL_SPEC, adapter_version="other")}).load(saved.model_version_id)

        original = self.registry.resolve(self.config.feature_ids)
        with self.assertRaisesRegex(ValueError, "frozen ModelSpec"):
            self.versions.save(experiment_artifact_id=self.artifact.artifact_id, dataset_contract=self.contract, config=replace(self.config, model_parameters={}), feature_specs=original, feature_registry=self.registry, population=self.population, adapter=object(), source_file_sha256=self.loaded.source_file_sha256)
        diagnostic = (replace(original[0], usage_status=FeatureUsageStatus.DIAGNOSTIC_ONLY), original[1])
        duplicate_column = (original[0], replace(original[1], column_name="f_a"))
        target_feature = (replace(original[0], column_name="target", usage_status=FeatureUsageStatus.TARGET), original[1])
        identifier_feature = (replace(original[0], column_name="id", usage_status=FeatureUsageStatus.IDENTIFIER), original[1])
        for label, specs in (("diagnostic", diagnostic), ("duplicate", duplicate_column), ("target", target_feature), ("identifier", identifier_feature)):
            with self.subTest(label=label):
                registry = FeatureRegistry(f"{label}-registry", specs, (FeatureGroup("base", "Base", "Base", 0, "source", ("f_a", "f_b")),))
                contract = replace(self.contract, feature_registry_id=registry.registry_id, feature_registry_hash=registry.registry_hash)
                with self.assertRaises(ValueError):
                    self.versions.save(experiment_artifact_id=self.artifact.artifact_id, dataset_contract=contract, config=self.config, feature_specs=specs, feature_registry=registry, population=self.population, adapter=object(), source_file_sha256=self.loaded.source_file_sha256)
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.versions.save(experiment_artifact_id=self.artifact.artifact_id, dataset_contract=self.contract, config=self.config, feature_specs=original, feature_registry=FeatureRegistry("other-registry", original, (FeatureGroup("base", "Base", "Base", 0, "source", ("f_a", "f_b")),)), population=self.population, adapter=object(), source_file_sha256=self.loaded.source_file_sha256)

    def test_store_rejects_actual_adapter_mismatch_before_publication(self) -> None:
        X = self.frame.loc[:, ["f_a", "f_b"]]
        wrong_seed = CatBoostFactory().create(CATBOOST_PROFILE, self.config.seed + 1)
        wrong_seed.fit(X, self.frame["target"])
        root = Path(self.temp.name) / "models"
        before = set(root.iterdir())
        with self.assertRaisesRegex(ValueError, "profile or seed"):
            self.versions.save(experiment_artifact_id=self.artifact.artifact_id, dataset_contract=self.contract, config=self.config, feature_specs=self.registry.resolve(self.config.feature_ids), feature_registry=self.registry, population=self.population, adapter=wrong_seed, source_file_sha256=self.loaded.source_file_sha256)
        self.assertEqual(before, set(root.iterdir()))
        with self.assertRaisesRegex(ValueError, "adapter type"):
            self.versions.save(experiment_artifact_id=self.artifact.artifact_id, dataset_contract=self.contract, config=self.config, feature_specs=self.registry.resolve(self.config.feature_ids), feature_registry=self.registry, population=self.population, adapter=object(), source_file_sha256=self.loaded.source_file_sha256)
        incomplete_mean = GBDTMeanAdapter({})
        incomplete_mean._fitted = True
        with self.assertRaisesRegex(ValueError, "components"):
            validate_fitted_adapter_recipe("gbdt_mean", incomplete_mean, GBDT_MEAN_PROFILE, self.config.seed)

    def test_store_rejects_subclass_adapter_before_publication(self) -> None:
        class SubclassedCatBoostAdapter(CatBoostAdapter):
            pass

        X = self.frame.loc[:, ["f_a", "f_b"]]
        adapter = SubclassedCatBoostAdapter(CATBOOST_PROFILE, self.config.seed)
        adapter.fit(X, self.frame["target"])
        root = Path(self.temp.name) / "models"
        before = set(root.iterdir())
        with self.assertRaisesRegex(ValueError, "adapter type"):
            self.versions.save(experiment_artifact_id=self.artifact.artifact_id, dataset_contract=self.contract, config=self.config, feature_specs=self.registry.resolve(self.config.feature_ids), feature_registry=self.registry, population=self.population, adapter=adapter, source_file_sha256=self.loaded.source_file_sha256)
        self.assertEqual(before, set(root.iterdir()))
