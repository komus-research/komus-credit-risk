"""Точечные проверки контрактов и реестра первой версии pipeline."""

from __future__ import annotations

import unittest

from komus_risk.contracts import (
    DatasetContract,
    ExperimentConfig,
    ExperimentResult,
    FeatureGroup,
    FeatureSpec,
    FeatureUsageStatus,
)
from komus_risk.hashing import canonical_json, stable_hash
from komus_risk.registries import ModelRegistry, ModelSpec


class PipelineContractsTests(unittest.TestCase):
    def test_hash_is_deterministic_for_dictionary_key_order(self) -> None:
        self.assertEqual(stable_hash({"б": [2, 1], "а": {"x": True}}), stable_hash({"а": {"x": True}, "б": [2, 1]}))
        self.assertEqual(canonical_json({"б": 2, "а": 1}), '{"а":1,"б":2}')

    def test_dataset_contract_round_trip(self) -> None:
        contract = DatasetContract(
            dataset_id="new-source", dataset_version="1", dataset_name="Новый набор",
            source_type="table", dataset_fingerprint="sha256:abc", row_count=2,
            column_count=3, target_column="target", positive_class=1,
            identifier_column="entity_id", feature_registry_id="features-v1",
            feature_registry_hash="sha256:def", validation_status="validated",
            final_test_locked=True,
        )
        self.assertEqual(DatasetContract.from_dict(contract.to_dict()), contract)

    def test_diagnostic_feature_is_explicitly_distinct_from_model_feature(self) -> None:
        diagnostic = FeatureSpec(
            feature_id="signal", column_name="signal", display_name_ru="Сигнал",
            description_ru="Только диагностика", group_id="finance", dtype="float",
            semantic_type="score", origin="source", usage_status="diagnostic_only",
            blocked_reason=None, source_reference=None, formula_hash=None, display_order=1,
        )
        allowed = FeatureSpec(
            **{**diagnostic.to_dict(), "feature_id": "allowed", "usage_status": "model_allowed"}
        )
        self.assertIs(diagnostic.usage_status, FeatureUsageStatus.DIAGNOSTIC_ONLY)
        self.assertIs(allowed.usage_status, FeatureUsageStatus.MODEL_ALLOWED)

    def test_feature_group_has_explicit_feature_ids(self) -> None:
        group = FeatureGroup("finance", "Финансы", "Явная группа", 1, "catalog", ("f2", "f1"))
        self.assertEqual(group.feature_ids, ("f2", "f1"))
        self.assertEqual(FeatureGroup.from_dict(group.to_dict()), group)

    def test_experiment_config_serialization_and_feature_set_hash(self) -> None:
        config = ExperimentConfig(
            experiment_id="run-1", dataset_id="dataset-1", dataset_fingerprint="sha256:dataset",
            target="default", feature_ids=("f2", "f1"), feature_set_hash=None,
            feature_groups=("finance",), model_id="generic-model", model_version="1",
            model_parameters={"depth": 4}, protocol_id="cv", protocol_version="1",
            seed=42, folds=3, evaluation_level="oof", reference_result_id=None,
            changed_dimension="model", changed_elements=("depth",),
        )
        restored = ExperimentConfig.from_dict(config.to_dict())
        same_set = ExperimentConfig(
            **{**config.to_dict(), "experiment_id": "run-2", "feature_ids": ["f1", "f2"], "feature_set_hash": None}
        )
        self.assertEqual(restored, config)
        self.assertEqual(restored.config_hash, config.config_hash)
        self.assertEqual(same_set.feature_set_hash, config.feature_set_hash)

    def test_experiment_result_round_trip(self) -> None:
        result = ExperimentResult(
            result_id="result-1", experiment_config_id="run-1", config_hash="sha256:config",
            dataset_fingerprint="sha256:dataset", feature_set_hash="sha256:features",
            model_id="generic-model", model_version="1", evaluation_level="oof",
            metrics={"gini": 0.8}, confusion={"tp": 3}, fold_metrics=({"gini": 0.7},),
            runtime_seconds=1.5, comparison={"baseline": "result-0"},
            code_version="abc123", created_at="2026-09-10T12:00:00+03:00",
            limitations=("Только формат; метрики не рассчитывались этим контрактом.",),
        )
        self.assertEqual(ExperimentResult.from_dict(result.to_dict()), result)

    def test_model_registry_register_get_list_and_conflict(self) -> None:
        registry = ModelRegistry()
        beta = ModelSpec("beta", "Бета", "1", ("binary",), "Описание", {}, {"cpu": True}, "1")
        alpha = ModelSpec("alpha", "Альфа", "1", ("binary",), "Описание", {}, {"cpu": True}, "1")
        registry.register(beta)
        registry.register(alpha)
        self.assertIs(registry.get("alpha"), alpha)
        self.assertEqual([item.model_id for item in registry.list()], ["alpha", "beta"])
        with self.assertRaisesRegex(ValueError, "несовместимым"):
            registry.register(ModelSpec("alpha", "Другое имя", "1", ("binary",), "Описание", {}, {"cpu": True}, "1"))


if __name__ == "__main__":
    unittest.main()
