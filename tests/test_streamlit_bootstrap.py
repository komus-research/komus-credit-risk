"""Targeted tests for local source resolution and historical preparation."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

import app.bootstrap as bootstrap
from app.bootstrap import (
    DatasetSourcePreparation,
    HistoricalDatasetProvider,
    LocalDatasetSourceResolver,
    ResolvedDatasetSource,
    prepare_resolved_source,
)
from komus_risk.contracts import DatasetContract
from komus_risk.data import LoadedDataset


def _source(path: Path, *, source_kind: str = "explicit_local") -> ResolvedDatasetSource:
    return ResolvedDatasetSource(source_kind, "Тестовый источник", path, path.name, "xlsb", 1)


class StreamlitBootstrapTests(unittest.TestCase):
    def test_accepted_stage1_evidence_provides_exact_working_population(self) -> None:
        split = bootstrap._load_accepted_working_split()
        full_target = np.zeros(bootstrap._ACCEPTED_FULL_ROW_COUNT, dtype=np.int8)
        full_target[np.asarray(split.row_positions, dtype=np.int64)] = split.target
        contract = DatasetContract(
            "accepted", "1", "Data_final", "ready_xlsb", "fingerprint", bootstrap._ACCEPTED_FULL_ROW_COUNT, 52,
            "DefMark", 1, "INN", "registry", "hash", "validated", True,
        )
        loaded = LoadedDataset(
            pd.DataFrame({"DefMark": full_target}), contract, Path("Data_final.xlsb"), "xlsb", bootstrap._ACCEPTED_DATASET_SHA256,
        )
        provider = HistoricalDatasetProvider()

        with (
            patch.object(provider, "_validate_source_identity"),
            patch("app.bootstrap.ReadyDatasetAdapter.load", return_value=loaded),
        ):
            context = provider.prepare(_source(Path("accepted-copy.xlsb")))

        positions = np.asarray(context.population.row_positions, dtype=np.int64)
        in_working = np.zeros(bootstrap._ACCEPTED_FULL_ROW_COUNT, dtype=bool)
        in_working[positions] = True
        self.assertEqual(context.loaded_dataset.contract.row_count, 362_018)
        self.assertEqual(len(positions), 289_614)
        self.assertEqual(context.population.population_fingerprint, bootstrap._ACCEPTED_WORKING_INDEX_SHA256)
        self.assertEqual(bootstrap._sha256_int64(positions), context.population.population_fingerprint)
        self.assertEqual(int((~in_working).sum()), 72_404)

    def test_repository_and_explicit_paths_share_the_same_source_resolution_result(self) -> None:
        with TemporaryDirectory() as directory:
            repository_path = Path(directory) / "Data_final.xlsb"
            explicit_path = Path(directory) / "copy.xlsb"
            repository_path.write_bytes(b"accepted-copy")
            explicit_path.write_bytes(b"accepted-copy")
            resolver = LocalDatasetSourceResolver(repository_path)

            repository_source = resolver.resolve_repository_data_final()
            explicit_source = resolver.resolve_explicit_local_path(explicit_path)

        self.assertEqual(repository_source.local_runtime_path.suffix, ".xlsb")
        self.assertEqual(explicit_source.local_runtime_path.suffix, ".xlsb")
        self.assertEqual(repository_source.physical_format, explicit_source.physical_format)
        self.assertEqual(repository_source.file_size, explicit_source.file_size)
        self.assertEqual(repository_source.source_kind, "repository_local")
        self.assertEqual(explicit_source.source_kind, "explicit_local")

    def test_default_repository_source_is_permitted_for_historical_preparation(self) -> None:
        with TemporaryDirectory() as directory:
            repository_path = Path(directory) / "Data_final.xlsb"
            repository_path.write_bytes(b"accepted-copy")
            source = LocalDatasetSourceResolver(repository_path).resolve_repository_data_final()
            context = SimpleNamespace(context_id="historical_data_final_v1")
            provider = SimpleNamespace(prepare=Mock(return_value=context))

            with patch("app.bootstrap._sha256_file", return_value=bootstrap._ACCEPTED_DATASET_SHA256):
                result = prepare_resolved_source(source, historical_provider=provider)

        self.assertEqual(source.file_name, "Data_final.xlsb")
        self.assertEqual(result.preparation_status, "historical_context_prepared")
        self.assertIs(result.context, context)

    def test_exact_accepted_copy_from_another_path_receives_historical_context(self) -> None:
        source = _source(Path("another-location") / "Data_final.xlsb")
        context = SimpleNamespace(context_id="historical_data_final_v1")
        provider = SimpleNamespace(prepare=Mock(return_value=context))

        with patch("app.bootstrap._sha256_file", return_value=bootstrap._ACCEPTED_DATASET_SHA256):
            result = prepare_resolved_source(source, historical_provider=provider)

        self.assertEqual(result.preparation_status, "historical_context_prepared")
        self.assertIs(result.context, context)
        provider.prepare.assert_called_once_with(source, progress_listener=None)

    def test_wrong_identity_never_receives_historical_population_or_context(self) -> None:
        source = _source(Path("elsewhere") / "Data_final.xlsb")
        provider = SimpleNamespace(prepare=Mock())

        with (
            patch("app.bootstrap._sha256_file", return_value="not-the-accepted-file"),
            patch("app.bootstrap._load_accepted_working_split") as load_split,
        ):
            result = prepare_resolved_source(source, historical_provider=provider)

        self.assertEqual(result.preparation_status, "context_not_prepared")
        self.assertIsNone(result.context)
        provider.prepare.assert_not_called()
        load_split.assert_not_called()

    def test_explicit_schema_like_local_file_resolves_but_is_not_prepared(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Data_final.csv"
            path.write_text("INN,DefMark,Q_A1_norm\n1,0,0.1\n2,1,0.2\n", encoding="utf-8")
            source = LocalDatasetSourceResolver().resolve_explicit_local_path(path)
            with patch("app.bootstrap._sha256_file", return_value="different-content"), patch(
                "app.bootstrap._load_accepted_working_split"
            ) as load_split:
                result = prepare_resolved_source(source)

        self.assertEqual(source.physical_format, "csv")
        self.assertEqual(result.preparation_status, "context_not_prepared")
        self.assertIsNone(result.context)
        load_split.assert_not_called()

    def test_missing_explicit_local_path_is_a_source_error(self) -> None:
        missing_path = Path("missing-local-source.csv")

        with self.assertRaises(FileNotFoundError):
            LocalDatasetSourceResolver().resolve_explicit_local_path(missing_path)

    def test_data_progress_reports_only_historical_preparation_stages(self) -> None:
        provider = HistoricalDatasetProvider()
        events = []
        with (
            patch.object(provider, "_validate_source_identity"),
            patch("app.bootstrap._load_accepted_working_split", return_value=object()),
            patch("app.bootstrap.ReadyDatasetAdapter.load", side_effect=ValueError("unreadable")),
        ):
            with self.assertRaisesRegex(ValueError, "unreadable"):
                provider.prepare(_source(Path("synthetic.xlsb")), progress_listener=events.append)

        self.assertEqual(events, ["checking_file_identity", "checking_working_split", "loading_dataset"])
        self.assertNotIn("preparing_context", events)

    def test_unprepared_source_result_cannot_expose_a_context(self) -> None:
        result = DatasetSourcePreparation(_source(Path("arbitrary.csv")), "context_not_prepared", None)

        self.assertFalse(result.is_prepared)
        self.assertIsNone(result.context)

    def test_streamlit_module_uses_browser_upload_with_explicit_local_runtime_path(self) -> None:
        import app.streamlit_app as prototype

        source = Path(prototype.__file__).read_text(encoding="utf-8")
        self.assertIn("st.file_uploader", source)
        self.assertIn("persist_uploaded_file", source)
        self.assertIn("resolve_explicit_local_path", source)
        self.assertIn("preparation.is_prepared", source)

    def test_data_screen_uses_locked_user_facing_copy_and_keeps_details_collapsed(self) -> None:
        import app.streamlit_app as prototype

        source = Path(prototype.__file__).read_text(encoding="utf-8")

        self.assertIn('"accepted_historical": "Исторический набор данных"', source)
        self.assertIn('"Какие данные использовать?"', source)
        self.assertIn('"Файл данных"', source)
        self.assertNotIn('"Указать путь вручную"', source)
        self.assertNotIn('"Путь к файлу"', source)
        self.assertIn('_SUPPORTED_SOURCE_EXTENSIONS = (".csv", ".xlsx", ".xlsb")', source)
        self.assertIn('type=[extension.removeprefix(".") for extension in _SUPPORTED_SOURCE_EXTENSIONS]', source)
        self.assertIn('st.expander("Технические сведения", expanded=False)', source)
        self.assertIn('"Данные готовы к эксперименту"', source)
        self.assertIn('"Продолжить к признакам →"', source)
        self.assertIn('completion_label="Проверка источника завершена"', source)
        self.assertIn('status.update(label=completion_label, state="complete", expanded=False)', source)
        self.assertIn('_restore_source_controls(st.session_state)', source)
        self.assertIn('columns[0].metric("Организации / строки"', source)
        self.assertIn('columns[1].metric("Рабочая выборка"', source)
        self.assertIn('columns[2].metric("Защищённая контрольная выборка"', source)
        self.assertNotIn("st.subheader(source.display_name)", source)
        self.assertIn("st.file_uploader", source)

    def test_wizard_navigation_uses_non_destructive_transitions(self) -> None:
        import app.streamlit_app as prototype

        source = Path(prototype.__file__).read_text(encoding="utf-8")

        self.assertIn('"← Назад"', source)
        self.assertIn('"В начало"', source)
        self.assertIn('"Новый эксперимент"', source)
        self.assertIn('navigate_to_step(st.session_state, target_step)', source)
        self.assertNotIn("return_to_experiment(st.session_state)", source)
        self.assertIn('_navigation_button(navigation[2], "Новый эксперимент", 3, primary=True)', source)

    def test_step_navigator_keeps_the_compact_caption_visual(self) -> None:
        import app.streamlit_app as prototype

        class SessionState(dict):
            def __getattr__(self, key: str):
                return self[key]

        class Navigation:
            def __init__(self) -> None:
                self.elements: list[tuple[str, str, dict]] = []

            def button(self, label: str, **kwargs):
                self.elements.append(("button", label, kwargs))
                return False

            def caption(self, label: str):
                self.elements.append(("caption", label, {}))

        class Streamlit:
            def __init__(self) -> None:
                self.session_state = SessionState(current_step=1, highest_reached_step=1)
                self.navigation = Navigation()
                self.html_blocks: list[str] = []

            def html(self, body: str):
                self.html_blocks.append(body)

            def container(self, **_kwargs):
                return self.navigation

        streamlit = Streamlit()
        with patch.object(prototype, "st", streamlit):
            prototype._render_step_navigation()

        self.assertEqual(
            [(kind, label) for kind, label, _kwargs in streamlit.navigation.elements],
            [
                ("button", "○ Данные"), ("caption", "→"),
                ("button", "● Признаки"), ("caption", "→"),
                ("caption", "○ Модель"), ("caption", "→"),
                ("caption", "○ Эксперимент"), ("caption", "→"),
                ("caption", "○ Результат"), ("caption", "→"),
                ("caption", "○ SHAP"), ("caption", "→"),
                ("caption", "○ Прогноз"),
            ],
        )
        markup = "".join(streamlit.html_blocks)
        self.assertIn(".st-key-step-navigator", markup)
        self.assertNotIn("underline", markup)
        self.assertNotIn("|", markup)
        source = Path(prototype.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_STEP_NAVIGATION_QUERY_KEY", source)
        self.assertNotIn("st.query_params", source)
        self.assertIn("highest_reached_step", source)

    def test_navigator_features_click_changes_only_current_step(self) -> None:
        import app.streamlit_app as prototype

        class SessionState(dict):
            def __getattr__(self, key: str):
                return self[key]

        class Navigation:
            def __init__(self) -> None:
                self.buttons: list[tuple[str, dict]] = []

            def button(self, label: str, **kwargs):
                self.buttons.append((label, kwargs))
                return False

            def caption(self, _label: str):
                return None

        class Streamlit:
            def __init__(self, state: dict) -> None:
                self.session_state = state
                self.navigation = Navigation()

            def html(self, _body: str):
                return None

            def container(self, **_kwargs):
                return self.navigation

        context = object()
        preparation = SimpleNamespace(context=context, is_prepared=True)
        plan = object()
        result = object()
        state = SessionState({
            "current_step": 2,
            "highest_reached_step": 2,
            "dataset_source_preparation": preparation,
            "dataset_context": context,
            "prototype_source_control_locator": ("accepted_historical", ""),
            "prototype_source_kind": "accepted_historical",
            "prototype_selected_local_file_path": "",
            "prototype_manual_local_file_path": "",
            "selected_feature_ids": ("Q_A1_norm",),
            "selected_model_id": "lightgbm_v1",
            "experiment_inputs": {"folds": 5},
            "experiment_plan": plan,
            "loaded_artifact": result,
        })
        preserved = {key: state[key] for key in state if key != "current_step"}
        streamlit = Streamlit(state)

        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "prepare_resolved_source") as prepare_source,
        ):
            prototype._render_step_navigation()
            features_click = next(kwargs for label, kwargs in streamlit.navigation.buttons if label == "○ Признаки")
            features_click["on_click"](*features_click["args"])

        self.assertEqual(state["current_step"], 1)
        self.assertEqual(state["highest_reached_step"], 2)
        self.assertEqual({key: state[key] for key in preserved}, preserved)
        prepare_source.assert_not_called()

    def test_navigator_result_data_result_preserves_the_prepared_session(self) -> None:
        import app.streamlit_app as prototype

        class SessionState(dict):
            def __getattr__(self, key: str):
                return self[key]

        class Navigation:
            def __init__(self) -> None:
                self.buttons: list[tuple[str, dict]] = []

            def button(self, label: str, **kwargs):
                self.buttons.append((label, kwargs))
                return False

            def caption(self, _label: str):
                return None

        class Streamlit:
            def __init__(self, state: dict) -> None:
                self.session_state = state
                self.navigation = Navigation()

            def html(self, _body: str):
                return None

            def container(self, **_kwargs):
                return self.navigation

        context = object()
        preparation = SimpleNamespace(context=context, is_prepared=True)
        result = object()
        state = SessionState({
            "current_step": 4,
            "highest_reached_step": 4,
            "dataset_source_preparation": preparation,
            "dataset_context": context,
            "prototype_source_control_locator": ("accepted_historical", ""),
            "prototype_source_kind": "accepted_historical",
            "selected_feature_ids": ("Q_A1_norm",),
            "selected_model_id": "lightgbm_v1",
            "experiment_inputs": {"folds": 5},
            "experiment_plan": object(),
            "loaded_artifact": result,
        })
        preserved = {key: state[key] for key in state if key != "current_step"}
        streamlit = Streamlit(state)

        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "prepare_resolved_source") as prepare_source,
        ):
            prototype._render_step_navigation()
            data_click = next(kwargs for label, kwargs in streamlit.navigation.buttons if label == "○ Данные")
            data_click["on_click"](*data_click["args"])
            self.assertEqual(state["current_step"], 0)

            streamlit.navigation = Navigation()
            prototype._render_step_navigation()
            result_click = next(kwargs for label, kwargs in streamlit.navigation.buttons if label == "○ Результат")
            result_click["on_click"](*result_click["args"])

        self.assertEqual(state["current_step"], 4)
        self.assertEqual(state["highest_reached_step"], 4)
        self.assertEqual({key: state[key] for key in preserved}, preserved)
        self.assertIs(state["dataset_context"], context)
        self.assertIs(state["loaded_artifact"], result)
        prepare_source.assert_not_called()

    def test_progress_reaches_terminal_state_for_success_and_error(self) -> None:
        import app.streamlit_app as prototype

        class Status:
            def __init__(self) -> None:
                self.updates: list[dict] = []

            def write(self, _message: str):
                return None

            def update(self, **kwargs):
                self.updates.append(kwargs)

        class Streamlit:
            def __init__(self) -> None:
                self.statuses: list[Status] = []

            def status(self, _label: str, *, expanded: bool):
                status = Status()
                self.statuses.append(status)
                return status

        streamlit = Streamlit()
        with patch.object(prototype, "st", streamlit):
            self.assertEqual(
                prototype._run_with_progress({}, lambda _report: "done", completion_label="Готово"),
                "done",
            )
            with self.assertRaisesRegex(RuntimeError, "failed"):
                prototype._run_with_progress({}, lambda _report: (_ for _ in ()).throw(RuntimeError("failed")))

        self.assertEqual(streamlit.statuses[0].updates[-1], {"label": "Готово", "state": "complete", "expanded": False})
        self.assertEqual(streamlit.statuses[1].updates[-1], {"label": "Операция не завершена", "state": "error", "expanded": True})

    def test_checked_source_uses_recheck_action_even_when_not_run_ready(self) -> None:
        import app.streamlit_app as prototype

        source = Path(prototype.__file__).read_text(encoding="utf-8")

        self.assertIn('already_checked = preparation is not None', source)
        self.assertIn('"Проверить повторно" if already_checked', source)

    def test_manual_recheck_runs_the_existing_preparation_flow(self) -> None:
        import app.streamlit_app as prototype

        class SessionState(dict):
            def __getattr__(self, key: str):
                return self[key]

        class Status:
            def write(self, _value):
                return None

            def update(self, **_kwargs):
                return None

            def empty(self):
                return None

        class Streamlit:
            def __init__(self) -> None:
                self.session_state = SessionState()
                self.buttons: list[tuple[str, dict]] = []

            def button(self, label: str, **kwargs):
                self.buttons.append((label, kwargs))
                return True

            def status(self, _label: str, *, expanded: bool):
                return Status()

            def error(self, _value: str):
                return None

            def write(self, _value: str):
                return None

        source = SimpleNamespace(source_kind="repository_local", local_runtime_path=Path("Data_final.xlsb"))
        existing = SimpleNamespace(source=source, preparation_status="historical_context_prepared", context=object(), is_prepared=True)
        streamlit = Streamlit()
        streamlit.session_state["dataset_source_preparation"] = existing
        streamlit.session_state["prototype_source_control_locator"] = ("accepted_historical", "")
        resolver = SimpleNamespace(resolve_repository_data_final=Mock(return_value=source))
        rechecked = SimpleNamespace(source=source, preparation_status="historical_context_prepared", context=object(), is_prepared=True)

        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "LocalDatasetSourceResolver", return_value=resolver),
            patch.object(prototype, "prepare_resolved_source", return_value=rechecked) as prepare,
        ):
            prototype._render_source_check_action("accepted_historical", "", ("accepted_historical", ""))

        self.assertEqual(streamlit.buttons, [("Проверить повторно", {"type": "secondary", "disabled": False})])
        prepare.assert_called_once_with(source, progress_listener=unittest.mock.ANY)

    def test_browser_upload_is_persisted_under_runtime_storage(self) -> None:
        from app.local_file_picker import persist_uploaded_file

        with TemporaryDirectory() as directory:
            result = Path(
                persist_uploaded_file(
                    "client_dataset.csv",
                    b"target,feature\n0,1\n",
                    (".csv", ".xlsb"),
                    upload_root=Path(directory),
                )
            )

            self.assertTrue(result.is_file())
            self.assertEqual(result.read_bytes(), b"target,feature\n0,1\n")
            self.assertTrue(result.name.endswith("-client_dataset.csv"))

    def test_browser_upload_rejects_an_unsupported_selected_extension(self) -> None:
        from app.local_file_picker import UnsupportedLocalFileExtension, persist_uploaded_file

        with TemporaryDirectory() as directory:
            with self.assertRaises(UnsupportedLocalFileExtension):
                persist_uploaded_file(
                    "client_dataset.txt",
                    b"fixture",
                    (".csv", ".xlsx", ".xlsb"),
                    upload_root=Path(directory),
                )

    def test_upload_history_reuses_only_unchanged_checked_files(self) -> None:
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_bytes(b"a,b\n1,2\n")
            state = {
                prototype._UPLOAD_HISTORY_KEY: [{"name": "sample.csv", "path": str(path), "size": path.stat().st_size}],
            }
            source = SimpleNamespace(source_kind="explicit_local", local_runtime_path=path)
            preparation = SimpleNamespace(source=source, context=None, preparation_status="context_not_prepared")

            prototype._commit_source_preparation(state, ("explicit_local", str(path)), preparation)
            self.assertIs(prototype._cached_source_preparation(state, source), preparation)

            path.write_bytes(b"a,b\n3,4,5\n")
            self.assertIsNone(prototype._cached_source_preparation(state, source))

    def test_history_selection_accepts_only_existing_session_upload(self) -> None:
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_bytes(b"a\n1\n")
            streamlit = SimpleNamespace(session_state={
                prototype._UPLOAD_HISTORY_KEY: [{"name": "sample.csv", "path": str(path), "size": 4}],
            })
            with patch.object(prototype, "st", streamlit):
                prototype._select_uploaded_from_history(str(path))
                self.assertEqual(streamlit.session_state[prototype._SELECTED_LOCAL_FILE_PATH_KEY], str(path))
                self.assertEqual(streamlit.session_state[prototype._LOCAL_FILE_UPLOADER_REVISION_KEY], 1)
                prototype._select_uploaded_from_history(str(Path(directory) / "unknown.csv"))
                self.assertEqual(streamlit.session_state[prototype._SELECTED_LOCAL_FILE_PATH_KEY], str(path))

    def test_upload_is_processed_on_widget_change_and_recorded_once(self) -> None:
        import app.streamlit_app as prototype

        upload = SimpleNamespace(name="data.csv", size=5, getvalue=Mock(return_value=b"a\n1\n"))
        streamlit = SimpleNamespace(session_state={"upload_widget": upload})
        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "persist_uploaded_file", return_value="stored.csv") as persist,
        ):
            prototype._on_local_file_uploaded("upload_widget")

        persist.assert_called_once()
        upload.getvalue.assert_called_once()
        self.assertEqual(streamlit.session_state[prototype._UPLOAD_HISTORY_KEY][0]["name"], "data.csv")
        self.assertFalse(streamlit.session_state[prototype._UPLOAD_HISTORY_VISIBLE_KEY])

    def test_upload_with_history_token_is_saved_for_page_reload(self) -> None:
        import app.streamlit_app as prototype

        upload = SimpleNamespace(name="data.csv", size=4, getvalue=Mock(return_value=b"a\n1\n"))
        state = {"upload_widget": upload, prototype._UPLOAD_HISTORY_TOKEN_KEY: "a" * 48}
        streamlit = SimpleNamespace(session_state=state)
        with (
            patch.object(prototype, "st", streamlit),
            patch.object(prototype, "persist_uploaded_file", return_value="stored.csv"),
            patch.object(prototype, "save_upload_history") as save_history,
        ):
            prototype._on_local_file_uploaded("upload_widget")

        save_history.assert_called_once_with("a" * 48, state[prototype._UPLOAD_HISTORY_KEY])
        self.assertFalse(state[prototype._UPLOAD_HISTORY_VISIBLE_KEY])

    def test_upload_history_appears_only_after_advancing_to_features(self) -> None:
        import app.streamlit_app as prototype

        class SessionState(dict):
            def __getattr__(self, key: str):
                return self[key]

        state = SessionState({
            "dataset_source_preparation": None,
            prototype._SOURCE_KIND_WIDGET_KEY: "explicit_local",
            prototype._SELECTED_LOCAL_FILE_PATH_KEY: "",
            prototype._UPLOAD_HISTORY_KEY: [{"name": "data.csv", "path": "stored.csv", "size": 5}],
            prototype._UPLOAD_HISTORY_VISIBLE_KEY: False,
        })
        streamlit = SimpleNamespace(
            session_state=state,
            subheader=Mock(),
            write=Mock(),
            caption=Mock(),
            selectbox=Mock(return_value="stored.csv"),
            button=Mock(return_value=False),
            file_uploader=Mock(),
        )
        with patch.object(prototype, "st", streamlit):
            prototype._render_local_source_controls()
            streamlit.selectbox.assert_not_called()

            state[prototype._SELECTED_LOCAL_FILE_PATH_KEY] = "stored.csv"
            prototype._reveal_upload_history()
            prototype._render_local_source_controls()
            streamlit.selectbox.assert_called_once()
            self.assertEqual(streamlit.selectbox.call_args.args[0], "Недавно загруженные файлы")
            self.assertIn("История сохраняется", streamlit.selectbox.call_args.kwargs["help"])

    def test_unprepared_source_shows_cached_header_preview_without_ml_context(self) -> None:
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            path = Path(directory) / "new.csv"
            path.write_text("INN,DefMark,A1_norm\n1,0,0.5\n", encoding="utf-8")
            streamlit = SimpleNamespace(
                session_state={}, subheader=Mock(), caption=Mock(), dataframe=Mock(), warning=Mock(),
            )
            source = SimpleNamespace(local_runtime_path=path)
            with (
                patch.object(prototype, "st", streamlit),
                patch.object(prototype.TabularReader, "preview_columns", return_value=("INN", "DefMark", "A1_norm")) as preview,
            ):
                prototype._render_source_columns(source)
                prototype._render_source_columns(source)

                path.write_text("INN,DefMark,A1_norm,B2_norm\n1,0,0.5,0.7\n", encoding="utf-8")
                prototype._render_source_columns(source)

            self.assertEqual(preview.call_count, 2)
            self.assertEqual(streamlit.dataframe.call_count, 3)
            self.assertEqual(len(streamlit.dataframe.call_args.args[0]), 3)

    def test_local_source_resolver_allows_csv_xlsx_and_xlsb(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for file_name, expected_format in (("data.csv", "csv"), ("data.xlsx", "xlsx"), ("data.xlsb", "xlsb")):
                path = root / file_name
                path.write_bytes(b"fixture")
                with self.subTest(file_name=file_name):
                    self.assertEqual(LocalDatasetSourceResolver().resolve_explicit_local_path(path).physical_format, expected_format)
            for file_name in ("data.parquet", "data.txt"):
                path = root / file_name
                path.write_bytes(b"fixture")
                with self.subTest(file_name=file_name):
                    with self.assertRaisesRegex(ValueError, "Неподдерживаемое расширение"):
                        LocalDatasetSourceResolver().resolve_explicit_local_path(path)

    def test_supported_protocol_is_defined_once_in_composition(self) -> None:
        protocol = bootstrap.SUPPORTED_PROTOCOL
        self.assertIsNone(bootstrap.validate_supported_protocol({
            "protocol_id": protocol.protocol_id,
            "protocol_version": protocol.protocol_version,
            "evaluation_level": protocol.evaluation_level,
            "folds": protocol.minimum_folds,
        }))


if __name__ == "__main__":
    unittest.main()
