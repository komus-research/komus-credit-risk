"""Focused regression coverage for AXION Home navigation decisions."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.session_state import (
    cancel_new_analysis,
    confirm_new_analysis,
    continue_current_analysis,
    has_meaningful_analysis,
    initialize,
    open_home,
    request_new_analysis,
)


class HomeSessionNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state: dict[str, object] = {}
        initialize(self.state)

    def test_fresh_session_opens_home_without_changing_wizard_step(self) -> None:
        self.assertEqual(self.state["presentation_surface"], "HOME")
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["highest_reached_step"], 0)

    def test_opening_home_preserves_analysis_objects(self) -> None:
        dataset, plan, result = object(), object(), object()
        self.state.update(
            presentation_surface="ANALYSIS",
            current_step=3,
            highest_reached_step=3,
            dataset_context=dataset,
            experiment_plan=plan,
            loaded_artifact=result,
        )

        open_home(self.state)

        self.assertEqual(self.state["presentation_surface"], "HOME")
        self.assertEqual(self.state["current_step"], 3)
        self.assertIs(self.state["dataset_context"], dataset)
        self.assertIs(self.state["experiment_plan"], plan)
        self.assertIs(self.state["loaded_artifact"], result)

    def test_continue_returns_to_exact_step_without_reaching_a_new_one(self) -> None:
        self.state.update(
            current_step=2, highest_reached_step=3, selected_model_id="catboost"
        )

        continue_current_analysis(self.state)

        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertEqual(self.state["current_step"], 2)
        self.assertEqual(self.state["highest_reached_step"], 3)

    def test_empty_new_analysis_opens_clean_data_step_without_confirmation(
        self,
    ) -> None:
        confirmation_needed = request_new_analysis(self.state)

        self.assertFalse(confirmation_needed)
        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertTrue(self.state["analysis_started"])
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["highest_reached_step"], 0)

    def test_staged_upload_and_selected_source_each_require_confirmation(self) -> None:
        self.state["prototype_staged_dataset_upload"] = object()
        self.assertTrue(has_meaningful_analysis(self.state))
        self.assertTrue(request_new_analysis(self.state))
        self.assertTrue(self.state["new_analysis_confirmation_pending"])

        other: dict[str, object] = {}
        initialize(other)
        other["prototype_source_control_locator"] = (
            "explicit_local",
            "C:/selected.csv",
        )
        self.assertTrue(has_meaningful_analysis(other))
        self.assertTrue(request_new_analysis(other))

    def test_source_error_without_selected_source_does_not_require_confirmation(
        self,
    ) -> None:
        self.state["prototype_source_error"] = "unreadable"

        self.assertFalse(has_meaningful_analysis(self.state))
        self.assertFalse(request_new_analysis(self.state))

    def test_prepared_and_downstream_state_require_confirmation_and_cancel_preserves_them(
        self,
    ) -> None:
        prepared, model, artifact = object(), object(), object()
        self.state.update(
            dataset_source_preparation=prepared,
            selected_model_id="catboost",
            experiment_plan=model,
            loaded_artifact=artifact,
        )

        self.assertTrue(request_new_analysis(self.state))
        cancel_new_analysis(self.state)

        self.assertFalse(self.state["new_analysis_confirmation_pending"])
        self.assertIs(self.state["dataset_source_preparation"], prepared)
        self.assertEqual(self.state["selected_model_id"], "catboost")
        self.assertIs(self.state["experiment_plan"], model)
        self.assertIs(self.state["loaded_artifact"], artifact)

    def test_confirmed_reset_clears_only_session_analysis_state(self) -> None:
        persistent_marker = object()
        self.state.update(
            current_step=4,
            highest_reached_step=4,
            dataset_context=object(),
            dataset_source_preparation=object(),
            dataset_preparation_snapshot=object(),
            selected_feature_ids=("Q_A1_norm",),
            selected_model_id="catboost",
            experiment_inputs={"seed": 42},
            experiment_plan=object(),
            loaded_artifact=object(),
            loaded_model_version=SimpleNamespace(
                summary=SimpleNamespace(model_version_id="v1")
            ),
            inference_snapshot=object(),
            prediction_batch=object(),
            result_interpreter_response=object(),
            prototype_staged_dataset_upload=object(),
            prototype_staged_inference_upload=object(),
            prototype_source_control_locator=("explicit_local", "C:/selected.csv"),
            prototype_source_error="error",
            prototype_7_feature="selected",
            external_persisted_store_marker=persistent_marker,
        )

        confirm_new_analysis(self.state)

        for key in (
            "dataset_context",
            "dataset_source_preparation",
            "dataset_preparation_snapshot",
            "selected_model_id",
            "experiment_plan",
            "loaded_artifact",
            "loaded_model_version",
            "inference_snapshot",
            "prediction_batch",
            "result_interpreter_response",
        ):
            self.assertIsNone(self.state[key])
        self.assertEqual(self.state["selected_feature_ids"], ())
        self.assertEqual(self.state["experiment_inputs"], {})
        self.assertNotIn("prototype_staged_dataset_upload", self.state)
        self.assertNotIn("prototype_staged_inference_upload", self.state)
        self.assertNotIn("prototype_source_control_locator", self.state)
        self.assertNotIn("prototype_source_error", self.state)
        self.assertNotIn("prototype_7_feature", self.state)
        self.assertIs(self.state["external_persisted_store_marker"], persistent_marker)
        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertEqual(self.state["current_step"], 0)

    def test_home_source_has_only_truthful_empty_states_and_session_model_scope(
        self,
    ) -> None:
        source = open("app/streamlit_app.py", encoding="utf-8").read()

        self.assertIn("Сводная история пока не подключена", source)
        self.assertIn("История проектов пока не подключена", source)
        self.assertIn("Сейчас нет фоновых операций", source)
        self.assertIn("Нет уведомлений, требующих внимания", source)
        self.assertIn("Текущая сессия", source)
        self.assertNotIn('"12"', source)
        self.assertNotIn('"8"', source)
        self.assertNotIn('"3"', source)
        self.assertNotIn('"7"', source)


if __name__ == "__main__":
    unittest.main()
