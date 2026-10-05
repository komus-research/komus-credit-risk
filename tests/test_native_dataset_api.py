"""N2a native upload, session and editable preparation-draft evidence."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import SESSION_COOKIE_NAME, create_app
from komus_risk.application.dataset_onboarding import NativeDatasetOnboardingService
from komus_risk.application.native_session import NativeSessionStore
from komus_risk.preparation import PreparedDatasetContextAuthority


def _dataset() -> bytes:
    return (
        b"client_id,target,alternate_target,score\n"
        b"a,0,1,0.2\n"
        b"b,1,0,0.9\n"
        b"c,0,1,0.1\n"
        b"d,1,0,0.8\n"
    )


def _upload(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/dataset/upload",
        files={"file": ("customer.csv", _dataset(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_returns_only_public_dataset_dto_and_auto_draft() -> None:
    payload = _upload(TestClient(create_app()))

    assert payload["source"] == {
        "handle": payload["source"]["handle"],
        "display_name": "customer.csv",
        "format": "csv",
        "size": len(_dataset()),
        "rows": 4,
        "columns": 4,
    }
    assert payload["draft"]["target"] in payload["options"]["columns"]
    assert payload["draft"]["identifier"] in payload["options"]["columns"]
    assert payload["draft"]["target"] != payload["draft"]["identifier"]
    assert "local_path" not in str(payload).lower()
    assert "upload-" not in str(payload)


def test_upload_returns_structured_preparation_warnings_without_internal_evidence() -> None:
    payload = _upload(TestClient(create_app()))
    warnings = payload["summary"]["warnings"]

    assert warnings
    assert all(isinstance(warning, dict) for warning in warnings)
    for warning in warnings:
        assert set(warning) == {
            "code", "severity", "scope", "column_name", "detected_reasons",
            "detected_requires_confirmation", "resolution_state", "resolution_code",
            "subject_ru", "title_ru", "detail_ru", "check_ru", "resolution_note_ru", "action",
        }
        assert warning["severity"] in {"WARNING", "INFO"}
        assert warning["scope"] in {"COLUMN", "DATASET"}
        assert isinstance(warning["detected_reasons"], list) and warning["detected_reasons"]
        assert warning["resolution_state"] in {"ACTION_REQUIRED", "RESOLVED", "INFO"}
        assert warning["subject_ru"]
        assert warning["title_ru"] and warning["detail_ru"]
        assert "evidence" not in warning
        assert "column_position" not in warning
    counts = payload["summary"]["warning_counts"]
    assert counts == {
        "action_required": sum(warning["resolution_state"] == "ACTION_REQUIRED" for warning in warnings),
        "resolved": sum(warning["resolution_state"] == "RESOLVED" for warning in warnings),
        "info": sum(warning["resolution_state"] == "INFO" for warning in warnings),
    }


def test_warning_resolution_and_counts_refresh_when_draft_changes() -> None:
    client = TestClient(create_app())
    uploaded = _upload(client)
    multiple = next((item for item in uploaded["summary"]["warnings"] if item["code"] == "multiple_target_candidates"), None)
    assert multiple is not None
    assert multiple["resolution_state"] == "RESOLVED"
    assert multiple["subject_ru"] == "Целевая колонка"
    assert multiple["resolution_note_ru"] == f"Выбрана целевая колонка {uploaded['draft']['target']}."

    changed = client.patch(
        "/api/v1/dataset/preparation/draft",
        json={"target": None},
    )
    assert changed.status_code == 200, changed.text
    new_warnings = changed.json()["summary"]["warnings"]
    changed_multiple = next(item for item in new_warnings if item["code"] == "multiple_target_candidates")
    assert changed_multiple["resolution_state"] == "ACTION_REQUIRED"
    assert changed_multiple["subject_ru"] == "Целевая колонка"
    assert changed_multiple["resolution_note_ru"] is None
    assert changed.json()["summary"]["warning_counts"]["action_required"] == sum(
        item["resolution_state"] == "ACTION_REQUIRED" for item in new_warnings
    )


def test_upload_finishes_with_ready_progress() -> None:
    client = TestClient(create_app())

    _upload(client)
    progress = client.get("/api/v1/dataset/progress")
    session = client.get("/api/v1/session")

    assert progress.status_code == 200
    assert progress.json()["status"] == "READY"
    assert progress.json()["stage"] == "READY"
    assert session.json()["analysis_active"] is True
    assert session.json()["data_substep"] == "ROLES"
    assert session.json()["resume_route"] == "#/analysis/data/roles"
    assert progress.json()["stage_label"] == "Файл успешно проверен"


def test_upload_rejects_empty_and_unsupported_files_without_traceback() -> None:
    store = NativeSessionStore()
    client = TestClient(create_app(session_store=store))
    for name, content in (("bad.exe", b"x"), ("empty.csv", b"")):
        response = client.post("/api/v1/dataset/upload", files={"file": (name, content)})
        assert response.status_code == 422
        assert "traceback" not in response.text.lower()
        assert "upload-" not in response.text

    progress = client.get("/api/v1/dataset/progress").json()
    assert progress["status"] == "ERROR"
    assert progress["stage"] == "ERROR"
    assert "traceback" not in str(progress).lower()
    assert "path" not in str(progress).lower()
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id is not None
    assert not store.snapshot(session_id).has_meaningful_temporary_work


def test_failed_replacement_preserves_previous_dataset_and_meaningful_work() -> None:
    store = NativeSessionStore()
    client = TestClient(create_app(session_store=store))
    previous = _upload(client)
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id is not None

    failed = client.post(
        "/api/v1/dataset/upload",
        files={"file": ("replacement.csv", b"", "text/csv")},
    )

    assert failed.status_code == 422
    assert client.get("/api/v1/dataset/preparation").json() == previous
    assert store.snapshot(session_id).has_meaningful_temporary_work


def test_confirmed_reset_cleans_staged_upload_during_inspection(monkeypatch) -> None:
    entered, release = Event(), Event()
    original = NativeDatasetOnboardingService.inspect

    def slow_inspect(self, *args, progress_listener=None, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(self, *args, progress_listener=progress_listener, **kwargs)

    monkeypatch.setattr(NativeDatasetOnboardingService, "inspect", slow_inspect)
    store = NativeSessionStore()
    with TestClient(create_app(session_store=store)) as client:
        client.get("/api/v1/session")
        response: dict[str, object] = {}

        def upload() -> None:
            response["value"] = client.post(
                "/api/v1/dataset/upload",
                files={"file": ("customer.csv", _dataset(), "text/csv")},
            )

        worker = Thread(target=upload)
        worker.start()
        assert entered.wait(timeout=5)
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        assert session_id is not None
        staged = store._sessions[session_id].inspection_upload
        assert staged is not None and staged.local_path.is_file()

        confirmation = client.post("/api/v1/analysis/new", json={"confirm_reset": False})
        assert confirmation.json()["status"] == "CONFIRMATION_REQUIRED"
        reset = client.post("/api/v1/analysis/new", json={"confirm_reset": True})
        assert reset.json()["status"] == "STARTED"
        assert not staged.local_path.exists()
        release.set()
        worker.join(timeout=5)

    assert response["value"].status_code == 422
    assert store.dataset_inspection_progress(session_id).status.value == "IDLE"
    assert not store.snapshot(session_id).has_meaningful_temporary_work


def test_progress_endpoint_is_responsive_while_inspection_runs(monkeypatch) -> None:
    entered, release = Event(), Event()
    original = NativeDatasetOnboardingService.inspect

    def slow_inspect(self, *args, progress_listener=None, **kwargs):
        assert progress_listener is not None
        progress_listener("reading_source")
        entered.set()
        assert release.wait(timeout=5)
        return original(self, *args, progress_listener=progress_listener, **kwargs)

    monkeypatch.setattr(NativeDatasetOnboardingService, "inspect", slow_inspect)
    with TestClient(create_app()) as client:
        client.get("/api/v1/session")
        response: dict[str, object] = {}

        def upload() -> None:
            response["value"] = client.post(
                "/api/v1/dataset/upload",
                files={"file": ("customer.csv", _dataset(), "text/csv")},
            )

        worker = Thread(target=upload)
        worker.start()
        assert entered.wait(timeout=5)
        progress = client.get("/api/v1/dataset/progress")
        health = client.get("/api/v1/health")
        release.set()
        worker.join(timeout=5)

    assert progress.status_code == 200
    assert progress.json()["status"] == "RUNNING"
    assert progress.json()["stage"] == "READING_SOURCE"
    assert health.json() == {"status": "ok"}
    assert response["value"].status_code == 200


def test_patch_keeps_roles_distinct_and_clears_stale_positive_class() -> None:
    client = TestClient(create_app())
    uploaded = _upload(client)

    conflict = client.patch(
        "/api/v1/dataset/preparation/draft",
        json={"target": "client_id", "identifier": "client_id"},
    )
    assert conflict.status_code == 422
    assert conflict.json()["detail"]["code"] == "TARGET_IDENTIFIER_CONFLICT"

    next_target = "target" if uploaded["draft"]["target"] == "alternate_target" else "alternate_target"
    changed = client.patch("/api/v1/dataset/preparation/draft", json={"target": next_target})
    assert changed.status_code == 200
    assert changed.json()["draft"]["target"] == next_target
    assert changed.json()["draft"]["positive_class"] is None
    assert changed.json()["options"]["positive_classes"] == [0, 1]


def test_patch_null_clears_the_explicit_field_and_omitted_fields_are_preserved() -> None:
    client = TestClient(create_app())
    uploaded = _upload(client)
    target = uploaded["draft"]["target"]
    identifier = uploaded["draft"]["identifier"]
    assert target is not None

    selected = client.patch(
        "/api/v1/dataset/preparation/draft", json={"positive_class": 1}
    )
    assert selected.status_code == 200
    assert selected.json()["draft"]["target"] == target
    assert selected.json()["draft"]["identifier"] == identifier
    assert selected.json()["draft"]["positive_class"] == 1

    target_cleared = client.patch(
        "/api/v1/dataset/preparation/draft", json={"target": None}
    )
    assert target_cleared.status_code == 200
    assert target_cleared.json()["draft"] == {
        "target": None,
        "positive_class": None,
        "identifier": identifier,
    }

    identifier_cleared = client.patch(
        "/api/v1/dataset/preparation/draft", json={"identifier": None}
    )
    assert identifier_cleared.status_code == 200
    assert identifier_cleared.json()["draft"] == {
        "target": None,
        "positive_class": None,
        "identifier": None,
    }

    unchanged = client.patch("/api/v1/dataset/preparation/draft", json={})
    assert unchanged.status_code == 200
    assert unchanged.json()["draft"] == identifier_cleared.json()["draft"]


def test_sessions_are_isolated_and_confirmed_reset_removes_only_own_upload() -> None:
    store = NativeSessionStore()
    first, second = TestClient(create_app(session_store=store)), TestClient(create_app(session_store=store))
    _upload(first)
    first_id = first.cookies.get(SESSION_COOKIE_NAME)
    assert first_id is not None
    first_upload = store._sessions[first_id].staged_upload
    assert first_upload is not None and first_upload.local_path.is_file()

    assert second.get("/api/v1/dataset/preparation").status_code == 404
    reset = first.post("/api/v1/analysis/new", json={"confirm_reset": True})
    assert reset.status_code == 200
    assert not first_upload.local_path.exists()
    assert second.get("/api/v1/dataset/preparation").status_code == 404


def test_explicit_confirmation_materializes_only_after_acknowledgement() -> None:
    client = TestClient(create_app())
    uploaded = _upload(client)
    assert uploaded["draft"]["target"] is not None

    assert client.patch(
        "/api/v1/dataset/preparation/draft", json={"positive_class": 1}
    ).status_code == 200
    review = client.post("/api/v1/dataset/preparation/review")
    assert review.status_code == 200
    assert review.json()["data_substep"] == "CONFIRMATION"
    assert review.json()["resume_route"] == "#/analysis/data/confirmation"

    blocked = client.post("/api/v1/dataset/preparation/confirm", json={})
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "POPULATION_POLICY_NOT_ACKNOWLEDGED"
    assert client.get("/api/v1/session").json()["data_substep"] == "CONFIRMATION"

    confirmed = client.post(
        "/api/v1/dataset/preparation/confirm",
        json={"population_policy_acknowledged": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data_substep"] == "PREPARED"
    assert confirmed.json()["current_step"] == 1
    assert confirmed.json()["resume_route"] == "#/analysis/features"
    invalid_edit = client.patch(
        "/api/v1/dataset/preparation/draft", json={"positive_class": 0}
    )
    assert invalid_edit.status_code == 409
    assert invalid_edit.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
    assert client.get("/api/v1/session").json()["data_substep"] == "PREPARED"
    for endpoint in ("review", "roles"):
        invalid = client.post(f"/api/v1/dataset/preparation/{endpoint}")
        assert invalid.status_code == 409
        assert invalid.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
        assert client.get("/api/v1/session").json()["data_substep"] == "PREPARED"

    reset = client.post("/api/v1/analysis/new", json={"confirm_reset": True})
    assert reset.status_code == 200
    assert reset.json()["data_substep"] == "FILE"
    assert reset.json()["resume_route"] == "#/analysis/data/file"


def test_direct_confirm_from_roles_fails_before_any_materialization(monkeypatch) -> None:
    from komus_risk.preparation.komus_service import KomusDatasetPreparationService

    store = NativeSessionStore()
    client = TestClient(create_app(session_store=store))
    uploaded = _upload(client)
    assert client.patch(
        "/api/v1/dataset/preparation/draft", json={"positive_class": 1}
    ).status_code == 200
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id is not None
    before_draft = store.dataset_state(session_id)[1]

    materialize = Mock(side_effect=AssertionError("materialization must not run"))
    prepare = Mock(side_effect=AssertionError("prepare must not run"))
    register = Mock(side_effect=AssertionError("authority registration must not run"))
    monkeypatch.setattr(NativeDatasetOnboardingService, "materialize_confirmation", materialize)
    monkeypatch.setattr(KomusDatasetPreparationService, "prepare", prepare)
    monkeypatch.setattr(PreparedDatasetContextAuthority, "register", register)

    response = client.post(
        "/api/v1/dataset/preparation/confirm",
        json={"population_policy_acknowledged": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
    assert "traceback" not in response.text.lower()
    assert materialize.call_count == 0
    assert prepare.call_count == 0
    assert register.call_count == 0
    assert store.snapshot(session_id).data_substep == "ROLES"
    assert store.dataset_state(session_id)[1] == before_draft
    assert store._sessions[session_id].prepared_context_id is None


def test_review_and_back_reject_invalid_transitions_without_state_change() -> None:
    client = TestClient(create_app())
    _upload(client)

    invalid_back = client.post("/api/v1/dataset/preparation/roles")
    assert invalid_back.status_code == 409
    assert invalid_back.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
    assert client.get("/api/v1/session").json()["data_substep"] == "ROLES"

    first_review = client.post("/api/v1/dataset/preparation/review")
    assert first_review.status_code == 200
    repeated_review = client.post("/api/v1/dataset/preparation/review")
    assert repeated_review.status_code == 409
    assert repeated_review.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
    invalid_edit = client.patch(
        "/api/v1/dataset/preparation/draft", json={"positive_class": 1}
    )
    assert invalid_edit.status_code == 409
    assert invalid_edit.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
    assert client.get("/api/v1/session").json()["data_substep"] == "CONFIRMATION"

    assert client.post("/api/v1/dataset/preparation/roles").status_code == 200
    assert client.get("/api/v1/session").json()["data_substep"] == "ROLES"
    assert client.post("/api/v1/dataset/preparation/roles").status_code == 409


def test_confirmation_reservation_blocks_same_session_transitions_until_complete(monkeypatch) -> None:
    store = NativeSessionStore()
    materializing, release = Event(), Event()
    registered_contexts: list[str] = []
    original_materialize = NativeDatasetOnboardingService.materialize_confirmation
    original_register = PreparedDatasetContextAuthority.register

    def blocked_materialize(self, dataset, draft, *, context_authority):
        materializing.set()
        assert release.wait(timeout=5)
        return original_materialize(
            self, dataset, draft, context_authority=context_authority
        )

    def tracked_register(authority, context):
        registered_contexts.append(context.context_id)
        return original_register(authority, context)

    monkeypatch.setattr(
        NativeDatasetOnboardingService,
        "materialize_confirmation",
        blocked_materialize,
    )
    monkeypatch.setattr(PreparedDatasetContextAuthority, "register", tracked_register)

    with TestClient(create_app(session_store=store)) as client:
        _upload(client)
        assert client.patch(
            "/api/v1/dataset/preparation/draft", json={"positive_class": 1}
        ).status_code == 200
        assert client.post("/api/v1/dataset/preparation/review").status_code == 200
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        assert session_id is not None
        confirmation_result: dict[str, object] = {}

        def confirm() -> None:
            confirmation_result["response"] = client.post(
                "/api/v1/dataset/preparation/confirm",
                json={"population_policy_acknowledged": True},
            )

        worker = Thread(target=confirm)
        worker.start()
        assert materializing.wait(timeout=5)

        back = client.post("/api/v1/dataset/preparation/roles")
        duplicate_confirm = client.post(
            "/api/v1/dataset/preparation/confirm",
            json={"population_policy_acknowledged": True},
        )
        reset = client.post("/api/v1/analysis/new", json={"confirm_reset": True})
        draft_edit = client.patch(
            "/api/v1/dataset/preparation/draft", json={"positive_class": 0}
        )
        replacement_upload = client.post(
            "/api/v1/dataset/upload",
            files={"file": ("replacement.csv", _dataset(), "text/csv")},
        )
        assert back.status_code == 409
        assert back.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
        for rejected in (duplicate_confirm, reset, draft_edit, replacement_upload):
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "INVALID_DATA_TRANSITION"
        assert client.get("/api/v1/session").json()["data_substep"] == "CONFIRMATION"
        assert registered_contexts == []

        release.set()
        worker.join(timeout=5)
        assert not worker.is_alive()

        confirmed = confirmation_result["response"]
        assert confirmed.status_code == 200
        assert confirmed.json()["data_substep"] == "PREPARED"
        assert confirmed.json()["resume_route"] == "#/analysis/features"
        assert len(registered_contexts) == 1
        assert store._sessions[session_id].confirmation_operation_token is None

        reset_after_complete = client.post(
            "/api/v1/analysis/new", json={"confirm_reset": True}
        )
        assert reset_after_complete.status_code == 200
        assert reset_after_complete.json()["data_substep"] == "FILE"


def test_failed_materialization_releases_confirmation_reservation(monkeypatch) -> None:
    store = NativeSessionStore()
    client = TestClient(create_app(session_store=store))
    _upload(client)
    assert client.patch(
        "/api/v1/dataset/preparation/draft", json={"positive_class": 1}
    ).status_code == 200
    assert client.post("/api/v1/dataset/preparation/review").status_code == 200
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id is not None

    def fail_materialization(*_args, **_kwargs):
        raise RuntimeError("private materializer detail")

    monkeypatch.setattr(
        NativeDatasetOnboardingService,
        "materialize_confirmation",
        fail_materialization,
    )
    failed = client.post(
        "/api/v1/dataset/preparation/confirm",
        json={"population_policy_acknowledged": True},
    )

    assert failed.status_code == 500
    assert failed.json()["detail"]["code"] == "PREPARATION_FAILED"
    assert "private materializer detail" not in failed.text
    assert store._sessions[session_id].confirmation_operation_token is None
    assert client.get("/api/v1/session").json()["data_substep"] == "CONFIRMATION"
    assert client.post("/api/v1/dataset/preparation/roles").status_code == 200
