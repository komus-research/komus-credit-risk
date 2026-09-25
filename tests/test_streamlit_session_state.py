"""Tests for wizard state invalidation and snapshot-only execution mapping."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.session_state import (
    apply_feature_widget_selection,
    apply_group_widget_selection,
    initialize,
    navigate_to_step,
    return_to_experiment,
    run_request_from_snapshot,
    save_artifact,
    set_dataset_context,
    set_dataset_source_preparation,
    set_experiment_inputs,
    set_group_selection,
    set_loaded_model_version,
    set_inference_source_path,
    set_prediction_batch,
    set_selected_prediction_row_id,
    set_local_explanation_evidence,
    set_result_interpretation_error,
    set_result_interpretation_success,
    set_result_interpreter_request,
    set_selected_feature_ids,
    set_selected_model_id,
    synchronize_feature_widgets,
    toggle_feature,
)
from app.streamlit_app import _available_wizard_steps, _restore_source_controls, _source_control_locator, _synchronize_source_selection
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

    def test_unprepared_source_clears_context_and_blocks_downstream_state(self) -> None:
        prepared_context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        set_dataset_context(self.state, prepared_context)
        self.state.update(
            current_step=3,
            selected_feature_ids=("Q_A1_norm",),
            selected_model_id="model",
            experiment_inputs={"seed": 42},
        )
        preparation = SimpleNamespace(
            source=SimpleNamespace(local_runtime_path="arbitrary.csv"),
            preparation_status="context_not_prepared",
            context=None,
        )

        set_dataset_source_preparation(self.state, preparation)

        self.assertIsNone(self.state["dataset_context"])
        self.assertIs(self.state["dataset_source_preparation"], preparation)
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["selected_feature_ids"], ())
        self.assertIsNone(self.state["selected_model_id"])

    def test_wizard_navigation_only_changes_the_current_step(self) -> None:
        context = SimpleNamespace(context_id="accepted")
        artifact = SimpleNamespace(artifact_id="saved-artifact")
        self.state.update(
            current_step=4,
            dataset_context=context,
            dataset_source_preparation=SimpleNamespace(context=context),
            selected_feature_ids=("Q_A1_norm",),
            selected_model_id="model",
            experiment_inputs={"seed": 42},
            experiment_plan=object(),
            loaded_artifact=artifact,
            comparison_result=object(),
            highest_reached_step=4,
        )

        for target_step in (3, 0, 1):
            navigate_to_step(self.state, target_step)

            self.assertEqual(self.state["current_step"], target_step)
            self.assertIs(self.state["dataset_context"], context)
            self.assertEqual(self.state["selected_feature_ids"], ("Q_A1_norm",))
            self.assertEqual(self.state["selected_model_id"], "model")
            self.assertEqual(self.state["experiment_inputs"], {"seed": 42})
            self.assertIs(self.state["loaded_artifact"], artifact)
            self.assertEqual(self.state["highest_reached_step"], 4)

    def test_wizard_navigation_rejects_an_unknown_step(self) -> None:
        with self.assertRaises(ValueError):
            navigate_to_step(self.state, 5)

    def test_step_navigator_keeps_reached_destinations_available(self) -> None:
        self.assertEqual(_available_wizard_steps(self.state), (True, False, False, False, False))

        self.state["dataset_context"] = object()
        navigate_to_step(self.state, 1)
        self.assertEqual(_available_wizard_steps(self.state), (True, True, False, False, False))

        self.state["selected_feature_ids"] = ("Q_A1_norm",)
        navigate_to_step(self.state, 2)
        self.assertEqual(_available_wizard_steps(self.state), (True, True, True, False, False))

        self.state["selected_model_id"] = "model"
        navigate_to_step(self.state, 3)
        self.assertEqual(_available_wizard_steps(self.state), (True, True, True, True, False))

        self.state["loaded_artifact"] = object()
        navigate_to_step(self.state, 4)
        self.assertEqual(_available_wizard_steps(self.state), (True, True, True, True, True))

    def test_return_to_data_restores_prepared_source_controls_without_stale_reset(self) -> None:
        context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(
            source=SimpleNamespace(source_kind="repository_local", local_runtime_path="Data_final.xlsb"),
            preparation_status="historical_context_prepared",
            context=context,
            is_prepared=True,
        )
        locator = _source_control_locator("accepted_historical", "")
        self.state.update(
            current_step=3,
            dataset_context=context,
            dataset_source_preparation=preparation,
            prototype_source_control_locator=locator,
        )

        navigate_to_step(self.state, 0)
        self.state.pop("prototype_source_kind", None)  # Simulate Streamlit widget cleanup between steps.
        _restore_source_controls(self.state)
        _synchronize_source_selection(
            self.state,
            _source_control_locator(self.state["prototype_source_kind"], ""),
        )

        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["prototype_source_kind"], "accepted_historical")
        self.assertIs(self.state["dataset_source_preparation"], preparation)
        self.assertIs(self.state["dataset_context"], context)
        self.assertTrue(self.state["dataset_source_preparation"].is_prepared)

    def test_return_to_data_restores_exact_local_data_final_instead_of_defaulting_source_kind(self) -> None:
        context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(
            source=SimpleNamespace(source_kind="explicit_local", local_runtime_path=r"C:\data\Data_final.xlsb"),
            preparation_status="historical_context_prepared",
            context=context,
            is_prepared=True,
        )
        locator = _source_control_locator("explicit_local", r"C:\data\Data_final.xlsb")
        self.state.update(
            dataset_context=context,
            dataset_source_preparation=preparation,
            prototype_source_control_locator=locator,
        )

        navigate_to_step(self.state, 0)
        self.state.pop("prototype_source_kind", None)
        self.state["prototype_selected_local_file_path"] = r"C:\data\stale-picker-value.xlsb"
        _restore_source_controls(self.state)
        restored_locator = _source_control_locator(
            self.state["prototype_source_kind"],
            self.state["prototype_selected_local_file_path"],
        )
        _synchronize_source_selection(self.state, restored_locator)

        self.assertEqual(restored_locator, locator)
        self.assertEqual(self.state["prototype_selected_local_file_path"], locator[1])
        self.assertIs(self.state["dataset_source_preparation"], preparation)
        self.assertIs(self.state["dataset_context"], context)

    def test_source_change_after_return_to_data_still_runs_stale_reset(self) -> None:
        context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(source=SimpleNamespace(local_runtime_path="Data_final.xlsb"), context=context)
        self.state.update(
            dataset_context=context,
            dataset_source_preparation=preparation,
            prototype_source_control_locator=_source_control_locator("accepted_historical", ""),
        )

        navigate_to_step(self.state, 0)
        _restore_source_controls(self.state)
        _synchronize_source_selection(
            self.state,
            _source_control_locator("explicit_local", "other-source.xlsb"),
        )

        self.assertIsNone(self.state["dataset_source_preparation"])
        self.assertIsNone(self.state["dataset_context"])

    def test_same_prepared_identity_from_another_path_preserves_downstream_state(self) -> None:
        contract = SimpleNamespace(dataset_id="historical", dataset_fingerprint="sha256:accepted")
        population = SimpleNamespace(population_fingerprint="working-population")
        current_context = SimpleNamespace(
            context_id="historical_data_final_v1",
            loaded_dataset=SimpleNamespace(contract=contract),
            population=population,
        )
        next_context = SimpleNamespace(
            context_id="historical_data_final_v1",
            loaded_dataset=SimpleNamespace(contract=contract),
            population=population,
        )
        current = SimpleNamespace(
            source=SimpleNamespace(local_runtime_path="C:/original/Data_final.xlsb"),
            preparation_status="historical_context_prepared",
            context=current_context,
        )
        accepted_copy = SimpleNamespace(
            source=SimpleNamespace(local_runtime_path="D:/copy/Data_final.xlsb"),
            preparation_status="historical_context_prepared",
            context=next_context,
        )
        artifact = object()
        self.state.update(
            dataset_source_preparation=current,
            dataset_context=current_context,
            selected_feature_ids=("Q_A1_norm",),
            selected_model_id="model",
            experiment_inputs={"seed": 42},
            loaded_artifact=artifact,
            highest_reached_step=4,
        )

        set_dataset_source_preparation(self.state, accepted_copy)

        self.assertIs(self.state["dataset_source_preparation"], accepted_copy)
        self.assertIs(self.state["dataset_context"], current_context)
        self.assertEqual(self.state["selected_feature_ids"], ("Q_A1_norm",))
        self.assertEqual(self.state["selected_model_id"], "model")
        self.assertIs(self.state["loaded_artifact"], artifact)
        self.assertEqual(self.state["highest_reached_step"], 4)

    def test_switching_source_kind_immediately_clears_prepared_context(self) -> None:
        historical_locator = _source_control_locator("accepted_historical", "")
        prepared_context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(source=SimpleNamespace(local_runtime_path="Data_final.xlsb"), preparation_status="historical_context_prepared", context=prepared_context)
        set_dataset_source_preparation(self.state, preparation)
        self.state["prototype_source_control_locator"] = historical_locator
        self.state.update(current_step=3, selected_feature_ids=("Q_A1_norm",), selected_model_id="model", experiment_plan=object())

        _synchronize_source_selection(self.state, _source_control_locator("explicit_local", "other.xlsb"))

        self.assertIsNone(self.state["dataset_source_preparation"])
        self.assertIsNone(self.state["dataset_context"])
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["selected_feature_ids"], ())
        self.assertIsNone(self.state["selected_model_id"])
        self.assertIsNone(self.state["experiment_plan"])

    def test_failed_resolution_after_source_switch_does_not_restore_historical_context(self) -> None:
        prepared_context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(source=SimpleNamespace(local_runtime_path="Data_final.xlsb"), preparation_status="historical_context_prepared", context=prepared_context)
        set_dataset_source_preparation(self.state, preparation)
        self.state["prototype_source_control_locator"] = _source_control_locator("accepted_historical", "")
        self.state.update(current_step=2, selected_feature_ids=("Q_A1_norm",), selected_model_id="model")

        _synchronize_source_selection(self.state, _source_control_locator("explicit_local", "missing-file.xlsb"))
        # A source-resolution failure does not call set_dataset_source_preparation again.

        self.assertIsNone(self.state["dataset_source_preparation"])
        self.assertIsNone(self.state["dataset_context"])
        self.assertEqual(self.state["current_step"], 0)
        self.assertEqual(self.state["selected_feature_ids"], ())
        self.assertIsNone(self.state["selected_model_id"])

    def test_unchanged_source_controls_do_not_reset_prepared_context_on_rerun(self) -> None:
        locator = _source_control_locator("accepted_historical", "")
        prepared_context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(source=SimpleNamespace(local_runtime_path="Data_final.xlsb"), preparation_status="historical_context_prepared", context=prepared_context)
        set_dataset_source_preparation(self.state, preparation)
        self.state["prototype_source_control_locator"] = locator
        self.state.update(current_step=2, selected_feature_ids=("Q_A1_norm",), selected_model_id="model")

        _synchronize_source_selection(self.state, locator)

        self.assertIs(self.state["dataset_context"], prepared_context)
        self.assertIs(self.state["dataset_source_preparation"], preparation)
        self.assertEqual(self.state["current_step"], 2)
        self.assertEqual(self.state["selected_feature_ids"], ("Q_A1_norm",))
        self.assertEqual(self.state["selected_model_id"], "model")

    def test_changing_explicit_path_invalidates_previous_preparation_before_validation(self) -> None:
        first_locator = _source_control_locator("explicit_local", "source-a.xlsb")
        prepared_context = SimpleNamespace(context_id="accepted", loaded_dataset=SimpleNamespace(contract="accepted"))
        preparation = SimpleNamespace(source=SimpleNamespace(local_runtime_path="source-a.xlsb"), preparation_status="historical_context_prepared", context=prepared_context)
        set_dataset_source_preparation(self.state, preparation)
        self.state["prototype_source_control_locator"] = first_locator
        self.state.update(current_step=1, selected_feature_ids=("Q_A1_norm",))

        _synchronize_source_selection(self.state, _source_control_locator("explicit_local", "source-b.xlsb"))

        self.assertIsNone(self.state["dataset_source_preparation"])
        self.assertIsNone(self.state["dataset_context"])
        self.assertEqual(self.state["current_step"], 0)

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

    def test_global_widget_selects_all_selectable_features_only(self) -> None:
        selectable_ids = ("Q_A1_norm", "Q_B3_norm", "A1_norm")
        restricted_or_service_ids = ("INN", "DefMark", "Q_B1_norm", "Q_B2_norm")
        keys = {feature_id: f"widget_{feature_id}" for feature_id in selectable_ids}
        global_key = "widget_all_allowed"
        synchronize_feature_widgets(self.state, selectable_ids, group_widget_key=global_key, feature_widget_keys=keys)
        self.state[global_key] = True

        apply_group_widget_selection(self.state, selectable_ids, group_widget_key=global_key, feature_widget_keys=keys)

        self.assertEqual(self.state["selected_feature_ids"], selectable_ids)
        self.assertTrue(self.state[global_key])
        self.assertTrue(all(feature_id not in self.state["selected_feature_ids"] for feature_id in restricted_or_service_ids))

    def test_global_widget_deselects_all_selectable_features(self) -> None:
        selectable_ids = ("Q_A1_norm", "Q_B3_norm", "A1_norm")
        keys = {feature_id: f"widget_{feature_id}" for feature_id in selectable_ids}
        global_key = "widget_all_allowed"
        set_selected_feature_ids(self.state, selectable_ids)
        synchronize_feature_widgets(self.state, selectable_ids, group_widget_key=global_key, feature_widget_keys=keys)
        self.assertTrue(self.state[global_key])
        self.state[global_key] = False

        apply_group_widget_selection(self.state, selectable_ids, group_widget_key=global_key, feature_widget_keys=keys)

        self.assertEqual(self.state["selected_feature_ids"], ())
        self.assertFalse(self.state[global_key])

    def test_family_group_widget_selects_only_its_own_features(self) -> None:
        family_ids = ("Q_A1_norm", "Q_A2_norm")
        keys = {feature_id: f"widget_{feature_id}" for feature_id in family_ids}
        group_key = "widget_family_q_a"
        set_selected_feature_ids(self.state, ("Q_B3_norm",))
        synchronize_feature_widgets(self.state, family_ids, group_widget_key=group_key, feature_widget_keys=keys)
        self.state[group_key] = True

        apply_group_widget_selection(self.state, family_ids, group_widget_key=group_key, feature_widget_keys=keys)

        self.assertEqual(self.state["selected_feature_ids"], ("Q_B3_norm", "Q_A1_norm", "Q_A2_norm"))

    def test_family_individual_deselection_clears_full_family_state(self) -> None:
        family_ids = ("A1_norm", "A2_norm")
        keys = {feature_id: f"widget_{feature_id}" for feature_id in family_ids}
        group_key = "widget_family_a"
        set_selected_feature_ids(self.state, family_ids)
        synchronize_feature_widgets(self.state, family_ids, group_widget_key=group_key, feature_widget_keys=keys)
        self.state[keys["A1_norm"]] = False

        apply_feature_widget_selection(
            self.state,
            "A1_norm",
            family_ids,
            group_widget_key=group_key,
            feature_widget_keys=keys,
        )

        self.assertEqual(self.state["selected_feature_ids"], ("A2_norm",))
        self.assertFalse(self.state[group_key])

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

    def test_successful_artifact_is_available_as_the_session_comparison_reference(self) -> None:
        artifact = SimpleNamespace(artifact_id="saved-artifact")

        save_artifact(self.state, artifact, comparison=None)

        self.assertEqual(self.state["last_successful_artifact_id"], "saved-artifact")
        self.assertEqual(self.state["current_step"], 4)

    def test_new_model_version_clears_inference_row_and_evidence(self) -> None:
        self.state.update(inference_snapshot=object(), prediction_batch=object(), selected_prediction_row_id="row-1", local_explanation_evidence=object())

        set_loaded_model_version(self.state, SimpleNamespace(summary=SimpleNamespace(model_version_id="model-1")))

        self.assertEqual(self.state["active_model_version_id"], "model-1")
        self.assertIsNone(self.state["inference_snapshot"])
        self.assertIsNone(self.state["prediction_batch"])
        self.assertIsNone(self.state["selected_prediction_row_id"])
        self.assertIsNone(self.state["local_explanation_evidence"])

    def test_result_interpretation_is_invalidated_with_each_downstream_input_change(self) -> None:
        self.state.update(
            result_interpreter_request=object(), result_interpreter_response=object(),
            result_interpreter_dispatch_receipt=object(), result_interpreter_error_code="failed",
            local_explanation_evidence=object(), selected_prediction_row_id="row-1",
        )
        set_selected_prediction_row_id(self.state, "row-2")
        for key in (
            "result_interpreter_request", "result_interpreter_response",
            "result_interpreter_dispatch_receipt", "result_interpreter_error_code",
        ):
            self.assertIsNone(self.state[key])

    def test_interpretation_error_preserves_request_and_evidence_for_retry(self) -> None:
        evidence, request = object(), object()
        self.state["local_explanation_evidence"] = evidence
        set_result_interpreter_request(self.state, request)
        set_result_interpretation_error(self.state, "RESULT_INTERPRETER_CALL_FAILED")

        self.assertIs(self.state["local_explanation_evidence"], evidence)
        self.assertIs(self.state["result_interpreter_request"], request)
        self.assertEqual(self.state["result_interpreter_error_code"], "RESULT_INTERPRETER_CALL_FAILED")

    def test_interpretation_success_stores_response_and_receipt(self) -> None:
        response, receipt = SimpleNamespace(text="safe explanation", interpreter_model="configured-model"), object()
        set_result_interpretation_success(self.state, SimpleNamespace(response=response, dispatch_receipt=receipt))

        self.assertEqual(self.state["result_interpreter_response"].text, "safe explanation")
        self.assertFalse(hasattr(self.state["result_interpreter_response"], "interpreter_model"))
        self.assertIs(self.state["result_interpreter_dispatch_receipt"], receipt)
        self.assertIsNone(self.state["result_interpreter_error_code"])

    def test_changed_inference_source_clears_stale_batch_but_preserves_model(self) -> None:
        model = SimpleNamespace(summary=SimpleNamespace(model_version_id="model-1"))
        snapshot = SimpleNamespace(source_path="A.csv")
        batch = object()
        evidence = object()
        self.state.update(
            active_model_version_id="model-1",
            loaded_model_version=model,
            inference_source_path="A.csv",
            inference_snapshot=snapshot,
            prediction_batch=batch,
            selected_prediction_row_id="row-1",
            local_explanation_evidence=evidence,
        )

        set_inference_source_path(self.state, "B.csv")

        self.assertEqual(self.state["inference_source_path"], "B.csv")
        self.assertIs(self.state["loaded_model_version"], model)
        self.assertEqual(self.state["active_model_version_id"], "model-1")
        self.assertIsNone(self.state["inference_snapshot"])
        self.assertIsNone(self.state["prediction_batch"])
        self.assertIsNone(self.state["selected_prediction_row_id"])
        self.assertIsNone(self.state["local_explanation_evidence"])

    def test_same_inference_source_preserves_current_batch(self) -> None:
        snapshot = object()
        batch = object()
        evidence = object()
        self.state.update(
            inference_source_path="A.csv",
            inference_snapshot=snapshot,
            prediction_batch=batch,
            selected_prediction_row_id="row-1",
            local_explanation_evidence=evidence,
        )

        set_inference_source_path(self.state, " A.csv ")

        self.assertIs(self.state["inference_snapshot"], snapshot)
        self.assertIs(self.state["prediction_batch"], batch)
        self.assertEqual(self.state["selected_prediction_row_id"], "row-1")
        self.assertIs(self.state["local_explanation_evidence"], evidence)

    def test_new_prediction_batch_clears_row_and_evidence(self) -> None:
        self.state.update(selected_prediction_row_id="row-1", local_explanation_evidence=object())

        set_prediction_batch(self.state, object(), object())

        self.assertIsNone(self.state["selected_prediction_row_id"])
        self.assertIsNone(self.state["local_explanation_evidence"])

    def test_changed_row_clears_evidence_but_same_row_preserves_it(self) -> None:
        evidence = object()
        self.state.update(selected_prediction_row_id="row-1", local_explanation_evidence=evidence)

        set_selected_prediction_row_id(self.state, "row-1")
        self.assertIs(self.state["local_explanation_evidence"], evidence)
        set_selected_prediction_row_id(self.state, "row-2")

        self.assertIsNone(self.state["local_explanation_evidence"])

    def test_new_experiment_artifact_clears_model_version_and_downstream_state(self) -> None:
        self.state.update(
            active_model_version_id="model-1", loaded_model_version=object(), inference_snapshot=object(),
            prediction_batch=object(), selected_prediction_row_id="row-1", local_explanation_evidence=object(),
        )

        save_artifact(self.state, SimpleNamespace(artifact_id="new-experiment"), comparison=None)

        self.assertIsNone(self.state["active_model_version_id"])
        self.assertIsNone(self.state["loaded_model_version"])
        self.assertIsNone(self.state["prediction_batch"])
        self.assertIsNone(self.state["selected_prediction_row_id"])
        self.assertIsNone(self.state["local_explanation_evidence"])

    def test_return_to_experiment_keeps_the_successful_reference_and_clears_current_result(self) -> None:
        artifact = SimpleNamespace(artifact_id="saved-artifact")
        self.state.update(
            planning_request_snapshot=object(),
            experiment_plan=object(),
            selected_feature_ids=("score",),
            selected_model_id="model",
        )
        save_artifact(self.state, artifact, comparison=object())

        return_to_experiment(self.state)

        self.assertEqual(self.state["current_step"], 1)
        self.assertIsNone(self.state["planning_request_snapshot"])
        self.assertIsNone(self.state["experiment_plan"])
        self.assertIsNone(self.state["loaded_artifact"])
        self.assertIsNone(self.state["comparison_result"])
        self.assertEqual(self.state["last_successful_artifact_id"], "saved-artifact")
        self.assertEqual(self.state["selected_feature_ids"], ("score",))
        self.assertEqual(self.state["selected_model_id"], "model")


if __name__ == "__main__":
    unittest.main()
