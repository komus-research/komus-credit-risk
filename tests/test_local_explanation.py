from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from catboost import CatBoostClassifier
import numpy as np
import pandas as pd

from komus_risk.application import (
    LocalExplanationService,
    ModelInferenceService,
    PredictionBatch,
    PredictionRow,
)
from komus_risk.artifacts import LoadedModelVersion, ModelVersionSummary
from komus_risk.data import TabularSnapshot
from komus_risk.model_platform import (
    TrustedExplanationContext,
    build_builtin_model_plugin_registry,
)
from komus_risk.models.gbdt.native import NativePredictor, load_native_predictor


class _ProbabilityMeanPredictor:
    """Small deterministic stand-in for the persisted equal-weight ensemble."""

    def predict_positive_proba(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame.to_numpy(dtype=float)
        return 0.1 + 0.001 * values.sum(axis=1)

    def component_positive_probabilities(
        self, frame: pd.DataFrame
    ) -> dict[str, np.ndarray]:
        probability = self.predict_positive_proba(frame)
        return {model_id: probability for model_id in ("catboost", "xgboost", "lightgbm")}


class LocalExplanationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.columns = ("f_a", "f_b")
        train = pd.DataFrame({
            "f_a": [0.0, 0.2, 0.8, 1.0, 0.1, 0.9, 0.3, 0.7],
            "f_b": [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0],
        })
        target = [0, 0, 1, 1, 0, 1, 0, 1]
        model = CatBoostClassifier(iterations=20, depth=3, learning_rate=0.15, loss_function="Logloss", verbose=False, allow_writing_files=False, random_seed=7)
        model.fit(train, target)
        native_dir = Path(self.temp.name) / "native"
        native_dir.mkdir()
        model.save_model(native_dir / "model.cbm")
        predictor = load_native_predictor("catboost", native_dir, self.columns)
        self.summary = ModelVersionSummary("model-version-1", "experiment-1", "catboost", "test-v1", ("feature-a", "feature-b"))
        self.metadata = {
            "model_id": "catboost",
            "model_version": "test-v1",
            "experiment_artifact_id": "experiment-1",
            "dataset_contract": {"dataset_id": "dataset-1", "dataset_fingerprint": "fingerprint-1", "identifier_column": "company_id"},
            "feature_set_hash": "feature-set-1",
            "feature_columns": list(self.columns),
            "feature_ids": ["feature-a", "feature-b"],
            "feature_specs": [
                {"feature_id": "feature-a", "column_name": "f_a"},
                {"feature_id": "feature-b", "column_name": "f_b"},
            ],
        }
        self.loaded = LoadedModelVersion(self.summary, self.metadata, {}, predictor)
        snapshot = TabularSnapshot(
            source_path=Path(self.temp.name) / "inference.csv",
            source_format="csv",
            read_options={"separator": ",", "encoding": "utf-8"},
            fingerprint="inference-fingerprint",
            row_count=2,
            column_count=3,
            dataframe=pd.DataFrame({"company_id": ["a-1", "b-2"], "f_a": [0.15, 0.85], "f_b": [1.0, 0.0]}),
            source_file_sha256="a" * 64,
            physical_headers=("company_id", "f_a", "f_b"),
        )
        self.batch = ModelInferenceService().predict(loaded_model_version=self.loaded, snapshot=snapshot)
        self.service = LocalExplanationService()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_real_native_catboost_local_shap_evidence(self) -> None:
        evidence = self.service.explain(loaded_model_version=self.loaded, prediction_batch=self.batch, row_id=self.batch.rows[0].row_id)
        self.assertEqual(self.batch.rows[0].probability, evidence.probability)
        self.assertEqual("raw_margin", evidence.shap_output_space)
        self.assertAlmostEqual(evidence.raw_model_output, evidence.base_value + sum(item.shap_value for item in evidence.features), places=7)
        self.assertEqual({"f_a": 0.15, "f_b": 1.0}, {item.column_name: item.raw_value for item in evidence.features})
        self.assertEqual({"f_a": "feature-a", "f_b": "feature-b"}, {item.column_name: item.feature_id for item in evidence.features})
        self.assertEqual([1, 2], [item.abs_rank for item in evidence.features])
        self.assertEqual(
            sorted(evidence.features, key=lambda item: (-abs(item.shap_value), self.columns.index(item.column_name))),
            list(evidence.features),
        )
        repeat = self.service.explain(loaded_model_version=self.loaded, prediction_batch=self.batch, row_id=self.batch.rows[0].row_id)
        self.assertEqual(evidence.evidence_hash, repeat.evidence_hash)

    def test_native_batch_preserves_and_validates_oof_provenance(self) -> None:
        plugins = build_builtin_model_plugin_registry()
        provider = plugins.explanation_providers.validate_plugin_provider(plugins.get("catboost"))
        oof_loaded = LoadedModelVersion(
            self.summary,
            {**self.metadata, "fold_model_binding_id": "fold-model-0", "fold_id": "fold-0"},
            {}, self.loaded.predictor,
        )
        context = TrustedExplanationContext(
            source_kind="oof_fold", source_artifact_id="experiment-1",
            model_binding_id="fold-model-0", feature_columns=self.columns,
            background_values=((0.1, 0.2),), background_row_positions=(10,),
            background_policy_id="outer_train_hash_top128_v1",
            validation_row_positions=(0, 1), fold_id="fold-0",
        )
        evidence = provider.explain_batch(
            loaded_model_version=oof_loaded, prediction_batch=self.batch,
            row_ids=(self.batch.rows[0].row_id,), explanation_context=context,
        )[0]
        self.assertEqual("oof_fold", evidence.source_kind)
        self.assertEqual("experiment-1", evidence.source_artifact_id)
        self.assertEqual("fold-model-0", evidence.model_binding_id)
        self.assertEqual("fold-0", evidence.provenance["fold_id"])
        self.assertEqual([0, 1], evidence.provenance["validation_row_positions"])
        self.assertNotEqual(evidence.model_version_id, evidence.model_binding_id)
        for changed in (
            replace(context, source_artifact_id="foreign-artifact"),
            replace(context, model_binding_id="foreign-fold-model"),
            replace(context, fold_id="foreign-fold"),
            replace(context, validation_row_positions=(99,), validation_row_position=None),
        ):
            with self.subTest(context=changed):
                with self.assertRaises(ValueError):
                    provider.explain_batch(
                        loaded_model_version=oof_loaded, prediction_batch=self.batch,
                        row_ids=(self.batch.rows[0].row_id,), explanation_context=changed,
                    )

    def test_native_oof_batch_contract_is_shared_by_all_gbdt_providers(self) -> None:
        plugins = build_builtin_model_plugin_registry()
        for model_id in ("catboost", "xgboost", "lightgbm"):
            with self.subTest(model_id=model_id):
                plugin = plugins.get(model_id)
                provider = plugins.explanation_providers.validate_plugin_provider(plugin)
                version_id = f"{model_id}-version"
                binding_id = f"{model_id}-fold-model"
                summary = ModelVersionSummary(version_id, "shared-artifact", model_id, "v1", ("feature",))
                probability = float(1 / (1 + np.exp(-0.1)))
                predictor = NativePredictor(
                    model_id, ("x",), lambda frame: np.full(len(frame), probability),
                    local_shap=lambda frame: np.asarray([[0.2, -0.1]]),
                    raw_predict=lambda frame: np.asarray([0.1]),
                )
                loaded = LoadedModelVersion(summary, {
                    "model_id": model_id, "model_version": "v1",
                    "experiment_artifact_id": "shared-artifact", "feature_set_hash": "feature-hash",
                    "feature_columns": ["x"], "feature_ids": ["feature"],
                    "feature_specs": [{"feature_id": "feature", "column_name": "x"}],
                    "fold_model_binding_id": binding_id, "fold_id": "fold-a",
                    "dataset_contract": {"identifier_column": "company", "dataset_id": "dataset", "dataset_fingerprint": "fingerprint"},
                }, {}, predictor)
                row = PredictionRow("source-hash:3", 3, "company-3", probability)
                batch = PredictionBatch(version_id, "source-hash", "company", ("x",), (row,), (), ((0.7,),))
                context = TrustedExplanationContext(
                    "oof_fold", "shared-artifact", binding_id, ("x",), ((0.1,),), (10,),
                    "outer_train_hash_top128_v1", validation_row_positions=(3,), fold_id="fold-a",
                )
                evidence = provider.explain_batch(
                    loaded_model_version=loaded, prediction_batch=batch,
                    row_ids=(row.row_id,), explanation_context=context,
                )[0]
                self.assertEqual("oof_fold", evidence.source_kind)
                self.assertEqual(binding_id, evidence.model_binding_id)
                self.assertEqual("fold-a", evidence.provenance["fold_id"])
                with self.assertRaises(ValueError):
                    provider.explain_batch(
                        loaded_model_version=loaded, prediction_batch=batch,
                        row_ids=(row.row_id,), explanation_context=replace(context, fold_id="fold-b"),
                    )

    def test_v2_evidence_identity_rules_are_source_specific(self) -> None:
        evidence = self.service.explain(
            loaded_model_version=self.loaded, prediction_batch=self.batch,
            row_id=self.batch.rows[0].row_id,
        )
        from dataclasses import replace as dc_replace
        oof = dc_replace(
            evidence, source_kind="oof_fold", model_binding_id="fold-model-0",
            provenance={"fold_id": "fold-0"},
        )
        self.assertEqual("fold-model-0", oof.model_binding_id)
        with self.assertRaisesRegex(ValueError, "ModelVersion identity"):
            dc_replace(evidence, model_binding_id="foreign")

    def test_gbdt_mean_probability_provider_reconstructs_and_fails_closed(self) -> None:
        plugins = build_builtin_model_plugin_registry()
        provider = plugins.explanation_providers.validate_plugin_provider(
            plugins.get("gbdt_mean")
        )
        columns = tuple(f"f_{index:02d}" for index in range(47))
        feature_ids = tuple(f"feature-{index:02d}" for index in range(47))
        summary = ModelVersionSummary(
            "mean-version-1", "experiment-mean-1", "gbdt_mean", "mean-v1", feature_ids
        )
        metadata = {
            "model_id": "gbdt_mean",
            "model_version": "mean-v1",
            "experiment_artifact_id": "experiment-mean-1",
            "fold_model_binding_id": "mean-fold-model-1",
            "fold_id": 1,
            "dataset_contract": {"dataset_id": "dataset-mean", "dataset_fingerprint": "fingerprint-mean"},
            "feature_set_hash": "feature-set-mean",
            "feature_columns": list(columns),
            "feature_specs": [
                {
                    "feature_id": feature_id,
                    "column_name": column,
                    "display_name_ru": f"Признак {index}",
                    "description_ru": f"Описание {index}",
                }
                for index, (feature_id, column) in enumerate(zip(feature_ids, columns, strict=True))
            ],
        }
        values = tuple((index + 1) / 100 for index in range(47))
        probability = float(_ProbabilityMeanPredictor().predict_positive_proba(pd.DataFrame([values], columns=columns))[0])
        second_values = tuple((index + 2) / 100 for index in range(47))
        second_probability = float(_ProbabilityMeanPredictor().predict_positive_proba(pd.DataFrame([second_values], columns=columns))[0])
        batch = PredictionBatch(
            "mean-version-1", "source-mean", "company_id", columns,
            (
                PredictionRow("row-mean-1", 7, "company-mean", probability),
                PredictionRow("row-mean-2", 6, "company-mean-2", second_probability),
            ),
            (),
            (values, second_values),
        )
        loaded = LoadedModelVersion(summary, metadata, {}, _ProbabilityMeanPredictor())
        large_context = TrustedExplanationContext.from_oof_evidence(
            source_artifact_id="experiment-mean-1",
            model_binding_id="mean-fold-model-1",
            feature_columns=columns,
            model_input_values=tuple(
                tuple((row + index) / 1000 for index in range(47))
                for row in range(300)
            ),
            row_positions=tuple(range(300)),
            fold_assignments=tuple(1 if 200 <= row < 250 else 0 for row in range(300)),
            validation_fold=1,
            validation_row_position=201,
            final_test_row_positions=(299,),
        )
        repeated_large_context = TrustedExplanationContext.from_oof_evidence(
            source_artifact_id="experiment-mean-1",
            model_binding_id="mean-fold-model-1",
            feature_columns=columns,
            model_input_values=tuple(
                tuple((row + index) / 1000 for index in range(47))
                for row in range(300)
            ),
            row_positions=tuple(range(300)),
            fold_assignments=tuple(1 if 200 <= row < 250 else 0 for row in range(300)),
            validation_fold=1,
            validation_row_position=201,
            final_test_row_positions=(299,),
        )
        self.assertEqual(128, len(large_context.background_row_positions))
        self.assertEqual(large_context.background_row_positions, repeated_large_context.background_row_positions)
        self.assertEqual(large_context.background_hash, repeated_large_context.background_hash)
        self.assertTrue(all(position < 200 or 250 <= position < 299 for position in large_context.background_row_positions))
        context = TrustedExplanationContext.from_oof_evidence(
            source_artifact_id="experiment-mean-1",
            model_binding_id="mean-fold-model-1",
            feature_columns=columns,
            model_input_values=tuple(
                tuple((row + index) / 100 for index in range(47))
                for row in range(10)
            ),
            row_positions=tuple(range(10)),
            fold_assignments=(0, 0, 0, 0, 1, 1, 1, 1, 0, 0),
            validation_fold=1,
            validation_row_position=7,
            final_test_row_positions=(9,),
        )
        evidence = provider.explain(
            loaded_model_version=loaded,
            prediction_batch=batch,
            row_id="row-mean-1",
            explanation_context=context,
        )
        self.assertEqual("probability", evidence.output_space)
        self.assertEqual(47, len(evidence.features))
        self.assertAlmostEqual(
            probability,
            evidence.base_value + sum(item.shap_value for item in evidence.features),
            places=9,
        )
        repeated = provider.explain(
            loaded_model_version=loaded,
            prediction_batch=batch,
            row_id="row-mean-1",
            explanation_context=context,
        )
        self.assertEqual(evidence.evidence_hash, repeated.evidence_hash)
        self.assertEqual("oof_fold", evidence.provenance["source_kind"])
        self.assertNotIn(9, evidence.provenance["background_row_positions"])
        self.assertNotIn(7, evidence.provenance["background_row_positions"])
        batch_evidence = provider.explain_batch(
            loaded_model_version=loaded,
            prediction_batch=batch,
            row_ids=("row-mean-2", "row-mean-1"),
            explanation_context=context,
        )
        self.assertEqual(["row-mean-2", "row-mean-1"], [item.row_id for item in batch_evidence])
        self.assertTrue(all(item.source_kind == "oof_fold" for item in batch_evidence))
        self.assertTrue(all(item.source_artifact_id == "experiment-mean-1" for item in batch_evidence))
        self.assertTrue(all(item.model_binding_id == "mean-fold-model-1" for item in batch_evidence))
        self.assertTrue(all(item.model_binding_id != item.model_version_id for item in batch_evidence))
        self.assertTrue(all(item.provenance["fold_id"] == "1" for item in batch_evidence))
        self.assertTrue(all(item.provenance["validation_row_positions"] == [4, 5, 6, 7] for item in batch_evidence))
        for item in batch_evidence:
            self.assertAlmostEqual(
                item.probability,
                item.base_value + sum(feature.shap_value for feature in item.features),
                places=9,
            )
        invalid_contexts = (
            replace(context, source_artifact_id="foreign-artifact"),
            replace(context, model_binding_id="foreign-fold-model"),
            replace(context, fold_id="foreign-fold"),
            replace(context, validation_row_positions=(99,), validation_row_position=None),
            replace(context, validation_row_positions=(), validation_row_position=None),
            replace(context, feature_columns=tuple(reversed(columns))),
            replace(context, source_kind="model_version"),
        )
        for invalid in invalid_contexts:
            with self.subTest(invalid_context=invalid):
                with self.assertRaises(ValueError):
                    provider.explain_batch(
                        loaded_model_version=loaded,
                        prediction_batch=batch,
                        row_ids=("row-mean-1",),
                        explanation_context=invalid,
                    )
        with self.assertRaisesRegex(ValueError, "trusted background context"):
            provider.explain(
                loaded_model_version=loaded,
                prediction_batch=batch,
                row_id="row-mean-1",
            )
        with self.assertRaisesRegex(ValueError, "background binding"):
            TrustedExplanationContext(
                source_kind="oof_fold",
                source_artifact_id="experiment-mean-1",
                model_binding_id="mean-version-1",
                feature_columns=columns,
                background_values=(values,),
                background_row_positions=(9,),
                background_policy_id="outer_train_deterministic_v1",
                validation_row_position=7,
                final_test_row_positions=(9,),
                fold_id="1",
            )
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            provider.explain(
                loaded_model_version=loaded,
                prediction_batch=replace(
                    batch,
                    rows=(replace(batch.rows[0], probability=probability + 0.01),),
                    validated_feature_values=(values,),
                ),
                row_id="row-mean-1",
                explanation_context=context,
            )
        with self.assertRaisesRegex(ValueError, "Trusted OOF context"):
            provider.explain(
                loaded_model_version=loaded,
                prediction_batch=batch,
                row_id="row-mean-1",
                explanation_context=replace(context, feature_columns=tuple(reversed(columns))),
            )

    def test_unknown_row_wrong_version_and_changed_probability_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.service.explain(loaded_model_version=self.loaded, prediction_batch=self.batch, row_id="unknown")
        with self.assertRaisesRegex(ValueError, "model_version_id"):
            self.service.explain(loaded_model_version=self.loaded, prediction_batch=replace(self.batch, model_version_id="other-version"), row_id=self.batch.rows[0].row_id)
        changed_row = replace(self.batch.rows[0], probability=0.123456)
        changed_batch = replace(self.batch, rows=(changed_row, *self.batch.rows[1:]))
        with self.assertRaisesRegex(ValueError, "Recomputed probability"):
            self.service.explain(loaded_model_version=self.loaded, prediction_batch=changed_batch, row_id=changed_row.row_id)

    def test_non_catboost_is_explicitly_unsupported(self) -> None:
        unsupported = LoadedModelVersion(
            replace(self.summary, model_id="xgboost"),
            {**self.metadata, "model_id": "xgboost"},
            {},
            self.loaded.predictor,
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.service.explain(loaded_model_version=unsupported, prediction_batch=self.batch, row_id=self.batch.rows[0].row_id)


if __name__ == "__main__":
    unittest.main()
