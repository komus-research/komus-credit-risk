"""Tests for display-only predictor family grouping."""

from __future__ import annotations

import unittest

from app.feature_display import FeatureFamily, feature_family_id, group_feature_ids_by_family


class FeatureDisplayTests(unittest.TestCase):
    def test_numbered_feature_ids_map_to_display_families(self) -> None:
        self.assertEqual(feature_family_id("Q_A1_norm"), "Q_A")
        self.assertEqual(feature_family_id("Q_B3_norm"), "Q_B")
        self.assertEqual(feature_family_id("A1_norm"), "A")
        self.assertEqual(feature_family_id("D5_norm"), "D")

    def test_non_numbered_ids_with_and_without_norm_remain_distinct_families(self) -> None:
        feature_ids = ("TOTAL_norm", "TOTAL", "risk_score_norm", "risk_score")

        families = group_feature_ids_by_family(feature_ids)

        self.assertEqual(
            families,
            tuple(FeatureFamily(feature_id, (feature_id,)) for feature_id in feature_ids),
        )

    def test_grouping_preserves_feature_registry_order(self) -> None:
        feature_ids = ("Q_A1_norm", "Q_A7_norm", "Q_B3_norm", "A1_norm", "A6_norm", "D1_norm", "D5_norm")

        families = group_feature_ids_by_family(feature_ids)

        self.assertEqual(
            families,
            (
                FeatureFamily("Q_A", ("Q_A1_norm", "Q_A7_norm")),
                FeatureFamily("Q_B", ("Q_B3_norm",)),
                FeatureFamily("A", ("A1_norm", "A6_norm")),
                FeatureFamily("D", ("D1_norm", "D5_norm")),
            ),
        )
        self.assertEqual(tuple(feature_id for family in families for feature_id in family.feature_ids), feature_ids)


if __name__ == "__main__":
    unittest.main()
