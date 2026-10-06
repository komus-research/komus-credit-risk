from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from komus_risk.application.project_workspace import ProjectWorkspaceError, ProjectWorkspaceService
from komus_risk.application.saved_model_inference import SavedModelInferenceError
from komus_risk.artifacts.project_workspace_store import ProjectWorkspaceStore


class _SavedInference:
    def __init__(self, *, model_version_id: str = "model-v1", missing: bool = False) -> None:
        self.model_version_id, self.missing = model_version_id, missing

    def summary(self, inference_result_id: str):
        if self.missing or inference_result_id != "result-1":
            raise SavedModelInferenceError("INFERENCE_RESULT_NOT_FOUND")
        return SimpleNamespace(inference_result_id="result-1", model_version_id=self.model_version_id,
            display_name="Пользовательская модель", source_display_name="Проверка_100.xlsb",
            source_fingerprint="source-fingerprint", created_at="2026-10-06T12:00:00+00:00", row_count=17)


def _service(root: Path, inference: _SavedInference | None = None) -> ProjectWorkspaceService:
    return ProjectWorkspaceService(store=ProjectWorkspaceStore(root / "projects"), saved_inference_service=inference or _SavedInference())


def test_canonical_project_storage_schema_and_restart_persistence() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); first = _service(root)
        record = first.save(inference_result_id="result-1", name="Проект  с  пробелами")
        path = root / "projects" / record.project_id / "project.json"
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        reloaded = _service(root).detail(record.project_id)

        assert path.is_file()
        assert set(payload) == {"schema_version", "project_id", "name", "work_type", "inference_result_id", "model_version_id", "source_fingerprint", "created_at", "updated_at", "last_opened_at"}
        assert payload["work_type"] == "SAVED_MODEL_INFERENCE"
        assert payload["source_fingerprint"] == "source-fingerprint"
        assert payload["last_opened_at"] is None
        assert reloaded["inference_result_id"] == "result-1"


def test_duplicate_and_competing_save_return_one_canonical_project_without_rewriting_name() -> None:
    with TemporaryDirectory() as directory:
        service = _service(Path(directory))
        first = service.save(inference_result_id="result-1", name="Первое  имя")
        second = service.save(inference_result_id="result-1", name="Другое имя")
        assert second.project_id == first.project_id and second.name == "Первое  имя"

        with ThreadPoolExecutor(max_workers=4) as executor:
            records = list(executor.map(lambda name: service.save(inference_result_id="result-1", name=name), ("A", "B", "C", "D")))
        assert {record.project_id for record in records} == {first.project_id}
        assert service.list().total_count == 1


def test_simultaneous_first_save_creates_one_canonical_project_without_rewriting_name() -> None:
    with TemporaryDirectory() as directory:
        service = _service(Path(directory)); barrier = Barrier(4)
        def first_save(name: str):
            barrier.wait()
            return service.save(inference_result_id="result-1", name=name)
        with ThreadPoolExecutor(max_workers=4) as executor:
            records = list(executor.map(first_save, ("Первое", "Второе", "Третье", "Четвёртое")))

        assert len({record.project_id for record in records}) == 1
        directories = [path for path in (Path(directory) / "projects").iterdir() if path.is_dir() and not path.name.startswith(".")]
        assert len(directories) == 1
        assert ProjectWorkspaceStore(Path(directory) / "projects").get(records[0].project_id).name in {"Первое", "Второе", "Третье", "Четвёртое"}


def test_default_name_uses_display_names_and_russian_date() -> None:
    with TemporaryDirectory() as directory:
        assert _service(Path(directory)).suggested_name("result-1") == "Пользовательская модель — Проверка_100.xlsb — 06.10.2026"


def test_open_updates_last_opened_only_after_exact_binding_validation() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); service = _service(root)
        record = service.save(inference_result_id="result-1", name="Проект")
        opened = service.open(record.project_id)
        assert opened["inference_result_id"] == "result-1" and opened["last_opened_at"] is not None

        mismatched = _service(root, _SavedInference(model_version_id="other-model"))
        before = ProjectWorkspaceStore(root / "projects").get(record.project_id).last_opened_at
        with pytest.raises(ProjectWorkspaceError, match="PROJECT_WORKSPACE_INTEGRITY_ERROR"):
            mismatched.open(record.project_id)
        assert ProjectWorkspaceStore(root / "projects").get(record.project_id).last_opened_at == before


def test_missing_result_fails_closed_without_open_timestamp_mutation() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); service = _service(root); record = service.save(inference_result_id="result-1", name="Проект")
        before = ProjectWorkspaceStore(root / "projects").get(record.project_id).last_opened_at
        with pytest.raises(ProjectWorkspaceError, match="PROJECT_INFERENCE_RESULT_UNAVAILABLE"):
            _service(root, _SavedInference(missing=True)).open(record.project_id)
        assert ProjectWorkspaceStore(root / "projects").get(record.project_id).last_opened_at == before


def test_list_projection_and_open_api_return_exact_result() -> None:
    with TemporaryDirectory() as directory:
        workspace = _service(Path(directory)); client = TestClient(create_app(project_workspace_service=workspace))
        saved = client.post("/api/v1/inference-results/result-1/project", json={"name": "Проект API"})
        project_id = saved.json()["project_id"]
        listing = client.get("/api/v1/projects?offset=0&limit=5")
        opened = client.post(f"/api/v1/projects/{project_id}/open")

        assert saved.status_code == 200 and listing.json()["total_count"] == 1
        assert listing.json()["resumable_count"] == 1
        assert opened.status_code == 200 and opened.json()["inference_result_id"] == "result-1"
        assert opened.json()["last_opened_at"] is not None


@pytest.mark.parametrize("field", ("created_at", "updated_at", "last_opened_at"))
def test_naive_project_timestamp_fails_closed_and_api_returns_integrity_error(field: str) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); service = _service(root); record = service.save(inference_result_id="result-1", name="Проект")
        path = root / "projects" / record.project_id / "project.json"
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        payload[field] = "2026-10-06T12:00:00" if field != "last_opened_at" else "2026-10-06T12:00:00"
        path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        with pytest.raises(ProjectWorkspaceError, match="PROJECT_WORKSPACE_INTEGRITY_ERROR"):
            service.open(record.project_id)
        client = TestClient(create_app(project_workspace_service=service))
        response = client.post(f"/api/v1/projects/{record.project_id}/open")
        assert response.status_code == 409 and response.json()["detail"]["code"] == "PROJECT_WORKSPACE_INTEGRITY_ERROR"


def test_malformed_project_timestamp_fails_closed() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); service = _service(root); record = service.save(inference_result_id="result-1", name="Проект")
        path = root / "projects" / record.project_id / "project.json"; payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        payload["updated_at"] = "not-a-timestamp"; path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        with pytest.raises(ProjectWorkspaceError, match="PROJECT_WORKSPACE_INTEGRITY_ERROR"):
            service.open(record.project_id)
        response = TestClient(create_app(project_workspace_service=service)).post(f"/api/v1/projects/{record.project_id}/open")
        assert response.status_code == 409 and response.json()["detail"]["code"] == "PROJECT_WORKSPACE_INTEGRITY_ERROR"
