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
        return False


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

    def header(self, *args, **kwargs) -> None:
        return None

    def slider(self, *args, **kwargs) -> float:
        return 0.62

    def success(self, *args, **kwargs) -> None:
        return None

    def info(self, *args, **kwargs) -> None:
        return None

    def error(self, message, *args, **kwargs) -> None:
        self.errors.append(message)

    def write(self, *args, **kwargs) -> None:
        return None

    def caption(self, *args, **kwargs) -> None:
        return None

    def subheader(self, *args, **kwargs) -> None:
        return None

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

    def test_overview_uses_oof_service_without_artifact_run_output(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        service = SimpleNamespace(summary=Mock(return_value=self._summary()), threshold=Mock(return_value=self._threshold()))
        runtime = SimpleNamespace(oof_result_service=service)

        with (patch.object(prototype, "st", ui), patch.object(prototype, "_render_local_model_use_flow"), patch.object(prototype, "_navigation_button")):
            prototype._render_result_step(runtime)

        service.summary.assert_called_once_with("artifact-1")
        service.threshold.assert_called_once_with("artifact-1", 0.62)
        self.assertEqual(ui.session_state.result_v2_threshold, 0.62)
        self.assertIn(("TP", "2"), ui.metrics)

    def test_service_failure_is_fail_closed_without_legacy_fallback(self) -> None:
        ui = _Streamlit()
        ui.session_state.loaded_artifact = _Artifact()
        service = SimpleNamespace(summary=Mock(side_effect=RuntimeError("bad evidence")), threshold=Mock())
        runtime = SimpleNamespace(oof_result_service=service)

        with (patch.object(prototype, "st", ui), patch.object(prototype, "_render_local_model_use_flow"), patch.object(prototype, "_navigation_button")):
            prototype._render_result_step(runtime)

        service.summary.assert_called_once_with("artifact-1")
        service.threshold.assert_not_called()
        self.assertEqual(len(ui.errors), 1)
