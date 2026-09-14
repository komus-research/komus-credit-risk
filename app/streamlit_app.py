"""Single-page Streamlit prototype over the accepted Pipeline V1 services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import streamlit as st

from app.bootstrap import create_runtime, list_available_contexts, resolve_context, validate_supported_protocol
from app.session_state import (
    apply_feature_widget_selection,
    apply_group_widget_selection,
    can_run,
    initialize,
    run_request_from_snapshot,
    save_artifact,
    save_plan,
    set_dataset_context,
    set_experiment_inputs,
    set_selected_model_id,
    synchronize_feature_widgets,
)
from komus_risk.planning import PlanningRequestMetadata


_STEPS = ("Данные", "Признаки", "Модель", "Эксперимент", "Результат")


@st.cache_resource
def _runtime():
    return create_runtime()


def main() -> None:
    st.set_page_config(page_title="KOMUS · Prototype V1", layout="wide")
    initialize(st.session_state)
    runtime = _runtime()
    step = st.session_state.current_step
    st.title("KOMUS · Experiment Prototype V1")
    st.caption(" → ".join(f"{'●' if index == step else '○'} {name}" for index, name in enumerate(_STEPS)))

    if step == 0:
        _render_data_step()
    elif step == 1:
        _render_features_step(runtime)
    elif step == 2:
        _render_models_step(runtime)
    elif step == 3:
        _render_experiment_step(runtime)
    else:
        _render_result_step()


def _render_data_step() -> None:
    st.header("1. Данные")
    options = list_available_contexts()
    if not options:
        st.error("Нет подготовленных контекстов данных.")
        return
    by_id = {option.context_id: option for option in options}
    selected_id = st.selectbox(
        "Подготовленный контекст",
        tuple(by_id),
        format_func=lambda context_id: by_id[context_id].display_name,
        key="prototype_context_id",
    )
    option = by_id[selected_id]
    uploaded = None
    if option.upload_capable:
        uploaded = st.file_uploader(
            "Загрузить файл для выбранного контекста (необязательно)",
            key="prototype_upload",
            help="Файл проверяется только правилами выбранного подготовленного контекста.",
        )
    if st.button("Подготовить контекст", type="primary"):
        try:
            set_dataset_context(st.session_state, resolve_context(selected_id, uploaded))
        except (FileNotFoundError, ValueError):
            st.error("Не удалось подготовить данные. Проверьте выбранный контекст и файл.")

    context = st.session_state.dataset_context
    if context is None:
        st.info("Выберите и подготовьте контекст данных, чтобы продолжить.")
        return
    passport = context.loaded_dataset.contract
    st.subheader(context.display_name)
    columns = st.columns(3)
    columns[0].write(f"**Набор:** {passport.dataset_name} · {passport.dataset_version}")
    columns[0].write(f"**Источник:** {passport.source_type}")
    columns[1].write(f"**Строк / столбцов:** {passport.row_count:,} / {passport.column_count}")
    columns[1].write(f"**Цель:** {passport.target_column}; положительный класс: {passport.positive_class}")
    columns[2].write(f"**Идентификатор:** {passport.identifier_column}")
    columns[2].write(f"**Статус:** {passport.validation_status}; final test locked: {'да' if passport.final_test_locked else 'нет'}")
    st.caption(f"Fingerprint: {passport.dataset_fingerprint[:12]}…")
    with st.expander("Технические сведения"):
        st.code(passport.dataset_fingerprint)
    if st.button("Далее: признаки", type="primary"):
        st.session_state.current_step = 1
        st.rerun()


def _render_features_step(runtime) -> None:
    context = _context_or_previous_step()
    if context is None:
        return
    st.header("2. Признаки")
    views = runtime.planning_service.list_features(context.feature_registry)
    groups = runtime.planning_service.list_feature_groups(context.feature_registry)
    views_by_group = {group.group_id: [view for view in views if view.group_id == group.group_id] for group in groups}
    selected = st.session_state.selected_feature_ids
    revision = st.session_state.context_revision
    for group in groups:
        group_views = views_by_group[group.group_id]
        selectable_ids = tuple(view.feature_id for view in group_views if view.selectable)
        group_widget_key = f"prototype_{revision}_group_{group.group_id}"
        feature_widget_keys = {
            feature_id: f"prototype_{revision}_feature_{feature_id}"
            for feature_id in selectable_ids
        }
        if selectable_ids:
            synchronize_feature_widgets(
                st.session_state,
                selectable_ids,
                group_widget_key=group_widget_key,
                feature_widget_keys=feature_widget_keys,
            )
        selected_count = sum(feature_id in selected for feature_id in selectable_ids)
        st.subheader(f"{group.name_ru} · {selected_count}/{len(selectable_ids)}")
        st.caption(group.description_ru)
        st.checkbox(
            "Выбрать всю группу",
            key=group_widget_key,
            disabled=not selectable_ids,
            on_change=_on_group_widget_change if selectable_ids else None,
            args=(selectable_ids, group_widget_key, feature_widget_keys) if selectable_ids else None,
        )
        for view in group_views:
            label = f"{view.display_name_ru} — {view.description_ru}"
            if not view.selectable:
                reason = view.blocked_reason or f"Статус: {view.usage_status.value}"
                st.checkbox(label, value=False, disabled=True, key=f"prototype_{revision}_feature_{view.feature_id}", help=reason)
                continue
            st.checkbox(
                label,
                key=feature_widget_keys[view.feature_id],
                on_change=_on_feature_widget_change,
                args=(view.feature_id, selectable_ids, group_widget_key, feature_widget_keys),
            )
    if not st.session_state.selected_feature_ids:
        st.warning("Выберите хотя бы один разрешённый признак.")
    navigation = st.columns(2)
    if navigation[0].button("Назад"):
        st.session_state.current_step = 0
        st.rerun()
    if navigation[1].button("Далее: модель", type="primary", disabled=not st.session_state.selected_feature_ids):
        st.session_state.current_step = 2
        st.rerun()


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
    st.write(model.description_ru)
    st.write(f"Версия: {model.model_version}")
    st.json(_plain(model.runtime_requirements))
    with st.expander("Замороженный профиль и технические сведения"):
        st.json(_plain(model.default_profile))
        st.caption(f"model_id: {model.model_id}; adapter version: {model.adapter_version}")
    navigation = st.columns(2)
    if navigation[0].button("Назад"):
        st.session_state.current_step = 1
        st.rerun()
    if navigation[1].button("Далее: эксперимент", type="primary"):
        st.session_state.current_step = 3
        st.rerun()


def _render_experiment_step(runtime) -> None:
    context = _context_or_previous_step()
    if context is None or not st.session_state.selected_feature_ids or not st.session_state.selected_model_id:
        st.warning("Сначала подтвердите признаки и модель.")
        return
    st.header("4. Эксперимент")
    previous = st.session_state.experiment_inputs
    revision = st.session_state.context_revision
    protocol = runtime.supported_protocol
    st.text_input("Протокол", value=protocol.protocol_id, disabled=True, key=f"prototype_{revision}_protocol")
    st.text_input("Версия протокола", value=protocol.protocol_version, disabled=True, key=f"prototype_{revision}_protocol_version")
    seed = st.number_input("Seed", min_value=0, value=int(previous.get("seed", protocol.default_seed)), step=1, key=f"prototype_{revision}_seed")
    folds = st.number_input("Фолды", min_value=protocol.minimum_folds, value=max(int(previous.get("folds", protocol.default_folds)), protocol.minimum_folds), step=1, key=f"prototype_{revision}_folds")
    st.text_input("Уровень оценки", value=protocol.evaluation_level, disabled=True, key=f"prototype_{revision}_evaluation")
    reference_artifact_id = st.text_input("Reference artifact ID (необязательно)", value=previous.get("reference_artifact_id", ""), key=f"prototype_{revision}_reference")
    changed_dimension = st.selectbox(
        "Изменённое измерение",
        ("", "model", "feature_set"),
        index=("", "model", "feature_set").index(previous.get("changed_dimension") or ""),
        format_func=lambda value: "Не указано" if not value else value,
        key=f"prototype_{revision}_changed_dimension",
    )
    changed_elements_text = st.text_area(
        "Изменённые элементы (по одному в строке)",
        value="\n".join(previous.get("changed_elements", ())),
        key=f"prototype_{revision}_changed_elements",
    )
    values = {
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.protocol_version,
        "seed": int(seed),
        "folds": int(folds),
        "evaluation_level": protocol.evaluation_level,
        "reference_artifact_id": reference_artifact_id.strip() or None,
        "changed_dimension": changed_dimension or None,
        "changed_elements": tuple(item.strip() for item in changed_elements_text.splitlines() if item.strip()),
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
            st.error("Проверьте параметры эксперимента и декларацию изменения для reference.")
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
            artifact = runtime.application_service.run_experiment(
                loaded_dataset=context.loaded_dataset,
                feature_registry=context.feature_registry,
                population=context.population,
                request=run_request_from_snapshot(snapshot),
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
    st.write(f"Датасет: {plan.dataset.dataset_name} · {plan.dataset.dataset_version}; final test locked: {'да' if plan.dataset.final_test_locked else 'нет'}")
    st.write(f"Признаки: {', '.join(plan.selected_feature_ids)}")
    st.write(f"Группы: {', '.join(plan.feature_groups)}")
    st.write(f"Модель: {plan.model.display_name_ru if plan.model else 'не найдена'}")
    if plan.model:
        with st.expander("Замороженный профиль модели"):
            st.json(_plain(plan.model.default_profile))
    request = plan.request
    st.write(f"Протокол: {request.protocol_id} v{request.protocol_version}; seed: {request.seed}; folds: {request.folds}; level: {request.evaluation_level}")
    st.write(f"Популяция: {plan.population.population_id} · {plan.population.population_size:,} · {plan.population.partition_role}")
    st.write(f"Reference: {request.reference_artifact_id or 'не задан'}")
    st.write(f"Изменение: {request.changed_dimension or 'не задано'}; элементы: {', '.join(request.changed_elements) or 'не заданы'}")
    st.write(f"Статус валидации: {'валиден' if plan.is_valid else 'невалиден'}")


def _render_result_step() -> None:
    artifact = st.session_state.loaded_artifact
    if artifact is None:
        st.info("Текущего успешного результата нет.")
        if st.button("Вернуться к эксперименту"):
            st.session_state.current_step = 3
            st.rerun()
        return
    st.header("5. Результат")
    result = artifact.run_output.result
    metrics = result.metrics
    labels = (
        ("gini", "Gini"), ("roc_auc", "ROC-AUC"), ("pr_auc", "PR-AUC"),
        ("precision_at_0_5", "Precision@0.5"), ("recall_at_0_5", "Recall@0.5"), ("f1_at_0_5", "F1@0.5"),
    )
    columns = st.columns(3)
    for index, (key, label) in enumerate(labels):
        columns[index % 3].metric(label, _number(metrics.get(key)))
    st.subheader("Матрица ошибок")
    st.json(_plain(result.confusion))
    st.write(f"Runtime: {_number(result.runtime_seconds)} s; evaluation: {result.evaluation_level}")
    with st.expander("Метрики фолдов"):
        st.json(_plain(result.fold_metrics))
    with st.expander("Ограничения"):
        for limitation in result.limitations:
            st.write(f"- {limitation}")
    st.caption(f"Artifact ID: {artifact.artifact_id}; Result ID: {result.result_id}")
    comparison = st.session_state.comparison_result
    if comparison is not None:
        st.subheader("Сопоставление с reference")
        st.write(f"Сопоставимы: {'да' if comparison.is_comparable else 'нет'}")
        st.write(f"Причины: {', '.join(comparison.reason_codes) or 'не указаны'}")
        st.write(f"Изменённое измерение: {comparison.changed_dimension or 'не указано'}")
        st.json({"metrics": comparison.metric_deltas, "confusion": comparison.confusion_deltas, "feature_change": comparison.feature_change, "model_change": comparison.model_change})


def _context_or_previous_step():
    context = st.session_state.dataset_context
    if context is not None:
        return context
    st.warning("Сначала подготовьте контекст данных.")
    if st.button("К данным"):
        st.session_state.current_step = 0
        st.rerun()
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
