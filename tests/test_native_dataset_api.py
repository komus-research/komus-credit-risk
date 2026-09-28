"""N2a native upload, session and editable preparation-draft evidence."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event, Thread

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import SESSION_COOKIE_NAME, create_app
from komus_risk.application.dataset_onboarding import NativeDatasetOnboardingService
from komus_risk.application.native_session import NativeSessionStore


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


def test_upload_finishes_with_ready_progress() -> None:
    client = TestClient(create_app())

    _upload(client)
    progress = client.get("/api/v1/dataset/progress")

    assert progress.status_code == 200
    assert progress.json()["status"] == "READY"
    assert progress.json()["stage"] == "READY"
    assert progress.json()["stage_label"] == "Файл успешно проверен"


def test_upload_rejects_empty_and_unsupported_files_without_traceback() -> None:
    client = TestClient(create_app())
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
