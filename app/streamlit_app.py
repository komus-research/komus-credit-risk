"""Single-page Streamlit prototype over the accepted Pipeline V1 services."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import streamlit as st

from app.bootstrap import (
    LocalDatasetSourceResolver,
    confirm_dataset_preparation,
    create_runtime,
    default_preparation_draft,
    prepare_resolved_source,
    reopen_dataset_preparation,
    validate_supported_protocol,
)
from app.feature_display import group_feature_ids_by_family
from app.local_file_picker import NativeFilePickerUnavailable, choose_local_file
from app.session_state import (
    apply_feature_widget_selection,
    apply_group_widget_selection,
    can_run,
    initialize,
    navigate_to_step,
    run_request_from_snapshot,
    save_artifact,
    save_plan,
    set_loaded_model_version,
    set_local_explanation_evidence,
    set_prediction_batch,
    set_selected_prediction_row_id,
    set_dataset_source_preparation,
    set_experiment_inputs,
    set_selected_model_id,
    synchronize_feature_widgets,
    return_to_experiment,
)
from komus_risk.planning import PlanningRequestMetadata
from komus_risk.data import TabularReader
from komus_risk.preparation import DatasetPreparationError
from komus_risk.preparation.predictor_compatibility import predictor_compatibility_error


_DATA_PROGRESS_LABELS = {
    "reading_source": "Чтение файла",
    "inspecting_dataset": "Проверка структуры и значений набора данных",
    "analyzing_preparation": "Анализ вариантов подготовки",
    "validating_confirmation": "Проверка подтверждённой подготовки",
    "materializing_dataset": "Подготовка набора данных",
    "prepared_context_ready": "Контекст подготовленного набора данных готов",
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
_MANUAL_LOCAL_FILE_PATH_KEY = "prototype_manual_local_file_path"
_SOURCE_ERROR_KEY = "prototype_source_error"
_SOURCE_RECHECK_INVALID_KEY = "prototype_source_recheck_invalid"
_PREPARATION_DRAFT_KEY = "dataset_preparation_draft"
_PREPARATION_STEP_KEY = "dataset_preparation_step"
_STALE_PREPARATION_ERROR_CODES = frozenset({
    "STALE_SNAPSHOT",
    "REPORT_IDENTITY_MISMATCH",
    "PROPOSAL_IDENTITY_MISMATCH",
    "CONFIRMATION_IDENTITY_MISMATCH",
})
_SUPPORTED_SOURCE_EXTENSIONS = tuple(LocalDatasetSourceResolver._FORMATS)
_DATASET_ONBOARDING_STEPS = ("Файл", "Подготовка", "Проверка")
_STEP_NAVIGATION_LABELS = ("Данные", "Признаки", "Модель", "Эксперимент", "Результат")
_STEP_NAVIGATION_CONTAINER_KEY = "step-navigator"
_INFERENCE_SELECTED_LOCAL_FILE_PATH_KEY = "prototype_inference_selected_local_file_path"
_INFERENCE_MANUAL_LOCAL_FILE_PATH_KEY = "prototype_inference_manual_local_file_path"


@st.cache_resource
def _runtime():
    return create_runtime()


def main() -> None:
    st.set_page_config(page_title="KOMUS · Prototype V1", layout="wide")
    initialize(st.session_state)
    runtime = _runtime()
    step = st.session_state.current_step
    st.title("KOMUS · Experiment Prototype V1")
    _render_step_navigation()

    if step == 0:
        _render_data_step()
    elif step == 1:
        _render_features_step(runtime)
    elif step == 2:
        _render_models_step(runtime)
    elif step == 3:
        _render_experiment_step(runtime)
    else:
        _render_result_step(runtime)


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


def _render_data_step() -> None:
    st.header("Подготовка набора данных")
    st.caption("Файл → Подготовка → Проверка → Признаки → Модель → Эксперимент → Результат")
    preparation = st.session_state.dataset_source_preparation
    if preparation is not None and preparation.is_prepared and getattr(preparation, "preparation_status", None) == "historical_context_prepared":
        _render_prepared_source(preparation)
        _render_change_file_action()
        _navigation_button(st, "Продолжить к признакам →", 1, primary=True)
        return
    if preparation is None or st.session_state.get(_SOURCE_RECHECK_INVALID_KEY):
        _restore_source_controls(st.session_state)
        source_kind = "explicit_local"
        explicit_local_path = _render_local_source_controls()
        draft_locator = _source_control_locator(source_kind, explicit_local_path)
        _synchronize_source_selection(st.session_state, draft_locator)
        _render_source_check_action(source_kind, explicit_local_path, draft_locator)
        preparation = st.session_state.dataset_source_preparation
    else:
        source_kind = "explicit_local"
        explicit_local_path = ""
    is_display_ready = bool(preparation and preparation.is_prepared and not st.session_state.get(_SOURCE_RECHECK_INVALID_KEY))
    if preparation is None or (preparation.is_prepared and not is_display_ready):
        _render_unchecked_source(source_kind, explicit_local_path)
    elif not preparation.is_prepared and getattr(preparation, "snapshot", None) is not None:
        _render_dataset_onboarding(preparation)
        # The generic onboarding owns its navigation.  Rendering the legacy
        # footer below would create its "continue" button a second time.
        return
    elif not preparation.is_prepared:
        source = preparation.source
        st.success("Файл успешно проверен")
        st.subheader(source.file_name)
        st.write(
            "Этот набор данных ещё не подготовлен для эксперимента. "
            "Для продолжения потребуется отдельная подготовка данных и признаков."
        )
    else:
        _render_prepared_source(preparation)
        _render_change_file_action()
        if getattr(preparation, "preparation_status", None) == "confirmed_context_prepared":
            if st.button("Изменить подготовку", type="secondary"):
                editable = reopen_dataset_preparation(preparation)
                set_dataset_source_preparation(st.session_state, editable)
                st.session_state[_PREPARATION_DRAFT_KEY] = default_preparation_draft(editable)
                st.session_state[_PREPARATION_STEP_KEY] = 1
                st.rerun()

    ready_to_continue = is_display_ready
    if not ready_to_continue and (preparation is None or st.session_state.get(_SOURCE_RECHECK_INVALID_KEY)):
        st.caption("Сначала проверьте файл.")
    _navigation_button(
        st,
        "Продолжить к признакам →",
        1,
        primary=True,
        disabled=not ready_to_continue,
    )


def _render_local_source_controls() -> str:
    """Render local-source selection without showing a host filesystem path."""
    st.subheader("1. Файл")
    st.write("Загрузите файл, который хотите подготовить для эксперимента.")
    st.caption("Новый файл не становится автоматически готовым к эксперименту.")
    if st.button("Выбрать файл…", type="primary"):
        try:
            selected = choose_local_file(_SUPPORTED_SOURCE_EXTENSIONS)
        except NativeFilePickerUnavailable:
            st.warning("Не удалось открыть окно выбора файла. Укажите путь вручную ниже.")
        else:
            if selected:
                st.session_state[_SELECTED_LOCAL_FILE_PATH_KEY] = selected
                st.session_state[_MANUAL_LOCAL_FILE_PATH_KEY] = ""
                st.session_state.pop(_SOURCE_ERROR_KEY, None)

    selected_path = st.session_state.get(_SELECTED_LOCAL_FILE_PATH_KEY, "")
    manual_path = ""
    with st.expander("Указать расположение файла вручную", expanded=False):
        manual_path = st.text_input(
            "Путь к файлу",
            key=_MANUAL_LOCAL_FILE_PATH_KEY,
            placeholder="Выберите файл или укажите его расположение",
        )
    effective_path = manual_path.strip() or selected_path
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


def _clear_local_file_selection() -> None:
    """Reset local-file controls before Streamlit instantiates their widgets."""
    st.session_state.pop(_SELECTED_LOCAL_FILE_PATH_KEY, None)
    st.session_state[_MANUAL_LOCAL_FILE_PATH_KEY] = ""


def _render_source_check_action(
    source_kind: str, explicit_local_path: str, draft_locator: tuple[str, str],
) -> None:
    """Confirm a draft source before it can replace the active dataset state."""
    preparation = st.session_state.dataset_source_preparation
    has_selected_local_file = bool(explicit_local_path.strip())
    already_checked = preparation is not None and draft_locator == st.session_state.get(_SOURCE_CONTROL_LOCATOR_KEY)
    label = "Проверить файл повторно" if already_checked else "Проверить файл"
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
        preparation = _run_with_progress(
            _DATA_PROGRESS_LABELS,
            lambda listener: prepare_resolved_source(source, progress_listener=listener),
            initial_label="Проверяем файл…",
            completion_label="Проверка файла завершена",
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
                "Не удалось проверить файл",
                "Проверьте выбранный файл и повторите попытку.",
            )
    except OSError:
        st.session_state[_SOURCE_ERROR_KEY] = (
            "Не удалось проверить файл",
            "Проверьте выбранный файл и повторите попытку.",
        )
    _render_source_error()


def _commit_source_preparation(
    state: MutableMapping[str, Any], locator: tuple[str, str], preparation: Any,
) -> None:
    """Commit only a successfully checked source; draft control changes remain harmless."""
    set_dataset_source_preparation(state, preparation)
    state[_SOURCE_CONTROL_LOCATOR_KEY] = locator


def _render_source_error() -> None:
    error = st.session_state.get(_SOURCE_ERROR_KEY)
    if error:
        title, detail = error
        st.error(title)
        st.write(detail)


def _render_unchecked_source(source_kind: str, explicit_local_path: str) -> None:
    if not explicit_local_path:
        st.info("Выберите файл, затем проверьте его.")


def _render_prepared_source(preparation: Any) -> None:
    """Render every prepared context from its contract and evaluation population."""
    context = preparation.context
    if context is None:
        return
    st.success("Данные готовы к эксперименту")
    passport = context.loaded_dataset.contract
    population_size = len(context.population.row_positions)
    st.subheader(passport.dataset_name or context.display_name)
    columns = st.columns(3)
    columns[0].metric("Строки", f"{passport.row_count:,}")
    columns[1].metric("Популяция оценки", f"{population_size:,}")
    columns[2].metric("Реестр признаков", passport.feature_registry_id)
    st.write(f"**Целевая колонка:** {passport.target_column}")
    st.write(f"**Колонка-идентификатор:** {passport.identifier_column}")
    if passport.final_test_locked:
        st.info("Для набора данных задана защищённая финальная тестовая выборка.")
        if population_size < passport.row_count:
            st.caption(f"Строк вне текущей популяции оценки: {passport.row_count - population_size:,}.")
    else:
        st.info("Для текущего протокола оценки используется вся подтверждённая популяция. Защищённая финальная тестовая выборка не задана.")
    with st.expander("Технические сведения", expanded=False):
        st.json({
            "dataset_name": passport.dataset_name,
            "dataset_version": passport.dataset_version,
            "source_type": passport.source_type,
            "dataset_fingerprint": passport.dataset_fingerprint,
            "dataset_id": passport.dataset_id,
            "target_column": passport.target_column,
            "identifier_column": passport.identifier_column,
            "validation_status": passport.validation_status,
            "final_test_locked": passport.final_test_locked,
            "evaluation_population": {
                "population_id": context.population.population_id,
                "population_size": population_size,
                "partition_role": context.population.partition_role,
            },
            "preparation_status": preparation.preparation_status,
        })


def _render_dataset_onboarding(preparation: Any) -> None:
    """Render one explicit confirmation decision at a time for a checked source."""
    snapshot = preparation.snapshot
    report = preparation.inspection_report
    state = st.session_state
    draft = _onboarding_draft(preparation)
    step = min(max(int(state.get(_PREPARATION_STEP_KEY, 0)), 0), len(_DATASET_ONBOARDING_STEPS) - 1)
    state[_PREPARATION_STEP_KEY] = step
    _render_completed_onboarding_steps(preparation, draft, step)

    if step == 0:
        _render_file_onboarding_step(preparation)
    elif step == 1:
        _render_preparation_onboarding_step(preparation, draft, report)
    else:
        _render_review_onboarding_step(preparation, draft)


def _onboarding_draft(preparation: Any) -> dict[str, Any]:
    """Keep proposal defaults internal until the person explicitly confirms each choice."""
    state = st.session_state
    draft = state.get(_PREPARATION_DRAFT_KEY)
    snapshot = preparation.snapshot
    if not isinstance(draft, dict) or draft.get("snapshot_fingerprint") != snapshot.fingerprint:
        draft = default_preparation_draft(preparation)
        state[_PREPARATION_DRAFT_KEY] = draft
    return draft


def _render_completed_onboarding_steps(preparation: Any, draft: Mapping[str, Any], active_step: int) -> None:
    """Show previous decisions as compact summaries, never as duplicate forms."""
    active_step = min(active_step, len(_DATASET_ONBOARDING_STEPS) - 1)
    summaries = (
        f"{preparation.source.file_name} — {preparation.snapshot.row_count:,} строк, {preparation.snapshot.column_count:,} столбцов",
        "Цель: " + str(draft.get("target_column") or "не выбрана")
        + "; идентификатор: " + str(draft.get("identifier_column") or "не выбран"),
    )
    for step in range(active_step):
        left, right = st.columns((5, 1))
        left.write(f"✓ {_DATASET_ONBOARDING_STEPS[step]}: {summaries[step]}")
        if right.button("Изменить", key=f"dataset-preparation-edit-{step}"):
            st.session_state[_PREPARATION_STEP_KEY] = step
            st.rerun()


def _render_file_onboarding_step(preparation: Any) -> None:
    st.subheader("1. Файл")
    st.success("Файл успешно проверен")
    summary = st.columns(2)
    summary[0].metric("Строки", f"{preparation.snapshot.row_count:,}")
    summary[1].metric("Столбцы", f"{preparation.snapshot.column_count:,}")
    st.write(f"Файл: {preparation.source.file_name}")
    if preparation.proposal.warnings:
        with st.expander("Подробнее", expanded=False):
            _render_aggregated_warnings(preparation.proposal.warnings)
    _render_change_file_action()
    _onboarding_next_button("Продолжить к подготовке →", 1)


def _render_change_file_action() -> None:
    """Allow every prepared profile to return to the same file-selection entry point."""
    if st.button("Изменить файл", type="secondary"):
        _reset_for_file_change()


def _reset_for_file_change() -> None:
    """Drop the active preparation and every UI-owned file selection before a new choice."""
    state = st.session_state
    _clear_local_file_selection()
    for key in (_SOURCE_CONTROL_LOCATOR_KEY, _SOURCE_KIND_WIDGET_KEY, _SOURCE_ERROR_KEY, _SOURCE_RECHECK_INVALID_KEY):
        state.pop(key, None)
    set_dataset_source_preparation(state, None)
    state[_PREPARATION_STEP_KEY] = 0
    st.rerun()


def _render_preparation_onboarding_step(
    preparation: Any, draft: MutableMapping[str, Any], report: Any,
) -> None:
    """Confirm the only user decisions required before final preparation."""
    snapshot = preparation.snapshot
    state = st.session_state
    st.subheader("2. Подготовка")
    st.caption("Проверьте предложенные цель и идентификатор. Разрешения признаков сформированы автоматически.")
    placeholder = "— выберите —"
    revision = int(state.get("context_revision", 0))
    target_key = _preparation_form_key(revision, snapshot.fingerprint, "target")
    if target_key not in state:
        state[target_key] = draft.get("target_column") or placeholder
    target = st.selectbox("Целевая колонка", [placeholder, *snapshot.physical_headers], key=target_key)
    target_values = _target_values(report, target)
    positive_placeholder = "— выберите положительное событие —"
    positive_key = _bind_positive_class_to_target(
        state,
        form_revision=revision,
        snapshot_fingerprint=snapshot.fingerprint,
        target=target,
        target_values=target_values,
        placeholder=positive_placeholder,
        initial_target=draft.get("target_column"),
        initial_positive_class=draft.get("positive_class"),
    )
    positive = st.selectbox(
        "Какое значение считать положительным событием?",
        [positive_placeholder, *target_values],
        key=positive_key,
        format_func=lambda value: value if isinstance(value, str) else repr(value),
        disabled=not target_values,
    )
    identifier_key = _preparation_form_key(revision, snapshot.fingerprint, "identifier")
    identifier_options = [placeholder, *(name for name in snapshot.physical_headers if name != target)]
    if identifier_key not in state or state[identifier_key] not in identifier_options:
        candidate = draft.get("identifier_column")
        state[identifier_key] = candidate if candidate in identifier_options else placeholder
    identifier = st.selectbox("Колонка-идентификатор", identifier_options, key=identifier_key)
    complete = target != placeholder and positive != positive_placeholder and identifier != placeholder
    if st.button("Продолжить к проверке →", type="primary", disabled=not complete):
        draft["target_column"] = target
        draft["positive_class"] = positive
        draft["identifier_column"] = identifier
        _onboarding_go_to(2)


_ADVANCED_STATUS_LABELS = {
    "MODEL_ALLOWED": "Использовать моделью",
    "DIAGNOSTIC_ONLY": "Только для анализа",
    "BLOCKED": "Заблокировать",
}


def _render_review_onboarding_step(preparation: Any, draft: MutableMapping[str, Any]) -> None:
    st.subheader("3. Проверка")
    statuses = _predictor_statuses(draft)
    st.write(f"Файл: {preparation.source.file_name}")
    st.write(f"Цель: {draft.get('target_column') or 'не выбрана'}")
    st.write(f"Положительное событие: {draft.get('positive_class')!r}")
    st.write(f"Идентификатор: {draft.get('identifier_column') or 'не выбран'}")
    st.write(f"Признаки модели: {sum(value == 'MODEL_ALLOWED' for value in statuses.values())}")
    st.write(f"Только для анализа: {sum(value == 'DIAGNOSTIC_ONLY' for value in statuses.values())}")
    st.write(f"Исключены: {sum(value == 'BLOCKED' for value in statuses.values())}")
    st.write("Оценка: OOF на всех строках без отдельной финальной тестовой выборки")
    _render_feature_constraints(preparation, draft)
    key = _preparation_form_key(
        int(st.session_state.get("context_revision", 0)),
        preparation.snapshot.fingerprint,
        "population_acknowledged",
    )
    if key not in st.session_state:
        st.session_state[key] = bool(draft.get("population_policy_acknowledged", False))
    acknowledged = st.checkbox("Подтверждаю это условие оценки.", key=key)
    confirmation_blocked = _has_blocked_predictor_without_reason(draft)
    if confirmation_blocked:
        st.warning("Укажите причину для каждого заблокированного признака.")
    if st.button("Подтвердить и продолжить", type="primary", disabled=not acknowledged or confirmation_blocked):
        draft["population_policy_acknowledged"] = acknowledged
        _confirm_dataset_onboarding(preparation, draft)


def _target_values(report: Any, target: str) -> list[Any]:
    if not target:
        return []
    column = next((item for item in report.columns if item.column_name == target), None)
    return [item.value for item in (column.value_counts if column is not None else ()) or ()]


def _predictor_statuses(draft: Mapping[str, Any]) -> dict[str, str]:
    """Counts and summaries never classify the selected target or identifier as predictors."""
    protected = {str(draft.get("target_column") or ""), str(draft.get("identifier_column") or "")}
    return {
        name: status
        for name, status in dict(draft.get("column_statuses") or {}).items()
        if name not in protected
    }


def _render_feature_constraints(preparation: Any, draft: MutableMapping[str, Any]) -> None:
    """Render rare dataset-level permission overrides without creating another step."""
    state = st.session_state
    snapshot = preparation.snapshot
    statuses = draft.setdefault("column_statuses", {})
    reasons = draft.setdefault("blocked_reasons", {})
    protected = {str(draft.get("target_column") or ""), str(draft.get("identifier_column") or "")}
    revision = int(state.get("context_revision", 0))

    with st.expander("Ограничения признаков", expanded=False):
        st.caption("Меняйте только редкие исключения. Цель и идентификатор здесь не редактируются.")
        for name in snapshot.physical_headers:
            if name in protected:
                continue
            compatible = predictor_compatibility_error(snapshot.dataframe[name]) is None
            options = ["DIAGNOSTIC_ONLY", "BLOCKED"]
            if compatible:
                options.insert(0, "MODEL_ALLOWED")
            current = str(statuses.get(name, "DIAGNOSTIC_ONLY"))
            if current not in options:
                current = "DIAGNOSTIC_ONLY"
                _set_advanced_column_status(draft, name, current, compatible=compatible, state=state)
            status_key = _preparation_form_key(revision, snapshot.fingerprint, f"feature-status:{name}")
            if status_key not in state or state[status_key] not in options:
                state[status_key] = current
            selected = st.selectbox(
                name,
                options,
                key=status_key,
                format_func=_ADVANCED_STATUS_LABELS.__getitem__,
                on_change=_on_advanced_status_change,
                args=(draft, name, compatible, status_key),
            )
            status = str(statuses.get(name, selected))
            if status != "BLOCKED":
                continue
            reason_key = _preparation_form_key(revision, snapshot.fingerprint, f"blocked-reason:{name}")
            if reason_key not in state:
                state[reason_key] = str(reasons.get(name) or "")
            reason = st.text_input("Причина блокировки", key=reason_key)
            reasons[name] = reason.strip()


def _on_advanced_status_change(
    draft: MutableMapping[str, Any],
    name: str,
    compatible: bool,
    status_key: str,
) -> None:
    """Persist the changed status before Streamlit reruns the review screen."""
    state = st.session_state
    _set_advanced_column_status(
        draft,
        name,
        str(state.get(status_key, "DIAGNOSTIC_ONLY")),
        compatible=compatible,
        state=state,
    )


def _set_advanced_column_status(
    draft: MutableMapping[str, Any],
    name: str,
    requested_status: str,
    *,
    compatible: bool,
    state: MutableMapping[str, Any] | None = None,
) -> str:
    """Apply one advanced override, retaining technical eligibility as the MODEL_ALLOWED gate."""
    status = requested_status if requested_status in _ADVANCED_STATUS_LABELS else "DIAGNOSTIC_ONLY"
    if status == "MODEL_ALLOWED" and not compatible:
        status = "DIAGNOSTIC_ONLY"
    statuses = draft.setdefault("column_statuses", {})
    reasons = draft.setdefault("blocked_reasons", {})
    statuses[name] = status
    if status != "BLOCKED":
        reasons.pop(name, None)
        if state is not None:
            stale_keys = [key for key in state if key.endswith(f"blocked-reason:{name}")]
            for key in stale_keys:
                state.pop(key, None)
    return status


def _has_blocked_predictor_without_reason(draft: Mapping[str, Any]) -> bool:
    reasons = dict(draft.get("blocked_reasons") or {})
    return any(
        status == "BLOCKED" and not str(reasons.get(name) or "").strip()
        for name, status in _predictor_statuses(draft).items()
    )


def _render_aggregated_warnings(warnings: Any) -> None:
    counts: dict[str, int] = {}
    for warning in warnings:
        text = " ".join(warning.reasons_ru) or "Найдена особенность данных, требующая проверки."
        counts[text] = counts.get(text, 0) + 1
    for text, count in counts.items():
        prefix = f"Найдено {count}: " if count > 1 else ""
        st.warning(f"{prefix}{text}")


def _onboarding_next_button(label: str, target_step: int) -> None:
    if st.button(label, type="primary"):
        _onboarding_go_to(target_step)


def _onboarding_go_to(step: int) -> None:
    st.session_state[_PREPARATION_STEP_KEY] = step
    st.rerun()


def _confirm_dataset_onboarding(preparation: Any, draft: Mapping[str, Any]) -> None:
    state = st.session_state
    explicit_draft = dict(draft)
    explicit_draft["snapshot_fingerprint"] = preparation.snapshot.fingerprint
    explicit_draft["population_policy"] = "FULL_OOF_NO_PROTECTED_FINAL_TEST"
    state[_PREPARATION_DRAFT_KEY] = explicit_draft
    try:
        confirmed = _run_with_progress(
            _DATA_PROGRESS_LABELS,
            lambda listener: confirm_dataset_preparation(preparation, explicit_draft, progress_listener=listener),
            initial_label="Подтверждаем подготовку…", completion_label="Подготовка набора данных завершена",
        )
    except DatasetPreparationError as error:
        if error.code in _STALE_PREPARATION_ERROR_CODES:
            _invalidate_stale_preparation(state)
            st.error("Файл или результаты анализа изменились. Проверьте файл заново.")
        else:
            _render_dataset_preparation_error(error)
    except ValueError as error:
        st.error("Не удалось подтвердить подготовку данных.")
        with st.expander("Технические сведения", expanded=False):
            st.code(str(error))
    else:
        _commit_source_preparation(state, state.get(_SOURCE_CONTROL_LOCATOR_KEY, ("", "")), confirmed)
        state[_PREPARATION_STEP_KEY] = 5
        navigate_to_step(state, 1)
        st.rerun()


def _bind_positive_class_to_target(
    state: MutableMapping[str, Any],
    *,
    form_revision: int,
    snapshot_fingerprint: str,
    target: str,
    target_values: list[Any],
    placeholder: str,
    initial_target: Any,
    initial_positive_class: Any,
) -> str:
    """Invalidate the positive-class widget whenever its selected target changes."""
    positive_key = _preparation_form_key(form_revision, snapshot_fingerprint, "positive")
    target_key = _preparation_form_key(form_revision, snapshot_fingerprint, "positive_target")
    bound_target = state.get(target_key)
    if target_key not in state:
        state[target_key] = target
        state[positive_key] = (
            initial_positive_class
            if target == initial_target and initial_positive_class in target_values
            else placeholder
        )
    elif bound_target != target:
        state[target_key] = target
        state[positive_key] = placeholder
    elif not target_values or state.get(positive_key) not in target_values:
        state[positive_key] = placeholder
    return positive_key


def _preparation_form_key(
    form_revision: int,
    snapshot_fingerprint: str,
    control: str,
    column_name: str | None = None,
) -> str:
    """Scope every confirmation-form widget to one editable preparation lifecycle."""
    suffix = f"_{column_name}" if column_name is not None else ""
    return f"preparation_{form_revision}_{snapshot_fingerprint}_{control}{suffix}"


def _invalidate_stale_preparation(state: MutableMapping[str, Any]) -> None:
    """Fail closed while retaining source controls for an immediate re-check."""
    set_dataset_source_preparation(state, None)
    state[_SOURCE_RECHECK_INVALID_KEY] = False


def _render_dataset_preparation_error(error: DatasetPreparationError) -> None:
    messages = {
        "INCOMPLETE_CONFIRMATION": "Заполните цель, идентификатор и статусы всех колонок.",
        "BLOCKED_REASON_MISSING": "Для исключённой колонки укажите причину.",
        "INVALID_TARGET": "Цель должна содержать два непустых класса с достаточным числом строк.",
        "POSITIVE_CLASS_MISSING": "Выберите значение положительного класса из фактических значений цели.",
        "POPULATION_POLICY_NOT_ACKNOWLEDGED": "Подтвердите использование всей популяции для OOF-оценки.",
        "NO_MODEL_ALLOWED_FEATURES": "Разрешите для модели хотя бы одну совместимую колонку.",
        "UNSUPPORTED_PREDICTOR_REPRESENTATION": "Одна из разрешённых колонок не поддерживается моделью.",
        "NON_FINITE_PREDICTOR": "В разрешённой колонке есть нечисловые или бесконечные значения.",
        "STALE_SNAPSHOT": "Файл изменился после проверки. Проверьте файл повторно.",
        "REPORT_IDENTITY_MISMATCH": "Отчёт проверки не соответствует текущему файлу. Проверьте файл повторно.",
        "PROPOSAL_IDENTITY_MISMATCH": "Предложение не соответствует текущему файлу. Проверьте файл повторно.",
        "CONFIRMATION_IDENTITY_MISMATCH": "Черновик относится к другой версии проверки. Проверьте файл повторно.",
    }
    st.error(messages.get(error.code, "Не удалось подтвердить подготовку данных."))
    with st.expander("Технические сведения", expanded=False):
        st.code(error.code)


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
    if source_kind == "explicit_local" and local_path and (
        restoring_after_navigation or _MANUAL_LOCAL_FILE_PATH_KEY not in state
    ):
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
    st.write("**Проверенная фиксированная конфигурация**")
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
        st.write(f"Рабочая выборка: {plan.population.population_size:,} организаций.")
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
    st.caption(f"Статус валидации: {'валиден' if plan.is_valid else 'невалиден'}")


def _render_result_step(runtime) -> None:
    artifact = st.session_state.loaded_artifact
    if artifact is None:
        st.info("Текущего успешного результата нет.")
        _navigation_button(st, "← Назад", 3)
        return
    st.header("5. Результат")
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
    _render_local_model_use_flow(runtime, artifact)
    navigation = st.columns(3)
    _navigation_button(navigation[0], "← Назад", 3)
    _navigation_button(navigation[1], "В начало", 0)
    if navigation[2].button("Новый эксперимент на этих данных", type="primary"):
        return_to_experiment(st.session_state)
        st.rerun()


def _render_local_model_use_flow(runtime, artifact: Any) -> None:
    """Keep the local ModelVersion → inference → evidence sequence on Result."""
    workflow = runtime.integration_workflow_service
    context = st.session_state.get("dataset_context")
    st.divider()
    st.subheader("Применить модель к новым данным")
    capabilities = workflow.capabilities(
        experiment_artifact_id=artifact.artifact_id,
        prepared_dataset_context=context,
        loaded_model_version=st.session_state.loaded_model_version,
        prediction_batch=st.session_state.prediction_batch,
        selected_row_id=st.session_state.selected_prediction_row_id,
    )
    if st.session_state.loaded_model_version is None:
        st.write("Шаг 1. Сохранить модель")
        if st.button(
            "Сохранить модель для прогноза",
            key="save-model-version-for-inference",
            type="primary",
            disabled=capabilities["final_model_save"].state != "AVAILABLE",
        ):
            try:
                loaded = workflow.save_model(
                    experiment_artifact_id=artifact.artifact_id,
                    prepared_dataset_context=context,
                )
            except (KeyError, TypeError, ValueError, RuntimeError, OSError):
                st.error("Не удалось сохранить модель для прогноза. Результат эксперимента сохранён.")
            else:
                set_loaded_model_version(st.session_state, loaded)
                st.rerun()
        return

    loaded_model_version = st.session_state.loaded_model_version
    summary = loaded_model_version.summary
    st.success("Модель сохранена.")
    st.write(f"{summary.model_id} · признаков: {len(summary.feature_ids)} · источник: текущий эксперимент.")
    with st.expander("Технические сведения сохранённой модели", expanded=False):
        st.code(summary.model_version_id)

    st.write("Шаг 2. Выбрать файл для прогноза")
    if st.button("Выбрать файл…", key="choose-inference-local-file", type="secondary"):
        try:
            selected = choose_local_file(_SUPPORTED_SOURCE_EXTENSIONS)
        except NativeFilePickerUnavailable:
            st.warning("Не удалось открыть окно выбора файла. Укажите путь вручную ниже.")
        else:
            if selected:
                st.session_state[_INFERENCE_SELECTED_LOCAL_FILE_PATH_KEY] = selected
                st.session_state[_INFERENCE_MANUAL_LOCAL_FILE_PATH_KEY] = ""
    with st.expander("Указать расположение файла вручную", expanded=False):
        manual_path = st.text_input(
            "Путь к файлу для прогноза",
            key=_INFERENCE_MANUAL_LOCAL_FILE_PATH_KEY,
            placeholder="Выберите файл или укажите его расположение",
        )
    source_path = manual_path.strip() or st.session_state.get(_INFERENCE_SELECTED_LOCAL_FILE_PATH_KEY, "")
    if st.button(
        "Получить прогноз",
        key="run-targetless-inference",
        type="primary",
        disabled=not bool(source_path),
    ):
        try:
            snapshot = TabularReader().read(Path(source_path))
            batch = workflow.predict(loaded_model_version=loaded_model_version, snapshot=snapshot)
        except (KeyError, TypeError, ValueError, RuntimeError, OSError):
            st.error("Не удалось получить прогноз. Проверьте файл и соответствие его столбцов сохранённой модели.")
        else:
            set_prediction_batch(st.session_state, snapshot, batch)
            st.rerun()

    prediction_batch = st.session_state.prediction_batch
    if prediction_batch is None:
        return
    st.write("Шаг 3. Результаты прогноза")
    st.dataframe(
        [
            {
                "Строка": row.source_row_position + 1,
                prediction_batch.identifier_column: row.identifier_value,
                "Вероятность": row.probability,
            }
            for row in prediction_batch.rows
        ],
        hide_index=True,
        use_container_width=True,
    )
    row_ids = tuple(row.row_id for row in prediction_batch.rows)
    row_by_id = {row.row_id: row for row in prediction_batch.rows}
    selected_row_id = st.session_state.selected_prediction_row_id
    if selected_row_id not in row_by_id:
        st.session_state.pop("selected-prediction-row-widget", None)
    selected_index = row_ids.index(selected_row_id) if selected_row_id in row_by_id else 0
    selected_row_id = st.selectbox(
        "Выберите строку для объяснения",
        row_ids,
        index=selected_index,
        key="selected-prediction-row-widget",
        format_func=lambda row_id: (
            f"{row_by_id[row_id].identifier_value} · строка {row_by_id[row_id].source_row_position + 1}"
        ),
    )
    set_selected_prediction_row_id(st.session_state, selected_row_id)
    capabilities = workflow.capabilities(
        loaded_model_version=loaded_model_version,
        prediction_batch=prediction_batch,
        selected_row_id=selected_row_id,
    )
    explanation_capability = capabilities["local_explanation"]
    if explanation_capability.state == "UNSUPPORTED":
        st.info("Для этой версии модели локальное объяснение пока недоступно.")
        return
    if explanation_capability.state != "AVAILABLE":
        return
    if st.button("Показать факторы модели", key="show-local-model-factors", type="secondary"):
        try:
            evidence = workflow.explain(
                loaded_model_version=loaded_model_version,
                prediction_batch=prediction_batch,
                row_id=selected_row_id,
            )
        except (KeyError, TypeError, ValueError, RuntimeError, OSError):
            st.error("Не удалось построить локальное объяснение. Прогноз сохранён.")
        else:
            set_local_explanation_evidence(st.session_state, evidence)
            st.rerun()
    evidence = st.session_state.local_explanation_evidence
    if evidence is None:
        return
    st.write(f"Вероятность: {evidence.probability:.4f}")
    st.dataframe(
        [
            {
                "Признак / столбец": feature.column_name,
                "Значение": feature.raw_value,
                "SHAP": feature.shap_value,
                "Ранг": feature.abs_rank,
            }
            for feature in evidence.features
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption("SHAP описывает поведение модели, а не причинность.")


def _navigation_button(
    container: Any, label: str, target_step: int, *, primary: bool = False, disabled: bool = False,
) -> None:
    """Render a non-destructive wizard transition in the supplied layout slot."""
    if container.button(label, type="primary" if primary else "secondary", disabled=disabled):
        navigate_to_step(st.session_state, target_step)
        st.rerun()


def _available_wizard_steps(state: Mapping[str, Any]) -> tuple[bool, bool, bool, bool, bool]:
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
