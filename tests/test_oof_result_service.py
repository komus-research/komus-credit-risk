"""Result V2 reads only complete, immutable V3 OOF evidence."""

from __future__ import annotations

from dataclasses import replace
import math
import unittest

import numpy as np

from komus_risk.application.oof_result import OOFResultError, OOFResultService
from komus_risk.artifacts import LoadedExperimentArtifact
from komus_risk.contracts import ExperimentConfig, ExperimentResult
from komus_risk.experiments import ExperimentRunOutput, OOFResultEvidence


class _Store:
    def __init__(self, artifact: LoadedExperimentArtifact | Exception) -> None:
        self.artifact = artifact

    def load(self, artifact_id: str) -> LoadedExperimentArtifact:
        if isinstance(self.artifact, Exception):
            raise self.artifact
        return self.artifact


class OOFResultServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.artifact = self._artifact()
        self.service = OOFResultService(_Store(self.artifact))

    def test_summary_returns_persisted_metrics_and_immutable_collections(self) -> None:
        summary = self.service.summary("artifact-v3")

        self.assertEqual(summary.object_count, 6)
        self.assertEqual(summary.feature_count, 2)
        self.assertEqual((summary.gini, summary.roc_auc, summary.pr_auc), (0.4, 0.7, 0.6))
        self.assertEqual(summary.fold_metrics[0]["fold"], 1)
        with self.assertRaises(TypeError):
            summary.fold_metrics[0]["fold"] = 99  # type: ignore[index]

    def test_threshold_derives_metrics_and_reproduces_persisted_half(self) -> None:
        half = self.service.threshold("artifact-v3", 0.5)
        other = self.service.threshold("artifact-v3", 0.75)

        self.assertEqual((half.tp, half.tn, half.fp, half.fn), (2, 1, 2, 1))
        self.assertAlmostEqual(half.precision, 0.5)
        self.assertAlmostEqual(half.recall, 2 / 3)
        self.assertAlmostEqual(half.f1, 4 / 7)
        self.assertEqual((half.above_threshold_count, half.above_threshold_share), (4, 4 / 6))
        self.assertEqual((other.tp, other.tn, other.fp, other.fn), (1, 2, 1, 2))
        self.assertAlmostEqual(other.f1, 0.4)
        for invalid in (-0.1, 1.1, math.inf, math.nan, "0.5"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(OOFResultError, "INVALID_THRESHOLD"):
                self.service.threshold("artifact-v3", invalid)  # type: ignore[arg-type]

    def test_threshold_sweep_returns_bounded_points_from_same_oof_evidence(self) -> None:
        sweep = self.service.threshold_sweep("artifact-v3")

        self.assertEqual(len(sweep), 51)
        self.assertEqual(sweep[0].threshold, 0.0)
        self.assertEqual(sweep[25].threshold, 0.5)
        self.assertEqual(sweep[-1].threshold, 1.0)
        self.assertEqual((sweep[25].tp, sweep[25].tn, sweep[25].fp, sweep[25].fn), (2, 1, 2, 1))
        self.assertAlmostEqual(sweep[25].recall, 2 / 3)

    def test_capture_curve_uses_descending_scores_and_row_position_for_ties(self) -> None:
        capture = self.service.summary("artifact-v3").capture

        self.assertEqual(capture.total_positive_events, 3)
        self.assertEqual((capture.points[0].object_share, capture.points[0].event_share), (0.0, 0.0))
        self.assertEqual((capture.points[-1].object_share, capture.points[-1].event_share), (1.0, 1.0))
        ordered_y_true = (0, 1, 1, 0, 0, 1)
        for requested_percent, point in enumerate(capture.points[1:], start=1):
            selected_count = min(6, math.ceil(6 * requested_percent / 100))
            with self.subTest(requested_percent=requested_percent):
                self.assertAlmostEqual(point.object_share, selected_count / 6)
                self.assertAlmostEqual(
                    point.event_share,
                    sum(ordered_y_true[:selected_count]) / capture.total_positive_events,
                )

        # At 1%, one row is selected.  The two highest scores tie, and the
        # smaller row_position (10, a negative target) must win the tie.
        self.assertEqual(capture.points[1].object_share, 1 / 6)
        self.assertEqual(capture.points[1].event_share, 0.0)
        # At 17%, both tied rows are selected; the row at position 40 is positive.
        self.assertEqual(capture.points[17].object_share, 2 / 6)
        self.assertEqual(capture.points[17].event_share, 1 / 3)
        self.assertIsNotNone(capture.marker)
        self.assertEqual(capture.marker.object_share, 1 / 6)  # type: ignore[union-attr]
        self.assertEqual(capture.marker.event_share, 0.0)  # type: ignore[union-attr]

    def test_capture_curve_is_safely_unavailable_without_positive_events(self) -> None:
        evidence = replace(
            self.artifact.run_output.oof_evidence,
            y_true=np.zeros(6, dtype=np.int64),
        )
        output = replace(
            self.artifact.run_output,
            oof_evidence=evidence,
            result=replace(
                self.artifact.run_output.result,
                confusion={"threshold": 0.5, "tp": 0, "tn": 2, "fp": 4, "fn": 0},
                metrics={
                    **self.artifact.run_output.result.metrics,
                    "precision_at_0_5": 0.0,
                    "recall_at_0_5": 0.0,
                    "f1_at_0_5": 0.0,
                },
            ),
        )
        capture = OOFResultService(_Store(replace(self.artifact, run_output=output))).summary("artifact-v3").capture

        self.assertEqual(capture.total_positive_events, 0)
        self.assertEqual(capture.points, ())
        self.assertIsNone(capture.marker)

    def test_objects_support_unicode_filters_and_inclusive_scores(self) -> None:
        view = self.service.objects(
            "artifact-v3", 0.5, 0, 20, search="  кЛиЕнТ ",
            min_score=0.1, max_score=0.8,
        )

        self.assertEqual((view.total_count, view.filtered_count, view.returned_count), (6, 2, 2))
        self.assertEqual([item.identifier_display for item in view.items], ["кЛИЕНТ-2", "Клиент"])
        self.assertEqual([item.outcome for item in view.items], ["FP", "TP"])

    def test_objects_sort_with_row_position_tie_break_and_filter_combinations(self) -> None:
        descending = self.service.objects("artifact-v3", 0.5, 0, 20, sort="SCORE_DESC")
        ascending = self.service.objects("artifact-v3", 0.5, 0, 20, sort="SCORE_ASC")
        distance = self.service.objects("artifact-v3", 0.5, 0, 20, sort="DISTANCE_TO_THRESHOLD_ASC")
        filtered = self.service.objects(
            "artifact-v3", 0.5, 0, 20, target="NEGATIVE", outcomes=("FP", "TN"), min_score=0.2, max_score=0.8,
        )

        self.assertEqual([item.identifier_display for item in descending.items[:2]], ["кЛИЕНТ-2", "Клиент"])
        self.assertEqual([item.identifier_display for item in ascending.items[:2]], ["Other", "Duplicate"])
        self.assertEqual([item.identifier_display for item in distance.items[:2]], ["Duplicate", "Other-2"])
        self.assertEqual([item.outcome for item in filtered.items], ["FP", "FP", "TN"])
        self.assertEqual(filtered.total_count, 6)
        self.assertEqual(filtered.filtered_count, 3)

    def test_random_access_and_identity_are_deterministic_and_detail_is_aligned(self) -> None:
        first = self.service.objects("artifact-v3", 0.5, 0, 20, sort="SCORE_DESC")
        jump = self.service.objects("artifact-v3", 0.5, 4, 1, sort="SCORE_DESC")
        duplicate_ids = [item.object_id for item in first.items if item.identifier_display == "Duplicate"]
        detail = self.service.object_detail("artifact-v3", jump.items[0].object_id, 0.5)

        self.assertEqual(jump.returned_count, 1)
        self.assertEqual([item.identifier_display for item in jump.items], ["Duplicate"])
        self.assertEqual(len(set(duplicate_ids)), 2)
        self.assertEqual(detail.identifier_display, "Duplicate")
        self.assertEqual(detail.fold_number, 1)
        self.assertEqual(detail.score, 0.2)
        with self.assertRaisesRegex(OOFResultError, "OBJECT_NOT_FOUND"):
            self.service.object_detail("artifact-v3", "unknown", 0.5)

    def test_random_access_jumps_into_a_large_sorted_view(self) -> None:
        count = 120_100
        positions = np.arange(count, dtype=np.int64)
        scores = ((positions * 37) % count).astype(float) / (count - 1)
        y_true = (positions % 2).astype(np.int64)
        predicted = scores >= 0.5
        tp = int(np.count_nonzero(predicted & (y_true == 1)))
        tn = int(np.count_nonzero(~predicted & (y_true == 0)))
        fp = int(np.count_nonzero(predicted & (y_true == 0)))
        fn = int(np.count_nonzero(~predicted & (y_true == 1)))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        evidence = OOFResultEvidence(
            y_true=y_true, identifier_display=tuple(f"row-{item}" for item in positions),
            model_input=np.zeros((count, 2)), feature_ids=("score", "other"), feature_columns=("score", "other"), fold_models=(),
        )
        output = replace(
            self.artifact.run_output,
            oof_positive_proba=scores,
            fold_assignments=(positions % 3 + 1).astype(np.int64),
            row_positions=tuple(positions.tolist()),
            oof_evidence=evidence,
            result=replace(
                self.artifact.run_output.result,
                confusion={"threshold": 0.5, "tp": tp, "tn": tn, "fp": fp, "fn": fn},
                metrics={**self.artifact.run_output.result.metrics, "precision_at_0_5": precision, "recall_at_0_5": recall, "f1_at_0_5": f1},
            ),
        )
        large = replace(self.artifact, run_output=output)
        service = OOFResultService(_Store(large))

        view = service.objects("artifact-v3", 0.5, 120_000, 50, sort="SCORE_DESC")
        expected = np.lexsort((positions, -scores))[120_000:120_050]

        self.assertEqual((view.total_count, view.filtered_count, view.returned_count), (count, count, 50))
        self.assertEqual([item.identifier_display for item in view.items], [f"row-{item}" for item in expected])

    def test_incomplete_and_corrupt_results_fail_closed(self) -> None:
        legacy = replace(self.artifact, manifest={"artifact_schema_version": "2"})
        incomplete = replace(
            self.artifact,
            run_output=replace(self.artifact.run_output, oof_evidence=None),
        )
        mismatched = replace(
            self.artifact,
            run_output=replace(
                self.artifact.run_output,
                result=replace(self.artifact.run_output.result, confusion={"threshold": 0.5, "tp": 0, "tn": 0, "fp": 0, "fn": 0}),
            ),
        )
        for artifact, code in ((legacy, "OOF_RESULT_EVIDENCE_INCOMPLETE"), (incomplete, "OOF_RESULT_EVIDENCE_INCOMPLETE"), (mismatched, "RESULT_INTEGRITY_ERROR")):
            with self.subTest(code=code), self.assertRaisesRegex(OOFResultError, code):
                OOFResultService(_Store(artifact)).summary("artifact-v3")
        with self.assertRaisesRegex(OOFResultError, "RESULT_NOT_FOUND"):
            OOFResultService(_Store(ValueError("Experiment artifact directory is missing or incomplete."))).summary("unknown")
        with self.assertRaisesRegex(OOFResultError, "RESULT_INTEGRITY_ERROR"):
            OOFResultService(_Store(ValueError("Experiment artifact file integrity check failed."))).summary("artifact-v3")

    @staticmethod
    def _artifact() -> LoadedExperimentArtifact:
        config = ExperimentConfig(
            "experiment", "dataset", "fingerprint", "target", ("score", "other"), None,
            ("main",), "model", "1", {}, "oof", "1", 7, 3, "oof", None, None, (),
        )
        metrics = {
            "gini": 0.4, "roc_auc": 0.7, "pr_auc": 0.6,
            "precision_at_0_5": 0.5, "recall_at_0_5": 2 / 3, "f1_at_0_5": 4 / 7,
        }
        result = ExperimentResult(
            "result", config.experiment_id, config.config_hash, "fingerprint", config.feature_set_hash,
            "model", "1", "oof", metrics, {"threshold": 0.5, "tp": 2, "tn": 1, "fp": 2, "fn": 1},
            ({"fold": 1, "roc_auc": 0.7},), 1.5, {}, "code", "2026-01-01T00:00:00+00:00", ("OOF only",),
        )
        evidence = OOFResultEvidence(
            y_true=np.array([1, 0, 1, 0, 1, 0]),
            identifier_display=("Клиент", "кЛИЕНТ-2", "Duplicate", "Duplicate", "Other", "Other-2"),
            model_input=np.zeros((6, 2)), feature_ids=("score", "other"), feature_columns=("score", "other"), fold_models=(),
        )
        output = ExperimentRunOutput(
            result, np.array([0.8, 0.8, 0.5, 0.2, 0.1, 0.5]), np.array([1, 2, 3, 1, 2, 3]),
            (40, 10, 30, 20, 50, 60), "population", "population-fingerprint", evidence,
        )
        return LoadedExperimentArtifact("artifact-v3", config, object(), object(), output, {"artifact_schema_version": "3"})


if __name__ == "__main__":
    unittest.main()
