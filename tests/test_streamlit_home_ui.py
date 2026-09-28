"""Focused regression coverage for AXION Home navigation decisions."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app.streamlit_app as prototype
from app.session_state import (
    cancel_new_analysis,
    confirm_new_analysis,
    continue_current_analysis,
    has_current_analysis,
    has_meaningful_analysis,
    initialize,
    open_home,
    open_result,
    request_new_analysis,
)
from app.upload_staging import StagedUpload


class HomeSessionNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state: dict[str, object] = {}
        initialize(self.state)

    def test_fresh_session_opens_home_without_changing_wizard_step(self) -> None:
        self.assertEqual(self.state["presentation_surface"], "HOME")
        self.assertFalse(self.state["analysis_started"])
        self.assertFalse(has_current_analysis(self.state))
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
        self.assertFalse(has_meaningful_analysis(self.state))
        self.assertTrue(has_current_analysis(self.state))
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["highest_reached_step"], 0)

    def test_clean_started_analysis_is_resumable_from_home_without_reset_confirmation(
        self,
    ) -> None:
        self.assertFalse(request_new_analysis(self.state))
        open_home(self.state)
        streamlit = _QuickStartStreamlit(self.state)

        with patch.object(prototype, "st", streamlit):
            prototype._render_quick_start()

        self.assertIn("Продолжить текущий анализ", streamlit.button_labels)
        continue_current_analysis(self.state)
        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["highest_reached_step"], 0)

    def test_meaningful_legacy_state_is_current_analysis_without_started_marker(
        self,
    ) -> None:
        self.state.update(selected_model_id="catboost", analysis_started=False)

        self.assertTrue(has_meaningful_analysis(self.state))
        self.assertTrue(has_current_analysis(self.state))

    def test_started_empty_analysis_does_not_require_reset_confirmation(self) -> None:
        self.state["analysis_started"] = True

        self.assertFalse(has_meaningful_analysis(self.state))
        self.assertFalse(request_new_analysis(self.state))
        self.assertFalse(self.state["new_analysis_confirmation_pending"])

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

    def test_analysis_confirmation_is_rendered_and_cancel_keeps_exact_analysis_position(
        self,
    ) -> None:
        self.state.update(
            presentation_surface="ANALYSIS",
            current_step=3,
            highest_reached_step=3,
            selected_model_id="catboost",
        )
        self.assertTrue(request_new_analysis(self.state))
        streamlit = _ConfirmationStreamlit(self.state)

        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "_render_analysis"),
        ):
            prototype.main()

        self.assertEqual(len(streamlit.warnings), 1)
        cancel_new_analysis(self.state)
        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertEqual(self.state["current_step"], 3)
        self.assertEqual(self.state["highest_reached_step"], 3)

    def test_confirm_from_analysis_opens_clean_data_step(self) -> None:
        self.state.update(
            presentation_surface="ANALYSIS",
            current_step=2,
            highest_reached_step=2,
            selected_model_id="catboost",
            experiment_plan=object(),
        )
        request_new_analysis(self.state)

        confirm_new_analysis(self.state)

        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["highest_reached_step"], 0)
        self.assertIsNone(self.state["selected_model_id"])
        self.assertIsNone(self.state["experiment_plan"])

    def test_session_model_result_navigation_opens_analysis_and_preserves_state(
        self,
    ) -> None:
        dataset = object()
        artifact = SimpleNamespace(artifact_id="artifact-1")
        model = SimpleNamespace(
            summary=SimpleNamespace(experiment_artifact_id="artifact-1")
        )
        self.state.update(
            presentation_surface="HOME",
            current_step=1,
            highest_reached_step=3,
            dataset_context=dataset,
            loaded_artifact=artifact,
            loaded_model_version=model,
        )

        open_result(self.state)

        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")
        self.assertEqual(self.state["current_step"], 4)
        self.assertEqual(self.state["highest_reached_step"], 4)
        self.assertIs(self.state["dataset_context"], dataset)
        self.assertIs(self.state["loaded_artifact"], artifact)
        self.assertIs(self.state["loaded_model_version"], model)

    def test_confirmed_reset_clears_only_session_analysis_state(self) -> None:
        persistent_marker = object()
        staging_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, staging_root, ignore_errors=True)
        dataset_upload = staging_root / "upload-dataset"
        inference_upload = staging_root / "upload-inference"
        dataset_upload.mkdir()
        inference_upload.mkdir()
        dataset_path = dataset_upload / "dataset.csv"
        inference_path = inference_upload / "inference.csv"
        dataset_path.write_text("dataset", encoding="utf-8")
        inference_path.write_text("inference", encoding="utf-8")
        staged_dataset = StagedUpload(
            dataset_path, "dataset.csv", "dataset", staging_root
        )
        staged_inference = StagedUpload(
            inference_path, "inference.csv", "inference", staging_root
        )
        old_target_key = prototype._preparation_form_key(
            1, "same-fingerprint", "target"
        )
        old_identifier_key = prototype._preparation_form_key(
            1, "same-fingerprint", "identifier"
        )
        old_positive_key = prototype._preparation_form_key(
            1, "same-fingerprint", "positive"
        )
        self.state.update(
            current_step=4,
            highest_reached_step=4,
            context_revision=1,
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
            prototype_staged_dataset_upload=staged_dataset,
            prototype_staged_inference_upload=staged_inference,
            prototype_source_control_locator=("explicit_local", "C:/selected.csv"),
            prototype_source_error="error",
            prototype_7_feature="selected",
            **{
                old_target_key: "DefMark",
                old_identifier_key: "INN",
                old_positive_key: "1",
                "preparation_1_same-fingerprint_blocked-reason:score": "old reason",
            },
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
        self.assertFalse(dataset_path.exists())
        self.assertFalse(inference_path.exists())
        self.assertNotIn("prototype_source_control_locator", self.state)
        self.assertNotIn("prototype_source_error", self.state)
        self.assertNotIn("prototype_7_feature", self.state)
        self.assertFalse(any(key.startswith("preparation_") for key in self.state))
        self.assertGreater(self.state["context_revision"], 1)
        next_target_key = prototype._preparation_form_key(
            self.state["context_revision"], "same-fingerprint", "target"
        )
        self.assertNotEqual(next_target_key, old_target_key)
        self.assertNotIn(next_target_key, self.state)
        for old_key in (old_target_key, old_identifier_key, old_positive_key):
            self.assertNotIn(old_key, self.state)
        self.assertNotIn("DefMark", self.state.values())
        self.assertNotIn("INN", self.state.values())
        self.assertNotIn("1", self.state.values())
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


class _SessionState(dict):
    def __getattr__(self, key: str):
        return self[key]


class _ConfirmationColumn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def button(self, *_args, **_kwargs):
        return False


class _ConfirmationStreamlit:
    def __init__(self, state: dict[str, object]) -> None:
        self.session_state = _SessionState(state)
        self.sidebar = _ConfirmationColumn()
        self.warnings: list[str] = []

    def set_page_config(self, **_kwargs) -> None:
        return None

    def html(self, _body: str) -> None:
        return None

    def image(self, *_args, **_kwargs) -> None:
        return None

    def button(self, *_args, **_kwargs) -> bool:
        return False

    def divider(self) -> None:
        return None

    def caption(self, _body: str) -> None:
        return None

    def warning(self, body: str) -> None:
        self.warnings.append(body)

    def columns(self, _specification, **_kwargs):
        return _ConfirmationColumn(), _ConfirmationColumn()


class _QuickStartColumn(_ConfirmationColumn):
    def __init__(self, button_labels: list[str]) -> None:
        self._button_labels = button_labels

    def button(self, label: str, **_kwargs) -> bool:
        self._button_labels.append(label)
        return False

    def caption(self, _body: str) -> None:
        return None


class _QuickStartStreamlit:
    def __init__(self, state: dict[str, object]) -> None:
        self.session_state = _SessionState(state)
        self.button_labels: list[str] = []

    def html(self, _body: str) -> None:
        return None

    def columns(self, _specification, **_kwargs):
        return tuple(_QuickStartColumn(self.button_labels) for _ in range(3))

    def button(self, label: str, **_kwargs) -> bool:
        self.button_labels.append(label)
        return False

    def caption(self, _body: str) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
