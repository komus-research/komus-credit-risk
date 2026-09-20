from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from copy import deepcopy

import pandas as pd

from komus_risk.data import DatasetInspector, TabularReadError, TabularReader, TabularSnapshot
from komus_risk.preparation import DatasetPreparationAnalyzer, PredictorEligibility, ProposedColumnRole
from komus_risk.preparation.service import DEFAULT_POLICY


class DatasetOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inspector = DatasetInspector()
        self.analyzer = DatasetPreparationAnalyzer()

    def _report(self, dataframe: pd.DataFrame):
        snapshot = TabularSnapshot(Path("fixture.csv"), "csv", {"separator": ",", "encoding": "utf-8"}, "a" * 64, "fixture", len(dataframe), len(dataframe.columns), dataframe)
        return self.inspector.inspect(snapshot)

    def test_generic_target_identifier_and_positive_alternatives(self) -> None:
        frame = pd.DataFrame({"customer_id": [f"C{i}" for i in range(20)], "default_flag": [0, 1] * 10, "amount": list(range(20))})
        proposal = self.analyzer.analyze(self._report(frame))
        self.assertEqual("default_flag", proposal.target_candidates[0].column_name)
        self.assertEqual("customer_id", proposal.identifier_candidates[0].column_name)
        self.assertEqual({0, 1}, {item.value for item in proposal.positive_class_candidates})
        self.assertTrue(all(item.requires_confirmation for item in proposal.positive_class_candidates))

    def test_structural_facts_and_roles_are_not_confirmed(self) -> None:
        frame = pd.DataFrame({"all_missing": [None] * 50, "constant": ["x"] * 50, "almost_id": list(range(49)) + [0], "when": pd.date_range("2026-01-01", periods=50)})
        report = self._report(frame)
        columns = {item.column_name: item for item in report.columns}
        self.assertTrue(columns["all_missing"].is_all_missing)
        self.assertTrue(columns["constant"].is_constant)
        self.assertTrue(columns["almost_id"].is_near_unique)
        self.assertEqual("datetime", columns["when"].inferred_logical_type)
        proposal = self.analyzer.analyze(report)
        roles = {item.column_name: item for item in proposal.column_roles}
        self.assertEqual(PredictorEligibility.NOT_RECOMMENDED_CANDIDATE, roles["all_missing"].predictor_eligibility)
        self.assertTrue(roles["almost_id"].requires_confirmation)

    def test_relation_block_produces_only_proxy_warning(self) -> None:
        target = [0, 1] * 30
        frame = pd.DataFrame({"event_flag": target, "result_copy": target, "category": ["a", "b", "c"] * 20})
        report = self._report(frame)
        self.assertTrue(report.relation_blocks)
        proposal = self.analyzer.analyze(report)
        self.assertIn("potential_target_proxy", {item.code for item in proposal.warnings})

    def test_no_target_and_determinism(self) -> None:
        report = self._report(pd.DataFrame({"amount": [1.1, 1.1, 2.2, 2.2, 3.3, 3.3], "note": ["one", "one", "two", "two", "three", "three"]}))
        first = self.analyzer.analyze(report)
        second = self.analyzer.analyze(report)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertIn("no_target_candidate", {item.code for item in first.warnings})
        self.assertIn("no_identifier_candidate", {item.code for item in first.warnings})

    def test_multiple_target_candidates_remain_ambiguous(self) -> None:
        frame = pd.DataFrame({"event_flag": [0, 1] * 10, "outcome_label": [False, True] * 10, "measure": list(range(20))})
        proposal = self.analyzer.analyze(self._report(frame))
        self.assertEqual({"event_flag", "outcome_label"}, {item.column_name for item in proposal.target_candidates})
        self.assertIn("multiple_target_candidates", {item.code for item in proposal.warnings})

    def test_reader_duplicate_headers_and_options(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.csv"
            path.write_text("a,a\n1,2\n", encoding="utf-8")
            with self.assertRaises(TabularReadError) as error:
                TabularReader().read(path)
            self.assertEqual("duplicate_headers", error.exception.code)
            valid = Path(directory) / "valid.csv"
            valid.write_text("a;b\n1;2\n", encoding="utf-8")
            snapshot = TabularReader().read(valid, separator=";")
            self.assertEqual({"separator": ";", "encoding": "utf-8"}, snapshot.read_options)
            proposal = self.analyzer.analyze(self.inspector.inspect(snapshot))
            self.assertEqual(snapshot.fingerprint, proposal.snapshot_fingerprint)
            with self.assertRaises(TabularReadError) as error:
                TabularReader().read(valid, separator=";;")
            self.assertEqual("invalid_read_options", error.exception.code)
            with self.assertRaises(TabularReadError) as error:
                TabularReader().read(Path(directory) / "missing.csv")
            self.assertEqual("file_not_found", error.exception.code)

    def test_target_with_missing_keeps_target_role(self) -> None:
        frame = pd.DataFrame({"event_flag": [0, 1] * 9 + [None, None], "amount": list(range(20))})
        proposal = self.analyzer.analyze(self._report(frame))
        role = next(item for item in proposal.column_roles if item.column_name == "event_flag")
        self.assertEqual(ProposedColumnRole.TARGET_CANDIDATE, role.role)
        self.assertEqual(PredictorEligibility.REVIEW_REQUIRED, role.predictor_eligibility)
        self.assertIn("target_candidate_has_missing_values", {item.code for item in proposal.warnings})

    def test_multiple_identifier_candidates_and_identifier_examples_are_redacted(self) -> None:
        frame = pd.DataFrame({"account_key": [f"A{i}" for i in range(20)], "record_guid": [f"G{i}" for i in range(20)], "value": [1] * 20})
        report = self._report(frame)
        proposal = self.analyzer.analyze(report)
        self.assertEqual({"account_key", "record_guid"}, {item.column_name for item in proposal.identifier_candidates})
        self.assertIn("multiple_identifier_candidates", {item.code for item in proposal.warnings})
        account = next(item for item in report.columns if item.column_name == "account_key")
        self.assertTrue(account.examples_redacted)
        self.assertEqual((), account.safe_examples)

    def test_datetime_mixed_unknown_text_and_high_cardinality_warnings_have_russian_text(self) -> None:
        frame = pd.DataFrame({
            "when": pd.date_range("2026-01-01", periods=50),
            "free_text": [f"long text {i}" for i in range(50)],
            "mixed": [1, "x"] * 25,
            "unknown_values": [object()] * 50,
            "flag": [True, False] * 25,
        })
        proposal = self.analyzer.analyze(self._report(frame))
        warnings = {item.code: item for item in proposal.warnings}
        self.assertIn("datetime_semantics_unconfirmed", warnings)
        self.assertIn("mixed_value_types", warnings)
        self.assertIn("high_cardinality_non_numeric", warnings)
        self.assertTrue(all("_" not in warning.reasons_ru[0] for warning in warnings.values()))

    def test_zero_overlap_relation_block_is_retained(self) -> None:
        frame = pd.DataFrame({"event_flag": [0, 1, None, None], "category": [None, None, "a", "b"]})
        report = self._report(frame)
        block = next(item for item in report.relation_blocks if item.binary_reference_column == "event_flag" and item.source_column == "category")
        self.assertEqual(0, block.overlap_non_null_rows)
        self.assertEqual((), block.joint_counts)

    def test_binary_source_missing_one_overlap_category_does_not_crash(self) -> None:
        # Eighty target/source rows overlap (coverage 0.80), but only A occurs there.
        frame = pd.DataFrame({"event_flag": [0, 1] * 40 + [None] * 20, "source": ["A"] * 80 + ["B"] * 20})
        report = self._report(frame)
        block = next(item for item in report.relation_blocks if item.binary_reference_column == "event_flag" and item.source_column == "source")
        self.assertGreaterEqual(block.overlap_non_null_rows, 50)
        self.assertGreaterEqual(block.coverage_fraction, 0.80)
        self.assertEqual({"A"}, {item.source_value for item in block.joint_counts})
        proposal = self.analyzer.analyze(report)
        self.assertNotIn("potential_target_proxy", {item.code for item in proposal.warnings})

    def test_all_missing_and_header_only_reports_are_insufficient(self) -> None:
        proposal = self.analyzer.analyze(self._report(pd.DataFrame({"a": [None, None], "b": [None, None]})))
        self.assertEqual("INSUFFICIENT_DATA", proposal.analysis_status)
        self.assertIn("insufficient_evidence", {item.code for item in proposal.warnings})
        empty = self.analyzer.analyze(self._report(pd.DataFrame({"a": pd.Series(dtype="object")})))
        self.assertEqual("INSUFFICIENT_DATA", empty.analysis_status)

    def test_policy_hash_covers_significant_policy_change(self) -> None:
        changed = {**DEFAULT_POLICY, "target": {**DEFAULT_POLICY["target"], "base": 401}}
        self.assertNotEqual(self.analyzer.policy_hash, DatasetPreparationAnalyzer(changed).policy_hash)

    def test_policy_conflict_threshold_changes_hash_and_role(self) -> None:
        report = self._report(pd.DataFrame({"target_id": ["0", "1"]}))
        default_role = self.analyzer.analyze(report).column_roles[0].role
        changed = deepcopy(DEFAULT_POLICY)
        changed["role"]["conflict_score_difference"] = 50
        changed_analyzer = DatasetPreparationAnalyzer(changed)
        self.assertNotEqual(self.analyzer.policy_hash, changed_analyzer.policy_hash)
        self.assertEqual(ProposedColumnRole.REVIEW_REQUIRED, default_role)
        self.assertEqual(ProposedColumnRole.IDENTIFIER_CANDIDATE, changed_analyzer.analyze(report).column_roles[0].role)

    def test_policy_sorting_changes_hash_and_candidate_order(self) -> None:
        report = self._report(pd.DataFrame({"z_flag": [0, 1] * 10, "a_flag": [0, 1] * 10}))
        changed = deepcopy(DEFAULT_POLICY)
        changed["sorting"]["target"] = ("position_asc", "score_desc", "missing_asc", "minimum_class_desc", "normalized_name_asc")
        changed_analyzer = DatasetPreparationAnalyzer(changed)
        self.assertNotEqual(self.analyzer.policy_hash, changed_analyzer.policy_hash)
        self.assertEqual("a_flag", self.analyzer.analyze(report).target_candidates[0].column_name)
        self.assertEqual("z_flag", changed_analyzer.analyze(report).target_candidates[0].column_name)

    def test_policy_role_precedence_changes_hash_and_execution(self) -> None:
        report = self._report(pd.DataFrame({"target_id": ["0", "1"]}))
        changed = deepcopy(DEFAULT_POLICY)
        changed["role"]["precedence"] = ("exclude", "target", "conflict", "proxy_warning", "identifier", "feature", "unknown")
        changed_analyzer = DatasetPreparationAnalyzer(changed)
        self.assertNotEqual(self.analyzer.policy_hash, changed_analyzer.policy_hash)
        self.assertEqual(ProposedColumnRole.TARGET_CANDIDATE, changed_analyzer.analyze(report).column_roles[0].role)

    def test_pairwise_warning_sorting_changes_hash_and_execution_order(self) -> None:
        target = [0, 1] * 30
        report = self._report(pd.DataFrame({"event_flag": target, "z_proxy": target, "a_proxy": target}))
        def pairwise_sources(analyzer: DatasetPreparationAnalyzer) -> list[str]:
            return [warning.column_name for warning in analyzer.analyze(report).warnings if warning.code == "potential_target_proxy" and warning.evidence.get("related_target_candidate") == "event_flag"]
        changed = deepcopy(DEFAULT_POLICY)
        changed["sorting"]["pairwise_warnings"] = ("target_rank_asc", "warning_strength_desc", "warning_code_asc", "source_position_asc", "source_normalized_name_asc")
        changed_analyzer = DatasetPreparationAnalyzer(changed)
        self.assertNotEqual(self.analyzer.policy_hash, changed_analyzer.policy_hash)
        self.assertEqual(["a_proxy", "z_proxy"], pairwise_sources(self.analyzer))
        self.assertEqual(["z_proxy", "a_proxy"], pairwise_sources(changed_analyzer))

    def test_positive_class_policy_only_uses_report_value_families(self) -> None:
        report = self._report(pd.DataFrame({"event_flag": [1, "z"] * 5}))
        changed = deepcopy(DEFAULT_POLICY)
        changed["sorting"]["positive_class"] = ("string", "integer", "float", "bool", "other")
        changed_analyzer = DatasetPreparationAnalyzer(changed)
        self.assertNotIn("datetime", self.analyzer.policy["sorting"]["positive_class"])
        self.assertNotEqual(self.analyzer.policy_hash, changed_analyzer.policy_hash)
        self.assertEqual([1, "z"], [item.value for item in self.analyzer.analyze(report).positive_class_candidates])
        self.assertEqual(["z", 1], [item.value for item in changed_analyzer.analyze(report).positive_class_candidates])

    def test_xlsx_parquet_and_xlsb_reader_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            frame = pd.DataFrame({"a": [1], "b": [2]})
            xlsx = root / "data.xlsx"
            frame.to_excel(xlsx, index=False)
            self.assertEqual("xlsx", TabularReader().read(xlsx).source_format)
            with self.assertRaises(TabularReadError) as error:
                TabularReader().read(xlsx, sheet_name="absent")
            self.assertEqual("invalid_read_options", error.exception.code)
            parquet = root / "data.parquet"
            frame.to_parquet(parquet, index=False)
            self.assertEqual("parquet", TabularReader().read(parquet).source_format)
            xlsb = root / "data.xlsb"
            xlsb.write_bytes(b"fixture")
            with patch.object(TabularReader, "_validate_headers"), patch("komus_risk.data.tabular.pd.read_excel", return_value=frame) as read_excel:
                self.assertEqual("xlsb", TabularReader().read(xlsb).source_format)
            read_excel.assert_called_once_with(xlsb, sheet_name=0, engine="pyxlsb")
            unsupported = root / "data.txt"
            unsupported.write_text("x", encoding="utf-8")
            with self.assertRaises(TabularReadError) as error:
                TabularReader().read(unsupported)
            self.assertEqual("unsupported_format", error.exception.code)
            corrupted = root / "corrupted.xlsx"
            corrupted.write_bytes(b"not an xlsx workbook")
            with self.assertRaises(TabularReadError) as error:
                TabularReader().read(corrupted)
            self.assertEqual("invalid_read_options", error.exception.code)


if __name__ == "__main__":
    unittest.main()
