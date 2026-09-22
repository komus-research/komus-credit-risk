"""Single-page Streamlit prototype over the accepted Pipeline V1 services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from app.bootstrap import DatasetSourcePreparation, LocalDatasetSourceResolver, PreparedDatasetContext, create_runtime, prepare_resolved_source, validate_supported_protocol
from app.feature_descriptions import FeatureDescriptionStore, MISSING_DESCRIPTION, historical_descriptions, parse_description_file
from app.feature_display import group_feature_ids_by_family
from app.local_file_picker import UnsupportedLocalFileExtension, persist_uploaded_file
from app.shap_evidence import load_stage2_evidence, model_display_name, stage2_matches_current_run
from app.session_state import (
    apply_feature_widget_selection,
    apply_group_widget_selection,
    can_run,
    initialize,
    navigate_to_step,
    run_request_from_snapshot,
    save_artifact,
    save_plan,
    set_dataset_source_preparation,
    set_experiment_inputs,
    set_selected_model_id,
    synchronize_feature_widgets,
)
from app.upload_history import UploadHistoryError, history_token, load_upload_history, save_upload_history
from komus_risk.application.model_inference import predict_uploaded_file
from komus_risk.data import DatasetInspector, TabularReadError, TabularReader
from komus_risk.hashing import stable_hash
from komus_risk.planning import PlanningRequestMetadata
from komus_risk.preparation import ConfirmedDatasetRoles, DatasetPreparationAnalyzer, materialize_confirmed_dataset
from komus_risk.preparation.evaluation import prepare_oof_evaluation, suspected_temporal_columns


_DATA_PROGRESS_LABELS = {
    "checking_file_identity": "Проверка файла и его идентичности",
    "checking_working_split": "Проверка рабочей выборки",
    "loading_dataset": "Загрузка датасета",
    "validating_target_split": "Проверка соответствия цели и выборки",
    "preparing_context": "Подготовка рабочего контекста",
}
_EXPERIMENT_PROGRESS_LABELS = {
    "run_started": "Подготовка эксперимента",
    "fold_started": "Проверка на части данных",
    "fold_completed": "Проверка части данных завершена",
    "aggregate_metrics_started": "Расчёт итоговых метрик",
    "persistence_started": "Сохранение результата",
    "completed": "Эксперимент завершён",
}
_SECONDARY_FEATURE_GROUP_LABELS = {
    "protected_columns": "Служебные поля",
    "restricted_signals": "Недоступные для модели признаки",
}
_SOURCE_CONTROL_LOCATOR_KEY = "prototype_source_control_locator"
_SOURCE_KIND_WIDGET_KEY = "prototype_source_kind"
_SELECTED_LOCAL_FILE_PATH_KEY = "prototype_selected_local_file_path"
_LOCAL_FILE_UPLOADER_REVISION_KEY = "prototype_local_file_uploader_revision"
_UPLOAD_HISTORY_KEY = "prototype_upload_history"
_UPLOAD_HISTORY_VISIBLE_KEY = "prototype_upload_history_visible"
_UPLOAD_HISTORY_TOKEN_KEY = "prototype_upload_history_token"
_UPLOAD_HISTORY_LOADED_KEY = "prototype_upload_history_loaded"
_UPLOAD_HISTORY_ERROR_KEY = "prototype_upload_history_error"
_PREPARATION_CACHE_KEY = "prototype_preparation_cache"
_SOURCE_COLUMNS_CACHE_KEY = "prototype_source_columns_cache"
_NEW_DATASET_ANALYSIS_KEY = "prototype_new_dataset_analysis"
_NEW_DATASET_CONFIRMATION_KEY = "prototype_new_dataset_confirmation"
_SOURCE_ERROR_KEY = "prototype_source_error"
_SOURCE_RECHECK_INVALID_KEY = "prototype_source_recheck_invalid"
_PREDICTION_RESULT_KEY = "prototype_prediction_result"
_SUPPORTED_SOURCE_EXTENSIONS = (".csv", ".xlsx", ".xlsb")
_STEP_NAVIGATION_LABELS = ("Данные", "Признаки", "Модель", "Эксперимент", "Результат", "SHAP", "Прогноз")
_STEP_NAVIGATION_CONTAINER_KEY = "step-navigator"


@st.cache_resource
def _runtime():
    return create_runtime()


def main() -> None:
    st.set_page_config(page_title="KOMUS · Prototype V1", layout="wide")
    initialize(st.session_state)
    _restore_upload_history(st.session_state)
    runtime = _runtime()
    if not hasattr(runtime, "model_store") or not hasattr(runtime, "model_training_service"):
        st.error("Сервер Streamlit использует старый runtime. Перезапустите Streamlit, чтобы открыть версии моделей.")
        return
    step = st.session_state.current_step
    st.title("KOMUS · Experiment Prototype V1")
    _render_step_navigation()

    if step == 0:
        _render_data_step(runtime)
    elif step == 1:
        _render_features_step(runtime)
    elif step == 2:
        _render_models_step(runtime)
    elif step == 3:
        _render_experiment_step(runtime)
    elif step == 4:
        _render_result_step(runtime)
    elif step == 5:
        _render_shap_step()
    else:
        _render_prediction_step(runtime)


def _progress_description(event: Any, labels: Mapping[str, str]) -> str:
    """Turn only emitted runtime stages into user-facing status text."""
    stage = event if isinstance(event, str) else getattr(event, "stage", "")
    description = labels.get(stage, "Выполняется подтверждённый этап")
    fold_number = getattr(event, "fold_number", None)
    folds_total = getattr(event, "folds_total", None)
    if fold_number is not None and folds_total is not None:
        return f"{description}: {fold_number} из {folds_total}"
    return description


def _run_with_progress(
    labels: Mapping[str, str], operation, *, initial_label: str = "Подготовка операции",
    completion_label: str = "Операция успешно завершена",
):
    """Render observed stages; completion is shown only after the operation returns."""
    status = st.status(initial_label, expanded=True)

    def report(event: Any) -> None:
        description = _progress_description(event, labels)
        stage = event if isinstance(event, str) else getattr(event, "stage", "")
        status.write(description)
        if stage == "completed":
            status.update(label=description, state="complete", expanded=False)
        else:
            status.update(label=description, state="running")

    try:
        result = operation(report)
    except Exception:
        status.update(label="Операция не завершена", state="error", expanded=True)
        raise
    status.update(label=completion_label, state="complete", expanded=False)
    return result


def _render_data_step(runtime) -> None:
    st.header("1. Данные")
    st.write("Выберите данные, с которыми будет работать эксперимент.")
    _restore_source_controls(st.session_state)
    source_kind = st.radio(
        "Какие данные использовать?",
        ("accepted_historical", "explicit_local"),
        format_func=lambda value: {
            "accepted_historical": "Исторический набор данных",
            "explicit_local": "Другой локальный файл",
        }[value],
        horizontal=True,
        key=_SOURCE_KIND_WIDGET_KEY,
    )
    explicit_local_path = ""
    if source_kind == "explicit_local":
        explicit_local_path = _render_local_source_controls()
    draft_locator = _source_control_locator(source_kind, explicit_local_path)
    _synchronize_source_selection(st.session_state, draft_locator)
    _render_source_check_action(source_kind, explicit_local_path, draft_locator)
    preparation = st.session_state.dataset_source_preparation
    is_display_ready = bool(preparation and preparation.is_prepared and not st.session_state.get(_SOURCE_RECHECK_INVALID_KEY))
    if preparation is None or (preparation.is_prepared and not is_display_ready):
        _render_unchecked_source(source_kind, explicit_local_path)
    elif not preparation.is_prepared:
        source = preparation.source
        st.success("Файл доступен")
        st.subheader(source.file_name)
        _render_source_columns(source)
        _render_new_dataset_confirmation(source, runtime)
        st.write(
            "Этот набор данных ещё не подготовлен для эксперимента. "
            "Для перехода к признакам подтвердите роли столбцов и протокол оценки."
        )
    else:
        _render_prepared_source(preparation, source_kind)

    ready_to_continue = is_display_ready
    if not ready_to_continue and (preparation is None or st.session_state.get(_SOURCE_RECHECK_INVALID_KEY)):
        st.caption("Сначала проверьте источник данных.")
    _navigation_button(
        st,
        "Продолжить к признакам →",
        1,
        primary=True,
        disabled=not ready_to_continue,
        on_navigate=_reveal_upload_history,
    )
    _render_saved_model_catalog(runtime)


def _render_saved_model_catalog(runtime) -> None:
    """Show persisted model versions even after Streamlit creates a new session."""
    st.subheader("Сохранённые версии моделей")
    try:
        versions, invalid = runtime.model_store.catalog()
    except OSError:
        st.warning("Не удалось прочитать локальный каталог моделей.")
        return
    if invalid:
        st.warning(f"Повреждённых или неполных записей каталога: {len(invalid)}. Они не будут загружены.")
    if not versions:
        st.caption("Пока нет итоговых обученных моделей. OOF-эксперимент сам по себе модель не сохраняет.")
        return
    selection = st.dataframe(
        [
            {
                "Версия": item.version_id[:12], "Дата": _format_saved_model_date(item.created_at),
                "Датасет": item.dataset_name, "Алгоритм": item.model_id,
                "Признаков": item.feature_count, "OOF-результат": item.experiment_artifact_id[:12],
            }
            for item in versions
        ],
        hide_index=True, use_container_width=True,
        on_select="rerun", selection_mode="single-row", key="prototype_saved_model_catalog",
    )
    st.caption("Нажмите на строку модели, чтобы открыть её признаки и загрузить файл для прогноза.")
    selected_rows = selection.selection.rows
    if selected_rows:
        st.session_state.selected_model_version_id = versions[selected_rows[0]].version_id
        st.session_state[_PREDICTION_RESULT_KEY] = None
        navigate_to_step(st.session_state, 6)
        st.rerun()


def _format_saved_model_date(value: str) -> str:
    """Display UTC model timestamps as a short Moscow-local calendar date."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return "—"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%y")


def _render_local_source_controls() -> str:
    """Render local-source selection without showing a host filesystem path."""
    st.subheader("Другой локальный файл")
    st.write("Добавьте файл через Проводник. Разрешены только форматы CSV, XLSX и XLSB.")
    st.caption("Новый файл не становится автоматически готовым к эксперименту.")
    history_error = st.session_state.get(_UPLOAD_HISTORY_ERROR_KEY)
    if history_error:
        st.warning(history_error)
    history = st.session_state.get(_UPLOAD_HISTORY_KEY, ())
    if history and st.session_state.get(_UPLOAD_HISTORY_VISIBLE_KEY, False):
        labels = {
            item["path"]: f'{item["name"]} · {item["size"] / 1024 / 1024:.1f} МБ'
            for item in history
        }
        selected_history_path = st.selectbox(
            "Недавно загруженные файлы",
            tuple(labels),
            format_func=labels.__getitem__,
            key="prototype_upload_history_selection",
            help=(
                "История сохраняется для этого адреса страницы. Не передавайте ссылку другим людям; "
                "после выбора файла проверьте источник заново."
            ),
        )
        st.button(
            "Использовать файл из истории",
            on_click=_select_uploaded_from_history,
            args=(selected_history_path,),
        )
    uploader_revision = int(st.session_state.get(_LOCAL_FILE_UPLOADER_REVISION_KEY, 0))
    uploader_key = f"prototype_local_file_uploader_{uploader_revision}"
    st.file_uploader(
        "Файл данных",
        type=[extension.removeprefix(".") for extension in _SUPPORTED_SOURCE_EXTENSIONS],
        accept_multiple_files=False,
        key=uploader_key,
        on_change=_on_local_file_uploaded,
        args=(uploader_key,),
        help="Выберите один файл CSV, XLSX или XLSB с вашего компьютера.",
    )

    selected_path = st.session_state.get(_SELECTED_LOCAL_FILE_PATH_KEY, "")
    effective_path = selected_path.strip()
    preparation = st.session_state.dataset_source_preparation
    selected_is_checked = bool(
        preparation
        and getattr(preparation.source, "source_kind", None) == "explicit_local"
        and _source_control_locator("explicit_local", effective_path)[1]
        == str(preparation.source.local_runtime_path)
    )
    if effective_path and not selected_is_checked:
        st.subheader("Выбран файл")
        st.write(Path(effective_path).name)
        st.write("**Статус:** файл выбран, но ещё не проверен")
        st.button("Выбрать другой файл", on_click=_clear_local_file_selection)
    return effective_path


def _on_local_file_uploaded(widget_key: str) -> None:
    """Persist a browser upload once, when its widget value actually changes."""
    uploaded_file = st.session_state.get(widget_key)
    if uploaded_file is None:
        return
    try:
        selected = persist_uploaded_file(
            uploaded_file.name, uploaded_file.getvalue(), _SUPPORTED_SOURCE_EXTENSIONS,
        )
    except UnsupportedLocalFileExtension:
        st.session_state[_SOURCE_ERROR_KEY] = (
            "Формат файла не поддерживается", "Выберите файл с расширением .csv, .xlsx или .xlsb.",
        )
        return
    st.session_state[_SELECTED_LOCAL_FILE_PATH_KEY] = selected
    st.session_state[_UPLOAD_HISTORY_VISIBLE_KEY] = False
    st.session_state.pop(_SOURCE_ERROR_KEY, None)
    history = [item for item in st.session_state.get(_UPLOAD_HISTORY_KEY, ()) if item["path"] != selected]
    recent = [
        {"name": Path(uploaded_file.name).name, "path": selected, "size": uploaded_file.size},
        *history,
    ][:10]
    st.session_state[_UPLOAD_HISTORY_KEY] = recent
    token = st.session_state.get(_UPLOAD_HISTORY_TOKEN_KEY)
    if token:
        try:
            save_upload_history(token, recent)
        except UploadHistoryError as error:
            st.session_state[_UPLOAD_HISTORY_ERROR_KEY] = str(error)
        else:
            st.session_state.pop(_UPLOAD_HISTORY_ERROR_KEY, None)
    cached = st.session_state.get(_PREPARATION_CACHE_KEY, {})
    st.session_state[_PREPARATION_CACHE_KEY] = {
        item["path"]: cached[item["path"]] for item in recent if item["path"] in cached
    }


def _select_uploaded_from_history(path: str) -> None:
    """Select only a path recorded by this browser session."""
    if path not in {item["path"] for item in st.session_state.get(_UPLOAD_HISTORY_KEY, ())}:
        return
    if not Path(path).is_file():
        st.session_state[_SOURCE_ERROR_KEY] = ("Файл не найден", "Загрузите этот файл ещё раз.")
        return
    st.session_state[_SELECTED_LOCAL_FILE_PATH_KEY] = path
    st.session_state[_LOCAL_FILE_UPLOADER_REVISION_KEY] = (
        int(st.session_state.get(_LOCAL_FILE_UPLOADER_REVISION_KEY, 0)) + 1
    )
    st.session_state.pop(_SOURCE_ERROR_KEY, None)


def _reveal_upload_history() -> None:
    """Expose history only after the selected upload reaches the next wizard step."""
    if (
        st.session_state.get(_SOURCE_KIND_WIDGET_KEY) == "explicit_local"
        and st.session_state.get(_SELECTED_LOCAL_FILE_PATH_KEY)
    ):
        st.session_state[_UPLOAD_HISTORY_VISIBLE_KEY] = True


def _restore_upload_history(state: MutableMapping[str, Any]) -> None:
    """Restore browser-scoped history after a full page reload, not model state."""
    if state.get(_UPLOAD_HISTORY_LOADED_KEY):
        return
    query_params = getattr(st, "query_params", None)
    if query_params is None:
        return
    token = history_token(query_params)
    state[_UPLOAD_HISTORY_TOKEN_KEY] = token
    current_history = list(state.get(_UPLOAD_HISTORY_KEY, ()))
    try:
        saved_history = load_upload_history(token)
        if current_history:
            seen = set()
            merged = []
            for item in [*current_history, *saved_history]:
                path = item.get("path") if isinstance(item, dict) else None
                if isinstance(path, str) and path not in seen:
                    merged.append(item)
                    seen.add(path)
            save_upload_history(token, merged[:10])
            history = load_upload_history(token)
        else:
            history = saved_history
    except UploadHistoryError as error:
        state[_UPLOAD_HISTORY_ERROR_KEY] = str(error)
        history = current_history
    state[_UPLOAD_HISTORY_KEY] = history
    if not current_history:
        state[_UPLOAD_HISTORY_VISIBLE_KEY] = bool(history)
    state[_UPLOAD_HISTORY_LOADED_KEY] = True


def _clear_local_file_selection() -> None:
    """Reset local-file controls before Streamlit instantiates their widgets."""
    st.session_state.pop(_SELECTED_LOCAL_FILE_PATH_KEY, None)
    st.session_state[_LOCAL_FILE_UPLOADER_REVISION_KEY] = (
        int(st.session_state.get(_LOCAL_FILE_UPLOADER_REVISION_KEY, 0)) + 1
    )


def _render_source_check_action(
    source_kind: str, explicit_local_path: str, draft_locator: tuple[str, str],
) -> None:
    """Confirm a draft source before it can replace the active dataset state."""
    preparation = st.session_state.dataset_source_preparation
    has_selected_local_file = bool(explicit_local_path.strip())
    already_checked = preparation is not None and draft_locator == st.session_state.get(_SOURCE_CONTROL_LOCATOR_KEY)
    label = "Проверить повторно" if already_checked else "Проверить источник"
    button_type = "secondary" if already_checked else "primary"
    if not st.button(
        label,
        type=button_type,
        disabled=source_kind == "explicit_local" and not has_selected_local_file,
    ):
        _render_source_error()
        return
    st.session_state[_SOURCE_RECHECK_INVALID_KEY] = bool(preparation and preparation.is_prepared)
    st.session_state.pop(_SOURCE_ERROR_KEY, None)
    try:
        resolver = LocalDatasetSourceResolver()
        source = (
            resolver.resolve_repository_data_final()
            if source_kind == "accepted_historical"
            else resolver.resolve_explicit_local_path(explicit_local_path)
        )
        cached = None if already_checked else _cached_source_preparation(st.session_state, source)
        if cached is not None:
            preparation = cached
            st.success("Использован результат предыдущей проверки неизменённого файла.")
        else:
            preparation = _run_with_progress(
                _DATA_PROGRESS_LABELS,
                lambda listener: prepare_resolved_source(source, progress_listener=listener),
                initial_label="Проверяем источник…",
                completion_label="Проверка источника завершена",
            )
        _commit_source_preparation(st.session_state, draft_locator, preparation)
        st.session_state[_SOURCE_RECHECK_INVALID_KEY] = False
    except FileNotFoundError:
        st.session_state[_SOURCE_ERROR_KEY] = (
            "Файл не найден",
            "Возможно, файл был перемещён или удалён. Выберите его заново или укажите другой файл.",
        )
    except ValueError as error:
        if "Неподдерживаемое расширение" in str(error):
            st.session_state[_SOURCE_ERROR_KEY] = (
                "Формат файла не поддерживается",
                f"Выберите файл поддерживаемого формата: {', '.join(_SUPPORTED_SOURCE_EXTENSIONS)}.",
            )
        else:
            st.session_state[_SOURCE_ERROR_KEY] = (
                "Не удалось проверить источник",
                "Проверьте выбранный файл и повторите попытку.",
            )
    except OSError:
        st.session_state[_SOURCE_ERROR_KEY] = (
            "Не удалось проверить источник",
            "Проверьте выбранный файл и повторите попытку.",
        )
    _render_source_error()


def _commit_source_preparation(
    state: MutableMapping[str, Any], locator: tuple[str, str], preparation: Any,
) -> None:
    """Commit only a successfully checked source; draft control changes remain harmless."""
    set_dataset_source_preparation(state, preparation)
    state[_SOURCE_CONTROL_LOCATOR_KEY] = locator
    source = preparation.source
    if source.source_kind == "explicit_local" and str(source.local_runtime_path) in {
        item["path"] for item in state.get(_UPLOAD_HISTORY_KEY, ())
    }:
        signature = _source_file_signature(source.local_runtime_path)
        if signature is not None:
            cache = dict(state.get(_PREPARATION_CACHE_KEY, {}))
            cache.pop(str(source.local_runtime_path), None)
            cache[str(source.local_runtime_path)] = (signature, preparation)
            state[_PREPARATION_CACHE_KEY] = dict(list(cache.items())[-2:])


def _source_file_signature(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_size, info.st_mtime_ns


def _cached_source_preparation(state: Mapping[str, Any], source: Any) -> Any | None:
    if source.source_kind != "explicit_local":
        return None
    cached = state.get(_PREPARATION_CACHE_KEY, {}).get(str(source.local_runtime_path))
    if cached is None or cached[0] != _source_file_signature(source.local_runtime_path):
        return None
    return cached[1]


def _render_source_columns(source: Any) -> None:
    """Show factual headers only; arbitrary sources are not made run-ready."""
    st.subheader("Найденные столбцы")
    signature = _source_file_signature(source.local_runtime_path)
    if signature is None:
        st.warning("Файл больше недоступен. Загрузите его снова.")
        return
    cache_key = (str(source.local_runtime_path), *signature)
    cached = st.session_state.get(_SOURCE_COLUMNS_CACHE_KEY)
    if cached is not None and cached[0] == cache_key:
        columns = cached[1]
    else:
        try:
            columns = TabularReader().preview_columns(source.local_runtime_path)
        except TabularReadError as error:
            st.warning(f"Не удалось прочитать заголовки: {error}")
            return
        st.session_state[_SOURCE_COLUMNS_CACHE_KEY] = (cache_key, columns)
    st.caption(f"Найдено столбцов: {len(columns)}. Это только структура файла; роли и признаки ещё не подтверждены.")
    st.dataframe(
        [{"№": index, "Название столбца": name} for index, name in enumerate(columns, start=1)],
        hide_index=True,
        use_container_width=True,
    )


def _render_new_dataset_confirmation(source: Any, runtime: Any = None) -> None:
    """Confirm new-file roles without activating the historical experiment path."""
    signature = _source_file_signature(source.local_runtime_path)
    if signature is None:
        return
    cache_key = (str(source.local_runtime_path), *signature)
    cached = st.session_state.get(_NEW_DATASET_ANALYSIS_KEY)
    if cached is None or cached[0] != cache_key:
        cached = None
    st.subheader("Подготовка нового набора данных")
    st.caption("Факты о файле → предложения системы → ваше подтверждение. Анализ прочитает всю таблицу.")
    if st.button("Изучить данные и предложить роли", type="secondary"):
        try:
            snapshot, inspection, proposal = _run_with_progress(
                {"reading": "Чтение таблицы", "inspecting": "Анализ столбцов", "proposing": "Подготовка предложений"},
                lambda report: _analyze_new_dataset_with_progress(source, report),
                initial_label="Изучаем новый набор данных…",
                completion_label="Анализ данных завершён",
            )
        except (TabularReadError, ValueError, OSError) as error:
            st.error(f"Не удалось изучить файл: {error}")
            return
        st.session_state[_NEW_DATASET_ANALYSIS_KEY] = (cache_key, snapshot, inspection, proposal)
        st.session_state.pop(_NEW_DATASET_CONFIRMATION_KEY, None)
        cached = st.session_state[_NEW_DATASET_ANALYSIS_KEY]
    if cached is None:
        return
    _, snapshot, inspection, proposal = cached
    st.write(f"Прочитано строк: {inspection.row_count:,}; столбцов: {inspection.column_count}.")
    with st.expander("Факты о столбцах", expanded=False):
        st.dataframe(
            [{"Столбец": item.column_name, "Тип": item.physical_dtype,
              "Пропусков": item.missing_count, "Уникальных значений": item.unique_non_null_count}
             for item in inspection.columns],
            hide_index=True, use_container_width=True,
        )
    st.caption("Предложения системы не подтверждаются автоматически.")
    suggested_target = proposal.target_candidates[0].column_name if proposal.target_candidates else None
    suggested_identifier = proposal.identifier_candidates[0].column_name if proposal.identifier_candidates else None
    if suggested_target:
        st.write(f"Предложенная цель: {suggested_target}")
    if suggested_identifier:
        st.write(f"Предложенный идентификатор: {suggested_identifier}")
    if proposal.warnings:
        with st.expander(f"Предупреждения анализа: {len(proposal.warnings)}", expanded=False):
            for warning in proposal.warnings:
                st.write(f"{warning.column_name or 'Набор данных'}: {'; '.join(warning.reasons_ru)}")

    names = tuple(item.column_name for item in inspection.columns)
    target = st.selectbox("Целевая колонка", names, index=names.index(suggested_target) if suggested_target in names else 0)
    identifier_options = tuple(name for name in names if name != target)
    identifier = st.selectbox(
        "Колонка идентификатора (например, ИНН)", identifier_options,
        index=identifier_options.index(suggested_identifier) if suggested_identifier in identifier_options else 0,
    ) if identifier_options else None
    values = tuple(_native_value(value) for value in snapshot.dataframe[target].dropna().unique())
    if len(values) != 2:
        st.warning("Выберите бинарную цель: нужны ровно два непустых значения.")
        return
    suggested_positive = next((item.value for item in proposal.positive_class_candidates if item.target_column == target), None)
    if suggested_positive not in values:
        suggested_positive = 1 if 1 in values else values[-1]
    positive = st.selectbox(
        "Какое значение означает дефолт / событие?", values,
        index=values.index(suggested_positive), format_func=str,
    )
    proxy_columns = {
        warning.column_name for warning in proposal.warnings
        if warning.code in {"potential_target_proxy", "potential_deterministic_target_proxy"}
    }
    eligible = tuple(
        item.column_name for item in inspection.columns
        if item.column_name not in {target, identifier}
        and item.column_name not in proxy_columns
        and item.inferred_logical_type in {"numeric", "boolean"}
        and not item.missing_count and not item.is_constant
    )
    st.caption("Цель, идентификатор, нечисловые и подозрительные proxy-колонки не предлагаются для модели.")
    allowed = st.multiselect("Разрешить как признаки", eligible, default=eligible)
    acknowledged = st.checkbox("Подтверждаю роли столбцов и понимаю, что это ещё не запуск модели")
    if st.button("Подтвердить подготовку", disabled=not (identifier and allowed and acknowledged)):
        roles = ConfirmedDatasetRoles(snapshot.fingerprint, target, positive, identifier, tuple(allowed))
        if _source_file_signature(source.local_runtime_path) != signature:
            st.error("Файл изменился после анализа. Запустите анализ повторно.")
            return
        try:
            materialized = materialize_confirmed_dataset(snapshot, inspection, proposal, roles)
        except ValueError as error:
            st.error(f"Не удалось подтвердить датасет: {error}")
        else:
            st.session_state[_NEW_DATASET_CONFIRMATION_KEY] = (cache_key, materialized)
    confirmed = st.session_state.get(_NEW_DATASET_CONFIRMATION_KEY)
    if confirmed is not None and confirmed[0] == cache_key:
        current = ConfirmedDatasetRoles(snapshot.fingerprint, target, positive, identifier, tuple(allowed))
        if confirmed[1].roles == current:
            st.success("Роли подтверждены; паспорт, реестр признаков и популяция этого датасета созданы.")
            if runtime is not None:
                prepared = confirmed[1]
                _render_description_upload(
                    runtime, prepared.loaded_dataset.contract.dataset_fingerprint,
                    tuple(spec.column_name for spec in prepared.feature_registry.resolve(allowed)),
                    "new_dataset",
                )
            _render_new_dataset_oof_protocol(source, cache_key, confirmed[1])


def _render_new_dataset_oof_protocol(source: Any, cache_key: tuple[Any, ...], materialized: Any) -> None:
    """Activate the existing OOF wizard only after an explicit non-temporal decision."""
    st.subheader("Протокол оценки нового датасета")
    temporal = suspected_temporal_columns(materialized)
    if temporal:
        st.warning(
            "Возможная временная структура: " + ", ".join(temporal)
            + ". Случайная OOF-проверка здесь заблокирована; нужен временной протокол."
        )
        return
    st.info(
        "Доступна исследовательская стратифицированная OOF-оценка по всем строкам нового файла. "
        "Независимая финальная выборка не выделена; итоговый Gini нельзя считать проверкой на будущих периодах."
    )
    acknowledged = st.checkbox(
        "Подтверждаю: одна строка соответствует одному ИНН, временной последовательности наблюдений нет",
        key=f"prototype_non_temporal_{materialized.loaded_dataset.contract.dataset_fingerprint[:16]}",
    )
    if not st.button("Разрешить OOF-оценку", disabled=not acknowledged):
        return
    if _source_file_signature(source.local_runtime_path) != cache_key[1:]:
        st.error("Файл изменился после анализа. Проверьте и подтвердите его повторно.")
        return
    try:
        ready = prepare_oof_evaluation(materialized, confirm_no_time_axis=acknowledged)
    except (OSError, ValueError) as error:
        st.error(f"Нельзя утвердить протокол: {error}")
        return
    context = PreparedDatasetContext(
        context_id=f"user_oof_{ready.loaded_dataset.contract.dataset_fingerprint[:16]}",
        display_name=f"{source.file_name} — исследовательская OOF-популяция",
        loaded_dataset=ready.loaded_dataset,
        feature_registry=ready.feature_registry,
        population=ready.population,
    )
    preparation = DatasetSourcePreparation(source, "user_oof_context_prepared", context)
    _commit_source_preparation(st.session_state, ("explicit_local", str(source.local_runtime_path)), preparation)
    st.rerun()


def _analyze_new_dataset_with_progress(source: Any, report: Callable[[str], None]) -> tuple[Any, Any, Any]:
    report("reading")
    snapshot = TabularReader().read(source.local_runtime_path)
    report("inspecting")
    inspection = DatasetInspector().inspect(snapshot)
    report("proposing")
    proposal = DatasetPreparationAnalyzer().analyze(inspection)
    return snapshot, inspection, proposal


def _native_value(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _render_source_error() -> None:
    error = st.session_state.get(_SOURCE_ERROR_KEY)
    if error:
        title, detail = error
        st.error(title)
        st.write(detail)


def _render_unchecked_source(source_kind: str, explicit_local_path: str) -> None:
    if source_kind == "accepted_historical":
        st.subheader("Исторический набор данных")
        st.write("Data_final.xlsb")
        st.caption("Подготовленный исторический набор для воспроизводимых экспериментов.")
        st.write("**Статус:** требуется проверка")
    elif not explicit_local_path:
        st.info("Выберите файл, затем проверьте источник.")


def _render_prepared_source(preparation: Any, source_kind: str) -> None:
    """Show the exact prepared population without conflating new and historical data."""
    context = preparation.context
    if context is None:
        return
    st.success("Данные готовы к эксперименту")
    if preparation.preparation_status == "user_oof_context_prepared":
        passport = context.loaded_dataset.contract
        st.subheader(context.display_name)
        st.write(f"**Строк для OOF-оценки:** {len(context.population.row_positions):,}")
        st.write(f"**Цель:** {passport.target_column}; **идентификатор:** {passport.identifier_column}")
        st.warning("У нового файла нет закрытой финальной выборки. OOF-метрики исследовательские; модель для новых ИНН ещё не сохранена.")
        return
    if source_kind == "explicit_local":
        st.write("Выбранный файл распознан как исторический Data_final.")
    st.subheader("Исторический Data_final — рабочая популяция")
    passport = context.loaded_dataset.contract
    columns = st.columns(3)
    columns[0].metric("Организации / строки", f"{passport.row_count:,}")
    columns[1].metric("Рабочая выборка", f"{len(context.population.row_positions):,}")
    columns[2].metric("Защищённая контрольная выборка", f"{passport.row_count - len(context.population.row_positions):,}")
    st.write("**Цель:** признак дефолта организации")
    st.info("Контрольная выборка не используется при выборе и настройке модели; она сохраняется для финальной проверки.")
    with st.expander("Технические сведения", expanded=False):
        st.json({
            "source": {
                "source_kind": preparation.source.source_kind,
                "display_name": preparation.source.display_name,
                "local_runtime_path": str(preparation.source.local_runtime_path),
                "file_name": preparation.source.file_name,
                "physical_format": preparation.source.physical_format,
                "file_size": preparation.source.file_size,
                "preparation_status": preparation.preparation_status,
            },
            "dataset_name": passport.dataset_name,
            "dataset_version": passport.dataset_version,
            "source_type": passport.source_type,
            "dataset_fingerprint": passport.dataset_fingerprint,
            "dataset_id": passport.dataset_id,
            "target_column": passport.target_column,
            "identifier_column": passport.identifier_column,
            "validation_status": passport.validation_status,
            "final_test_locked": passport.final_test_locked,
        })


def _source_control_locator(source_kind: str, explicit_local_path: str) -> tuple[str, str]:
    """Return a stable locator for source controls without resolving a dataset."""
    if source_kind == "accepted_historical":
        return source_kind, ""
    path = explicit_local_path.strip()
    return source_kind, str(Path(path).expanduser().resolve(strict=False)) if path else ""


def _restore_source_controls(state: MutableMapping[str, Any]) -> None:
    """Restore source widgets from their durable locator after leaving the Data step.

    Streamlit can discard widget state for controls that were not rendered on
    later wizard steps.  The locator is application-owned state and therefore
    remains the authoritative UI selection until the user changes it.
    """
    locator = state.get(_SOURCE_CONTROL_LOCATOR_KEY)
    if not isinstance(locator, tuple) or len(locator) != 2:
        return
    source_kind, local_path = locator
    if source_kind not in {"accepted_historical", "explicit_local"}:
        return
    restoring_after_navigation = _SOURCE_KIND_WIDGET_KEY not in state
    if restoring_after_navigation:
        state[_SOURCE_KIND_WIDGET_KEY] = source_kind
    if source_kind == "explicit_local" and local_path and restoring_after_navigation:
        state[_SELECTED_LOCAL_FILE_PATH_KEY] = local_path


def _synchronize_source_selection(state: MutableMapping[str, Any], locator: tuple[str, str]) -> None:
    """Invalidate a prepared context only when source controls actually change."""
    previous = state.get(_SOURCE_CONTROL_LOCATOR_KEY)
    if previous is None:
        state[_SOURCE_CONTROL_LOCATOR_KEY] = locator
        return
    if previous == locator:
        return
    set_dataset_source_preparation(state, None)
    state.pop(_NEW_DATASET_ANALYSIS_KEY, None)
    state.pop(_NEW_DATASET_CONFIRMATION_KEY, None)
    state.pop(_SOURCE_ERROR_KEY, None)
    state.pop(_SOURCE_RECHECK_INVALID_KEY, None)
    state[_SOURCE_CONTROL_LOCATOR_KEY] = locator


def _render_features_step(runtime) -> None:
    context = _context_or_previous_step()
    if context is None:
        return
    st.header("2. Признаки")
    views = runtime.planning_service.list_features(context.feature_registry)
    groups = runtime.planning_service.list_feature_groups(context.feature_registry)
    views_by_group = {group.group_id: [view for view in views if view.group_id == group.group_id] for group in groups}
    revision = st.session_state.context_revision
    for group in groups:
        group_views = views_by_group[group.group_id]
        selectable_views = [view for view in group_views if view.selectable]
        nonselectable_views = [view for view in group_views if not view.selectable]
        if selectable_views:
            st.subheader(group.name_ru)
            st.caption(group.description_ru)
            _render_selectable_feature_families(group.group_id, selectable_views, revision)
        if nonselectable_views:
            _render_nonselectable_feature_group(
                _SECONDARY_FEATURE_GROUP_LABELS.get(group.group_id, group.name_ru),
                group.description_ru,
                nonselectable_views,
                revision,
            )
    if not st.session_state.selected_feature_ids:
        st.warning("Выберите хотя бы один разрешённый признак.")
    navigation = st.columns(2)
    _navigation_button(navigation[0], "← Назад", 0)
    _navigation_button(
        navigation[1],
        "Далее: модель →",
        2,
        primary=True,
        disabled=not st.session_state.selected_feature_ids,
    )


def _render_selectable_feature_families(group_id: str, selectable_views: list[Any], revision: int) -> None:
    """Render display-only families without changing registry or selection order."""
    views_by_id = {view.feature_id: view for view in selectable_views}
    selectable_ids = tuple(views_by_id)
    feature_widget_keys = {
        feature_id: f"prototype_{revision}_feature_{feature_id}"
        for feature_id in selectable_ids
    }
    global_widget_key = f"prototype_{revision}_all_{group_id}"
    synchronize_feature_widgets(
        st.session_state,
        selectable_ids,
        group_widget_key=global_widget_key,
        feature_widget_keys=feature_widget_keys,
    )
    selected = set(st.session_state.selected_feature_ids)
    selected_count = sum(feature_id in selected for feature_id in selectable_ids)
    st.caption(f"Выбрано {selected_count} из {len(selectable_ids)}")
    st.checkbox(
        "Выбрать все разрешённые признаки",
        key=global_widget_key,
        on_change=_on_group_widget_change,
        args=(selectable_ids, global_widget_key, feature_widget_keys),
    )
    columns = st.columns(4)
    for index, family in enumerate(group_feature_ids_by_family(selectable_ids)):
        family_ids = family.feature_ids
        family_widget_key = f"prototype_{revision}_family_{group_id}_{family.family_id}"
        synchronize_feature_widgets(
            st.session_state,
            family_ids,
            group_widget_key=family_widget_key,
            feature_widget_keys=feature_widget_keys,
        )
        selected_count = sum(feature_id in selected for feature_id in family_ids)
        with columns[index % len(columns)]:
            st.checkbox(
                f"Группа {family.family_id} · {selected_count}/{len(family_ids)}",
                key=family_widget_key,
                on_change=_on_group_widget_change,
                args=(family_ids, family_widget_key, feature_widget_keys),
            )
            with st.expander("Показать признаки", expanded=False):
                for feature_id in family_ids:
                    view = views_by_id[feature_id]
                    st.checkbox(
                        f"{view.display_name_ru} — {view.description_ru}",
                        key=feature_widget_keys[feature_id],
                        on_change=_on_feature_widget_change,
                        args=(feature_id, family_ids, family_widget_key, feature_widget_keys),
                    )


def _render_nonselectable_feature_group(group_name: str, description: str, views: list[Any], revision: int) -> None:
    """Keep protected and restricted registry sections visibly separate."""
    with st.expander(group_name, expanded=False):
        st.caption(description)
        for view in views:
            reason = view.blocked_reason or f"Статус: {view.usage_status.value}"
            st.checkbox(
                f"{view.display_name_ru} — {view.description_ru}",
                value=False,
                disabled=True,
                key=f"prototype_{revision}_feature_{view.feature_id}",
                help=reason,
            )


def _on_group_widget_change(
    group_feature_ids: tuple[str, ...], group_widget_key: str, feature_widget_keys: dict[str, str],
) -> None:
    apply_group_widget_selection(
        st.session_state,
        group_feature_ids,
        group_widget_key=group_widget_key,
        feature_widget_keys=feature_widget_keys,
    )


def _on_feature_widget_change(
    feature_id: str,
    group_feature_ids: tuple[str, ...],
    group_widget_key: str,
    feature_widget_keys: dict[str, str],
) -> None:
    apply_feature_widget_selection(
        st.session_state,
        feature_id,
        group_feature_ids,
        group_widget_key=group_widget_key,
        feature_widget_keys=feature_widget_keys,
    )


def _render_models_step(runtime) -> None:
    context = _context_or_previous_step()
    if context is None:
        return
    st.header("3. Модель")
    models = tuple(
        model for model in runtime.planning_service.list_models(runtime.model_registry, runtime.model_factories) if model.runnable
    )
    if not models:
        st.error("Нет доступного predictor для выбранного runtime.")
        return
    by_id = {model.model_id: model for model in models}
    revision = st.session_state.context_revision
    current = st.session_state.selected_model_id
    index = tuple(by_id).index(current) if current in by_id else 0
    selected_id = st.selectbox(
        "Predictor",
        tuple(by_id),
        index=index,
        format_func=lambda model_id: by_id[model_id].display_name_ru,
        key=f"prototype_{revision}_model_selection",
    )
    set_selected_model_id(st.session_state, selected_id)
    model = by_id[selected_id]
    st.subheader(model.display_name_ru)
    st.write(model.description_ru)
    st.write("**Проверенная фиксированная конфигурация**" if context.loaded_dataset.contract.final_test_locked else "**Фиксированная конфигурация алгоритма**")
    if not context.loaded_dataset.contract.final_test_locked:
        st.caption("Профиль модели принят на исторических данных; качество на новом файле ещё не проверено.")
    st.write(f"Версия: {model.model_version}")
    with st.expander("Технические параметры"):
        st.caption("Замороженный профиль и требования runtime доступны только для технической проверки.")
        st.json(_plain(model.default_profile))
        st.json(_plain(model.runtime_requirements))
        st.caption(f"model_id: {model.model_id}; adapter version: {model.adapter_version}")
    navigation = st.columns(3)
    _navigation_button(navigation[0], "← Назад", 1)
    _navigation_button(navigation[1], "В начало", 0)
    _navigation_button(navigation[2], "Далее: эксперимент →", 3, primary=True)


def _render_experiment_step(runtime) -> None:
    context = _context_or_previous_step()
    if context is None or not st.session_state.selected_feature_ids or not st.session_state.selected_model_id:
        st.warning("Сначала подтвердите признаки и модель.")
        return
    st.header("4. Эксперимент")
    navigation = st.columns(3)
    _navigation_button(navigation[0], "← Назад", 2)
    _navigation_button(navigation[1], "В начало", 0)
    previous = st.session_state.experiment_inputs
    revision = st.session_state.context_revision
    protocol = runtime.supported_protocol
    with st.expander("Технические сведения протокола", expanded=False):
        st.json({
            "protocol_id": protocol.protocol_id,
            "protocol_version": protocol.protocol_version,
            "evaluation_level": protocol.evaluation_level,
        })
    seed = st.number_input(
        "Случайное разбиение (seed)",
        min_value=0,
        value=int(previous.get("seed", protocol.default_seed)),
        step=1,
        help=(
            "Что это: число, задающее случайное разбиение организаций на части проверки. "
            "Зачем: позволяет воспроизвести один и тот же эксперимент. "
            "Когда менять: только для заранее запланированной новой проверки. "
            "Что изменится: разбиение, OOF-прогнозы и итоговые метрики могут измениться; "
            "сопоставление с запуском на другом seed не является прямым. "
            "Значение по умолчанию и рекомендуемое: 42."
        ),
        key=f"prototype_{revision}_seed",
    )
    folds = st.number_input(
        "Количество частей проверки",
        min_value=protocol.minimum_folds,
        value=max(int(previous.get("folds", protocol.default_folds)), protocol.minimum_folds),
        step=1,
        help=(
            "Что это: количество частей OOF-проверки. "
            "Зачем: каждая организация оценивается моделью, не обучавшейся на ней. "
            "Когда менять: только при заранее запланированном изменении схемы проверки. "
            "Что изменится: состав обучающих и проверочных частей, расчёт и итоговые метрики могут измениться; "
            "сопоставление с запуском на другом числе частей не является прямым. "
            "Значение по умолчанию и рекомендуемое: 3."
        ),
        key=f"prototype_{revision}_folds",
    )
    st.info("OOF-оценка: для каждой организации прогноз получен моделью, которая не обучалась на этой организации.")
    reference_default = previous.get("reference_artifact_id") or st.session_state.last_successful_artifact_id or ""
    with st.expander("Сравнение с предыдущим успешным результатом", expanded=False):
        compare_with_reference = st.checkbox(
            "Включить сопоставление",
            value=bool(previous.get("reference_artifact_id")),
            key=f"prototype_{revision}_comparison_enabled",
        )
        reference_artifact_id = st.text_input(
            "Идентификатор результата для сопоставления",
            value=reference_default,
            disabled=not compare_with_reference,
            key=f"prototype_{revision}_reference",
            help="По умолчанию используется последний успешно сохранённый результат этой сессии.",
        )
    values = {
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.protocol_version,
        "seed": int(seed),
        "folds": int(folds),
        "evaluation_level": protocol.evaluation_level,
        "reference_artifact_id": reference_artifact_id.strip() if compare_with_reference and reference_artifact_id.strip() else None,
        "changed_dimension": None,
        "changed_elements": (),
    }
    set_experiment_inputs(st.session_state, values)
    if st.button("Построить план", type="primary"):
        validation_message = validate_supported_protocol(values, protocol)
        if validation_message:
            st.error(validation_message)
            return
        if not context.loaded_dataset.contract.final_test_locked:
            target = context.loaded_dataset.dataframe[context.loaded_dataset.contract.target_column]
            if int(target.value_counts().min()) < values["folds"]:
                st.error("Число частей OOF не должно превышать число строк самого редкого класса.")
                return
        if values["reference_artifact_id"] is not None:
            try:
                runtime.application_service.load_experiment(values["reference_artifact_id"])
            except ValueError:
                st.error("Указанный reference artifact не найден или повреждён.")
                return
        try:
            snapshot = PlanningRequestMetadata(
                selected_feature_ids=st.session_state.selected_feature_ids,
                model_id=st.session_state.selected_model_id,
                **values,
            )
            run_request_from_snapshot(snapshot)
        except ValueError:
            st.error("Проверьте параметры эксперимента.")
            return
        try:
            plan = runtime.planning_service.build_plan(
                snapshot,
                loaded_dataset=context.loaded_dataset,
                feature_registry=context.feature_registry,
                model_registry=runtime.model_registry,
                model_factories=runtime.model_factories,
                population=context.population,
            )
        except (TypeError, ValueError):
            st.error("Эксперимент не запущен: обнаружена ошибка согласованности backend-контрактов.")
            return
        save_plan(st.session_state, snapshot, plan)

    plan = st.session_state.experiment_plan
    if plan is None:
        return
    _render_plan(plan)
    if not plan.is_valid:
        st.error("План содержит ошибки пользовательского выбора: " + ", ".join(_plan_error_message(error) for error in plan.validation_errors))
        return
    if plan.request.reference_artifact_id:
        st.info("Выбран reference для будущей проверки.")
    if st.button("Запустить эксперимент", type="primary", disabled=not can_run(st.session_state)):
        snapshot = st.session_state.planning_request_snapshot
        try:
            artifact = _run_with_progress(
                _EXPERIMENT_PROGRESS_LABELS,
                lambda listener: runtime.application_service.run_experiment(
                    loaded_dataset=context.loaded_dataset,
                    feature_registry=context.feature_registry,
                    population=context.population,
                    request=run_request_from_snapshot(snapshot),
                    progress_listener=listener,
                ),
            )
            comparison = None
            if snapshot.reference_artifact_id:
                comparison = runtime.application_service.compare_experiments(snapshot.reference_artifact_id, artifact.artifact_id)
        except (KeyError, TypeError, ValueError, RuntimeError, OSError):
            st.error("Эксперимент не запущен: обнаружена ошибка согласованности backend-контрактов.")
            return
        save_artifact(st.session_state, artifact, comparison)
        st.rerun()


def _render_plan(plan) -> None:
    st.subheader("Подтверждённый план")
    request = plan.request
    with st.expander("Данные", expanded=True):
        st.write(f"{plan.dataset.dataset_name} · версия {plan.dataset.dataset_version}")
        population_label = "Рабочая выборка" if plan.dataset.final_test_locked else "Популяция исследовательской оценки"
        st.write(f"{population_label}: {plan.population.population_size:,} организаций.")
        st.write(f"Финальная контрольная выборка закрыта: {'да' if plan.dataset.final_test_locked else 'нет'}.")
    with st.expander("Признаки", expanded=True):
        st.write(f"Выбрано: {len(plan.selected_features)}")
        st.write(", ".join(feature.display_name_ru for feature in plan.selected_features))
        st.caption("Группы: " + ", ".join(plan.feature_groups))
    with st.expander("Модель", expanded=True):
        st.write(plan.model.display_name_ru if plan.model else "Модель не найдена")
        if plan.model:
            st.caption(f"Версия: {plan.model.model_version}")
            with st.expander("Технические параметры"):
                st.json(_plain(plan.model.default_profile))
    with st.expander("Проверка", expanded=True):
        st.write(f"OOF · {request.folds} частей · seed {request.seed}")
        with st.expander("Технические сведения протокола", expanded=False):
            st.caption(f"{request.protocol_id} v{request.protocol_version}")
    with st.expander("Сравнение", expanded=False):
        st.write("Не выбрано" if request.reference_artifact_id is None else f"Reference: {request.reference_artifact_id}")
    if not plan.dataset.final_test_locked:
        st.warning("Для нового файла нет независимой финальной проверки: OOF-результаты исследовательские.")
    st.caption(f"ID конфигурации: {_evaluation_configuration_id(plan)}")
    st.caption(f"Статус валидации: {'валиден' if plan.is_valid else 'невалиден'}")


def _evaluation_configuration_id(plan: Any) -> str:
    """Stable identity for the chosen data, feature set, model and OOF protocol."""
    request = plan.request
    return stable_hash({
        "dataset_fingerprint": plan.dataset.dataset_fingerprint,
        "population_fingerprint": plan.population.population_fingerprint,
        "feature_ids": sorted(request.selected_feature_ids),
        "model_id": request.model_id,
        "model_version": plan.model.model_version if plan.model else None,
        "model_profile": _plain(plan.model.default_profile) if plan.model else None,
        "protocol_id": request.protocol_id,
        "protocol_version": request.protocol_version,
        "evaluation_level": request.evaluation_level,
        "seed": request.seed,
        "folds": request.folds,
    })


def _render_result_step(runtime) -> None:
    artifact = st.session_state.loaded_artifact
    if artifact is None:
        st.info("Текущего успешного результата нет.")
        _navigation_button(st, "← Назад", 3)
        return
    st.header("5. Результат")
    if not artifact.dataset_contract.final_test_locked:
        st.warning("Это исследовательская OOF-оценка нового датасета без независимой финальной выборки. Она не подтверждает качество на будущих данных.")
        plan = st.session_state.experiment_plan
        if plan is not None and plan.dataset.dataset_fingerprint == artifact.dataset_contract.dataset_fingerprint:
            st.caption(f"ID конфигурации: {_evaluation_configuration_id(plan)}")
    result = artifact.run_output.result
    metrics = result.metrics
    st.subheader("Качество ранжирования")
    labels = (("gini", "Gini"), ("roc_auc", "ROC-AUC"), ("pr_auc", "PR-AUC"))
    columns = st.columns(3)
    for index, (key, label) in enumerate(labels):
        columns[index % 3].metric(label, _number(metrics.get(key)))
    st.subheader("При фиксированном пороге 0.5")
    threshold_columns = st.columns(3)
    for index, (key, label) in enumerate((("precision_at_0_5", "Precision"), ("recall_at_0_5", "Recall"), ("f1_at_0_5", "F1"))):
        threshold_columns[index].metric(label, _number(metrics.get(key)))
    st.subheader("Ошибки модели")
    errors = st.columns(4)
    error_labels = (
        ("tp", "Верно выявленные дефолты (TP)", "Модель предсказала дефолт, и дефолт действительно произошёл."),
        ("tn", "Верно выявленные недефолты (TN)", "Модель не предсказала дефолт, и дефолта действительно не было."),
        ("fp", "Ложные тревоги (FP)", "Модель предсказала дефолт, но дефолта не было."),
        ("fn", "Пропущенные дефолты (FN)", "Модель не предсказала дефолт, хотя он произошёл."),
    )
    for index, (key, label, explanation) in enumerate(error_labels):
        errors[index].metric(label, str(result.confusion[key]))
        errors[index].caption(explanation)
    st.subheader("Стабильность по частям проверки")
    st.dataframe(
        [
            {
                "Часть": fold["fold"],
                "Gini": _number(fold.get("gini")),
                "ROC-AUC": _number(fold.get("roc_auc")),
                "Precision @ 0.5": _number(fold.get("precision_at_0_5")),
                "Recall @ 0.5": _number(fold.get("recall_at_0_5")),
            }
            for fold in result.fold_metrics
        ],
        hide_index=True,
        use_container_width=True,
    )
    model_saved = _render_final_model_section(runtime, artifact)
    st.subheader("Ограничения")
    with st.expander("Показать ограничения", expanded=False):
        for limitation in result.limitations:
            st.write(f"- {limitation}")
    st.subheader("Технические сведения")
    with st.expander("Показать технические сведения", expanded=False):
        st.json({
            "artifact_id": artifact.artifact_id,
            "result_id": result.result_id,
            "runtime_seconds": result.runtime_seconds,
            "evaluation_level": result.evaluation_level,
            "confusion": _plain(result.confusion),
            "fold_metrics": _plain(result.fold_metrics),
        })
    comparison = st.session_state.comparison_result
    if comparison is not None:
        with st.expander("Сопоставление с reference", expanded=False):
            st.write(f"Сопоставимы: {'да' if comparison.is_comparable else 'нет'}")
            st.write(f"Причины: {', '.join(comparison.reason_codes) or 'не указаны'}")
            st.json({"metrics": comparison.metric_deltas, "confusion": comparison.confusion_deltas, "feature_change": comparison.feature_change, "model_change": comparison.model_change})
    if model_saved:
        return
    navigation = st.columns(3)
    _navigation_button(navigation[0], "← Назад", 3)
    _navigation_button(navigation[1], "В начало", 0)
    _navigation_button(navigation[2], "Новый эксперимент", 3, primary=True)
    _navigation_button(st, "Исторический SHAP Stage 2 →", 5)


def _render_final_model_section(runtime, artifact) -> bool:
    """Present a single-save flow; never present historical SHAP as this model's SHAP."""
    with st.container(border=True):
        st.subheader("Итоговая модель")
        config = artifact.config
        model_name = runtime.model_registry.get(config.model_id).display_name_ru
        facts = st.columns(3)
        facts[0].metric("Алгоритм", model_name)
        facts[1].metric("Признаков", str(len(config.feature_ids)))
        facts[2].metric("Строк для обучения", f"{len(artifact.population.row_positions):,}")
        try:
            versions, invalid = runtime.model_store.catalog()
        except (OSError, ValueError):
            versions, invalid = (), ()
            catalog_available = False
            st.error("Каталог моделей недоступен. Обучение не запускается, чтобы не создать дубликат версии.")
        else:
            catalog_available = True
        if invalid:
            st.warning(f"Повреждённых записей каталога: {len(invalid)}. Они не считаются сохранёнными моделями.")
        matching = [
            item for item in versions
            if item.experiment_artifact_id == artifact.artifact_id
            and item.dataset_fingerprint == artifact.dataset_contract.dataset_fingerprint
            and item.model_id == config.model_id
            and item.feature_set_hash == config.feature_set_hash
        ]
        if matching:
            saved = matching[0]
            st.success("Модель обучена и сохранена на этом компьютере.")
            st.caption(f"ID сохранённой версии: {saved.version_id} · создана: {_format_saved_model_date(saved.created_at)}")
            st.button("Обучение завершено", disabled=True, type="primary", key="prototype_final_model_saved")
            st.info("SHAP именно этой сохранённой версии пока не рассчитан. Ниже можно открыть только исторический обзор Stage 2.")
            actions = st.columns(2)
            _navigation_button(actions[0], "Исторический SHAP →", 5)
            _navigation_button(actions[1], "Вернуться в начало", 0, primary=True)
            return True
        st.info("OOF-метрики уже получены. Чтобы применять модель позднее к новым ИНН, отдельно обучите и сохраните итоговую версию.")
        if artifact.dataset_contract.final_test_locked:
            st.caption("В обучение войдёт только рабочая часть Data_final. Закрытая контрольная часть останется вне обучения.")
        else:
            st.caption("В обучение войдут все подтверждённые размеченные строки. Отдельной контрольной выборки у нового файла нет.")
        st.caption("На большом датасете итоговое обучение может занять заметное время.")
        context = st.session_state.dataset_context
        same_context = bool(
            context and context.loaded_dataset.contract == artifact.dataset_contract
            and context.population == artifact.population
        )
        if not same_context:
            st.warning("Для обучения нужно снова подтвердить тот же датасет и открыть его результат.")
        if st.button("Обучить и сохранить модель", type="primary", disabled=not same_context or not catalog_available):
            try:
                _run_with_progress(
                    {
                        "verifying_source": "Проверка исходного файла",
                        "fitting_final_model": "Обучение итоговой модели",
                        "saving_model": "Сохранение нативной модели и паспорта",
                        "completed": "Версия модели сохранена",
                    },
                    lambda listener: runtime.model_training_service.train_and_save(
                        experiment_artifact_id=artifact.artifact_id,
                        loaded_dataset=context.loaded_dataset,
                        feature_registry=context.feature_registry,
                        population=context.population,
                        progress_listener=listener,
                    ),
                    initial_label="Готовим итоговую модель…",
                    completion_label="Итоговая модель сохранена",
                )
            except (OSError, ValueError, RuntimeError) as error:
                st.error(f"Не удалось сохранить модель: {error}")
            else:
                st.rerun()
    return False


def _render_shap_step() -> None:
    """Show accepted research evidence without presenting it as a fresh run's SHAP."""
    st.header("6. SHAP · объяснимость")
    st.info(
        "Здесь показаны сохранённые результаты исследования Stage 2. "
        "Это не SHAP обученной и сохранённой на предыдущем экране версии модели. "
        "Индивидуальный SHAP для неё пока не рассчитывается автоматически."
    )
    try:
        summary, by_model, consensus, details = load_stage2_evidence()
    except (OSError, ValueError, KeyError):
        st.error("Не удалось загрузить сохранённые данные SHAP Stage 2.")
        _navigation_button(st, "← К результату", 4)
        return

    artifact = st.session_state.loaded_artifact
    context = st.session_state.dataset_context
    comparable = stage2_matches_current_run(artifact, context, summary, by_model)
    if comparable:
        st.success("Датасет, модель, 47 признаков, seed и число фолдов совпадают с протоколом Stage 2.")
    else:
        st.warning(
            "Текущий запуск не совпадает с протоколом Stage 2 или ещё не выполнен. "
            "Рейтинги ниже относятся только к историческому исследованию, а не к текущему результату."
        )

    st.subheader("Глобальный рейтинг признаков")
    model_name = model_display_name(artifact.config.model_id) if artifact is not None else None
    if model_name is None:
        st.caption("Для GBDT_mean отдельный SHAP в Stage 2 не рассчитывался; показан общий рейтинг трёх моделей.")
        ranking = consensus.sort_values("Consensus место").head(15)
        st.dataframe(
            ranking.rename(columns={
                "Средний ранг": "Средний ранг *",
                "Std ранга": "Std ранга **",
                "Consensus место": "Consensus место ***",
            }),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "(*) Средний ранг — среднее место признака в рейтингах трёх моделей.\n\n"
            "(**) Std ранга — насколько различаются эти места между моделями.\n\n"
            "(***) Consensus место — итоговое место признака в общем рейтинге; 1 — первое."
        )
    else:
        st.caption(f"Модель исследования: {model_name}. Средний |SHAP| показывает силу вклада, но не его направление.")
        ranking = by_model.loc[by_model["Модель"] == model_name].sort_values("Ранг SHAP").head(15)
        st.bar_chart(ranking.set_index("Признак")["Средний |SHAP|"], horizontal=True)
        st.dataframe(
            ranking[["Признак", "Средний |SHAP|", "Std |SHAP| по фолдам", "Ранг SHAP"]].rename(columns={
                "Средний |SHAP|": "Средний |SHAP| *",
                "Std |SHAP| по фолдам": "Std |SHAP| по фолдам **",
                "Ранг SHAP": "Ранг SHAP ***",
            }),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "(*) Средний |SHAP| — средняя сила влияния признака на прогноз, без учёта направления.\n\n"
            "(**) Std |SHAP| по фолдам — насколько эта сила различалась между проверочными частями данных.\n\n"
            "(***) Ранг SHAP — место по среднему |SHAP|; 1 — наибольший вклад."
        )

    st.subheader("Локальные примеры из Stage 2")
    st.caption("Это три ранее сохранённых примера XGBoost, не компании из текущего запуска.")
    examples = details.get("локальные_примеры_xgboost", [])
    if examples:
        choices = {example["сценарий"]: example for example in examples}
        chosen = choices[st.selectbox("Сценарий", tuple(choices), key="stage2_shap_example")]
        st.metric("Вероятность дефолта в историческом примере", f"{chosen['вероятность_дефолта']:.4f}")
        st.dataframe(
            [
                {
                    "Признак": factor["признак"],
                    "Значение": factor["значение"],
                    "SHAP-вклад *": factor["shap"],
                    "Направление": "Повышает оценку риска" if factor["shap"] > 0 else "Понижает оценку риска",
                }
                for factor in chosen["top10_shap"]
            ],
            hide_index=True,
            use_container_width=True,
        )
    st.caption(
        "(*) SHAP-вклад — влияние признака на прогноз для этого примера: "
        "положительный сдвигает прогноз модели к большему риску, отрицательный — к меньшему. "
        "Вклад не равен изменению вероятности в процентах и не доказывает причинную связь."
    )
    _navigation_button(st, "← К результату", 4)


def _description_store(runtime) -> FeatureDescriptionStore:
    return FeatureDescriptionStore(runtime.model_store.root.parent)


def _effective_descriptions(runtime, dataset_fingerprint: str, dataset_id: str) -> dict[str, str]:
    descriptions = historical_descriptions(dataset_id)
    try:
        descriptions.update(_description_store(runtime).load(dataset_fingerprint))
    except (OSError, ValueError, KeyError) as error:
        st.warning(f"Сохранённый словарь описаний недоступен: {error}")
    return descriptions


def _highlight_missing_descriptions(frame: pd.DataFrame):
    """Give absent semantics a restrained red treatment in feature tables."""
    return frame.style.map(
        lambda value: "color: #ff6b6b; background-color: #3a2428; font-weight: 600"
        if value == MISSING_DESCRIPTION else "", subset=["Описание"],
    )


def _render_description_upload(
    runtime, dataset_fingerprint: str, feature_columns: tuple[str, ...], widget_scope: str,
) -> None:
    st.subheader("Словарь описаний признаков")
    st.caption("Необязательно. Сопоставление только по точному имени column_name; порядок строк значения не имеет.")
    template = pd.DataFrame({"column_name": feature_columns, "description": [""] * len(feature_columns)})
    st.download_button(
        "Скачать шаблон описаний CSV", template.to_csv(index=False).encode("utf-8-sig"),
        file_name="feature_descriptions_template.csv", mime="text/csv",
        key=f"description_template_{widget_scope}_{dataset_fingerprint[:12]}",
    )
    uploaded = st.file_uploader(
        "Загрузить описания CSV, XLSX или XLSB", type=["csv", "xlsx", "xlsb"],
        key=f"description_upload_{widget_scope}_{dataset_fingerprint[:12]}",
    )
    if uploaded is None:
        return
    try:
        parsed, missing = parse_description_file(uploaded.name, uploaded.getvalue(), feature_columns)
    except (OSError, ValueError) as error:
        st.error(f"Словарь не принят: {error}")
        return
    st.success(f"Совпало описаний: {len(parsed)}. Без описания в этом файле: {len(missing)}.")
    preview = pd.DataFrame(
        [{"Столбец": name, "Описание": parsed.get(name, MISSING_DESCRIPTION)} for name in feature_columns]
    )
    st.dataframe(_highlight_missing_descriptions(preview), hide_index=True, use_container_width=True, height=250)
    if st.button("Подтвердить и сохранить описания", key=f"description_save_{widget_scope}_{dataset_fingerprint[:12]}"):
        try:
            glossary = _description_store(runtime)
            merged = glossary.load(dataset_fingerprint)
            merged.update(parsed)
            glossary.save(dataset_fingerprint, merged, tuple(dict.fromkeys((*feature_columns, *merged))))
        except (OSError, ValueError, KeyError) as error:
            st.error(f"Не удалось сохранить описания: {error}")
        else:
            st.success("Описания сохранены отдельно от модели; переобучение не требуется.")
            st.rerun()


def _render_prediction_step(runtime) -> None:
    """Use a saved version for inference on an uploaded, unlabeled company table."""
    st.header("7. Прогноз для новых ИНН")
    version_id = st.session_state.selected_model_version_id
    if not version_id:
        st.info("Сначала выберите сохранённую модель в каталоге на вкладке «Данные».")
        _navigation_button(st, "← К каталогу моделей", 0)
        return
    try:
        model = runtime.model_store.load(version_id)
    except (OSError, ValueError, KeyError) as error:
        st.error(f"Не удалось открыть сохранённую модель: {error}")
        _navigation_button(st, "← К каталогу моделей", 0)
        return
    st.success(f"Модель: {model.summary.model_id} · {model.summary.dataset_name} · версия {version_id[:12]}")
    st.caption(f"Полный ID версии: {version_id}. Для прогноза модель не переобучается.")
    identifier = model.dataset_contract.identifier_column
    columns = [identifier, *(spec.column_name for spec in model.feature_specs)]
    st.subheader("Какие данные нужны")
    st.write(f"Файл должен содержать столбец **{identifier}** и все **{len(model.feature_specs)}** признаков модели. Имена столбцов должны совпадать точно; порядок в файле может отличаться.")
    st.subheader(f"Признаки, использованные при обучении ({len(model.feature_specs)})")
    descriptions = _effective_descriptions(
        runtime, model.dataset_contract.dataset_fingerprint, model.dataset_contract.dataset_id,
    )
    feature_table = pd.DataFrame([
        {
            "Столбец": spec.column_name,
            "Название": spec.display_name_ru,
            "Описание": descriptions.get(spec.column_name, MISSING_DESCRIPTION),
        }
        for spec in model.feature_specs
    ])
    highlighted = _highlight_missing_descriptions(feature_table)
    st.dataframe(highlighted, hide_index=True, use_container_width=True, height=500)
    specs_by_column = {spec.column_name: spec for spec in model.feature_specs}
    selected_column = st.selectbox(
        "Выберите признак, чтобы посмотреть описание",
        tuple(specs_by_column),
        format_func=lambda name: f"{name} — {specs_by_column[name].display_name_ru}",
        key=f"prototype_prediction_feature_{version_id}",
    )
    selected_spec = specs_by_column[selected_column]
    selected_description = descriptions.get(selected_column)
    if selected_description:
        st.write(f"**{selected_column}** — {selected_description}")
    else:
        st.markdown(f"**{selected_column}** — :red[{MISSING_DESCRIPTION}]")
    _render_description_upload(
        runtime, model.dataset_contract.dataset_fingerprint,
        tuple(specs_by_column), f"model_{version_id[:12]}",
    )
    st.download_button(
        "Скачать шаблон CSV",
        data=pd.DataFrame(columns=columns).to_csv(index=False).encode("utf-8-sig"),
        file_name=f"model_{version_id[:12]}_template.csv", mime="text/csv",
    )
    st.caption("Новые ИНН без значений этих признаков спрогнозировать нельзя. Столбец с фактической меткой дефолта не требуется и при наличии игнорируется.")
    uploaded = st.file_uploader(
        "Файл с ИНН и признаками", type=["csv", "xlsx", "xlsb"],
        key=f"prototype_prediction_upload_{version_id}", on_change=_clear_prediction_result,
    )
    if st.button("Получить прогноз", type="primary", disabled=uploaded is None):
        try:
            batch = predict_uploaded_file(model, uploaded.name, uploaded.getvalue())
        except (OSError, ValueError) as error:
            st.error(f"Прогноз не выполнен: {error}")
        else:
            st.session_state[_PREDICTION_RESULT_KEY] = batch
    batch = st.session_state.get(_PREDICTION_RESULT_KEY)
    if batch is not None and batch.version_id == version_id:
        st.subheader("Результат прогноза")
        st.write(f"Обработано ИНН: {len(batch.predictions)}")
        if batch.ignored_columns:
            st.warning("Дополнительные столбцы не использовались: " + ", ".join(batch.ignored_columns))
        st.dataframe(batch.predictions, hide_index=True, use_container_width=True)
        st.download_button(
            "Скачать прогноз CSV", batch.predictions.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"predictions_{version_id[:12]}.csv", mime="text/csv",
        )
        st.caption("Это прогноз сохранённой модели, а не фактическая метка дефолта. Порог 0,5 — технический пример, не утверждённое правило принятия решения. Индивидуальный SHAP для этих ИНН пока не реализован.")
    _navigation_button(st, "← К каталогу моделей", 0)


def _clear_prediction_result() -> None:
    st.session_state[_PREDICTION_RESULT_KEY] = None


def _navigation_button(
    container: Any, label: str, target_step: int, *, primary: bool = False, disabled: bool = False,
    on_navigate: Callable[[], None] | None = None,
) -> None:
    """Render a non-destructive wizard transition in the supplied layout slot."""
    if container.button(label, type="primary" if primary else "secondary", disabled=disabled):
        if on_navigate is not None:
            on_navigate()
        navigate_to_step(st.session_state, target_step)
        st.rerun()


def _available_wizard_steps(state: Mapping[str, Any]) -> tuple[bool, ...]:
    """Keep every reached tab directly accessible until an actual source change resets it."""
    highest_reached = min(max(int(state.get("highest_reached_step", 0)), 0), len(_STEP_NAVIGATION_LABELS) - 1)
    return tuple(step <= highest_reached for step in range(len(_STEP_NAVIGATION_LABELS)))


def _render_step_navigation() -> None:
    """Render the compact step row with in-session navigation callbacks."""
    current_step = st.session_state.current_step
    available = _available_wizard_steps(st.session_state)
    st.html(
        """
        <style>
        .st-key-step-navigator {
            width: fit-content !important; gap: 0.25rem !important; align-items: baseline !important;
            flex-wrap: nowrap !important;
        }
        .st-key-step-navigator > * { flex: 0 0 auto !important; width: fit-content !important; }
        .st-key-step-navigator [data-testid="stButton"] {
            width: fit-content !important; margin: 0 !important; padding: 0 !important;
        }
        .st-key-step-navigator [data-testid="stButton"] > button {
            min-height: 0 !important; margin: 0 !important; padding: 0 !important;
            border: 0 !important; background: transparent !important; box-shadow: none !important;
            color: inherit !important; font: inherit !important; font-size: 0.875rem !important;
            line-height: 1.2 !important; opacity: 0.6 !important;
        }
        .st-key-step-navigator [data-testid="stButton"] > button:hover,
        .st-key-step-navigator [data-testid="stButton"] > button:active {
            border: 0 !important; background: transparent !important; box-shadow: none !important;
            color: inherit !important;
        }
        </style>
        """
    )
    navigation = st.container(
        horizontal=True,
        gap=None,
        key=_STEP_NAVIGATION_CONTAINER_KEY,
    )
    for step, (label, is_available) in enumerate(zip(_STEP_NAVIGATION_LABELS, available, strict=True)):
        text = f"{'●' if step == current_step else '○'} {label}"
        if is_available:
            navigation.button(
                text,
                key=f"{_STEP_NAVIGATION_CONTAINER_KEY}-{step}",
                type="tertiary",
                on_click=navigate_to_step,
                args=(st.session_state, step),
            )
        else:
            navigation.caption(text)
        if step < len(_STEP_NAVIGATION_LABELS) - 1:
            navigation.caption("→")


def _context_or_previous_step():
    context = st.session_state.dataset_context
    if context is not None:
        return context
    st.warning("Сначала подготовьте контекст данных.")
    _navigation_button(st, "К данным", 0)
    return None


def _plan_error_message(error: str) -> str:
    if error.startswith("unknown_feature:"):
        return "неизвестный признак"
    if error.startswith("forbidden_feature:"):
        return "признак недоступен для модели"
    if error.startswith("unknown_model:"):
        return "неизвестная модель"
    if error.startswith("non_runnable_model:"):
        return "модель недоступна для запуска"
    return "некорректный выбор"


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _number(value: Any) -> str:
    return "—" if value is None else f"{float(value):.4f}"


if __name__ == "__main__":
    main()
