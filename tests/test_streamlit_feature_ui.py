"""Regression tests for the compact Streamlit feature-family controls."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.session_state import initialize
import app.streamlit_app as prototype


class _SessionState(dict):
    def __getattr__(self, key: str):
        return self[key]


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Column:
    def __init__(self, streamlit: "_StreamlitWithoutContextManager", index: int) -> None:
        self._streamlit = streamlit
        self._index = index

    def __enter__(self):
        self._streamlit.active_column = self._index
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._streamlit.active_column = None
        return False


class _StreamlitWithoutContextManager:
    """A minimal Streamlit double that deliberately cannot be used with ``with``."""

    def __init__(self) -> None:
        self.session_state = _SessionState()
        initialize(self.session_state)
        self.expanders: list[tuple[str, bool]] = []
        self.checkboxes: list[tuple[str, int | None]] = []
        self.columns_requested: list[int] = []
        self.active_column: int | None = None

    def caption(self, _text: str):
        return None

    def columns(self, count: int):
        self.columns_requested.append(count)
        return tuple(_Column(self, index) for index in range(count))

    def expander(self, label: str, *, expanded: bool):
        self.expanders.append((label, expanded))
        return _Expander()

    def checkbox(self, label: str, *, key: str, **_kwargs):
        self.checkboxes.append((label, self.active_column))
        return self.session_state.get(key, False)


class StreamlitFeatureUiTests(unittest.TestCase):
    def test_compact_grid_keeps_family_controls_visible_and_ordered(self) -> None:
        streamlit = _StreamlitWithoutContextManager()
        views = [
            SimpleNamespace(feature_id="Q_A1_norm", display_name_ru="Q_A1", description_ru="Первый", selectable=True),
            SimpleNamespace(feature_id="Q_A2_norm", display_name_ru="Q_A2", description_ru="Второй", selectable=True),
            SimpleNamespace(feature_id="Q_B3_norm", display_name_ru="Q_B3", description_ru="Третий", selectable=True),
            SimpleNamespace(feature_id="A1_norm", display_name_ru="A1", description_ru="Четвёртый", selectable=True),
            SimpleNamespace(feature_id="D5_norm", display_name_ru="D5", description_ru="Пятый", selectable=True),
        ]

        with patch.object(prototype, "st", streamlit):
            prototype._render_selectable_feature_families("accepted_predictors", views, revision=1)

        self.assertEqual(streamlit.columns_requested, [4])
        self.assertEqual(
            [label for label, _column in streamlit.checkboxes if label.startswith("Группа")],
            ["Группа Q_A · 0/2", "Группа Q_B · 0/1", "Группа A · 0/1", "Группа D · 0/1"],
        )
        self.assertEqual(
            [column for label, column in streamlit.checkboxes if label.startswith("Группа")],
            [0, 1, 2, 3],
        )
        self.assertEqual(streamlit.expanders, [("Показать признаки", False)] * 4)
        self.assertEqual(streamlit.checkboxes[0], ("Выбрать все разрешённые признаки", None))
        self.assertEqual(streamlit.checkboxes[1], ("Группа Q_A · 0/2", 0))
        self.assertEqual(
            [label for label, _column in streamlit.checkboxes if " — " in label],
            ["Q_A1 — Первый", "Q_A2 — Второй", "Q_B3 — Третий", "A1 — Четвёртый", "D5 — Пятый"],
        )


if __name__ == "__main__":
    unittest.main()
