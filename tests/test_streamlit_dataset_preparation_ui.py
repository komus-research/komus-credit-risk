"""Regression coverage for arbitrary-source confirmation wiring."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.bootstrap import (
    LocalDatasetSourceResolver,
    confirm_dataset_preparation,
    default_preparation_draft,
    prepare_resolved_source,
    reopen_dataset_preparation,
)
from app.session_state import initialize, set_dataset_source_preparation


class DatasetPreparationUiTests(unittest.TestCase):
    def _checked_source(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "arbitrary.csv"
        path.write_text(
            "entity_id,target,score,Q_B1_norm\n"
            "a,0,0.1,1.0\n"
            "b,1,0.9,0.2\n"
            "c,0,0.2,0.4\n"
            "d,1,0.8,0.3\n",
            encoding="utf-8",
        )
        source = LocalDatasetSourceResolver().resolve_explicit_local_path(path)
        return prepare_resolved_source(source)

    def _checked_two_target_source(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "two_targets.csv"
        path.write_text(
            "entity_id,target_a,target_b,score\n"
            "a,0,1,0.1\n"
            "b,1,0,0.9\n"
            "c,0,1,0.2\n"
            "d,1,0,0.8\n",
            encoding="utf-8",
        )
        source = LocalDatasetSourceResolver().resolve_explicit_local_path(path)
        return prepare_resolved_source(source)

    @staticmethod
    def _confirmation_draft(preparation, *, allowed: str):
        draft = default_preparation_draft(preparation)
        draft.update(
            target_column="target",
            identifier_column="entity_id",
            positive_class=1,
            population_policy_acknowledged=True,
        )
        draft["column_statuses"] = {
            "score": "MODEL_ALLOWED" if allowed == "score" else "DIAGNOSTIC_ONLY",
            "Q_B1_norm": "MODEL_ALLOWED" if allowed == "Q_B1_norm" else "DIAGNOSTIC_ONLY",
            "target": "DIAGNOSTIC_ONLY",
            "entity_id": "DIAGNOSTIC_ONLY",
        }
        return draft

    def test_analysis_prefills_only_a_draft_and_never_unlocks_navigation(self) -> None:
        preparation = self._checked_source()

        self.assertEqual(preparation.preparation_status, "context_not_prepared")
        self.assertIsNone(preparation.context)
        self.assertIsNone(preparation.manifest)
        self.assertEqual(default_preparation_draft(preparation)["positive_class"], None)
        self.assertFalse(default_preparation_draft(preparation)["population_policy_acknowledged"])

    def test_generic_onboarding_does_not_render_legacy_footer_navigation(self) -> None:
        import app.streamlit_app as prototype

        self.assertEqual(prototype._DATASET_ONBOARDING_STEPS, ("Файл", "Подготовка", "Проверка"))
        self.assertFalse(hasattr(prototype, "_render_feature_onboarding_step"))
        self.assertFalse(hasattr(prototype, "_render_evaluation_onboarding_step"))

        class State(dict):
            __getattr__ = dict.__getitem__

        class Streamlit:
            def __init__(self, preparation):
                self.session_state = State(dataset_source_preparation=preparation)

            def header(self, _label):
                return None

            def caption(self, _label):
                return None

        preparation = SimpleNamespace(is_prepared=False, snapshot=object())
        streamlit = Streamlit(preparation)
        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "_render_dataset_onboarding") as onboarding,
            patch.object(prototype, "_navigation_button") as navigation,
        ):
            prototype._render_data_step()

        onboarding.assert_called_once_with(preparation)
        navigation.assert_not_called()

    def test_generic_default_uses_technical_predictor_compatibility(self) -> None:
        preparation = self._checked_source()
        draft = default_preparation_draft(preparation)

        self.assertEqual(draft["column_statuses"]["entity_id"], "DIAGNOSTIC_ONLY")
        self.assertEqual(draft["column_statuses"]["target"], "MODEL_ALLOWED")
        self.assertEqual(draft["column_statuses"]["score"], "MODEL_ALLOWED")

    def test_generic_default_marks_non_finite_numeric_columns_diagnostic_only(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "non-finite.csv"
        path.write_text(
            "entity_id,target,score\n"
            "a,0,0.1\n"
            "b,1,inf\n"
            "c,0,0.2\n"
            "d,1,0.8\n",
            encoding="utf-8",
        )
        preparation = prepare_resolved_source(
            LocalDatasetSourceResolver().resolve_explicit_local_path(path)
        )

        self.assertEqual(default_preparation_draft(preparation)["column_statuses"]["score"], "DIAGNOSTIC_ONLY")

    def test_review_feature_constraints_are_compact_and_exclude_target_and_identifier(self) -> None:
        import app.streamlit_app as prototype

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "constraints.csv"
        path.write_text(
            "entity_id,target,score,comment\n"
            "a,0,0.1,low\n"
            "b,1,0.9,high\n",
            encoding="utf-8",
        )
        preparation = prepare_resolved_source(LocalDatasetSourceResolver().resolve_explicit_local_path(path))
        draft = default_preparation_draft(preparation)
        draft.update(target_column="target", identifier_column="entity_id", positive_class=1)

        class Expander:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Streamlit:
            def __init__(self):
                self.session_state = {"context_revision": 1}
                self.expanders = []
                self.selectboxes = []

            def expander(self, label, **kwargs):
                self.expanders.append((label, kwargs))
                return Expander()

            def selectbox(self, label, options, *, key, **_kwargs):
                self.selectboxes.append((label, tuple(options)))
                if key not in self.session_state:
                    self.session_state[key] = options[0]
                return self.session_state[key]

            def checkbox(self, _label, *, key):
                return self.session_state[key]

            def button(self, *_args, **_kwargs):
                return False

            def __getattr__(self, _name):
                return lambda *_args, **_kwargs: None

        streamlit = Streamlit()
        with patch.object(prototype, "st", streamlit):
            prototype._render_review_onboarding_step(preparation, draft)

        self.assertIn(("Ограничения признаков", {"expanded": False}), streamlit.expanders)
        controls = dict(streamlit.selectboxes)
        self.assertNotIn("target", controls)
        self.assertNotIn("entity_id", controls)
        self.assertEqual(controls["score"], ("MODEL_ALLOWED", "DIAGNOSTIC_ONLY", "BLOCKED"))
        self.assertEqual(controls["comment"], ("DIAGNOSTIC_ONLY", "BLOCKED"))

    def test_advanced_status_changes_only_the_preparation_draft(self) -> None:
        import app.streamlit_app as prototype

        draft = {
            "target_column": "target",
            "identifier_column": "entity_id",
            "column_statuses": {"score": "MODEL_ALLOWED", "target": "MODEL_ALLOWED", "entity_id": "MODEL_ALLOWED"},
            "blocked_reasons": {},
        }
        state = {"preparation_1_snapshot_blocked-reason:score": "old reason"}

        self.assertEqual(
            prototype._set_advanced_column_status(draft, "score", "DIAGNOSTIC_ONLY", compatible=True, state=state),
            "DIAGNOSTIC_ONLY",
        )
        self.assertEqual(draft["column_statuses"]["score"], "DIAGNOSTIC_ONLY")
        self.assertEqual(
            prototype._set_advanced_column_status(draft, "score", "MODEL_ALLOWED", compatible=True, state=state),
            "MODEL_ALLOWED",
        )
        self.assertEqual(draft["column_statuses"]["score"], "MODEL_ALLOWED")
        self.assertEqual(draft["column_statuses"]["target"], "MODEL_ALLOWED")
        self.assertEqual(draft["column_statuses"]["entity_id"], "MODEL_ALLOWED")
        self.assertNotIn("preparation_1_snapshot_blocked-reason:score", state)

    def test_advanced_blocked_reason_controls_confirmation_and_is_cleared_on_status_change(self) -> None:
        import app.streamlit_app as prototype

        draft = {
            "target_column": "target",
            "identifier_column": "entity_id",
            "column_statuses": {"score": "MODEL_ALLOWED"},
            "blocked_reasons": {},
        }
        state = {"preparation_1_snapshot_blocked-reason:score": "business exception"}

        prototype._set_advanced_column_status(draft, "score", "BLOCKED", compatible=True, state=state)
        self.assertTrue(prototype._has_blocked_predictor_without_reason(draft))
        draft["blocked_reasons"]["score"] = "business exception"
        self.assertFalse(prototype._has_blocked_predictor_without_reason(draft))
        prototype._set_advanced_column_status(draft, "score", "DIAGNOSTIC_ONLY", compatible=True, state=state)
        self.assertNotIn("score", draft["blocked_reasons"])
        self.assertNotIn("preparation_1_snapshot_blocked-reason:score", state)

    def test_review_disables_confirmation_for_a_blocked_predictor_without_reason(self) -> None:
        import app.streamlit_app as prototype

        preparation = self._checked_source()
        draft = default_preparation_draft(preparation)
        draft.update(
            target_column="target",
            identifier_column="entity_id",
            positive_class=1,
            population_policy_acknowledged=True,
        )
        draft["column_statuses"]["score"] = "BLOCKED"
        draft["blocked_reasons"] = {}

        class Expander:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Streamlit:
            def __init__(self):
                self.session_state = {"context_revision": 1}
                self.button_calls = []

            def expander(self, *_args, **_kwargs):
                return Expander()

            def selectbox(self, _label, options, *, key, **_kwargs):
                if key not in self.session_state:
                    self.session_state[key] = "BLOCKED" if "BLOCKED" in options and "score" in key else options[0]
                return self.session_state[key]

            def text_input(self, _label, *, key):
                return self.session_state[key]

            def checkbox(self, _label, *, key):
                return self.session_state[key]

            def button(self, label, **kwargs):
                self.button_calls.append((label, kwargs))
                return False

            def __getattr__(self, _name):
                return lambda *_args, **_kwargs: None

        streamlit = Streamlit()
        with patch.object(prototype, "st", streamlit):
            prototype._render_review_onboarding_step(preparation, draft)

        confirmation = next(kwargs for label, kwargs in streamlit.button_calls if label == "Подтвердить и продолжить")
        self.assertTrue(confirmation["disabled"])

    def test_advanced_controls_cannot_allow_an_incompatible_predictor(self) -> None:
        import app.streamlit_app as prototype

        draft = {"column_statuses": {"comment": "DIAGNOSTIC_ONLY"}, "blocked_reasons": {}}

        status = prototype._set_advanced_column_status(
            draft, "comment", "MODEL_ALLOWED", compatible=False,
        )

        self.assertEqual(status, "DIAGNOSTIC_ONLY")
        self.assertEqual(draft["column_statuses"]["comment"], "DIAGNOSTIC_ONLY")

    def test_predictor_summary_counts_current_statuses_without_target_or_identifier(self) -> None:
        import app.streamlit_app as prototype

        statuses = prototype._predictor_statuses({
            "target_column": "target",
            "identifier_column": "entity_id",
            "column_statuses": {
                "target": "MODEL_ALLOWED",
                "entity_id": "BLOCKED",
                "score": "MODEL_ALLOWED",
                "comment": "DIAGNOSTIC_ONLY",
                "legacy": "BLOCKED",
            },
        })

        self.assertEqual(statuses, {
            "score": "MODEL_ALLOWED", "comment": "DIAGNOSTIC_ONLY", "legacy": "BLOCKED",
        })

    def test_arbitrary_source_reports_actual_analysis_stages(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "progress.csv"
        path.write_text("id,target,score\na,0,0.1\nb,1,0.9\n", encoding="utf-8")
        source = LocalDatasetSourceResolver().resolve_explicit_local_path(path)
        events: list[str] = []

        prepare_resolved_source(source, progress_listener=events.append)

        self.assertEqual(events, ["reading_source", "inspecting_dataset", "analyzing_preparation"])

    def test_population_policy_acknowledgement_blocks_materialization(self) -> None:
        preparation = self._checked_source()
        draft = self._confirmation_draft(preparation, allowed="score")
        draft["population_policy_acknowledged"] = False

        with patch("app.bootstrap.KomusDatasetPreparationService.prepare") as materialize:
            with self.assertRaisesRegex(ValueError, "POPULATION_POLICY_NOT_ACKNOWLEDGED"):
                confirm_dataset_preparation(preparation, draft)

        materialize.assert_not_called()

    def test_confirmation_reports_materialization_stages_after_acknowledgement(self) -> None:
        preparation = self._checked_source()
        events: list[str] = []

        confirmed = confirm_dataset_preparation(
            preparation,
            self._confirmation_draft(preparation, allowed="score"),
            progress_listener=events.append,
        )

        self.assertTrue(confirmed.is_prepared)
        self.assertEqual(events, ["validating_confirmation", "materializing_dataset", "prepared_context_ready"])

    def test_positive_class_resets_for_same_values_after_target_changes(self) -> None:
        import app.streamlit_app as prototype

        state = {}
        key = prototype._bind_positive_class_to_target(
            state,
            form_revision=1,
            snapshot_fingerprint="snapshot",
            target="target_a",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target_a",
            initial_positive_class=1,
        )
        self.assertEqual(state[key], 1)

        prototype._bind_positive_class_to_target(
            state,
            form_revision=1,
            snapshot_fingerprint="snapshot",
            target="target_b",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target_a",
            initial_positive_class=1,
        )

        self.assertEqual(state[key], "choose")
        self.assertEqual(state["preparation_1_snapshot_positive_target"], "target_b")

    def test_target_change_blocks_confirmation_until_positive_class_is_reselected(self) -> None:
        import app.streamlit_app as prototype

        preparation = self._checked_two_target_source()
        state = {}
        key = prototype._bind_positive_class_to_target(
            state,
            form_revision=1,
            snapshot_fingerprint=preparation.snapshot.fingerprint,
            target="target_a",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target_a",
            initial_positive_class=1,
        )
        prototype._bind_positive_class_to_target(
            state,
            form_revision=1,
            snapshot_fingerprint=preparation.snapshot.fingerprint,
            target="target_b",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target_a",
            initial_positive_class=1,
        )
        draft = default_preparation_draft(preparation)
        draft.update(
            target_column="target_b",
            identifier_column="entity_id",
            positive_class=None if state[key] == "choose" else state[key],
            population_policy_acknowledged=True,
            column_statuses={
                "entity_id": "DIAGNOSTIC_ONLY",
                "target_a": "DIAGNOSTIC_ONLY",
                "target_b": "DIAGNOSTIC_ONLY",
                "score": "MODEL_ALLOWED",
            },
        )

        with patch("app.bootstrap.KomusDatasetPreparationService.prepare") as materialize:
            with self.assertRaisesRegex(ValueError, "POSITIVE_CLASS_MISSING"):
                confirm_dataset_preparation(preparation, draft)

        materialize.assert_not_called()
        state[key] = 1
        draft["positive_class"] = state[key]
        self.assertTrue(confirm_dataset_preparation(preparation, draft).is_prepared)

    def test_switching_back_requires_a_new_positive_class_selection(self) -> None:
        import app.streamlit_app as prototype

        state = {}
        key = prototype._bind_positive_class_to_target(
            state, form_revision=1, snapshot_fingerprint="snapshot", target="target_a", target_values=[0, 1],
            placeholder="choose", initial_target="target_a", initial_positive_class=1,
        )
        prototype._bind_positive_class_to_target(
            state, form_revision=1, snapshot_fingerprint="snapshot", target="target_b", target_values=[0, 1],
            placeholder="choose", initial_target="target_a", initial_positive_class=1,
        )
        state[key] = 1
        prototype._bind_positive_class_to_target(
            state, form_revision=1, snapshot_fingerprint="snapshot", target="target_a", target_values=[0, 1],
            placeholder="choose", initial_target="target_a", initial_positive_class=1,
        )

        self.assertEqual(state[key], "choose")

    def test_edit_preparation_restores_positive_class_only_while_target_is_unchanged(self) -> None:
        import app.streamlit_app as prototype

        state = {}
        key = prototype._bind_positive_class_to_target(
            state, form_revision=1, snapshot_fingerprint="snapshot", target="target_a", target_values=[0, 1],
            placeholder="choose", initial_target="target_a", initial_positive_class=1,
        )
        self.assertEqual(state[key], 1)

        prototype._bind_positive_class_to_target(
            state, form_revision=1, snapshot_fingerprint="snapshot", target="target_b", target_values=[0, 1],
            placeholder="choose", initial_target="target_a", initial_positive_class=1,
        )
        self.assertEqual(state[key], "choose")

    def test_stale_recheck_same_fingerprint_uses_a_new_form_lifecycle(self) -> None:
        import app.streamlit_app as prototype

        preparation = self._checked_source()
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, preparation)
        first_revision = state["context_revision"]
        first_positive = prototype._bind_positive_class_to_target(
            state,
            form_revision=first_revision,
            snapshot_fingerprint=preparation.snapshot.fingerprint,
            target="target",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target",
            initial_positive_class=1,
        )
        first_acknowledgement = prototype._preparation_form_key(
            first_revision, preparation.snapshot.fingerprint, "population_acknowledged",
        )
        state[first_acknowledgement] = True

        prototype._invalidate_stale_preparation(state)
        rechecked = prepare_resolved_source(preparation.source)
        set_dataset_source_preparation(state, rechecked)
        second_revision = state["context_revision"]
        second_positive = prototype._bind_positive_class_to_target(
            state,
            form_revision=second_revision,
            snapshot_fingerprint=rechecked.snapshot.fingerprint,
            target="target",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target",
            initial_positive_class=None,
        )
        second_acknowledgement = prototype._preparation_form_key(
            second_revision, rechecked.snapshot.fingerprint, "population_acknowledged",
        )

        self.assertEqual(preparation.snapshot.fingerprint, rechecked.snapshot.fingerprint)
        self.assertNotEqual(first_revision, second_revision)
        self.assertEqual(state[first_positive], 1)
        self.assertTrue(state[first_acknowledgement])
        self.assertEqual(state[second_positive], "choose")
        self.assertNotIn(second_acknowledgement, state)

    def test_reopen_confirmed_preparation_restores_draft_in_a_new_form_lifecycle(self) -> None:
        import app.streamlit_app as prototype

        preparation = self._checked_source()
        confirmed = confirm_dataset_preparation(preparation, self._confirmation_draft(preparation, allowed="score"))
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, confirmed)
        previous_revision = state["context_revision"]
        editable = reopen_dataset_preparation(confirmed)
        set_dataset_source_preparation(state, editable)
        form_revision = state["context_revision"]
        draft = default_preparation_draft(editable)
        positive_key = prototype._bind_positive_class_to_target(
            state,
            form_revision=form_revision,
            snapshot_fingerprint=editable.snapshot.fingerprint,
            target=draft["target_column"],
            target_values=[0, 1],
            placeholder="choose",
            initial_target=draft["target_column"],
            initial_positive_class=draft["positive_class"],
        )
        acknowledgement_key = prototype._preparation_form_key(
            form_revision, editable.snapshot.fingerprint, "population_acknowledged",
        )

        self.assertNotEqual(previous_revision, form_revision)
        self.assertEqual(draft["target_column"], "target")
        self.assertEqual(state[positive_key], 1)
        self.assertNotIn(acknowledgement_key, state)

    def test_correctable_error_keeps_widgets_in_the_same_form_lifecycle(self) -> None:
        import app.streamlit_app as prototype

        preparation = self._checked_source()
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, preparation)
        form_revision = state["context_revision"]
        positive_key = prototype._bind_positive_class_to_target(
            state,
            form_revision=form_revision,
            snapshot_fingerprint=preparation.snapshot.fingerprint,
            target="target",
            target_values=[0, 1],
            placeholder="choose",
            initial_target="target",
            initial_positive_class=1,
        )
        draft = self._confirmation_draft(preparation, allowed="none")

        with self.assertRaisesRegex(ValueError, "NO_MODEL_ALLOWED_FEATURES"):
            confirm_dataset_preparation(preparation, draft)

        self.assertEqual(state["context_revision"], form_revision)
        self.assertEqual(state[positive_key], 1)

    def test_source_change_uses_a_distinct_form_scope(self) -> None:
        import app.streamlit_app as prototype

        first = self._checked_source()
        second = self._checked_two_target_source()
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, first)
        first_revision = state["context_revision"]
        first_key = prototype._preparation_form_key(first_revision, first.snapshot.fingerprint, "target")
        state[first_key] = "target"

        set_dataset_source_preparation(state, second)
        second_revision = state["context_revision"]
        second_key = prototype._preparation_form_key(second_revision, second.snapshot.fingerprint, "target")

        self.assertNotEqual(first_key, second_key)
        self.assertEqual(state[first_key], "target")
        self.assertNotIn(second_key, state)

    def test_reconfirmation_with_different_semantics_replaces_context_and_clears_downstream(self) -> None:
        preparation = self._checked_source()
        first = confirm_dataset_preparation(preparation, self._confirmation_draft(preparation, allowed="score"))
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, first)
        state.update(
            selected_feature_ids=("score",), selected_model_id="model", experiment_inputs={"folds": 3},
            experiment_plan=object(), loaded_artifact=object(), highest_reached_step=4,
        )

        second = confirm_dataset_preparation(preparation, self._confirmation_draft(preparation, allowed="Q_B1_norm"))
        set_dataset_source_preparation(state, second)

        self.assertIs(state["dataset_context"], second.context)
        self.assertNotEqual(first.context.context_id, second.context.context_id)
        self.assertEqual(state["selected_feature_ids"], ("Q_B1_norm",))
        self.assertIsNone(state["selected_model_id"])
        self.assertEqual(state["experiment_inputs"], {})
        self.assertIsNone(state["experiment_plan"])
        self.assertIsNone(state["loaded_artifact"])
        self.assertGreaterEqual(state["context_revision"], 2)

    def test_source_change_drops_preparation_artifacts(self) -> None:
        preparation = self._checked_source()
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, preparation)

        set_dataset_source_preparation(state, None)

        self.assertIsNone(state["dataset_preparation_snapshot"])
        self.assertIsNone(state["dataset_preparation_report"])
        self.assertIsNone(state["dataset_preparation_proposal"])
        self.assertIsNone(state["dataset_preparation_draft"])
        self.assertIsNone(state["dataset_preparation_manifest"])

    def test_stale_invalidation_preserves_selected_source_controls(self) -> None:
        import app.streamlit_app as prototype

        preparation = self._checked_source()
        state = {}
        initialize(state)
        set_dataset_source_preparation(state, preparation)
        source_locator = ("explicit_local", str(preparation.source.local_runtime_path))
        state.update(
            prototype_source_control_locator=source_locator,
            prototype_source_kind="explicit_local",
            prototype_selected_local_file_path=str(preparation.source.local_runtime_path),
            selected_feature_ids=("score",),
            selected_model_id="model",
            experiment_inputs={"folds": 3},
            experiment_plan=object(),
            loaded_artifact=object(),
            comparison_result=object(),
        )

        prototype._invalidate_stale_preparation(state)

        self.assertIsNone(state["dataset_source_preparation"])
        self.assertIsNone(state["dataset_context"])
        self.assertIsNone(state["dataset_preparation_snapshot"])
        self.assertIsNone(state["dataset_preparation_proposal"])
        self.assertEqual(state["selected_feature_ids"], ())
        self.assertIsNone(state["selected_model_id"])
        self.assertIsNone(state["experiment_plan"])
        self.assertIsNone(state["loaded_artifact"])
        self.assertIsNone(state["comparison_result"])
        self.assertEqual(state["prototype_source_control_locator"], source_locator)
        self.assertEqual(state["prototype_selected_local_file_path"], str(preparation.source.local_runtime_path))

    def test_historical_prepared_change_file_clears_active_preparation_and_returns_to_file_step(self) -> None:
        import app.streamlit_app as prototype

        class Streamlit:
            def __init__(self, state):
                self.session_state = state
                self.reruns = 0

            def button(self, label, **_kwargs):
                return label == "Изменить файл"

            def rerun(self):
                self.reruns += 1

        historical_context = SimpleNamespace(context_id="historical_data_final_v1")
        historical = SimpleNamespace(
            source=SimpleNamespace(source_kind="repository_local", local_runtime_path="Data_final.xlsb"),
            preparation_status="historical_context_prepared",
            context=historical_context,
            is_prepared=True,
        )
        state = {}
        initialize(state)
        state.update(
            dataset_source_preparation=historical,
            dataset_context=historical_context,
            dataset_preparation_step=5,
            prototype_source_control_locator=("accepted_historical", ""),
            prototype_source_kind="accepted_historical",
            prototype_selected_local_file_path="Data_final.xlsb",
            prototype_manual_local_file_path="Data_final.xlsb",
        )
        streamlit = Streamlit(state)

        with patch.object(prototype, "st", streamlit):
            prototype._render_change_file_action()

        self.assertIsNone(state["dataset_source_preparation"])
        self.assertIsNone(state["dataset_context"])
        self.assertEqual(state["dataset_preparation_step"], 0)
        self.assertNotIn("prototype_source_control_locator", state)
        self.assertNotIn("prototype_selected_local_file_path", state)
        self.assertEqual(streamlit.reruns, 1)

    def test_generic_renderer_uses_context_contract_for_arbitrary_and_historical_contexts(self) -> None:
        import app.streamlit_app as prototype

        class Expander:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Column:
            def __init__(self, messages):
                self.messages = messages

            def metric(self, label, value):
                self.messages.append(("metric", label, value))

        class Streamlit:
            def __init__(self):
                self.messages = []

            def __getattr__(self, name):
                if name == "columns":
                    return lambda count: [Column(self.messages) for _ in range(count)]
                if name == "expander":
                    return lambda *_args, **_kwargs: Expander()
                return lambda value=None, *args, **kwargs: self.messages.append((name, value))

        def context(name, target, identifier, locked):
            return SimpleNamespace(
                display_name="fallback",
                loaded_dataset=SimpleNamespace(contract=SimpleNamespace(
                    dataset_name=name, row_count=10, target_column=target,
                    identifier_column=identifier, feature_registry_id="registry",
                    dataset_version="1", source_type="csv", dataset_fingerprint="fingerprint",
                    dataset_id="dataset", validation_status="validated", final_test_locked=locked,
                )),
                population=SimpleNamespace(row_positions=tuple(range(8 if locked else 10)), population_id="population", partition_role="working"),
            )

        streamlit = Streamlit()
        arbitrary = SimpleNamespace(context=context("custom", "outcome", "record_id", False), preparation_status="confirmed_context_prepared")
        historical = SimpleNamespace(context=context("baseline", "target", "entity", True), preparation_status="historical_context_prepared")
        with patch.object(prototype, "st", streamlit):
            prototype._render_prepared_source(arbitrary)
            prototype._render_prepared_source(historical)

        self.assertIn(("subheader", "custom"), streamlit.messages)
        self.assertIn(("subheader", "baseline"), streamlit.messages)
        self.assertIn(("write", "**Целевая колонка:** outcome"), streamlit.messages)
        self.assertIn(("write", "**Колонка-идентификатор:** record_id"), streamlit.messages)
        self.assertIn(("info", "Для текущего протокола оценки используется вся подтверждённая популяция. Защищённая финальная тестовая выборка не задана."), streamlit.messages)
        self.assertIn(("info", "Для набора данных задана защищённая финальная тестовая выборка."), streamlit.messages)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
