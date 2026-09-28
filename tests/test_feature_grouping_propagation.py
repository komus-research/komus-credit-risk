from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from komus_risk.contracts import FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import DatasetInspector, TabularReader
from komus_risk.preparation import (
    ConfirmedColumnDecision,
    ConfirmedDatasetPreparation,
    KomusDatasetPreparationService,
    PopulationPolicyV1,
)
from komus_risk.preparation.contracts import (
    ConfidenceLevel,
    ConfirmedColumnStatus,
    DatasetPreparationError,
    ProposedTechnicalGroup,
)
from komus_risk.preparation.materializer import (
    confirmation_hash,
    inspection_report_hash,
    proposal_hash,
)
from komus_risk.preparation.service import DatasetPreparationAnalyzer
from komus_risk.registries import FeatureRegistry


class FeatureGroupingPropagationTests(unittest.TestCase):
    _headers = ("entity_id", "target", "a", "b", "c", "diagnostic", "blocked")

    def _parts(self, groups=(), statuses=None):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "dataset.csv"
        path.write_text(
            "entity_id,target,a,b,c,diagnostic,blocked\n"
            "x1,0,1,10,100,7,8\n"
            "x2,1,2,20,200,8,9\n"
            "x3,0,3,30,300,9,10\n"
            "x4,1,4,40,400,10,11\n",
            encoding="utf-8",
        )
        snapshot = TabularReader().read(path)
        report = DatasetInspector().inspect(snapshot)
        proposal = replace(
            DatasetPreparationAnalyzer().analyze(report), technical_groups=tuple(groups)
        )
        status_by_name = {
            "entity_id": ConfirmedColumnStatus.IDENTIFIER,
            "target": ConfirmedColumnStatus.TARGET,
            "a": ConfirmedColumnStatus.MODEL_ALLOWED,
            "b": ConfirmedColumnStatus.MODEL_ALLOWED,
            "c": ConfirmedColumnStatus.MODEL_ALLOWED,
            "diagnostic": ConfirmedColumnStatus.DIAGNOSTIC_ONLY,
            "blocked": ConfirmedColumnStatus.BLOCKED,
        }
        status_by_name.update(statuses or {})
        decisions = tuple(
            ConfirmedColumnDecision(
                name,
                status_by_name[name],
                "Explicitly blocked"
                if status_by_name[name] is ConfirmedColumnStatus.BLOCKED
                else None,
            )
            for name in self._headers
        )
        report_hash = inspection_report_hash(report)
        confirmation = ConfirmedDatasetPreparation(
            "1",
            snapshot.fingerprint,
            report_hash,
            proposal_hash(proposal, report_hash),
            proposal.policy_id,
            proposal.policy_version,
            proposal.policy_hash,
            "Grouping test",
            "target",
            1,
            "entity_id",
            decisions,
            PopulationPolicyV1.FULL_OOF_NO_PROTECTED_FINAL_TEST,
        )
        return snapshot, report, proposal, confirmation

    @staticmethod
    def _group(kind, key, names):
        return ProposedTechnicalGroup(
            kind, key, tuple(names), None, ConfidenceLevel.HIGH
        )

    def _materialize(self, groups=(), statuses=None):
        return KomusDatasetPreparationService().prepare(*self._parts(groups, statuses))

    def test_technical_kinds_have_exact_presentation_and_physical_order(self) -> None:
        expected_names = {
            "structural_prefix": "Структура: q",
            "repeated_token": "Общий токен: q",
            "logical_type": "Тип: q",
        }
        for kind, expected_name in expected_names.items():
            with self.subTest(kind=kind):
                context, _manifest = self._materialize(
                    (self._group(kind, "q", ("a", "b")),)
                )
                group = next(
                    item
                    for item in context.feature_registry._groups.values()
                    if item.name_ru == expected_name
                )
                self.assertEqual(("a", "b"), group.feature_ids)
                self.assertEqual(
                    "dataset_preparation_v2:proposal_technical_group:" + kind,
                    group.source,
                )
                self.assertTrue(
                    group.group_id.startswith("technical_group_v1:" + kind + ":")
                )

    def test_fallback_combines_analyzer_fallback_and_ungrouped_allowed_features(
        self,
    ) -> None:
        context, _manifest = self._materialize(
            (self._group("fallback", "leftovers", ("a",)),)
        )
        group = context.feature_registry._groups["technical_group_v1:fallback"]
        self.assertEqual("Другие признаки", group.name_ru)
        self.assertEqual(("a", "b", "c"), group.feature_ids)

    def test_mixed_group_retains_only_model_allowed_members(self) -> None:
        groups = (
            self._group(
                "structural_prefix",
                "mixed",
                ("a", "target", "entity_id", "diagnostic", "blocked"),
            ),
        )
        context, _manifest = self._materialize(groups)
        registry = context.feature_registry
        technical = next(
            group
            for group in registry._groups.values()
            if group.name_ru == "Структура: mixed"
        )
        self.assertEqual(("a",), technical.feature_ids)
        self.assertEqual("usage_target", registry.get("target").group_id)
        self.assertEqual("usage_identifier", registry.get("entity_id").group_id)
        self.assertEqual("usage_diagnostic_only", registry.get("diagnostic").group_id)
        self.assertEqual("usage_blocked", registry.get("blocked").group_id)

    def test_singleton_is_preserved_and_zero_survivor_group_is_omitted(self) -> None:
        singleton, _manifest = self._materialize(
            (self._group("repeated_token", "only", ("a", "diagnostic")),)
        )
        self.assertEqual(
            ("a",),
            next(
                group
                for group in singleton.feature_registry._groups.values()
                if group.name_ru == "Общий токен: only"
            ).feature_ids,
        )
        zero, _manifest = self._materialize(
            (self._group("logical_type", "none", ("diagnostic", "blocked")),)
        )
        self.assertFalse(
            any(
                group.name_ru == "Тип: none"
                for group in zero.feature_registry._groups.values()
            )
        )

    def test_model_allowed_features_are_covered_once_without_permission_leakage(
        self,
    ) -> None:
        groups = (self._group("structural_prefix", "pair", ("a", "b", "diagnostic")),)
        context, _manifest = self._materialize(groups)
        registry = context.feature_registry
        allowed = [
            spec
            for spec in registry._features.values()
            if spec.usage_status is FeatureUsageStatus.MODEL_ALLOWED
        ]
        self.assertEqual({"a", "b", "c"}, {spec.feature_id for spec in allowed})
        self.assertTrue(
            all(spec.group_id.startswith("technical_group_v1:") for spec in allowed)
        )
        self.assertFalse("usage_model_allowed" in registry._groups)
        self.assertEqual(FeatureUsageStatus.TARGET, registry.get("target").usage_status)
        self.assertEqual(
            FeatureUsageStatus.IDENTIFIER, registry.get("entity_id").usage_status
        )
        self.assertEqual(
            FeatureUsageStatus.DIAGNOSTIC_ONLY, registry.get("diagnostic").usage_status
        )
        self.assertEqual(
            FeatureUsageStatus.BLOCKED, registry.get("blocked").usage_status
        )

    def test_projection_is_deterministic_and_versions_are_intentional(self) -> None:
        groups = (self._group("repeated_token", "shared", ("a", "b")),)
        first_context, first_manifest = self._materialize(groups)
        second_context, second_manifest = self._materialize(groups)
        self.assertEqual(
            first_context.feature_registry.registry_id,
            second_context.feature_registry.registry_id,
        )
        self.assertEqual(
            first_context.feature_registry.registry_hash,
            second_context.feature_registry.registry_hash,
        )
        self.assertEqual(first_context.context_id, second_context.context_id)
        self.assertEqual(
            first_manifest.materialization_identity,
            second_manifest.materialization_identity,
        )
        self.assertEqual("2", first_manifest.materializer_version)
        self.assertEqual("2", first_manifest.manifest_version)
        self.assertTrue(
            first_manifest.feature_registry_id.startswith("feature-registry-v2:")
        )
        self.assertEqual(
            first_manifest.proposal_hash,
            first_manifest.confirmed_preparation.proposal_hash,
        )
        self.assertEqual(
            first_manifest.confirmation_hash,
            confirmation_hash(first_manifest.confirmed_preparation),
        )

    def test_legacy_explicit_registry_remains_usable(self) -> None:
        spec = FeatureSpec(
            "legacy",
            "legacy",
            "Legacy",
            "Legacy feature",
            "legacy-group",
            "float64",
            "technical:numeric",
            "legacy",
            FeatureUsageStatus.MODEL_ALLOWED,
            None,
            None,
            None,
            0,
        )
        registry = FeatureRegistry(
            "feature-registry-v1:legacy",
            (spec,),
            (
                FeatureGroup(
                    "legacy-group", "Legacy", "Legacy group", 0, "legacy", ("legacy",)
                ),
            ),
        )
        self.assertEqual("legacy", registry.get("legacy").feature_id)

    def test_malformed_technical_groups_fail_closed(self) -> None:
        invalid_groups = (
            (self._group("unknown", "q", ("a",)),),
            (self._group("logical_type", " ", ("a",)),),
            (self._group("logical_type", "q", ("missing",)),),
            (self._group("logical_type", "q", ("a", "a")),),
            (
                self._group("logical_type", "q", ("a",)),
                self._group("repeated_token", "r", ("a",)),
            ),
            (
                self._group("fallback", "a", ("a",)),
                self._group("fallback", "b", ("b",)),
            ),
        )
        for groups in invalid_groups:
            with self.subTest(groups=groups):
                with self.assertRaisesRegex(
                    DatasetPreparationError, "INVALID_TECHNICAL_GROUP_STRUCTURE"
                ):
                    self._materialize(groups)
        for kind in ("structural_prefix", "repeated_token", "logical_type"):
            with self.subTest(kind=kind):
                groups = (
                    self._group(kind, "same", ("a",)),
                    self._group(kind, "same", ("b",)),
                )
                with self.assertRaisesRegex(
                    DatasetPreparationError, "INVALID_TECHNICAL_GROUP_STRUCTURE"
                ):
                    self._materialize(groups)


if __name__ == "__main__":
    unittest.main()
