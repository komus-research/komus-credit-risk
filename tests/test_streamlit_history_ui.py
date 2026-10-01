from __future__ import annotations

import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import app.streamlit_app as prototype
from app.session_state import (
    confirm_new_analysis,
    continue_current_analysis,
    initialize,
    open_history,
    open_home,
    request_new_analysis,
)


class HistoryStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state: dict[str, object] = {}
        initialize(self.state)

    def test_open_history_is_presentation_only_and_query_state_defaults(self) -> None:
        current = {
            "current_step": 3,
            "highest_reached_step": 4,
            "dataset_context": object(),
            "loaded_artifact": object(),
            "experiment_plan": object(),
            "result_v2_view": "OBJECT_DETAIL",
            "result_v2_threshold": 0.72,
            "result_v2_selected_object_id": "row-1",
            "result_v2_local_explanation_evidence": object(),
            "result_interpreter_response": object(),
            "loaded_model_version": object(),
            "inference_snapshot": object(),
        }
        self.state.update(current)

        open_history(self.state)

        self.assertEqual(self.state["presentation_surface"], "HISTORY")
        for key, value in current.items():
            self.assertIs(self.state[key], value) if not isinstance(value, (int, float, str)) else self.assertEqual(self.state[key], value)
        self.assertEqual(self.state["history_search"], "")
        self.assertEqual(self.state["history_sort"], "CREATED_DESC")
        self.assertEqual(self.state["history_offset"], 0)
        self.assertIsNone(self.state["history_query_snapshot"])

    def test_home_history_roundtrip_and_new_analysis_preserve_query(self) -> None:
        self.state.update(history_search="cat", history_sort="CREATED_ASC", history_offset=40)
        open_history(self.state)
        open_home(self.state)
        open_history(self.state)
        continue_current_analysis(self.state)

        self.assertEqual(
            (self.state["history_search"], self.state["history_sort"], self.state["history_offset"]),
            ("cat", "CREATED_ASC", 40),
        )
        self.assertEqual(self.state["presentation_surface"], "ANALYSIS")

    def test_confirmed_new_analysis_preserves_history_query_snapshot(self) -> None:
        snapshot = ("risk", "CREATED_ASC")
        self.state.update(
            history_search="risk",
            history_sort="CREATED_ASC",
            history_offset=40,
            history_query_snapshot=snapshot,
            selected_model_id="catboost",
        )

        self.assertTrue(request_new_analysis(self.state))
        confirm_new_analysis(self.state)

        self.assertEqual(
            (
                self.state["history_search"],
                self.state["history_sort"],
                self.state["history_offset"],
                self.state["history_query_snapshot"],
            ),
            ("risk", "CREATED_ASC", 40, snapshot),
        )


class HistoryUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state: dict[str, object] = {}
        initialize(self.state)
        self.ui = _HistoryStreamlit(self.state)
        self.runtime = SimpleNamespace(analysis_history_service=Mock())
        self.runtime.analysis_history_service.list.return_value = _page()

    def test_exact_list_call_and_dto_render_preserve_current_analysis(self) -> None:
        dataset, artifact, plan, explanation, interpreter = (object() for _ in range(5))
        self.state.update(
            history_search="  north  ",
            history_sort="CREATED_ASC",
            history_offset=20,
            history_query_snapshot=("north", "CREATED_ASC"),
            dataset_context=dataset,
            loaded_artifact=artifact,
            experiment_plan=plan,
            result_v2_view="OBJECT_DETAIL",
            result_v2_threshold=0.63,
            result_v2_selected_object_id="obj-7",
            result_v2_local_explanation_evidence=explanation,
            result_interpreter_response=interpreter,
        )
        before = dict(self.state)

        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)

        self.runtime.analysis_history_service.list.assert_called_once_with(
            offset=20, limit=20, search="north", model_id=None, sort="CREATED_ASC"
        )
        self.assertEqual(self.ui.tables[0], [{
            "Дата": "01.02.2026",
            "Данные": "North portfolio",
            "Алгоритм": "catboost",
            "Версия": "v7",
            "Признаки": 47,
            "Проверка": "OOF · 3 фолда",
            "Gini": "0.804",
            "Доступ": "Полный результат",
        }])
        for key in (
            "dataset_context", "loaded_artifact", "experiment_plan", "result_v2_view",
            "result_v2_threshold", "result_v2_selected_object_id",
            "result_v2_local_explanation_evidence", "result_interpreter_response",
        ):
            self.assertIs(self.state[key], before[key])

    def test_query_change_resets_offset_and_whitespace_search_becomes_none(self) -> None:
        self.state.update(history_search="  ", history_sort="CREATED_DESC", history_offset=60)
        self.state["history_query_snapshot"] = ("previous", "CREATED_DESC")

        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)

        self.assertEqual(self.state["history_offset"], 0)
        self.runtime.analysis_history_service.list.assert_called_once_with(
            offset=0, limit=20, search=None, model_id=None, sort="CREATED_DESC"
        )

    def test_legacy_dto_maps_to_summary_access_label(self) -> None:
        legacy = _page().items[0]
        self.runtime.analysis_history_service.list.return_value = _page(
            items=(SimpleNamespace(**{**vars(legacy), "result_access": "LEGACY_SUMMARY_ONLY"}),)
        )

        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)

        self.assertEqual(self.ui.tables[0][0]["Доступ"], "Только сводка")

    def test_non_oof_evaluation_level_is_rendered_from_dto(self) -> None:
        item = _page().items[0]
        item_data = vars(item)
        item_data["evaluation_level"] = "holdout"
        self.runtime.analysis_history_service.list.return_value = _page(
            items=(SimpleNamespace(**item_data),)
        )

        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)

        check_label = self.ui.tables[0][0]["Проверка"]
        self.assertEqual(check_label, "holdout · 3 фолда")
        self.assertNotIn("OOF", check_label)

    def test_pagination_uses_backend_counts_and_offsets(self) -> None:
        page = _page(offset=20, returned_count=20, filtered_count=41)
        self.runtime.analysis_history_service.list.return_value = page
        self.state.update(history_offset=20, history_query_snapshot=(None, "CREATED_DESC"))

        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)

        buttons = {entry["key"]: entry for entry in self.ui.buttons}
        self.assertFalse(buttons["history-previous"]["disabled"])
        self.assertFalse(buttons["history-next"]["disabled"])
        self.assertIn("Показано 21–40 из 41", self.ui.captions)
        with patch.object(prototype, "st", self.ui):
            prototype._change_history_page(-20)
            self.assertEqual(self.state["history_offset"], 0)
            prototype._change_history_page(20)
            self.assertEqual(self.state["history_offset"], 20)

    def test_distinct_empty_states_and_service_error_hide_exception(self) -> None:
        self.runtime.analysis_history_service.list.return_value = _page(total_count=0, filtered_count=0, items=())
        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)
        self.assertIn("История анализов пока пуста.", self.ui.infos)

        self.ui.infos.clear()
        self.runtime.analysis_history_service.list.return_value = _page(total_count=3, filtered_count=0, items=())
        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)
        self.assertIn("По заданным условиям анализы не найдены.", self.ui.infos)

        self.runtime.analysis_history_service.list.side_effect = RuntimeError("private artifact path")
        with patch.object(prototype, "st", self.ui):
            prototype._render_history(self.runtime)
        self.assertEqual(self.ui.errors[-1], "Не удалось загрузить историю анализов.")
        self.assertNotIn("private artifact path", self.ui.errors[-1])

    def test_history_renderer_has_no_storage_filesystem_or_oof_access(self) -> None:
        source = inspect.getsource(prototype._render_history)
        for forbidden in ("artifact_store", "Path(", ".glob(", "oof_result_service", "oof_explanation_service"):
            self.assertNotIn(forbidden, source)

    def test_sidebar_has_enabled_canonical_active_history_item(self) -> None:
        self.state["presentation_surface"] = "HISTORY"
        with patch.object(prototype, "st", self.ui):
            prototype._render_axion_sidebar()
        history_button = next(item for item in self.ui.buttons if item["key"] == "axion-nav-history")
        self.assertEqual(history_button["label"], "▤  История")
        self.assertEqual(history_button["type"], "primary")
        self.assertFalse(history_button.get("disabled", False))
        self.assertFalse(any("Проекты / История" in item["label"] for item in self.ui.buttons))


def _page(*, offset: int = 0, returned_count: int = 1, filtered_count: int = 1,
          total_count: int = 1, items=None):
    if items is None:
        items = (SimpleNamespace(
            artifact_id="a-1",
            result_id="r-1",
            created_at="2026-02-01T00:00:00+00:00",
            dataset_name="North portfolio",
            dataset_id="ds-1",
            model_id="catboost",
            model_version="v7",
            feature_count=47,
            folds=3,
            evaluation_level="oof",
            gini=0.804,
            result_access="FULL_RESULT_V2",
        ),)
    return SimpleNamespace(
        total_count=total_count,
        filtered_count=filtered_count,
        offset=offset,
        limit=20,
        returned_count=returned_count,
        items=items,
    )


class _Column:
    def __init__(self, parent):
        self.parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def button(self, label, **kwargs):
        return self.parent.button(label, **kwargs)

    def caption(self, label):
        self.parent.caption(label)

    def text_input(self, label, **kwargs):
        return self.parent.text_input(label, **kwargs)

    def selectbox(self, label, **kwargs):
        return self.parent.selectbox(label, **kwargs)


class _SessionState(dict):
    def __init__(self, backing):
        self.backing = backing

    def __getattr__(self, key):
        return self.backing[key]

    def __setattr__(self, key, value):
        if key == "backing":
            object.__setattr__(self, key, value)
        else:
            self.backing[key] = value

    def __getitem__(self, key):
        return self.backing[key]

    def __setitem__(self, key, value):
        self.backing[key] = value

    def get(self, key, default=None):
        return self.backing.get(key, default)


class _HistoryStreamlit:
    def __init__(self, state):
        self.session_state = _SessionState(state)
        self.sidebar = _Column(self)
        self.buttons = []
        self.captions = []
        self.infos = []
        self.errors = []
        self.tables = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def image(self, *_args, **_kwargs):
        pass

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return False

    def columns(self, specification, **_kwargs):
        return tuple(_Column(self) for _ in specification)

    def text_input(self, _label, **_kwargs):
        return self.session_state[_kwargs["key"]]

    def selectbox(self, _label, **_kwargs):
        return self.session_state[_kwargs["key"]]

    def html(self, _body):
        pass

    def dataframe(self, rows, **_kwargs):
        self.tables.append(rows)

    def caption(self, label):
        self.captions.append(label)

    def info(self, label):
        self.infos.append(label)

    def error(self, label):
        self.errors.append(label)

    def divider(self):
        pass

    def rerun(self):
        pass


if __name__ == "__main__":
    unittest.main()
