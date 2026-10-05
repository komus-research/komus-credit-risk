from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from komus_risk.application import FinalModelTrainingService, ModelLibraryService
from komus_risk.artifacts import (
    ExperimentArtifactStore,
    ModelLibraryRecord,
    ModelLibraryRecordStore,
    ModelVersionStore,
)
from komus_risk.contracts import (
    DatasetContract,
    ExperimentConfig,
    ExperimentResult,
    FeatureGroup,
    FeatureSpec,
    FeatureUsageStatus,
)
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput
from komus_risk.model_platform import (
    ModelConfigurationMode,
    ModelConfigurationRecord,
    ModelConfigurationService,
    ModelConfigurationSmokeTestService,
    build_builtin_model_plugin_registry,
)
from komus_risk.models.gbdt import (
    CATBOOST_MODEL_SPEC,
    CATBOOST_PROFILE,
    GBDT_MEAN_PROFILE,
    LIGHTGBM_PROFILE,
    XGBOOST_PROFILE,
    CatBoostAdapter,
    CatBoostFactory,
    GBDTMeanAdapter,
    GBDTMeanFactory,
    LightGBMFactory,
    XGBoostFactory,
)
from komus_risk.models.gbdt.native import (
    load_native_predictor,
    save_native_model,
    validate_fitted_adapter_recipe,
)
from komus_risk.preparation import PreparedDatasetContext
from komus_risk.registries import FeatureRegistry, ModelRegistry


class ModelVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "dataset.csv"
        rows = 40
        self.frame = pd.DataFrame(
            {
                "id": range(rows),
                "f_a": np.linspace(0, 1, rows),
                "f_b": np.tile([0.0, 1.0], rows // 2),
                "target": np.tile([0, 1], rows // 2),
            }
        )
        self.frame.to_csv(self.source, index=False)
        self.registry = FeatureRegistry(
            "features-v1",
            (
                FeatureSpec(
                    "f_a",
                    "f_a",
                    "A",
                    "A",
                    "base",
                    "float64",
                    "numeric",
                    "source",
                    FeatureUsageStatus.MODEL_ALLOWED,
                    None,
                    None,
                    None,
                    0,
                ),
                FeatureSpec(
                    "f_b",
                    "f_b",
                    "B",
                    "B",
                    "base",
                    "float64",
                    "numeric",
                    "source",
                    FeatureUsageStatus.MODEL_ALLOWED,
                    None,
                    None,
                    None,
                    1,
                ),
            ),
            (FeatureGroup("base", "Base", "Base", 0, "source", ("f_a", "f_b")),),
        )
        self.contract = DatasetContract(
            "dataset",
            "v1",
            "Synthetic",
            "ready_csv",
            "fingerprint",
            rows,
            4,
            "target",
            1,
            "id",
            self.registry.registry_id,
            self.registry.registry_hash,
            "validated",
            True,
        )
        self.loaded = LoadedDataset(
            self.frame,
            self.contract,
            self.source,
            "csv",
            sha256(self.source.read_bytes()).hexdigest(),
        )
        self.population = EvaluationPopulation(
            tuple(range(rows)), "working-v1", "population-sha", "working"
        )
        self.config = ExperimentConfig(
            "experiment-v1",
            "dataset",
            "fingerprint",
            "target",
            ("f_a", "f_b"),
            None,
            ("base",),
            "catboost",
            "accepted_stage1_v2",
            CATBOOST_PROFILE,
            "stratified_kfold_oof",
            "1",
            7,
            2,
            "oof",
            None,
            None,
            (),
        )
        result = ExperimentResult(
            "result-v1",
            self.config.experiment_id,
            self.config.config_hash,
            "fingerprint",
            self.config.feature_set_hash,
            "catboost",
            "accepted_stage1_v2",
            "oof",
            {"roc_auc": 0.5},
            {"threshold": 0.5},
            ({"fold": 1}, {"fold": 2}),
            0.0,
            {},
            "code-v1",
            datetime.now(timezone.utc).isoformat(),
            (),
        )
        self.output = ExperimentRunOutput(
            result,
            np.full(rows, 0.5),
            np.tile([1, 2], rows // 2),
            self.population.row_positions,
            self.population.population_id,
            self.population.population_fingerprint,
        )
        self.experiments = ExperimentArtifactStore(root / "experiments")
        self.artifact = self.experiments.save(
            config=self.config,
            dataset_contract=self.contract,
            population=self.population,
            run_output=self.output,
        )
        registry = ModelRegistry()
        registry.register(CATBOOST_MODEL_SPEC)
        self.versions = ModelVersionStore(
            root / "models",
            code_version="code-v1",
            model_specs={"catboost": CATBOOST_MODEL_SPEC},
        )
        self.service = FinalModelTrainingService(
            experiment_artifact_store=self.experiments,
            model_version_store=self.versions,
            model_registry=registry,
            model_factories={"catboost": CatBoostFactory()},
            code_version="code-v1",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_final_fit_persists_and_native_reload_preserves_prediction(self) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        X = self.frame.loc[:, ["f_a", "f_b"]]
        loaded = self.versions.load(
            saved.model_version_id,
            dataset_contract=self.contract,
            config=self.config,
            feature_registry=self.registry,
            population=self.population,
        )
        expected = CatBoostFactory().create(CATBOOST_PROFILE, self.config.seed)
        expected.fit(X, self.frame["target"])
        np.testing.assert_allclose(
            expected.predict_positive_proba(X),
            loaded.predictor.predict_positive_proba(X),
            rtol=1e-10,
            atol=1e-12,
        )
        self.assertEqual(
            loaded.metadata["experiment_artifact_id"], self.artifact.artifact_id
        )
        self.assertEqual(loaded.metadata["feature_ids"], ["f_a", "f_b"])
        with self.assertRaisesRegex(ValueError, "exact persisted"):
            loaded.predictor.predict_positive_proba(X.loc[:, ["f_b", "f_a"]])

    def test_metadata_lookup_finds_only_the_matching_experiment(self) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )

        assert self.versions.find_by_experiment_artifact_id(self.artifact.artifact_id) == (saved,)
        assert self.versions.find_by_experiment_artifact_id("other-artifact") == ()

    def test_metadata_lookup_rejects_corrupt_native_payload_without_predictor_load(self) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        native = Path(self.temp.name) / "models" / saved.model_version_id / "native" / "model.cbm"
        native.write_bytes(native.read_bytes() + b"corrupt")

        with patch(
            "komus_risk.artifacts.model_store.load_native_predictor",
            side_effect=AssertionError("metadata lookup must not load a predictor"),
        ):
            with self.assertRaisesRegex(ValueError, "metadata lookup"):
                self.versions.find_by_experiment_artifact_id(self.artifact.artifact_id)

    def test_browse_metadata_validates_versions_without_native_predictor_load(self) -> None:
        first = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        second = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        with patch(
            "komus_risk.artifacts.model_store.load_native_predictor",
            side_effect=AssertionError("metadata browse must not load a predictor"),
        ):
            metadata = self.versions.browse_metadata()

        self.assertEqual(
            {item.summary.model_version_id for item in metadata},
            {first.model_version_id, second.model_version_id},
        )

    def test_library_detail_projects_v1_persisted_adapter_and_omits_v2_only_provenance(self) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        records = ModelLibraryRecordStore(Path(self.temp.name) / "library")
        records.save(ModelLibraryRecord(
            1, self.artifact.artifact_id, saved.model_version_id,
            "CatBoost — Synthetic — v1", "v1", "2026-10-05T10:00:00+00:00",
        ))
        source = SimpleNamespace(read_metadata=lambda artifact_id: SimpleNamespace(
            artifact_id=artifact_id,
            result=SimpleNamespace(
                result_id="result-exact", created_at="2026-10-05T10:00:00+00:00",
                metrics={"gini": 0.4, "roc_auc": 0.7, "pr_auc": 0.6, "precision_at_0_5": 0.5, "recall_at_0_5": 0.8, "f1_at_0_5": 0.61},
            ),
        ))
        detail = ModelLibraryService(
            record_store=records,
            model_version_store=self.versions,
            integration_workflow_service=SimpleNamespace(),
            experiment_artifact_store=source,
        ).detail(saved.model_version_id).value

        self.assertEqual(
            detail["algorithm"]["adapter_version"],
            CATBOOST_MODEL_SPEC.adapter_version,
        )
        self.assertNotIn("plugin_contract_hash", detail["technical_provenance"])
        self.assertNotIn("configuration_record_id", detail["technical_provenance"])

    def test_mismatches_and_locked_final_test_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires the working"):
            self.service.train(
                experiment_artifact_id=self.artifact.artifact_id,
                loaded_dataset=self.loaded,
                feature_registry=self.registry,
                population=EvaluationPopulation(
                    self.population.row_positions, "full-v1", "full-sha", "full"
                ),
            )
        with self.assertRaisesRegex(ValueError, "MODEL_SAVE_SOURCE_CHANGED"):
            self.source.write_text("changed", encoding="utf-8")
            self.service.train(
                experiment_artifact_id=self.artifact.artifact_id,
                loaded_dataset=self.loaded,
                feature_registry=self.registry,
                population=self.population,
            )

    def test_generic_dataset_requires_and_allows_full_population(self) -> None:
        generic_contract = DatasetContract(
            "dataset",
            "v1",
            "Synthetic",
            "ready_csv",
            "fingerprint",
            len(self.frame),
            4,
            "target",
            1,
            "id",
            self.registry.registry_id,
            self.registry.registry_hash,
            "validated",
            False,
        )
        generic_population = EvaluationPopulation(
            tuple(range(len(self.frame))), "full-v1", "full-sha", "full"
        )
        generic_output = ExperimentRunOutput(
            self.output.result,
            self.output.oof_positive_proba,
            self.output.fold_assignments,
            generic_population.row_positions,
            generic_population.population_id,
            generic_population.population_fingerprint,
        )
        artifact = self.experiments.save(
            config=self.config,
            dataset_contract=generic_contract,
            population=generic_population,
            run_output=generic_output,
        )
        loaded = LoadedDataset(
            self.frame,
            generic_contract,
            self.source,
            "csv",
            self.loaded.source_file_sha256,
        )
        saved = self.service.train(
            experiment_artifact_id=artifact.artifact_id,
            loaded_dataset=loaded,
            feature_registry=self.registry,
            population=generic_population,
        )
        self.assertEqual(saved.model_id, "catboost")

    def test_corrupt_native_file_or_manifest_is_rejected(self) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        version_dir = Path(self.temp.name) / "models" / saved.model_version_id
        native = version_dir / "native" / "model.cbm"
        native.write_bytes(native.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.versions.load(saved.model_version_id)

    def test_corrupt_manifest_is_rejected(self) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        manifest = (
            Path(self.temp.name) / "models" / saved.model_version_id / "manifest.json"
        )
        manifest.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.versions.load(saved.model_version_id)

    def test_native_roundtrip_for_xgboost_lightgbm_and_gbdt_mean(self) -> None:
        X = self.frame.loc[:, ["f_a", "f_b"]]
        y = self.frame["target"]
        mean_factory = GBDTMeanFactory(
            {
                "catboost": CatBoostFactory(),
                "xgboost": XGBoostFactory(),
                "lightgbm": LightGBMFactory(),
            }
        )
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
                np.testing.assert_allclose(
                    adapter.predict_positive_proba(X),
                    restored.predict_positive_proba(X),
                    rtol=1e-8,
                    atol=1e-10,
                )

    def test_store_enforces_current_code_recipe_and_feature_registry_boundaries(
        self,
    ) -> None:
        saved = self.service.train(
            experiment_artifact_id=self.artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        root = Path(self.temp.name) / "models"
        with self.assertRaisesRegex(ValueError, "code identity"):
            ModelVersionStore(
                root,
                code_version="other-code",
                model_specs={"catboost": CATBOOST_MODEL_SPEC},
            ).load(saved.model_version_id)
        with self.assertRaises(ValueError):
            ModelVersionStore(
                root,
                code_version="code-v1",
                model_specs={
                    "catboost": replace(CATBOOST_MODEL_SPEC, default_profile={})
                },
            ).load(saved.model_version_id)
        with self.assertRaises(ValueError):
            ModelVersionStore(
                root,
                code_version="code-v1",
                model_specs={
                    "catboost": replace(CATBOOST_MODEL_SPEC, adapter_version="other")
                },
            ).load(saved.model_version_id)

        original = self.registry.resolve(self.config.feature_ids)
        with self.assertRaisesRegex(ValueError, "frozen ModelSpec"):
            self.versions.save(
                experiment_artifact_id=self.artifact.artifact_id,
                dataset_contract=self.contract,
                config=replace(self.config, model_parameters={}),
                feature_specs=original,
                feature_registry=self.registry,
                population=self.population,
                adapter=object(),
                source_file_sha256=self.loaded.source_file_sha256,
            )
        diagnostic = (
            replace(original[0], usage_status=FeatureUsageStatus.DIAGNOSTIC_ONLY),
            original[1],
        )
        duplicate_column = (original[0], replace(original[1], column_name="f_a"))
        target_feature = (
            replace(
                original[0],
                column_name="target",
                usage_status=FeatureUsageStatus.TARGET,
            ),
            original[1],
        )
        identifier_feature = (
            replace(
                original[0],
                column_name="id",
                usage_status=FeatureUsageStatus.IDENTIFIER,
            ),
            original[1],
        )
        for label, specs in (
            ("diagnostic", diagnostic),
            ("duplicate", duplicate_column),
            ("target", target_feature),
            ("identifier", identifier_feature),
        ):
            with self.subTest(label=label):
                registry = FeatureRegistry(
                    f"{label}-registry",
                    specs,
                    (
                        FeatureGroup(
                            "base", "Base", "Base", 0, "source", ("f_a", "f_b")
                        ),
                    ),
                )
                contract = replace(
                    self.contract,
                    feature_registry_id=registry.registry_id,
                    feature_registry_hash=registry.registry_hash,
                )
                with self.assertRaises(ValueError):
                    self.versions.save(
                        experiment_artifact_id=self.artifact.artifact_id,
                        dataset_contract=contract,
                        config=self.config,
                        feature_specs=specs,
                        feature_registry=registry,
                        population=self.population,
                        adapter=object(),
                        source_file_sha256=self.loaded.source_file_sha256,
                    )
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.versions.save(
                experiment_artifact_id=self.artifact.artifact_id,
                dataset_contract=self.contract,
                config=self.config,
                feature_specs=original,
                feature_registry=FeatureRegistry(
                    "other-registry",
                    original,
                    (
                        FeatureGroup(
                            "base", "Base", "Base", 0, "source", ("f_a", "f_b")
                        ),
                    ),
                ),
                population=self.population,
                adapter=object(),
                source_file_sha256=self.loaded.source_file_sha256,
            )

    def test_store_rejects_actual_adapter_mismatch_before_publication(self) -> None:
        X = self.frame.loc[:, ["f_a", "f_b"]]
        wrong_seed = CatBoostFactory().create(CATBOOST_PROFILE, self.config.seed + 1)
        wrong_seed.fit(X, self.frame["target"])
        root = Path(self.temp.name) / "models"
        before = set(root.iterdir())
        with self.assertRaisesRegex(ValueError, "profile or seed"):
            self.versions.save(
                experiment_artifact_id=self.artifact.artifact_id,
                dataset_contract=self.contract,
                config=self.config,
                feature_specs=self.registry.resolve(self.config.feature_ids),
                feature_registry=self.registry,
                population=self.population,
                adapter=wrong_seed,
                source_file_sha256=self.loaded.source_file_sha256,
            )
        self.assertEqual(before, set(root.iterdir()))
        with self.assertRaisesRegex(ValueError, "adapter type"):
            self.versions.save(
                experiment_artifact_id=self.artifact.artifact_id,
                dataset_contract=self.contract,
                config=self.config,
                feature_specs=self.registry.resolve(self.config.feature_ids),
                feature_registry=self.registry,
                population=self.population,
                adapter=object(),
                source_file_sha256=self.loaded.source_file_sha256,
            )
        incomplete_mean = GBDTMeanAdapter({})
        incomplete_mean._fitted = True
        with self.assertRaisesRegex(ValueError, "components"):
            validate_fitted_adapter_recipe(
                "gbdt_mean", incomplete_mean, GBDT_MEAN_PROFILE, self.config.seed
            )

    def test_store_rejects_subclass_adapter_before_publication(self) -> None:
        class SubclassedCatBoostAdapter(CatBoostAdapter):
            pass

        X = self.frame.loc[:, ["f_a", "f_b"]]
        adapter = SubclassedCatBoostAdapter(CATBOOST_PROFILE, self.config.seed)
        adapter.fit(X, self.frame["target"])
        root = Path(self.temp.name) / "models"
        before = set(root.iterdir())
        with self.assertRaisesRegex(ValueError, "adapter type"):
            self.versions.save(
                experiment_artifact_id=self.artifact.artifact_id,
                dataset_contract=self.contract,
                config=self.config,
                feature_specs=self.registry.resolve(self.config.feature_ids),
                feature_registry=self.registry,
                population=self.population,
                adapter=adapter,
                source_file_sha256=self.loaded.source_file_sha256,
            )
        self.assertEqual(before, set(root.iterdir()))

    def test_v2_provider_save_load_preserves_advanced_configuration(self) -> None:
        plugins = build_builtin_model_plugin_registry()
        resolved = ModelConfigurationService(plugins).resolve(
            model_id="catboost",
            mode=ModelConfigurationMode.ADVANCED,
            user_overrides={"/estimator_params/depth": 6},
        )
        record = ModelConfigurationRecord.from_resolved(
            resolved, plugins.get("catboost")
        )
        config = replace(
            self.config, model_parameters=resolved.resolved_parameters_dict()
        )
        store = ModelVersionStore(
            Path(self.temp.name) / "models-v2",
            code_version="code-v1",
            model_specs={"catboost": CATBOOST_MODEL_SPEC},
            model_plugin_registry=plugins,
        )
        X = self.frame.loc[:, ["f_a", "f_b"]]
        adapter = plugins.get("catboost").factory.create(
            dict(config.model_parameters), config.seed
        )
        adapter.fit(X, self.frame["target"])
        saved = store.save(
            experiment_artifact_id="v2-experiment",
            dataset_contract=self.contract,
            config=config,
            feature_specs=self.registry.resolve(config.feature_ids),
            feature_registry=self.registry,
            population=self.population,
            adapter=adapter,
            source_file_sha256=self.loaded.source_file_sha256,
            configuration_record=record,
        )
        with patch(
            "komus_risk.model_platform.persistence.NativeGBDTPersistenceProvider.load",
            side_effect=AssertionError("metadata browse must not invoke provider.load"),
        ):
            inspected = store.browse_metadata()
            found = store.find_by_experiment_artifact_id("v2-experiment")
        self.assertEqual(inspected[0].summary.model_version_id, saved.model_version_id)
        self.assertEqual(found, (saved,))
        records = ModelLibraryRecordStore(Path(self.temp.name) / "library-v2")
        records.save(ModelLibraryRecord(
            1, "v2-experiment", saved.model_version_id,
            "CatBoost — Synthetic — v1", "v1", "2026-10-05T10:00:00+00:00",
        ))
        source = SimpleNamespace(read_metadata=lambda artifact_id: SimpleNamespace(
            artifact_id=artifact_id,
            result=SimpleNamespace(
                result_id="result-v2", created_at="2026-10-05T10:00:00+00:00",
                metrics={"gini": 0.4, "roc_auc": 0.7, "pr_auc": 0.6, "precision_at_0_5": 0.5, "recall_at_0_5": 0.8, "f1_at_0_5": 0.61},
            ),
        ))
        detail = ModelLibraryService(
            record_store=records,
            model_version_store=store,
            integration_workflow_service=SimpleNamespace(),
            experiment_artifact_store=source,
        ).detail(saved.model_version_id).value
        self.assertEqual(detail["algorithm"]["adapter_version"], record.adapter_version)
        self.assertEqual(
            detail["technical_provenance"]["plugin_contract_hash"],
            record.plugin_contract_hash,
        )
        self.assertEqual(
            detail["technical_provenance"]["configuration_record_id"],
            record.configuration_record_id,
        )
        loaded = store.load(saved.model_version_id)
        self.assertEqual(loaded.metadata["schema_version"], 2)
        self.assertEqual(loaded.metadata["configuration_record"], record.to_dict())
        self.assertEqual(
            loaded.metadata["persistence_provider"]["provider_id"],
            "catboost_native_persistence",
        )
        np.testing.assert_allclose(
            adapter.predict_positive_proba(X),
            loaded.predictor.predict_positive_proba(X),
            rtol=1e-10,
            atol=1e-12,
        )
        with self.assertRaisesRegex(ValueError, "exact persisted"):
            loaded.predictor.predict_positive_proba(X.loc[:, ["f_b", "f_a"]])

    def test_pre_presentation_model_version_v2_fixture_loads_with_current_validation(
        self,
    ) -> None:
        model_version_id = (
            "2662c2c69ce8a9740582e75bb9bf0a04079d9dfb920779fbbff375a0bf939815"
        )
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "model_version_v2_pre_presentation"
            / model_version_id
        )
        with TemporaryDirectory() as root:
            copytree(fixture, Path(root) / model_version_id)
            plugins = build_builtin_model_plugin_registry()
            plugin = plugins.get("catboost")
            store = ModelVersionStore(
                root,
                code_version="code-v1",
                model_specs={"catboost": plugin.spec},
                model_plugin_registry=plugins,
            )
            loaded = store.load(model_version_id)

        self.assertEqual(loaded.metadata["schema_version"], 2)
        self.assertEqual(loaded.metadata["model_id"], "catboost")
        self.assertEqual(
            loaded.metadata["configuration_record"]["plugin_contract_hash"],
            plugin.plugin_contract_hash,
        )
        self.assertEqual(
            loaded.metadata["configuration_record"]["configuration_record_id"],
            "84b5eacfa236f53faa61956069e277da4508c6ced4b9de3c8682c7a527c8195f",
        )
        self.assertEqual(loaded.manifest["model_version_id"], model_version_id)

    def test_frozen_pre_presentation_v2_artifact_continues_through_final_fit_and_save(
        self,
    ) -> None:
        plugins = build_builtin_model_plugin_registry()
        plugin = plugins.get("catboost")
        resolved = ModelConfigurationService(plugins).resolve(
            model_id="catboost", mode=ModelConfigurationMode.RECOMMENDED
        )
        record = ModelConfigurationRecord.from_resolved(resolved, plugin)
        self.assertEqual(
            record.configuration_record_id,
            "e3af3d84c0ace1caac083a8b737c54e49be603c4e5f44507a49548dc7a467b3d",
        )
        context = PreparedDatasetContext(
            "frozen-pre-presentation-context",
            "Synthetic",
            self.loaded,
            self.registry,
            self.population,
        )
        smoke = ModelConfigurationSmokeTestService().run(
            context,
            self.config.feature_ids,
            resolved,
            self.config.seed,
            plugin,
        )
        self.assertEqual(smoke.status.value, "PASS")
        config = replace(
            self.config, model_parameters=resolved.resolved_parameters_dict()
        )
        historical_artifact = self.experiments.save(
            config=config,
            dataset_contract=self.contract,
            population=self.population,
            run_output=self.output,
            configuration_record=record,
            smoke_evidence=smoke,
        )
        loaded_artifact = self.experiments.load(historical_artifact.artifact_id)
        self.assertEqual(loaded_artifact.manifest["artifact_schema_version"], "2")
        self.assertEqual(
            loaded_artifact.configuration_record.configuration_record_id,
            record.configuration_record_id,
        )

        model_registry = ModelRegistry()
        model_registry.register(plugin.spec)
        versions = ModelVersionStore(
            Path(self.temp.name) / "continued-v2-models",
            code_version="code-v1",
            model_specs={"catboost": plugin.spec},
            model_plugin_registry=plugins,
        )
        final_fit = FinalModelTrainingService(
            experiment_artifact_store=self.experiments,
            model_version_store=versions,
            model_registry=model_registry,
            model_factories={"catboost": plugin.factory},
            code_version="code-v1",
            model_plugin_registry=plugins,
        )
        saved = final_fit.train(
            experiment_artifact_id=historical_artifact.artifact_id,
            loaded_dataset=self.loaded,
            feature_registry=self.registry,
            population=self.population,
        )
        self.assertEqual(
            versions.load(saved.model_version_id).metadata["schema_version"], 2
        )

    def test_v2_rejects_configuration_provenance_mismatch_before_publication(
        self,
    ) -> None:
        plugins = build_builtin_model_plugin_registry()
        resolved = ModelConfigurationService(plugins).resolve(
            model_id="catboost", mode="RECOMMENDED"
        )
        record = ModelConfigurationRecord.from_resolved(
            resolved, plugins.get("catboost")
        )
        advanced = ModelConfigurationService(plugins).resolve(
            model_id="catboost",
            mode="ADVANCED",
            user_overrides={"/estimator_params/depth": 6},
        )
        config = replace(
            self.config, model_parameters=advanced.resolved_parameters_dict()
        )
        store_root = Path(self.temp.name) / "models-v2-reject"
        store = ModelVersionStore(
            store_root,
            code_version="code-v1",
            model_specs={"catboost": CATBOOST_MODEL_SPEC},
            model_plugin_registry=plugins,
        )
        adapter = plugins.get("catboost").factory.create(
            dict(config.model_parameters), config.seed
        )
        adapter.fit(self.frame.loc[:, ["f_a", "f_b"]], self.frame["target"])
        with self.assertRaisesRegex(ValueError, "parameters do not match"):
            store.save(
                experiment_artifact_id="v2-experiment",
                dataset_contract=self.contract,
                config=config,
                feature_specs=self.registry.resolve(config.feature_ids),
                feature_registry=self.registry,
                population=self.population,
                adapter=adapter,
                source_file_sha256=self.loaded.source_file_sha256,
                configuration_record=record,
            )
        self.assertFalse(store_root.exists() and any(store_root.iterdir()))

    def test_v2_rejects_cryptographically_consistent_duplicate_identity_tampering(
        self,
    ) -> None:
        for label, mutate in (
            (
                "feature-order",
                lambda metadata: metadata.__setitem__("feature_ids", ["f_b", "f_a"]),
            ),
            (
                "adapter",
                lambda metadata: metadata.__setitem__("adapter_version", "wrong"),
            ),
            (
                "partition",
                lambda metadata: metadata.__setitem__("partition_role", "full"),
            ),
            ("model", lambda metadata: metadata.__setitem__("model_id", "wrong-model")),
            (
                "model-version",
                lambda metadata: metadata.__setitem__("model_version", "wrong-version"),
            ),
        ):
            with self.subTest(label=label):
                store, saved = self._saved_v2_catboost(label)
                tampered_id = self._rewrite_v2_metadata(
                    store, saved.model_version_id, mutate
                )
                with self.assertRaisesRegex(ValueError, "metadata or manifest"):
                    store.load(tampered_id)

    def _saved_v2_catboost(self, suffix: str = ""):
        plugins = build_builtin_model_plugin_registry()
        resolved = ModelConfigurationService(plugins).resolve(
            model_id="catboost",
            mode="ADVANCED",
            user_overrides={"/estimator_params/depth": 6},
        )
        record = ModelConfigurationRecord.from_resolved(
            resolved, plugins.get("catboost")
        )
        config = replace(
            self.config, model_parameters=resolved.resolved_parameters_dict()
        )
        store = ModelVersionStore(
            Path(self.temp.name) / f"models-v2-tamper-{suffix}",
            code_version="code-v1",
            model_specs={"catboost": CATBOOST_MODEL_SPEC},
            model_plugin_registry=plugins,
        )
        adapter = plugins.get("catboost").factory.create(
            dict(config.model_parameters), config.seed
        )
        adapter.fit(self.frame.loc[:, ["f_a", "f_b"]], self.frame["target"])
        saved = store.save(
            experiment_artifact_id="v2-tamper",
            dataset_contract=self.contract,
            config=config,
            feature_specs=self.registry.resolve(config.feature_ids),
            feature_registry=self.registry,
            population=self.population,
            adapter=adapter,
            source_file_sha256=self.loaded.source_file_sha256,
            configuration_record=record,
        )
        return store, saved

    @staticmethod
    def _rewrite_v2_metadata(store, model_version_id, mutate):
        directory = store.root / model_version_id
        metadata = store._read_json(directory / "metadata.json")
        mutate(metadata)
        replacement_id = store._version_id(metadata)
        store._write_json(directory / "metadata.json", metadata)
        store._write_json(
            directory / "manifest.json",
            store._manifest_v2(replacement_id, directory, metadata),
        )
        replacement = store.root / replacement_id
        directory.replace(replacement)
        return replacement_id
