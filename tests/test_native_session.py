"""Tests for framework-neutral native AXION session transitions."""

from __future__ import annotations

import ast
from pathlib import Path

from komus_risk.application.native_session import (
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
    assert not created.has_meaningful_temporary_work


def test_clean_new_analysis_starts_at_data_step() -> None:
    store = NativeSessionStore()
    session_id, _ = store.get_or_create(None)

    result = store.start_new_analysis(session_id)

    assert result.status is NewAnalysisStatus.STARTED
    assert result.session.current_step == 0
    assert not result.session.has_meaningful_temporary_work


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
