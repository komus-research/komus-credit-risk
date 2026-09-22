"""Tests for the read-only Stage 2 SHAP evidence view."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.shap_evidence import load_stage2_evidence, stage2_matches_current_run


class Stage2ShapEvidenceTests(unittest.TestCase):
    def test_published_evidence_has_three_models_and_local_examples(self) -> None:
        summary, by_model, consensus, details = load_stage2_evidence()

        self.assertEqual(set(by_model["Модель"]), {"CatBoost", "XGBoost", "LightGBM"})
        self.assertEqual(len(consensus), 47)
        self.assertEqual(len(details["локальные_примеры_xgboost"]), 3)
        self.assertEqual(summary["shap_sample_per_fold"], 5000)

    def test_matches_only_exact_dataset_features_and_cv(self) -> None:
        summary, by_model, _, _ = load_stage2_evidence()
        features = tuple(by_model.loc[by_model["Модель"] == "CatBoost", "Признак"])
        context = SimpleNamespace(
            loaded_dataset=SimpleNamespace(source_file_sha256=summary["dataset_sha256"])
        )
        config = SimpleNamespace(
            model_id="catboost", feature_ids=features, seed=42, folds=3,
            protocol_id="stratified_kfold_oof", protocol_version="1",
            evaluation_level="oof", model_version="accepted_stage1_v2",
        )
        artifact = SimpleNamespace(config=config)

        self.assertTrue(stage2_matches_current_run(artifact, context, summary, by_model))
        config.feature_ids = features[:-1]
        self.assertFalse(stage2_matches_current_run(artifact, context, summary, by_model))
        config.feature_ids = features
        config.model_id = "gbdt_mean"
        self.assertFalse(stage2_matches_current_run(artifact, context, summary, by_model))
        config.model_id = "catboost"
        context.loaded_dataset.source_file_sha256 = "different"
        self.assertFalse(stage2_matches_current_run(artifact, context, summary, by_model))


if __name__ == "__main__":
    unittest.main()
