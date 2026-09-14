"""Tests for wizard state invalidation and snapshot-only execution mapping."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.session_state import (
    apply_feature_widget_selection,
    apply_group_widget_selection,
    initialize,
    run_request_from_snapshot,
    set_dataset_context,
    set_experiment_inputs,
    set_group_selection,
    set_selected_feature_ids,
    set_selected_model_id,
    synchronize_feature_widgets,
    toggle_feature,
)
from komus_risk.planning import PlanningRequestMetadata


class SessionStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {}
        initialize(self.state)

    def test_dataset_switch_clears_all_downstream_current_state(self) -> None:
        first = SimpleNamespace(context_id="one", loaded_dataset=SimpleNamespace(contract="fingerprint-one"))
        second = SimpleNamespace(context_id="two", loaded_dataset=SimpleNamespace(contract="fingerprint-two"))
        set_dataset_context(self.state, first)
        self.state.update(
            selected_feature_ids=("a",), selected_model_id="model", experiment_inputs={"seed": 42},
            planning_request_snapshot=object(), experiment_plan=object(), loaded_artifact=object(), comparison_result=object(),
        )

        set_dataset_context(self.state, second)

        self.assertEqual(self.state["selected_feature_ids"], ())
        self.assertIsNone(self.state["selected_model_id"])
        self.assertEqual(self.state["experiment_inputs"], {})
        self.assertIsNone(self.state["planning_request_snapshot"])
        self.assertIsNone(self.state["experiment_plan"])
        self.assertIsNone(self.state["loaded_artifact"])
        self.assertIsNone(self.state["comparison_result"])

    def test_feature_model_and_input_changes_invalidate_an_old_plan(self) -> None:
        self.state.update(planning_request_snapshot=object(), experiment_plan=object(), loaded_artifact=object(), comparison_result=object())
        toggle_feature(self.state, "b", True)
        toggle_feature(self.state, "a", True)
        set_group_selection(self.state, ("c", "d"), True)
        set_selected_model_id(self.state, "dynamic-model")
        set_experiment_inputs(self.state, {"seed": 42})

        self.assertEqual(self.state["selected_feature_ids"], ("b", "a", "c", "d"))
        self.assertEqual(self.state["selected_model_id"], "dynamic-model")
        self.assertIsNone(self.state["planning_request_snapshot"])
        self.assertIsNone(self.state["experiment_plan"])
        self.assertIsNone(self.state["loaded_artifact"])
        self.assertIsNone(self.state["comparison_result"])

    def test_group_widget_selects_all_children_without_reordering_or_conflict(self) -> None:
        group_ids, keys, group_key = ("b", "a"), {"b": "widget_b", "a": "widget_a"}, "widget_group"
        self.state["blocked_widget"] = False
        synchronize_feature_widgets(self.state, group_ids, group_widget_key=group_key, feature_widget_keys=keys)
        self.state[group_key] = True

        apply_group_widget_selection(self.state, group_ids, group_widget_key=group_key, feature_widget_keys=keys)

        self.assertEqual(self.state["selected_feature_ids"], ("b", "a"))
        self.assertTrue(self.state[group_key])
        self.assertTrue(self.state["widget_b"])
        self.assertTrue(self.state["widget_a"])
        self.assertFalse(self.state["blocked_widget"])

    def test_individual_widget_updates_aggregate_group_state(self) -> None:
        group_ids, keys, group_key = ("a", "b"), {"a": "widget_a", "b": "widget_b"}, "widget_group"
        set_selected_feature_ids(self.state, ("a",))
        synchronize_feature_widgets(self.state, group_ids, group_widget_key=group_key, feature_widget_keys=keys)
        self.state["widget_b"] = True

        apply_feature_widget_selection(self.state, "b", group_ids, group_widget_key=group_key, feature_widget_keys=keys)

        self.assertEqual(self.state["selected_feature_ids"], ("a", "b"))
        self.assertTrue(self.state[group_key])
        self.state["widget_a"] = False
        apply_feature_widget_selection(self.state, "a", group_ids, group_widget_key=group_key, feature_widget_keys=keys)
        self.assertEqual(self.state["selected_feature_ids"], ("b",))
        self.assertFalse(self.state[group_key])

    def test_group_widget_deselect_removes_only_selectable_children(self) -> None:
        group_ids, keys, group_key = ("a", "b"), {"a": "widget_a", "b": "widget_b"}, "widget_group"
        set_selected_feature_ids(self.state, ("outside", "a", "b"))
        synchronize_feature_widgets(self.state, group_ids, group_widget_key=group_key, feature_widget_keys=keys)
        self.state[group_key] = False

        apply_group_widget_selection(self.state, group_ids, group_widget_key=group_key, feature_widget_keys=keys)

        self.assertEqual(self.state["selected_feature_ids"], ("outside",))
        self.assertFalse(self.state["widget_a"])
        self.assertFalse(self.state["widget_b"])

    def test_run_request_is_an_exact_copy_of_the_confirmed_snapshot(self) -> None:
        snapshot = PlanningRequestMetadata(
            selected_feature_ids=("b", "a"), model_id="dynamic-model", protocol_id="protocol", protocol_version="2",
            seed=43, folds=4, evaluation_level="oof", reference_artifact_id="reference", changed_dimension="feature_set",
            changed_elements=("removed/a", "added/b"),
        )

        request = run_request_from_snapshot(snapshot)
        set_selected_feature_ids(self.state, ("different",))

        self.assertEqual(request.selected_feature_ids, ("b", "a"))
        self.assertEqual(request.model_id, snapshot.model_id)
        self.assertEqual(request.protocol_id, snapshot.protocol_id)
        self.assertEqual(request.protocol_version, snapshot.protocol_version)
        self.assertEqual(request.seed, snapshot.seed)
        self.assertEqual(request.folds, snapshot.folds)
        self.assertEqual(request.evaluation_level, snapshot.evaluation_level)
        self.assertEqual(request.reference_artifact_id, snapshot.reference_artifact_id)
        self.assertEqual(request.changed_dimension, snapshot.changed_dimension)
        self.assertEqual(request.changed_elements, ("removed/a", "added/b"))


if __name__ == "__main__":
    unittest.main()
