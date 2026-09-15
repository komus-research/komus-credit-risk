"""State transitions and invalidation rules for the sequential prototype wizard."""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any

from komus_risk.application import RunExperimentRequest
from komus_risk.planning import ExperimentPlan, PlanningRequestMetadata


_DEFAULTS = {
    "current_step": 0,
    "dataset_context": None,
    "dataset_source_preparation": None,
    "selected_feature_ids": (),
    "selected_model_id": None,
    "experiment_inputs": {},
    "planning_request_snapshot": None,
    "experiment_plan": None,
    "loaded_artifact": None,
    "comparison_result": None,
    "last_successful_artifact_id": None,
    "context_revision": 0,
    "highest_reached_step": 0,
}


def initialize(state: MutableMapping[str, Any]) -> None:
    for key, value in _DEFAULTS.items():
        state.setdefault(key, value)
    if "highest_reached_step" not in state:
        state["highest_reached_step"] = 0
    state["highest_reached_step"] = max(
        int(state["highest_reached_step"]),
        int(state.get("current_step", 0)),
        4 if state.get("loaded_artifact") is not None else 0,
    )


def navigate_to_step(state: MutableMapping[str, Any], step: int) -> None:
    """Move through the wizard without changing any scientific or session state."""
    if step not in range(5):
        raise ValueError("Неизвестный шаг мастера.")
    state["current_step"] = step
    state["highest_reached_step"] = max(int(state.get("highest_reached_step", 0)), step)


def set_dataset_context(state: MutableMapping[str, Any], context: Any) -> None:
    current = state.get("dataset_context")
    current_id = getattr(current, "context_id", None)
    current_fingerprint = getattr(getattr(current, "loaded_dataset", None), "contract", None)
    next_fingerprint = getattr(getattr(context, "loaded_dataset", None), "contract", None)
    if current_id == getattr(context, "context_id", None) and current_fingerprint == next_fingerprint:
        return
    state["dataset_context"] = context
    state["dataset_source_preparation"] = None
    state["selected_feature_ids"] = ()
    state["selected_model_id"] = None
    state["experiment_inputs"] = {}
    state["context_revision"] = state.get("context_revision", 0) + 1
    state["highest_reached_step"] = 0
    _clear_plan_and_result(state)


def set_dataset_source_preparation(state: MutableMapping[str, Any], preparation: Any) -> None:
    """Store resolved-source state and expose a context only when it is prepared."""
    current = state.get("dataset_source_preparation")
    if (
        getattr(current, "source", None) == getattr(preparation, "source", None)
        and getattr(current, "preparation_status", None) == getattr(preparation, "preparation_status", None)
    ):
        return
    if _same_prepared_dataset_identity(current, preparation):
        state["dataset_source_preparation"] = preparation
        return
    state["dataset_source_preparation"] = preparation
    state["dataset_context"] = getattr(preparation, "context", None)
    state["selected_feature_ids"] = ()
    state["selected_model_id"] = None
    state["experiment_inputs"] = {}
    state["current_step"] = 0
    state["context_revision"] = state.get("context_revision", 0) + 1
    state["highest_reached_step"] = 0
    _clear_plan_and_result(state)


def set_selected_feature_ids(state: MutableMapping[str, Any], feature_ids: Iterable[str]) -> None:
    selected = tuple(feature_ids)
    if selected == state.get("selected_feature_ids", ()):
        return
    if len(selected) != len(set(selected)):
        raise ValueError("Выбранные признаки не должны повторяться.")
    state["selected_feature_ids"] = selected
    _clear_plan_and_result(state)


def toggle_feature(state: MutableMapping[str, Any], feature_id: str, selected: bool) -> None:
    current = list(state.get("selected_feature_ids", ()))
    if selected and feature_id not in current:
        current.append(feature_id)
    elif not selected and feature_id in current:
        current.remove(feature_id)
    set_selected_feature_ids(state, current)


def set_group_selection(state: MutableMapping[str, Any], group_feature_ids: Iterable[str], selected: bool) -> None:
    current = list(state.get("selected_feature_ids", ()))
    group_ids = tuple(group_feature_ids)
    if selected:
        current.extend(feature_id for feature_id in group_ids if feature_id not in current)
    else:
        current = [feature_id for feature_id in current if feature_id not in group_ids]
    set_selected_feature_ids(state, current)


def synchronize_feature_widgets(
    state: MutableMapping[str, Any],
    group_feature_ids: Iterable[str],
    *,
    group_widget_key: str,
    feature_widget_keys: dict[str, str],
) -> None:
    """Mirror canonical selection into widgets before they are rendered."""
    group_ids = tuple(group_feature_ids)
    selected = set(state.get("selected_feature_ids", ()))
    for feature_id in group_ids:
        state[feature_widget_keys[feature_id]] = feature_id in selected
    state[group_widget_key] = bool(group_ids) and all(feature_id in selected for feature_id in group_ids)


def apply_group_widget_selection(
    state: MutableMapping[str, Any],
    group_feature_ids: Iterable[str],
    *,
    group_widget_key: str,
    feature_widget_keys: dict[str, str],
) -> None:
    """Apply a group checkbox event, then synchronize every selectable child."""
    set_group_selection(state, group_feature_ids, bool(state[group_widget_key]))
    synchronize_feature_widgets(
        state,
        group_feature_ids,
        group_widget_key=group_widget_key,
        feature_widget_keys=feature_widget_keys,
    )


def apply_feature_widget_selection(
    state: MutableMapping[str, Any],
    feature_id: str,
    group_feature_ids: Iterable[str],
    *,
    group_widget_key: str,
    feature_widget_keys: dict[str, str],
) -> None:
    """Apply an individual checkbox event and refresh the aggregate group state."""
    toggle_feature(state, feature_id, bool(state[feature_widget_keys[feature_id]]))
    synchronize_feature_widgets(
        state,
        group_feature_ids,
        group_widget_key=group_widget_key,
        feature_widget_keys=feature_widget_keys,
    )


def set_selected_model_id(state: MutableMapping[str, Any], model_id: str | None) -> None:
    if model_id == state.get("selected_model_id"):
        return
    state["selected_model_id"] = model_id
    _clear_plan_and_result(state)


def set_experiment_inputs(state: MutableMapping[str, Any], values: dict[str, Any]) -> None:
    normalized = dict(values)
    if normalized == state.get("experiment_inputs", {}):
        return
    state["experiment_inputs"] = normalized
    _clear_plan_and_result(state)


def save_plan(state: MutableMapping[str, Any], snapshot: PlanningRequestMetadata, plan: ExperimentPlan) -> None:
    state["planning_request_snapshot"] = snapshot
    state["experiment_plan"] = plan
    state["loaded_artifact"] = None
    state["comparison_result"] = None


def can_run(state: MutableMapping[str, Any]) -> bool:
    snapshot = state.get("planning_request_snapshot")
    plan = state.get("experiment_plan")
    return isinstance(snapshot, PlanningRequestMetadata) and isinstance(plan, ExperimentPlan) and plan.is_valid and plan.request == snapshot


def run_request_from_snapshot(snapshot: PlanningRequestMetadata) -> RunExperimentRequest:
    """Build the execution request only from the snapshot used by ExperimentPlan."""
    return RunExperimentRequest(
        selected_feature_ids=snapshot.selected_feature_ids,
        model_id=snapshot.model_id,
        protocol_id=snapshot.protocol_id,
        protocol_version=snapshot.protocol_version,
        seed=snapshot.seed,
        folds=snapshot.folds,
        evaluation_level=snapshot.evaluation_level,
        reference_artifact_id=snapshot.reference_artifact_id,
        changed_dimension=snapshot.changed_dimension,
        changed_elements=snapshot.changed_elements,
    )


def save_artifact(state: MutableMapping[str, Any], artifact: Any, comparison: Any | None) -> None:
    state["loaded_artifact"] = artifact
    state["comparison_result"] = comparison
    state["last_successful_artifact_id"] = artifact.artifact_id
    state["current_step"] = 4
    state["highest_reached_step"] = 4


def return_to_experiment(state: MutableMapping[str, Any]) -> None:
    """Start a new plan while preserving the session's saved comparison reference."""
    _clear_plan_and_result(state)
    state["current_step"] = 3


def _clear_plan_and_result(state: MutableMapping[str, Any]) -> None:
    state["planning_request_snapshot"] = None
    state["experiment_plan"] = None
    state["loaded_artifact"] = None
    state["comparison_result"] = None


def _same_prepared_dataset_identity(current: Any, next_preparation: Any) -> bool:
    """Recognize an accepted dataset copied to another local path without resetting work."""
    current_context = getattr(current, "context", None)
    next_context = getattr(next_preparation, "context", None)
    if current_context is None or next_context is None:
        return False
    identity = _prepared_context_identity(current_context)
    return identity != (None, None, None, None) and identity == _prepared_context_identity(next_context)


def _prepared_context_identity(context: Any) -> tuple[Any, Any, Any, Any]:
    contract = getattr(getattr(context, "loaded_dataset", None), "contract", None)
    population = getattr(context, "population", None)
    return (
        getattr(context, "context_id", None),
        getattr(contract, "dataset_id", contract),
        getattr(contract, "dataset_fingerprint", None),
        getattr(population, "population_fingerprint", None),
    )
