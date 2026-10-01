"""Focused Result V2 overview boundary tests."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.session_state import initialize
import app.streamlit_app as prototype


class _SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class _Column:
    def __init__(self, ui) -> None:
        self.ui = ui

    def metric(self, *args, **kwargs) -> None:
        self.ui.metrics.append(args)

    def button(self, *args, **kwargs) -> bool:
        self.ui.buttons.append((args, kwargs))
        return False if kwargs.get("disabled") else self.ui.button_responses.get(args[0], False)


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class _Streamlit:
    def __init__(self) -> None:
        self.session_state = _SessionState()
        initialize(self.session_state)
        self.metrics = []
        self.buttons = []
        self.errors = []
        self.messages = []
        self.button_responses = {}
        self.rerun_calls = 0
        self.tables = []
        self.markdowns = []
        self.json_values = []
        self.dataframe_selection = {"selection": {"rows": []}}
        self.writes = []

    def header(self, *args, **kwargs) -> None:
        return None

    def slider(self, *args, **kwargs) -> float:
        self.slider_args = (args, kwargs)
        if "value" in kwargs and isinstance(kwargs["value"], tuple):
            return getattr(self, "slider_value", kwargs["value"])
        return self.slider_value if hasattr(self, "slider_value") else 0.62

    def text_input(self, label, *, key, **kwargs):
        return self.session_state[key]

    def selectbox(self, label, *, options, key, **kwargs):
        return self.session_state[key]

    def multiselect(self, label, *, options, key, **kwargs):
        return self.session_state[key]

    def rerun(self) -> None:
        self.rerun_calls += 1

    def button(self, label, **kwargs) -> bool:
        self.buttons.append(((label,), kwargs))
        return self.button_responses.get(label, False)

    def success(self, *args, **kwargs) -> None:
        return None

    def info(self, *args, **kwargs) -> None:
        self.messages.extend(args)

    def error(self, message, *args, **kwargs) -> None:
        self.errors.append(message)

    def caption(self, *args, **kwargs) -> None:
        self.messages.extend(args)

    def columns(self, count):
        return [_Column(self) for _ in range(count)]

    def dataframe(self, *args, **kwargs):
        self.tables.append((args, kwargs))
        return self.dataframe_selection

    def markdown(self, *args, **kwargs) -> None:
        self.markdowns.append((args, kwargs))

    def radio(self, label, *, options, key, **kwargs):
        return self.session_state.get(key, options[0])

    def spinner(self, *args, **kwargs):
        return _Expander()

    def write(self, *args, **kwargs) -> None:
        self.writes.extend(args)

    def subheader(self, *args, **kwargs) -> None:
        self.messages.extend(args)

    def expander(self, *args, **kwargs):
        return _Expander()

    def json(self, *args, **kwargs) -> None:
        self.json_values.append(args[0] if args else None)


class _Artifact:
    artifact_id = "artifact-1"

    @property
    def run_output(self):  # pragma: no cover - accessed only by a regression.
        raise AssertionError("Overview must not read artifact run output")


class ResultV2UiTests(unittest.TestCase):
    @staticmethod
    def _interpreter_evidence(evidence_hash="evidence-hash"):
        return SimpleNamespace(evidence_hash=evidence_hash)

    @staticmethod
    def _global_evidence(artifact_id="artifact-1"):
        return SimpleNamespace(
            artifact_id=artifact_id,
            model_id="model-from-dto",
            model_version="v-dto",
            row_count=19,
            feature_count=2,
            output_space="dto-output-space",
            provider_id="dto-provider",
            provider_version="provider-v",
            explanation_method_id="dto-method",
            explanation_method_version="method-v",
            background_policy_id="dto-background",
            feature_binding_hash="dto-binding",
            fold_model_binding_ids=("fold-1", "fold-2"),
            features=(
                SimpleNamespace(feature_id="b", column_name="exact_second", mean_abs_shap=0.0025, rank=2),
                SimpleNamespace(feature_id="a", column_name="exact_first", mean_abs_shap=0.037, rank=1),
            ),
            evidence_hash="dto-evidence-hash",
        )

    def test_overview_global_oof_action_is_enabled_and_routes_with_rerun(self) -> None:
        ui = _Streamlit()
        summary = SimpleNamespace(
            model_id="model", model_version="v1", object_count=19, feature_count=2, folds=3,
            evaluation_level="ROW", runtime_seconds=None, gini=0.2, roc_auc=0.7, pr_auc=0.4,
            fold_metrics=(), limitations=(), artifact_id="artifact-1", result_id="result-1",
        )
        result_service = SimpleNamespace(
            summary=Mock(return_value=summary),
            threshold=Mock(return_value=SimpleNamespace(
                precision=0.5, recall=0.4, f1=0.44, tp=2, tn=3, fp=2, fn=3,
                above_threshold_count=4, above_threshold_share=0.2,
            )),
        )
        ui.button_responses["Подробнее о влиянии признаков"] = True

        with patch.object(prototype, "st", ui), patch.object(prototype, "_render_local_model_use_flow"):
            prototype._render_result_overview(SimpleNamespace(oof_result_service=result_service), _Artifact())

        global_action = next(kwargs for args, kwargs in ui.buttons if args[0] == "Подробнее о влиянии признаков")
        self.assertFalse(global_action.get("disabled", False))
        self.assertEqual(ui.session_state.result_v2_view, "GLOBAL_OOF")
        self.assertEqual(ui.rerun_calls, 1)

    def test_global_oof_router_loads_exact_artifact_once_and_preserves_cached_evidence(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "GLOBAL_OOF"
        ui.session_state.result_v2_threshold = 0.17
        evidence = self._global_evidence()
        service = SimpleNamespace(global_oof=Mock(return_value=evidence))
        runtime = SimpleNamespace(oof_explanation_service=service)

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)
            ui.session_state.result_v2_threshold = 0.91
            prototype._render_result_step(runtime)

        service.global_oof.assert_called_once_with("artifact-1")
        self.assertIs(ui.session_state.result_v2_global_oof_explanation, evidence)
        self.assertEqual(ui.session_state.result_v2_global_oof_artifact_id, "artifact-1")
        self.assertEqual(ui.session_state.result_v2_threshold, 0.91)

    def test_global_oof_renders_trusted_rank_exact_values_and_only_relative_magnitudes(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "GLOBAL_OOF"
        service = SimpleNamespace(global_oof=Mock(return_value=self._global_evidence()))

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_explanation_service=service))

        rendered = "".join(args[0] for args, _ in ui.markdowns)
        self.assertLess(rendered.index("exact_first"), rendered.index("exact_second"))
        self.assertIn("0.037", rendered)
        self.assertIn("0.0025", rendered)
        self.assertIn("model-from-dto", " ".join(map(str, ui.writes)))
        displayed_facts = " ".join(map(str, ui.messages)) + " " + " ".join(map(str, ui.writes))
        self.assertIn("v-dto", displayed_facts)
        self.assertIn("19", displayed_facts)
        self.assertIn("2", displayed_facts)
        self.assertIn("dto-output-space", displayed_facts)
        self.assertNotIn("increases", rendered.lower())
        self.assertNotIn("decreases", rendered.lower())
        self.assertNotIn("↑", rendered)
        self.assertNotIn("↓", rendered)
        self.assertEqual(service.global_oof.call_args.args, ("artifact-1",))

    def test_global_oof_artifact_change_discards_stale_evidence_and_error(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = SimpleNamespace(artifact_id="artifact-2")
        ui.session_state.result_v2_view = "GLOBAL_OOF"
        ui.session_state.result_v2_global_oof_explanation = self._global_evidence("artifact-1")
        ui.session_state.result_v2_global_oof_artifact_id = "artifact-1"
        ui.session_state.result_v2_global_oof_error_code = "stale-error"
        fresh = self._global_evidence("artifact-2")
        service = SimpleNamespace(global_oof=Mock(return_value=fresh))

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_explanation_service=service))

        service.global_oof.assert_called_once_with("artifact-2")
        self.assertIs(ui.session_state.result_v2_global_oof_explanation, fresh)
        self.assertIsNone(ui.session_state.result_v2_global_oof_error_code)

    def test_global_oof_failure_hides_exception_and_retry_repeats_only_oof_call(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "GLOBAL_OOF"
        service = SimpleNamespace(
            global_oof=Mock(side_effect=[RuntimeError("private raw exception"), self._global_evidence()])
        )
        runtime = SimpleNamespace(oof_explanation_service=service)

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)
            self.assertEqual(ui.session_state.result_v2_global_oof_error_code, "GLOBAL_OOF_EXPLANATION_FAILED")
            ui.button_responses["Повторить расчёт"] = True
            prototype._render_result_step(runtime)
            ui.button_responses["Повторить расчёт"] = False
            prototype._render_result_step(runtime)

        self.assertEqual(service.global_oof.call_args_list, [unittest.mock.call("artifact-1")] * 2)
        self.assertTrue(any("Назад к результату" in args[0] for args, _ in ui.buttons))
        self.assertFalse(any("private raw exception" in str(message) for message in ui.errors + ui.messages))
        self.assertIsNotNone(ui.session_state.result_v2_global_oof_explanation)
        self.assertEqual(ui.session_state.result_v2_view, "GLOBAL_OOF")

    def test_global_oof_screen_does_not_call_interpreter(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "GLOBAL_OOF"
        integration = SimpleNamespace(interpret=Mock(), prepare_interpretation=Mock())
        service = SimpleNamespace(global_oof=Mock(return_value=self._global_evidence()))

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(
                oof_explanation_service=service, integration_workflow_service=integration,
            ))

        integration.interpret.assert_not_called()
        integration.prepare_interpretation.assert_not_called()

    def test_result_v2_interpreter_is_explicit_and_uses_exact_oof_boundary(self) -> None:
        ui = _Streamlit()
        evidence = self._interpreter_evidence()
        capability = SimpleNamespace(state="AVAILABLE")
        response = SimpleNamespace(
            text="Backend text, unchanged.", interpreter_id="interpreter-1", interpreter_model="model-1"
        )
        receipt = SimpleNamespace(
            policy_id="REDACTED_V1", policy_version=1, prompt_id="result-v2", prompt_version="3"
        )
        outcome = SimpleNamespace(response=response, dispatch_receipt=receipt)
        workflow = SimpleNamespace(
            capabilities=Mock(return_value={"result_interpretation": capability}),
            prepare_interpretation=Mock(return_value="prepared-request"),
            interpret=Mock(return_value=outcome),
        )
        runtime = SimpleNamespace(integration_workflow_service=workflow)

        with patch.object(prototype, "st", ui):
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)

        workflow.prepare_interpretation.assert_not_called()
        workflow.interpret.assert_not_called()
        self.assertTrue(any(args[0] == "Сформировать объяснение" for args, _ in ui.buttons))

        ui.button_responses["Сформировать объяснение"] = True
        with patch.object(prototype, "st", ui):
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)
            ui.button_responses["Сформировать объяснение"] = False
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)

        workflow.prepare_interpretation.assert_called_once_with(
            evidence=evidence, recipient_role="credit_controller"
        )
        workflow.interpret.assert_called_once_with(request="prepared-request")
        self.assertIs(ui.session_state.result_v2_interpreter_outcome, outcome)
        self.assertIn(("Backend text, unchanged.",), [args for args, _ in ui.markdowns])
        self.assertEqual(
            ui.session_state.result_v2_interpreter_binding,
            ("artifact", "object", "evidence-hash", "credit_controller"),
        )

    def test_result_v2_interpreter_unavailable_capability_disables_action(self) -> None:
        ui = _Streamlit()
        evidence = self._interpreter_evidence()
        workflow = SimpleNamespace(
            capabilities=Mock(return_value={"result_interpretation": SimpleNamespace(state="MISCONFIGURED")}),
            prepare_interpretation=Mock(),
            interpret=Mock(),
        )

        with patch.object(prototype, "st", ui):
            prototype._render_result_v2_interpreter(
                SimpleNamespace(integration_workflow_service=workflow), "artifact", "object", evidence
            )

        workflow.prepare_interpretation.assert_not_called()
        workflow.interpret.assert_not_called()
        self.assertTrue(any(kwargs.get("disabled") for _, kwargs in ui.buttons))
        self.assertTrue(any("не настроено" in str(message) for message in ui.messages))

    def test_result_v2_retry_reuses_prepared_request_and_regenerate_rebuilds(self) -> None:
        ui = _Streamlit()
        evidence = self._interpreter_evidence()
        capability = SimpleNamespace(state="AVAILABLE")
        first_outcome = SimpleNamespace(response=SimpleNamespace(text="first"), dispatch_receipt=None)
        second_outcome = SimpleNamespace(response=SimpleNamespace(text="second"), dispatch_receipt=None)
        workflow = SimpleNamespace(
            capabilities=Mock(return_value={"result_interpretation": capability}),
            prepare_interpretation=Mock(return_value="same-request"),
            interpret=Mock(side_effect=[RuntimeError("private error"), first_outcome, second_outcome]),
        )
        runtime = SimpleNamespace(integration_workflow_service=workflow)
        with patch.object(prototype, "st", ui):
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)
            ui.button_responses["Сформировать объяснение"] = True
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)
            ui.button_responses["Сформировать объяснение"] = False
            ui.button_responses["Повторить"] = True
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)

        workflow.prepare_interpretation.assert_called_once_with(
            evidence=evidence, recipient_role="credit_controller"
        )
        self.assertEqual(
            workflow.interpret.call_args_list,
            [unittest.mock.call(request="same-request")] * 2,
        )
        self.assertEqual(ui.session_state.result_v2_interpreter_outcome, first_outcome)
        self.assertEqual(ui.session_state.result_v2_interpreter_error_code, None)
        self.assertNotIn("private error", str(ui.errors))

        ui.button_responses["Сформировать заново"] = True
        with patch.object(prototype, "st", ui):
            prototype._render_result_v2_interpreter(runtime, "artifact", "object", evidence)
        self.assertEqual(workflow.prepare_interpretation.call_count, 2)
        self.assertEqual(workflow.interpret.call_count, 3)

    def _summary(self):
        return SimpleNamespace(
            artifact_id="artifact-1",
            result_id="result-1",
            model_id="model-1",
            model_version="1",
            object_count=10,
            feature_count=3,
            folds=5,
            evaluation_level="ORGANIZATION",
            runtime_seconds=1.5,
            gini=0.4,
            roc_auc=0.7,
            pr_auc=0.3,
            fold_metrics=({"fold": 1, "gini": 0.4},),
            limitations=("OOF only",),
        )

    def _threshold(self):
        return SimpleNamespace(
            artifact_id="artifact-1",
            threshold=0.62,
            tp=2,
            tn=5,
            fp=1,
            fn=2,
            precision=2 / 3,
            recall=0.5,
            f1=4 / 7,
            above_threshold_count=3,
            above_threshold_share=0.3,
        )

    def _objects(self, **changes):
        values = {
            "artifact_id": "artifact-1", "threshold": 0.5, "total_count": 100,
            "filtered_count": 100, "offset": 0, "limit": 50, "returned_count": 1,
            "items": (SimpleNamespace(
                object_id="object-1", identifier_display="ORG-1", y_true=1,
                score=0.7, predicted_positive=True, outcome="TP",
            ),),
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_overview_cta_opens_threshold_and_global_oof_action_is_enabled(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.button_responses["\u0418\u0441\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u0442\u044c \u043f\u043e\u0440\u043e\u0433"] = True
        service = SimpleNamespace(summary=Mock(return_value=self._summary()), threshold=Mock(return_value=self._threshold()))
        runtime = SimpleNamespace(oof_result_service=service)

        with (patch.object(prototype, "st", ui), patch.object(prototype, "_render_local_model_use_flow"), patch.object(prototype, "_navigation_button")):
            prototype._render_result_step(runtime)

        self.assertEqual(ui.session_state.result_v2_view, "THRESHOLD")
        self.assertEqual(ui.rerun_calls, 1)
        service.summary.assert_called_once_with("artifact-1")
        service.threshold.assert_called_once_with("artifact-1", 0.5)
        self.assertFalse(hasattr(ui, "slider_args"))
        enabled_labels = [args[0] for args, kwargs in ui.buttons if not kwargs.get("disabled")]
        self.assertIn("\u0418\u0441\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u0442\u044c \u043f\u043e\u0440\u043e\u0433", enabled_labels)
        self.assertIn("\u041f\u043e\u0441\u043c\u043e\u0442\u0440\u0435\u0442\u044c \u043e\u0431\u044a\u0435\u043a\u0442\u044b", enabled_labels)
        self.assertIn("\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0435\u0435 \u043e \u0432\u043b\u0438\u044f\u043d\u0438\u0438 \u043f\u0440\u0438\u0437\u043d\u0430\u043a\u043e\u0432", enabled_labels)

    def test_overview_uses_saved_threshold_and_displays_threshold_dto_without_slider(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_threshold = 0.37
        service = SimpleNamespace(summary=Mock(return_value=self._summary()), threshold=Mock(return_value=self._threshold()))
        with (patch.object(prototype, "st", ui), patch.object(prototype, "_render_local_model_use_flow"), patch.object(prototype, "_navigation_button")):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))

        service.summary.assert_called_once_with("artifact-1")
        service.threshold.assert_called_once_with("artifact-1", 0.37)
        self.assertFalse(hasattr(ui, "slider_args"))
        self.assertIn(("Precision", "0.6667"), ui.metrics)
        self.assertIn(("Recall", "0.5000"), ui.metrics)
        self.assertIn(("F1", "0.5714"), ui.metrics)
        self.assertIn(("TP", "2"), ui.metrics)
        self.assertIn(("TN", "5"), ui.metrics)
        self.assertIn(("FP", "1"), ui.metrics)
        self.assertIn(("FN", "2"), ui.metrics)
        self.assertTrue(any("0.37" in str(message) for message in ui.messages))
        self.assertTrue(any("3 (0.3000)" in str(message) for message in ui.messages))

    def test_threshold_uses_exact_saved_value_and_only_dto_metrics(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "THRESHOLD"
        ui.slider_value = 0.62
        service = SimpleNamespace(summary=Mock(return_value=self._summary()), threshold=Mock(return_value=self._threshold()))
        runtime = SimpleNamespace(oof_result_service=service)

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)

        service.summary.assert_called_once_with("artifact-1")
        service.threshold.assert_called_once_with("artifact-1", 0.62)
        self.assertEqual(ui.session_state.result_v2_threshold, 0.62)
        self.assertEqual(ui.slider_args[1]["min_value"], 0.0)
        self.assertEqual(ui.slider_args[1]["max_value"], 1.0)
        self.assertIn(("Recall", "0.5000"), ui.metrics)
        self.assertIn(("Precision", "0.6667"), ui.metrics)
        self.assertIn(("F1", "0.5714"), ui.metrics)
        self.assertIn(("TP", "2"), ui.metrics)
        self.assertIn(("TN", "5"), ui.metrics)
        self.assertIn(("FP", "1"), ui.metrics)
        self.assertIn(("FN", "2"), ui.metrics)
        self.assertTrue(any("3 (0.3000)" in str(message) for message in ui.messages))
        self.assertIn("\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435 \u043f\u043e\u0440\u043e\u0433\u0430 \u043d\u0435 \u043f\u0435\u0440\u0435\u043e\u0431\u0443\u0447\u0430\u0435\u0442 \u043c\u043e\u0434\u0435\u043b\u044c \u0438 \u043d\u0435 \u043c\u0435\u043d\u044f\u0435\u0442 \u043e\u0446\u0435\u043d\u043a\u0438 \u043e\u0431\u044a\u0435\u043a\u0442\u043e\u0432.", ui.messages)
        self.assertIn(("Gini", "0.4000"), ui.metrics)
        self.assertIn(("ROC-AUC", "0.7000"), ui.metrics)
        self.assertIn(("PR-AUC", "0.3000"), ui.metrics)

    def test_threshold_default_and_back_preserve_selected_threshold(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "THRESHOLD"
        ui.slider_value = 0.37
        ui.button_responses["\u2190 \u041d\u0430\u0437\u0430\u0434 \u043a \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0443"] = True
        service = SimpleNamespace(summary=Mock(return_value=self._summary()), threshold=Mock(return_value=self._threshold()))
        runtime = SimpleNamespace(oof_result_service=service)

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)

        self.assertEqual(ui.session_state.result_v2_view, "OVERVIEW")
        self.assertEqual(ui.session_state.result_v2_threshold, 0.37)
        self.assertEqual(ui.rerun_calls, 1)

        fresh_ui = _Streamlit()
        fresh_ui.session_state.loaded_artifact = _Artifact()
        fresh_ui.session_state.result_v2_view = "THRESHOLD"
        fresh_service = SimpleNamespace(summary=Mock(return_value=self._summary()), threshold=Mock(return_value=self._threshold()))
        with patch.object(prototype, "st", fresh_ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=fresh_service))
        self.assertEqual(fresh_ui.slider_args[1]["value"], 0.5)

    def test_service_failure_is_fail_closed_without_legacy_fallback(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "THRESHOLD"
        service = SimpleNamespace(summary=Mock(side_effect=RuntimeError("bad evidence")), threshold=Mock())
        runtime = SimpleNamespace(oof_result_service=service)

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)

        service.summary.assert_called_once_with("artifact-1")
        service.threshold.assert_not_called()
        self.assertEqual(len(ui.errors), 1)
        self.assertNotIn(("TP", "2"), ui.metrics)

        threshold_ui = _Streamlit()
        threshold_ui.session_state.loaded_artifact = _Artifact()
        threshold_ui.session_state.result_v2_view = "THRESHOLD"
        threshold_service = SimpleNamespace(
            summary=Mock(return_value=self._summary()),
            threshold=Mock(side_effect=RuntimeError("bad threshold evidence")),
        )
        with patch.object(prototype, "st", threshold_ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=threshold_service))
        threshold_service.summary.assert_called_once_with("artifact-1")
        threshold_service.threshold.assert_called_once_with("artifact-1", 0.62)
        self.assertEqual(len(threshold_ui.errors), 1)
        self.assertEqual(threshold_ui.metrics, [])

    def test_objects_query_dto_navigation_and_fail_closed(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECTS"
        ui.session_state.result_v2_threshold = 0.37
        ui.session_state.update(
            result_v2_objects_search="org-1", result_v2_objects_target="POSITIVE",
            result_v2_objects_outcomes=("TP",), result_v2_objects_min_score=0.23,
            result_v2_objects_max_score=0.81, result_v2_objects_sort="SCORE_ASC",
        )
        ui.slider_value = (0.23, 0.81)
        service = SimpleNamespace(objects=Mock(return_value=self._objects()))
        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))
        service.objects.assert_called_once_with(
            "artifact-1", 0.37, 0, 50, search="org-1", target="POSITIVE",
            outcomes=("TP",), min_score=0.23, max_score=0.81, sort="SCORE_ASC",
        )
        rows = ui.tables[0][0][0]
        self.assertEqual(rows[0]["Идентификатор"], "ORG-1")
        self.assertEqual(rows[0]["Целевое событие"], "Да")
        self.assertEqual(rows[0]["Положение относительно порога"], "Выше порога")
        self.assertEqual(rows[0]["Исход"], "TP")
        self.assertIn("0.23–0.81", ui.messages[-1])

        failed = _Streamlit()
        failed.session_state.loaded_artifact = _Artifact()
        failed.session_state.result_v2_view = "OBJECTS"
        broken = SimpleNamespace(objects=Mock(side_effect=RuntimeError("unavailable")))
        with patch.object(prototype, "st", failed):
            prototype._render_result_step(SimpleNamespace(oof_result_service=broken))
        self.assertEqual(len(failed.errors), 1)
        self.assertEqual(failed.tables, [])

    def test_objects_selection_opens_exact_dto_object_id(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECTS"
        ui.dataframe_selection = {"selection": {"rows": [1]}}
        items = (
            SimpleNamespace(object_id="opaque-1", identifier_display="SAME", y_true=0, score=0.1, predicted_positive=False, outcome="TN"),
            SimpleNamespace(object_id="exact-id-2", identifier_display="SAME", y_true=1, score=0.2, predicted_positive=False, outcome="FN"),
        )
        objects = self._objects(items=items, returned_count=2)
        service = SimpleNamespace(objects=Mock(return_value=objects))
        ui.button_responses["Открыть объект"] = True

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))

        self.assertEqual(ui.tables[0][1]["on_select"], "rerun")
        self.assertEqual(ui.tables[0][1]["selection_mode"], "single-row")
        self.assertEqual(ui.session_state.result_v2_selected_object_id, "exact-id-2")
        self.assertEqual(ui.session_state.result_v2_view, "OBJECT_DETAIL")
        self.assertEqual(ui.rerun_calls, 1)

    def test_detail_uses_exact_service_arguments_once_and_displays_dto_facts(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECT_DETAIL"
        ui.session_state.result_v2_selected_object_id = "object-id"
        ui.session_state.result_v2_threshold = 0.83
        detail = SimpleNamespace(
            identifier_display="ORG-7", score=0.2, threshold=0.83, y_true=1,
            predicted_positive=True, outcome="FN", fold_number=4,
        )
        service = SimpleNamespace(object_detail=Mock(return_value=detail))

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))

        service.object_detail.assert_called_once_with("artifact-1", "object-id", 0.83)
        rendered = " ".join(str(value) for value in ui.writes)
        self.assertIn("ORG-7", " ".join(str(value) for value in ui.messages))
        self.assertIn("0.2000", rendered)
        self.assertIn("Целевое событие: Да", rendered)
        self.assertIn("Положение: Выше порога", rendered)
        self.assertIn("Исход: FN", rendered)
        self.assertIn("Fold: 4", rendered)

    def _detail(self):
        return SimpleNamespace(
            identifier_display="ORG-7", score=0.2, threshold=0.5, y_true=1,
            predicted_positive=False, outcome="FN", fold_number=4,
        )

    def _evidence(self):
        features = tuple(
            SimpleNamespace(
                column_name=f"column-{index}",
                display_name_ru=(f"Признак {index}" if index == 1 else None),
                description_ru="Описание из evidence" if index == 2 else None,
                raw_value=index + 0.25,
                shap_value=(6 - index) * (1 if index % 2 else -1),
                abs_rank=index,
            )
            for index in range(1, 8)
        )
        return SimpleNamespace(
            base_value=0.125,
            explained_output_value=0.875,
            output_space="raw_margin",
            shap_output_space="raw_margin",
            features=features,
            explanation_method_id="method-from-evidence",
            explanation_method_version="method-v1",
            provider_id="provider-from-evidence",
            provider_version="provider-v2",
            model_binding_id="binding-from-evidence",
            source_kind="oof_fold",
            provenance={"fold_id": "fold-4", "other": "trusted"},
        )

    def test_automatic_local_explanation_exact_call_and_same_object_cache(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECT_DETAIL"
        ui.session_state.result_v2_selected_object_id = "object-id"
        service = SimpleNamespace(local=Mock(return_value=self._evidence()))
        runtime = SimpleNamespace(
            oof_result_service=SimpleNamespace(object_detail=Mock(return_value=self._detail())),
            oof_explanation_service=service,
        )

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)
            prototype._render_result_step(runtime)

        service.local.assert_called_once_with("artifact-1", "object-id")
        runtime.oof_result_service.object_detail.assert_called_once_with(
            "artifact-1", "object-id", 0.5
        )
        self.assertIs(ui.session_state.result_v2_local_explanation_evidence, service.local.return_value)
        self.assertEqual(ui.session_state.result_v2_local_explanation_object_id, "object-id")

    def test_new_object_cannot_render_or_reuse_previous_explanation(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECT_DETAIL"
        ui.session_state.result_v2_selected_object_id = "object-2"
        ui.session_state.result_v2_local_explanation_object_id = "object-1"
        ui.session_state.result_v2_local_explanation_evidence = self._evidence()
        service = SimpleNamespace(local=Mock(return_value=self._evidence()))
        runtime = SimpleNamespace(
            oof_result_service=SimpleNamespace(object_detail=Mock(return_value=self._detail())),
            oof_explanation_service=service,
        )

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)

        service.local.assert_called_once_with("artifact-1", "object-2")
        self.assertEqual(ui.session_state.result_v2_local_explanation_object_id, "object-2")
        self.assertTrue(any("Признак 1" in args[0] for args, _ in ui.markdowns))

    def test_brief_uses_abs_rank_sign_and_exact_remainder_sum(self) -> None:
        ui = _Streamlit()
        evidence = self._evidence()
        with patch.object(prototype, "st", ui):
            prototype._render_oof_explanation_brief(evidence)

        self.assertEqual(len(ui.markdowns), 5)
        self.assertIn("увеличивает оценку модели", ui.markdowns[0][0][0])
        self.assertIn("уменьшает оценку модели", ui.markdowns[1][0][0])
        remainder = sum(feature.shap_value for feature in evidence.features[5:])
        self.assertIn(f"{remainder:.6f}", str(ui.writes))
        self.assertIn("Признак 1", ui.markdowns[0][0][0])
        self.assertIn("column-2", ui.markdowns[1][0][0])

    def test_detailed_mode_uses_evidence_values_and_collapsed_provenance(self) -> None:
        ui = _Streamlit()
        evidence = self._evidence()
        ui.session_state.result_v2_local_explanation_mode = "DETAILED"
        with patch.object(prototype, "st", ui):
            prototype._render_oof_explanation_detailed(evidence)

        rows = ui.tables[0][0][0]
        self.assertEqual(rows[0]["Значение"], evidence.features[0].raw_value)
        self.assertEqual(rows[0]["Описание"], "")
        self.assertEqual(rows[1]["Признак"], "column-2")
        self.assertEqual(rows[1]["Описание"], "Описание из evidence")
        self.assertEqual(
            ui.json_values[0],
            {
                "explanation_method_id": "method-from-evidence",
                "explanation_method_version": "method-v1",
                "provider_id": "provider-from-evidence",
                "provider_version": "provider-v2",
                "model_binding_id": "binding-from-evidence",
                "source_kind": "oof_fold",
                "fold_id": "fold-4",
            },
        )

    def test_error_hides_raw_exception_and_retry_repeats_local_only(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECT_DETAIL"
        ui.session_state.result_v2_selected_object_id = "object-id"
        local = Mock(side_effect=[RuntimeError("private traceback"), self._evidence()])
        runtime = SimpleNamespace(
            oof_result_service=SimpleNamespace(object_detail=Mock(return_value=self._detail())),
            oof_explanation_service=SimpleNamespace(local=local),
        )

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(runtime)
            ui.button_responses["Повторить объяснение"] = True
            prototype._render_result_step(runtime)

        self.assertEqual(local.call_args_list[0].args, ("artifact-1", "object-id"))
        self.assertEqual(local.call_args_list[1].args, ("artifact-1", "object-id"))
        runtime.oof_result_service.object_detail.assert_called_once_with(
            "artifact-1", "object-id", 0.5
        )
        self.assertNotIn("private traceback", str(ui.errors))
        self.assertIsNone(ui.session_state.result_v2_local_explanation_error_code)
        self.assertIsNotNone(ui.session_state.result_v2_local_explanation_evidence)

    def test_detail_missing_id_and_service_error_fail_closed_with_back_available(self) -> None:
        missing = _Streamlit()
        missing.session_state.loaded_artifact = _Artifact()
        missing.session_state.result_v2_view = "OBJECT_DETAIL"
        service = SimpleNamespace(object_detail=Mock())
        with patch.object(prototype, "st", missing):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))
        service.object_detail.assert_not_called()
        self.assertEqual(len(missing.errors), 1)
        self.assertTrue(any(button[0][0] == "← К объектам" for button in missing.buttons))

        failed = _Streamlit()
        failed.session_state.loaded_artifact = _Artifact()
        failed.session_state.result_v2_view = "OBJECT_DETAIL"
        failed.session_state.result_v2_selected_object_id = "gone"
        failed_service = SimpleNamespace(object_detail=Mock(side_effect=RuntimeError("missing")))
        with patch.object(prototype, "st", failed):
            prototype._render_result_step(SimpleNamespace(oof_result_service=failed_service))
        failed_service.object_detail.assert_called_once_with("artifact-1", "gone", 0.5)
        self.assertEqual(len(failed.errors), 1)
        self.assertEqual(failed.writes, [])

    def test_detail_back_preserves_threshold_and_object_query_state(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECT_DETAIL"
        ui.session_state.result_v2_selected_object_id = "object-id"
        ui.session_state.result_v2_local_explanation_evidence = object()
        ui.session_state.result_v2_local_explanation_object_id = "object-id"
        ui.session_state.result_v2_threshold = 0.31
        ui.session_state.update(
            result_v2_objects_search="search text", result_v2_objects_target="NEGATIVE",
            result_v2_objects_outcomes=("FP",), result_v2_objects_min_score=0.14,
            result_v2_objects_max_score=0.72, result_v2_objects_score_range=(0.14, 0.72),
            result_v2_objects_sort="SCORE_ASC", result_v2_objects_offset=50,
            result_v2_objects_query_snapshot=("search text", "NEGATIVE", ("FP",), 0.14, 0.72, "SCORE_ASC"),
        )
        ui.button_responses["← К объектам"] = True
        service = SimpleNamespace(object_detail=Mock())

        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))

        service.object_detail.assert_not_called()
        self.assertEqual(ui.session_state.result_v2_view, "OBJECTS")
        self.assertEqual(ui.session_state.result_v2_threshold, 0.31)
        self.assertEqual(ui.session_state.result_v2_objects_search, "search text")
        self.assertEqual(ui.session_state.result_v2_objects_target, "NEGATIVE")
        self.assertEqual(ui.session_state.result_v2_objects_outcomes, ("FP",))
        self.assertEqual(ui.session_state.result_v2_objects_min_score, 0.14)
        self.assertEqual(ui.session_state.result_v2_objects_max_score, 0.72)
        self.assertEqual(ui.session_state.result_v2_objects_sort, "SCORE_ASC")
        self.assertEqual(ui.session_state.result_v2_objects_offset, 50)
        self.assertEqual(ui.session_state.result_v2_objects_query_snapshot[0], "search text")
        self.assertIsNotNone(ui.session_state.result_v2_local_explanation_evidence)
        self.assertEqual(ui.session_state.result_v2_local_explanation_object_id, "object-id")

    def test_objects_quick_views_and_default_score_range(self) -> None:
        cases = (
            ("Ошибки модели", ("FP", "FN"), "SCORE_DESC"),
            ("Пропущенные события", ("FN",), "SCORE_DESC"),
            ("Ложные срабатывания", ("FP",), "SCORE_DESC"),
            ("Пограничные", None, "DISTANCE_TO_THRESHOLD_ASC"),
            ("Высокая оценка", None, "SCORE_DESC"),
            ("Все объекты", None, "SCORE_DESC"),
        )
        for label, outcomes, sort in cases:
            with self.subTest(label=label):
                ui = _Streamlit()
                ui.session_state.loaded_artifact = _Artifact()
                ui.session_state.result_v2_view = "OBJECTS"
                ui.button_responses[label] = True
                service = SimpleNamespace(objects=Mock(return_value=self._objects()))
                with patch.object(prototype, "st", ui):
                    prototype._render_result_step(SimpleNamespace(oof_result_service=service))
                self.assertEqual(service.objects.call_args.kwargs["outcomes"], outcomes)
                self.assertEqual(service.objects.call_args.kwargs["sort"], sort)
                self.assertEqual(service.objects.call_args.kwargs["min_score"], 0.0)
                self.assertEqual(service.objects.call_args.kwargs["max_score"], 1.0)

    def test_objects_changed_query_resets_offset_and_next_uses_server_chunk(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECTS"
        ui.session_state.result_v2_objects_offset = 50
        ui.session_state.result_v2_objects_search = "new search"
        ui.session_state.result_v2_objects_query_snapshot = ("old search", "ANY", (), 0.0, 1.0, "SCORE_DESC")
        service = SimpleNamespace(objects=Mock(return_value=self._objects(filtered_count=120)))
        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))
        self.assertEqual(service.objects.call_args.args[2:4], (0, 50))
        self.assertEqual(ui.session_state.result_v2_objects_offset, 0)

        next_ui = _Streamlit()
        next_ui.session_state.loaded_artifact = _Artifact()
        next_ui.session_state.result_v2_view = "OBJECTS"
        next_ui.button_responses["Следующие →"] = True
        next_service = SimpleNamespace(objects=Mock(return_value=self._objects(filtered_count=120)))
        with patch.object(prototype, "st", next_ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=next_service))
        self.assertEqual(next_service.objects.call_args.args[2], 0)
        self.assertEqual(next_service.objects.call_args.args[3], 50)
        self.assertEqual(next_ui.session_state.result_v2_objects_offset, 50)

    def test_objects_back_preserves_threshold_and_previous_pages_back(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        ui.session_state.result_v2_view = "OBJECTS"
        ui.session_state.result_v2_threshold = 0.37
        ui.button_responses["← Назад к результату"] = True
        service = SimpleNamespace(objects=Mock(return_value=self._objects()))
        with patch.object(prototype, "st", ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=service))
        self.assertEqual(ui.session_state.result_v2_view, "OVERVIEW")
        self.assertEqual(ui.session_state.result_v2_threshold, 0.37)
        service.objects.assert_not_called()

        previous_ui = _Streamlit()
        previous_ui.session_state.loaded_artifact = _Artifact()
        previous_ui.session_state.result_v2_view = "OBJECTS"
        previous_ui.session_state.result_v2_objects_offset = 50
        previous_ui.button_responses["← Предыдущие"] = True
        previous_service = SimpleNamespace(objects=Mock(return_value=self._objects(offset=0)))
        with patch.object(prototype, "st", previous_ui):
            prototype._render_result_step(SimpleNamespace(oof_result_service=previous_service))
        self.assertEqual(previous_service.objects.call_args.args[2], 0)
