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
    return_to_experiment,
    save_artifact,
    save_plan,
    set_dataset_context,
    set_experiment_inputs,
    set_selected_model_id,
    synchronize_feature_widgets,
)
from komus_risk.planning import PlanningRequestMetadata


_STEPS = ("Данные", "Признаки", "Модель", "Эксперимент", "Результат")
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


def _progress_description(event: Any, labels: Mapping[str, str]) -> str:
    """Turn only emitted runtime stages into user-facing status text."""
    stage = event if isinstance(event, str) else getattr(event, "stage", "")
    description = labels.get(stage, "Выполняется подтверждённый этап")
    fold_number = getattr(event, "fold_number", None)
    folds_total = getattr(event, "folds_total", None)
    if fold_number is not None and folds_total is not None:
        return f"{description}: {fold_number} из {folds_total}"
    return description


def _run_with_progress(labels: Mapping[str, str], operation):
    """Render observed stages; completion is shown only after the operation returns."""
    status = st.status("Подготовка операции", expanded=True)

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
    status.update(label="Операция успешно завершена", state="complete", expanded=False)
    return result


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
            context = _run_with_progress(
                _DATA_PROGRESS_LABELS,
                lambda listener: resolve_context(selected_id, uploaded, progress_listener=listener),
            )
            set_dataset_context(st.session_state, context)
        except (FileNotFoundError, ValueError):
            st.error("Не удалось подготовить данные. Проверьте выбранный контекст и файл.")

    context = st.session_state.dataset_context
    if context is None:
        st.info("Выберите и подготовьте контекст данных, чтобы продолжить.")
        return
    passport = context.loaded_dataset.contract
    st.subheader(context.display_name)
    columns = st.columns(3)
    columns[0].metric("Организации / строки", f"{passport.row_count:,}")
    columns[1].metric("Рабочая выборка", f"{len(context.population.row_positions):,}")
    columns[2].metric("Защищённая контрольная выборка", f"{passport.row_count - len(context.population.row_positions):,}")
    st.write("**Цель:** признак дефолта организации.")
    st.info("Контрольная выборка не используется при выборе и настройке модели; она сохранена для финальной проверки.")
    with st.expander("Технические сведения"):
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
        })
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
        containers = st.columns(3) if len(selectable_ids) > 12 else (st,)
        for index, view in enumerate(group_views):
            with containers[index % len(containers)]:
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
    st.subheader(model.display_name_ru)
    st.write(model.description_ru)
    st.write("**Проверенная фиксированная конфигурация**")
    st.write(f"Версия: {model.model_version}")
    with st.expander("Технические параметры"):
        st.caption("Замороженный профиль и требования runtime доступны только для технической проверки.")
        st.json(_plain(model.default_profile))
        st.json(_plain(model.runtime_requirements))
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
    if st.button("Новый эксперимент", type="primary"):
        return_to_experiment(st.session_state)
        st.rerun()


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
