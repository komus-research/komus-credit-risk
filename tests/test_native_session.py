"""Tests for framework-neutral native AXION session transitions."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from komus_risk.application.native_session import (
    DatasetInspectionStage,
    DatasetInspectionStatus,
    NativeSessionTransitionError,
    NativeSessionStore,
    NewAnalysisStatus,
)


def test_session_is_created_and_reused() -> None:
    store = NativeSessionStore()

    session_id, created = store.get_or_create(None)
    reused_id, reused = store.get_or_create(session_id)

    assert session_id == reused_id
    assert created == reused
    assert created.current_step == 0
    assert not created.analysis_active
    assert created.data_substep == "FILE"
    assert not created.has_meaningful_temporary_work
    assert created.resume_route == "#/home"


def test_clean_new_analysis_starts_at_data_step() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)

    result = store.start_new_analysis(session_id)

    assert result.status is NewAnalysisStatus.STARTED
    assert result.session.current_step == 0
    assert result.session.analysis_active
    assert result.session.data_substep == "FILE"
    assert not result.session.has_meaningful_temporary_work
    assert result.session.resume_route == "#/analysis/data/file"


def test_meaningful_work_requires_confirmation_without_mutation() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    before = store.mark_meaningful_temporary_work(session_id)

    result = store.start_new_analysis(session_id)

    assert result.status is NewAnalysisStatus.CONFIRMATION_REQUIRED
    assert result.session == before
    assert store.snapshot(session_id) == before


def test_confirmed_reset_clears_only_transient_native_state() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    store.mark_meaningful_temporary_work(session_id)

    result = store.start_new_analysis(session_id, confirm_reset=True)

    assert result.status is NewAnalysisStatus.STARTED
    assert result.session.current_step == 0
    assert not result.session.has_meaningful_temporary_work


def test_dataset_inspection_progress_keeps_real_stage_transitions() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)

    token = store.start_dataset_inspection(session_id)
    assert store.snapshot(session_id).has_meaningful_temporary_work
    started = store.dataset_inspection_progress(session_id)
    store.update_dataset_inspection_progress(session_id, token, DatasetInspectionStage.STAGING_FILE)
    store.update_dataset_inspection_progress(session_id, token, DatasetInspectionStage.READING_SOURCE)
    store.finish_dataset_inspection(session_id, token)
    finished = store.dataset_inspection_progress(session_id)

    assert started.status is DatasetInspectionStatus.RUNNING
    assert started.stage is DatasetInspectionStage.RECEIVING_FILE
    assert finished.status is DatasetInspectionStatus.READY
    assert finished.stage is DatasetInspectionStage.READY
    assert finished.started_at == started.started_at
    assert finished.updated_at >= started.updated_at


def test_running_inspection_requires_confirmation_and_reset_supersedes_it() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    token = store.start_dataset_inspection(session_id)
    staged_upload = object()
    assert store.set_inspection_upload(session_id, token, staged_upload)
    before = store.dataset_inspection_progress(session_id)

    blocked = store.start_new_analysis(session_id)

    assert blocked.status is NewAnalysisStatus.CONFIRMATION_REQUIRED
    assert store.dataset_inspection_progress(session_id) == before
    assert store.start_new_analysis(session_id, confirm_reset=True).discarded_upload == (
        None,
        staged_upload,
    )
    assert store.dataset_inspection_progress(session_id).status is DatasetInspectionStatus.IDLE
    assert not store.update_dataset_inspection_progress(
        session_id, token, DatasetInspectionStage.READING_SOURCE
    )
    assert not store.finish_dataset_inspection(session_id, token)
    assert not store.snapshot(session_id).has_meaningful_temporary_work


def test_failed_first_inspection_clears_meaningful_work() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    token = store.start_dataset_inspection(session_id)

    assert store.snapshot(session_id).has_meaningful_temporary_work
    assert store.fail_dataset_inspection(session_id, token)
    assert not store.snapshot(session_id).has_meaningful_temporary_work
    assert store.dataset_inspection_progress(session_id).status is DatasetInspectionStatus.ERROR


def test_dataset_inspection_error_and_reset_are_session_owned() -> None:
    store = NativeSessionStore()
    first, _ = store.get_or_create(None)
    second, _ = store.get_or_create(None)
    token = store.start_dataset_inspection(first)
    store.fail_dataset_inspection(first, token)

    failed = store.dataset_inspection_progress(first)
    assert failed.status is DatasetInspectionStatus.ERROR
    assert failed.message == "Не удалось обработать загруженный файл."
    assert store.dataset_inspection_progress(second).status is DatasetInspectionStatus.IDLE

    store.start_new_analysis(first, confirm_reset=True)
    assert store.dataset_inspection_progress(first).status is DatasetInspectionStatus.IDLE


def test_native_session_module_has_no_frontend_or_persistence_dependencies() -> None:
    source = Path("src/komus_risk/application/native_session.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    references = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    references.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    references.update(
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
        for alias in node.names
    )
    references.update(
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    )
    references.update(
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    )

    assert not any(
        reference == "streamlit" or reference.startswith("streamlit.")
        for reference in references
    )
    assert {"ExperimentArtifactStore", "ModelVersionStore", "komus_risk.artifacts"}.isdisjoint(
        references
    )


def test_orphaned_prepared_context_from_algorithm_clears_feature_step_and_returns_to_roles() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    transient = store._sessions[session_id]
    transient.inspected_dataset = object()
    transient.preparation_draft = object()
    transient.analysis_active = True
    transient.data_substep = "PREPARED"
    transient.prepared_context_id = "missing-context"
    transient.selected_feature_ids = ("feature-a",)
    transient.features_completed = True
    transient.current_step = 2

    reconciled = store.reconcile_prepared_context(session_id, lambda _context_id: False)

    assert reconciled.current_step == 0
    assert reconciled.data_substep == "ROLES"
    assert reconciled.resume_route == "#/analysis/data/roles"
    assert transient.prepared_context_id is None
    assert transient.selected_feature_ids is None
    assert not transient.features_completed


def test_data_transitions_are_strict_and_fail_without_mutation() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)
    store.set_dataset(
        session_id,
        staged_upload=None,
        inspected_dataset=object(),
        preparation_draft=object(),
    )

    with pytest.raises(NativeSessionTransitionError) as invalid_back:
        store.return_to_roles(session_id)
    assert invalid_back.value.code == "INVALID_DATA_TRANSITION"
    assert store.snapshot(session_id).data_substep == "ROLES"

    store.begin_confirmation(session_id)
    before_confirmation = store.snapshot(session_id)
    with pytest.raises(NativeSessionTransitionError):
        store.begin_confirmation(session_id)
    assert store.snapshot(session_id) == before_confirmation

    store.return_to_roles(session_id)
    before_roles = store.snapshot(session_id)
    with pytest.raises(NativeSessionTransitionError):
        store.return_to_roles(session_id)
    assert store.snapshot(session_id) == before_roles

    store.begin_confirmation(session_id)
    store.set_prepared_context(session_id, "trusted-context")
    before_prepared = store.snapshot(session_id)
    with pytest.raises(NativeSessionTransitionError):
        store.begin_confirmation(session_id)
    with pytest.raises(NativeSessionTransitionError):
        store.return_to_roles(session_id)
    assert store.snapshot(session_id) == before_prepared


def test_confirmation_reservation_is_session_local_and_releases_on_abort() -> None:
    store = NativeSessionStore()
    first_id, _ = store.get_or_create(None)
    second_id, _ = store.get_or_create(None)
    for session_id in (first_id, second_id):
        store.set_dataset(
            session_id,
            staged_upload=None,
            inspected_dataset=object(),
            preparation_draft=object(),
        )
        store.begin_confirmation(session_id)

    operation_token, _, _ = store.begin_confirmation_materialization(first_id)

    with pytest.raises(NativeSessionTransitionError):
        store.begin_confirmation_materialization(first_id)
    with pytest.raises(NativeSessionTransitionError):
        store.return_to_roles(first_id)
    # The second session remains mutable while the first is reserved.
    assert store.return_to_roles(second_id).data_substep == "ROLES"
    assert store.abort_confirmation_materialization(first_id, operation_token)
    assert store.snapshot(first_id).data_substep == "CONFIRMATION"
    assert store.return_to_roles(first_id).data_substep == "ROLES"
