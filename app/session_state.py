"""State transitions and invalidation rules for the sequential prototype wizard."""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any

from komus_risk.application import RunExperimentRequest
from komus_risk.contracts import FeatureUsageStatus
from komus_risk.planning import ExperimentPlan, PlanningRequestMetadata


_DEFAULTS = {
    "current_step": 0,
    "dataset_context": None,
    "dataset_source_preparation": None,
    "dataset_preparation_snapshot": None,
    "dataset_preparation_report": None,
    "dataset_preparation_proposal": None,
    "dataset_preparation_draft": None,
    "dataset_preparation_confirmation": None,
    "dataset_preparation_manifest": None,
    "dataset_preparation_step": 0,
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
    "active_model_version_id": None,
    "loaded_model_version": None,
    "inference_snapshot": None,
    "prediction_batch": None,
    "selected_prediction_row_id": None,
    "local_explanation_evidence": None,
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
    state["selected_feature_ids"] = _model_allowed_feature_ids(context)
    state["selected_model_id"] = None
    state["experiment_inputs"] = {}
    state["context_revision"] = state.get("context_revision", 0) + 1
    state["highest_reached_step"] = 0
    _clear_plan_and_result(state)


def set_dataset_source_preparation(state: MutableMapping[str, Any], preparation: Any) -> None:
    """Store resolved-source state and expose a context only when it is prepared."""
    current = state.get("dataset_source_preparation")
    if preparation is None:
        if current is None and state.get("dataset_context") is None:
            return
        state["dataset_source_preparation"] = None
        state["dataset_context"] = None
        state["dataset_preparation_step"] = 0
        _clear_preparation_transients(state)
        state["selected_feature_ids"] = ()
        state["selected_model_id"] = None
        state["experiment_inputs"] = {}
        state["current_step"] = 0
        state["context_revision"] = state.get("context_revision", 0) + 1
        state["highest_reached_step"] = 0
        _clear_plan_and_result(state)
        return
    same_source_and_status = (
        getattr(current, "source", None) == getattr(preparation, "source", None)
        and getattr(current, "preparation_status", None) == getattr(preparation, "preparation_status", None)
    )
    if (
        same_source_and_status
        and _same_prepared_dataset_identity(current, preparation)
    ):
        # A repeated successful confirmation with identical context provenance is a no-op.
        state["dataset_source_preparation"] = preparation
        _store_preparation_transients(state, preparation)
        return
    if _same_prepared_dataset_identity(current, preparation):
        state["dataset_source_preparation"] = preparation
        _store_preparation_transients(state, preparation)
        return
    state["dataset_source_preparation"] = preparation
    state["dataset_context"] = getattr(preparation, "context", None)
    state["dataset_preparation_step"] = 0
    _store_preparation_transients(state, preparation)
    state["selected_feature_ids"] = _model_allowed_feature_ids(state["dataset_context"])
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
    _clear_integration_state(state)
    state["loaded_artifact"] = artifact
    state["comparison_result"] = comparison
    state["last_successful_artifact_id"] = artifact.artifact_id
    state["current_step"] = 4
    state["highest_reached_step"] = 4


def return_to_experiment(state: MutableMapping[str, Any]) -> None:
    """Start another experiment on the prepared context without re-preparing it."""
    _clear_plan_and_result(state)
    state["current_step"] = 1
    state["highest_reached_step"] = max(int(state.get("highest_reached_step", 0)), 1)


def _model_allowed_feature_ids(context: Any) -> tuple[str, ...]:
    """Read the initial experiment set from the prepared FeatureRegistry only."""
    registry = getattr(context, "feature_registry", None)
    groups = getattr(registry, "_groups", {})
    if registry is None or not isinstance(groups, dict):
        return ()
    feature_ids: list[str] = []
    for group in groups.values():
        for spec in registry.resolve(getattr(group, "feature_ids", ())):
            if spec.usage_status is FeatureUsageStatus.MODEL_ALLOWED:
                feature_ids.append(spec.feature_id)
    return tuple(feature_ids)


def _clear_plan_and_result(state: MutableMapping[str, Any]) -> None:
    state["planning_request_snapshot"] = None
    state["experiment_plan"] = None
    state["loaded_artifact"] = None
    state["comparison_result"] = None
    _clear_integration_state(state)


def set_loaded_model_version(state: MutableMapping[str, Any], loaded_model_version: Any) -> None:
    """Activate a new saved model and invalidate its downstream local use data."""
    if loaded_model_version is state.get("loaded_model_version"):
        return
    state["loaded_model_version"] = loaded_model_version
    state["active_model_version_id"] = getattr(getattr(loaded_model_version, "summary", None), "model_version_id", None)
    _clear_inference_state(state)


def set_prediction_batch(state: MutableMapping[str, Any], snapshot: Any, prediction_batch: Any) -> None:
    """Store one targetless inference result and reset row-level state."""
    if snapshot is state.get("inference_snapshot") and prediction_batch is state.get("prediction_batch"):
        return
    state["inference_snapshot"] = snapshot
    state["prediction_batch"] = prediction_batch
    state["selected_prediction_row_id"] = None
    state["local_explanation_evidence"] = None


def set_selected_prediction_row_id(state: MutableMapping[str, Any], row_id: str | None) -> None:
    """Change the selected prediction row without clearing evidence for the same row."""
    if row_id == state.get("selected_prediction_row_id"):
        return
    state["selected_prediction_row_id"] = row_id
    state["local_explanation_evidence"] = None


def set_local_explanation_evidence(state: MutableMapping[str, Any], evidence: Any) -> None:
    state["local_explanation_evidence"] = evidence


def _clear_inference_state(state: MutableMapping[str, Any]) -> None:
    state["inference_snapshot"] = None
    state["prediction_batch"] = None
    state["selected_prediction_row_id"] = None
    state["local_explanation_evidence"] = None


def _clear_integration_state(state: MutableMapping[str, Any]) -> None:
    state["active_model_version_id"] = None
    state["loaded_model_version"] = None
    _clear_inference_state(state)


def _store_preparation_transients(state: MutableMapping[str, Any], preparation: Any) -> None:
    """Keep analysis artefacts tied to the currently checked physical source."""
    state["dataset_preparation_snapshot"] = getattr(preparation, "snapshot", None)
    state["dataset_preparation_report"] = getattr(preparation, "inspection_report", None)
    state["dataset_preparation_proposal"] = getattr(preparation, "proposal", None)
    state["dataset_preparation_confirmation"] = getattr(preparation, "confirmation", None)
    state["dataset_preparation_manifest"] = getattr(preparation, "manifest", None)
    if getattr(preparation, "preparation_status", None) != "confirmed_context_prepared":
        state["dataset_preparation_draft"] = None


def _clear_preparation_transients(state: MutableMapping[str, Any]) -> None:
    for key in (
        "dataset_preparation_snapshot",
        "dataset_preparation_report",
        "dataset_preparation_proposal",
        "dataset_preparation_draft",
        "dataset_preparation_confirmation",
        "dataset_preparation_manifest",
    ):
        state[key] = None


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
