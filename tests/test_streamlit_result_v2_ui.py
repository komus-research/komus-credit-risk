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
        return self.ui.button_responses.get(args[0], False)


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

    def header(self, *args, **kwargs) -> None:
        return None

    def slider(self, *args, **kwargs) -> float:
        self.slider_args = (args, kwargs)
        return self.slider_value if hasattr(self, "slider_value") else 0.62

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

    def write(self, *args, **kwargs) -> None:
        return None

    def caption(self, *args, **kwargs) -> None:
        self.messages.extend(args)

    def subheader(self, *args, **kwargs) -> None:
        self.messages.extend(args)

    def columns(self, count):
        return [_Column(self) for _ in range(count)]

    def dataframe(self, *args, **kwargs) -> None:
        return None

    def expander(self, *args, **kwargs):
        return _Expander()

    def json(self, *args, **kwargs) -> None:
        return None


class _Artifact:
    artifact_id = "artifact-1"

    @property
    def run_output(self):  # pragma: no cover - accessed only by a regression.
        raise AssertionError("Overview must not read artifact run output")


class ResultV2UiTests(unittest.TestCase):
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

    def test_overview_cta_opens_threshold_and_future_screens_stay_inactive(self) -> None:
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
        disabled_labels = [args[0] for args, kwargs in ui.buttons if kwargs.get("disabled")]
        self.assertIn("\u041f\u043e\u0441\u043c\u043e\u0442\u0440\u0435\u0442\u044c \u043e\u0431\u044a\u0435\u043a\u0442\u044b", disabled_labels)
        self.assertIn("\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0435\u0435 \u043e \u0432\u043b\u0438\u044f\u043d\u0438\u0438 \u043f\u0440\u0438\u0437\u043d\u0430\u043a\u043e\u0432", disabled_labels)

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
