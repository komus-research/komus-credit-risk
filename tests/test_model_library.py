from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from types import SimpleNamespace

import pytest

from komus_risk.application import InvalidModelDisplayName, ModelLibraryService, ModelSaveBindingConflict
from komus_risk.artifacts import ModelLibraryRecord, ModelLibraryRecordStore, ModelVersionSummary


class _ModelVersions:
    def __init__(self) -> None:
        self.by_artifact: dict[str, list[ModelVersionSummary]] = {}

    def find_by_experiment_artifact_id(self, artifact_id: str):
        return tuple(self.by_artifact.get(artifact_id, ()))

    def load(self, model_version_id: str):
        for summaries in self.by_artifact.values():
            for summary in summaries:
                if summary.model_version_id == model_version_id:
                    return SimpleNamespace(summary=summary)
        raise ValueError("missing")

    @staticmethod
    def display_name_for(model_id: str) -> str:
        return {"catboost": "CatBoost", "xgboost": "XGBoost"}[model_id]


class _Workflow:
    def __init__(self, versions: _ModelVersions) -> None:
        self.versions = versions
        self.calls = 0

    def save_model(self, *, experiment_artifact_id: str, prepared_dataset_context):
        self.calls += 1
        sleep(0.02)
        summary = ModelVersionSummary(
            f"model-{experiment_artifact_id}", experiment_artifact_id,
            "catboost", "1", ("feature",),
        )
        self.versions.by_artifact.setdefault(experiment_artifact_id, []).append(summary)
        return SimpleNamespace(summary=summary)


class _ReadableVersions(_ModelVersions):
    def __init__(self) -> None:
        super().__init__()
        self.inspect_calls: list[str] = []

    def inspect_metadata(self, model_version_id: str):
        self.inspect_calls.append(model_version_id)
        summary = next(
            summary
            for values in self.by_artifact.values()
            for summary in values
            if summary.model_version_id == model_version_id
        )
        return SimpleNamespace(summary=summary, metadata={
            "model_id": "catboost", "model_version": "1", "feature_ids": ["f_b", "f_a"],
            "model_recipe": {"adapter_version": "adapter-v1"},
            "dataset_contract": {"dataset_id": "dataset-exact", "dataset_name": "Exact dataset", "dataset_version": "v1", "dataset_fingerprint": "fingerprint", "target_column": "target", "positive_class": 1, "identifier_column": "id"},
            "config": {"model_id": "catboost", "model_version": "1", "model_parameters": {"depth": 6}, "seed": 7, "folds": 5, "protocol_id": "oof", "protocol_version": "1", "evaluation_level": "oof"},
            "population": {"population_id": "working", "population_fingerprint": "population-sha", "partition_role": "working", "row_positions": [2, 4]},
            "feature_specs": [
                {"feature_id": "f_b", "column_name": "b", "display_name_ru": "B", "description_ru": "second", "semantic_type": "numeric", "usage_status": "model_allowed"},
                {"feature_id": "f_a", "column_name": "a", "display_name_ru": "A", "description_ru": "first", "semantic_type": "numeric", "usage_status": "model_allowed"},
            ],
            "config_hash": "config-hash", "feature_set_hash": "features-hash", "feature_registry": {"registry_id": "registry", "registry_hash": "registry-hash"}, "source_file_sha256": "a" * 64, "code_version": "code", "runtime": {"python": "test"}, "native_hashes": {"model.bin": "b" * 64},
        })


class _Artifacts:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def read_metadata(self, artifact_id: str):
        self.reads.append(artifact_id)
        return SimpleNamespace(
            artifact_id=artifact_id,
            result=SimpleNamespace(
                result_id=f"result-{artifact_id}", created_at="2026-10-05T10:00:00+00:00",
                metrics={"gini": 0.4, "roc_auc": 0.7, "pr_auc": 0.6, "precision_at_0_5": 0.5, "recall_at_0_5": 0.8, "f1_at_0_5": 0.61},
            ),
        )


def _context(name: str = "Dataset"):
    return SimpleNamespace(display_name=name)


def _service(root: Path, versions: _ModelVersions, workflow: _Workflow) -> ModelLibraryService:
    return ModelLibraryService(
        record_store=ModelLibraryRecordStore(root / "library"),
        model_version_store=versions,
        integration_workflow_service=workflow,
    )


def test_first_save_repeat_and_recomposition_are_idempotent() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        versions = _ModelVersions()
        workflow = _Workflow(versions)
        artifact_id = "a" * 64
        first = _service(root, versions, workflow).ensure_saved(
            experiment_artifact_id=artifact_id, prepared_dataset_context=_context()
        )
        repeated = _service(root, versions, workflow).ensure_saved(
            experiment_artifact_id=artifact_id, prepared_dataset_context=_context()
        )

        assert first.save_state == "CREATED"
        assert repeated.save_state == "ALREADY_SAVED"
        assert repeated.record.model_version_id == first.record.model_version_id
        assert first.record.display_name == "CatBoost — Dataset — v1"
        assert workflow.calls == 1


def test_concurrent_save_performs_one_final_fit() -> None:
    with TemporaryDirectory() as temporary:
        versions = _ModelVersions()
        workflow = _Workflow(versions)
        service = _service(Path(temporary), versions, workflow)
        artifact_id = "b" * 64
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(
                lambda _: service.ensure_saved(
                    experiment_artifact_id=artifact_id, prepared_dataset_context=_context()
                ),
                range(2),
            ))

        assert {outcome.save_state for outcome in outcomes} == {"CREATED", "ALREADY_SAVED"}
        assert len({outcome.record.model_version_id for outcome in outcomes}) == 1
        assert workflow.calls == 1


def test_concurrent_artifacts_allocate_unique_versions_for_one_model() -> None:
    with TemporaryDirectory() as temporary:
        versions = _ModelVersions()
        workflow = _Workflow(versions)
        service = _service(Path(temporary), versions, workflow)
        artifact_ids = ("d" * 64, "e" * 64)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(
                lambda artifact_id: service.ensure_saved(
                    experiment_artifact_id=artifact_id,
                    prepared_dataset_context=_context(),
                ),
                artifact_ids,
            ))

        assert {outcome.save_state for outcome in outcomes} == {"CREATED"}
        assert {outcome.record.display_version for outcome in outcomes} == {"v1", "v2"}
        assert len({outcome.record.display_name for outcome in outcomes}) == 2
        assert workflow.calls == 2


def test_orphan_is_bound_without_refit_and_duplicates_fail_closed() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        versions = _ModelVersions()
        workflow = _Workflow(versions)
        artifact_id = "c" * 64
        orphan = ModelVersionSummary("orphan", artifact_id, "xgboost", "1", ("feature",))
        versions.by_artifact[artifact_id] = [orphan]
        service = _service(root, versions, workflow)

        recovered = service.ensure_saved(
            experiment_artifact_id=artifact_id, prepared_dataset_context=_context()
        )
        assert recovered.save_state == "ALREADY_SAVED"
        assert recovered.record.model_version_id == "orphan"
        assert recovered.record.display_version == "v1"
        assert workflow.calls == 0

        versions.by_artifact[artifact_id].append(
            ModelVersionSummary("duplicate", artifact_id, "xgboost", "1", ("feature",))
        )
        with pytest.raises(ModelSaveBindingConflict):
            service.ensure_saved(
                experiment_artifact_id=artifact_id, prepared_dataset_context=_context()
            )


def test_library_read_uses_exact_trusted_bindings_without_model_load() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        versions = _ReadableVersions()
        artifact_id = "f" * 64
        versions.by_artifact[artifact_id] = [
            ModelVersionSummary("model-exact", artifact_id, "catboost", "1", ("f_b", "f_a"))
        ]
        records = ModelLibraryRecordStore(root / "library")
        records.save(ModelLibraryRecord(1, artifact_id, "model-exact", "CatBoost — Exact dataset — v1", "v1", "2026-10-05T10:00:00+00:00"))
        artifacts = _Artifacts()
        service = ModelLibraryService(
            record_store=records, model_version_store=versions,
            integration_workflow_service=_Workflow(versions), experiment_artifact_store=artifacts,
        )

        page = service.list(search="exact")
        detail = service.detail("model-exact").value

        assert page.items[0]["oof_roc_auc"] == 0.7
        assert detail["features"][0]["feature_id"] == "f_b"
        assert detail["configuration"]["resolved_parameters"] == {"depth": 6}
        assert detail["source_result"]["experiment_artifact_id"] == artifact_id
        assert artifacts.reads == [artifact_id, artifact_id]


def test_rename_changes_only_organizational_name_and_persists() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        versions = _ReadableVersions()
        artifact_id = "9" * 64
        versions.by_artifact[artifact_id] = [
            ModelVersionSummary("model-rename", artifact_id, "catboost", "1", ("f_b", "f_a"))
        ]
        records = ModelLibraryRecordStore(root / "library")
        original = ModelLibraryRecord(
            1, artifact_id, "model-rename", "CatBoost — Exact dataset — v1", "v1",
            "2026-10-05T10:00:00+00:00",
        )
        records.save(original)
        service = ModelLibraryService(
            record_store=records, model_version_store=versions,
            integration_workflow_service=_Workflow(versions), experiment_artifact_store=_Artifacts(),
        )

        renamed = service.rename("model-rename", "  Моя скоринговая модель  ")

        assert renamed.display_name == "Моя скоринговая модель"
        assert renamed.model_version_id == original.model_version_id
        assert renamed.experiment_artifact_id == original.experiment_artifact_id
        assert renamed.display_version == original.display_version
        assert renamed.saved_at == original.saved_at
        assert service.list().items[0]["display_name"] == "Моя скоринговая модель"
        assert service.detail("model-rename").value["display_name"] == "Моя скоринговая модель"
        reloaded = ModelLibraryRecordStore(root / "library").find_by_experiment_artifact_id(artifact_id)
        assert reloaded is not None
        assert reloaded.display_name == "Моя скоринговая модель"


@pytest.mark.parametrize("display_name", ["", "   ", "x" * 161, "две\nстроки"])
def test_rename_rejects_invalid_display_name(display_name: str) -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        versions = _ReadableVersions()
        artifact_id = "8" * 64
        versions.by_artifact[artifact_id] = [
            ModelVersionSummary("model-rename", artifact_id, "catboost", "1", ("f_b", "f_a"))
        ]
        records = ModelLibraryRecordStore(root / "library")
        records.save(ModelLibraryRecord(
            1, artifact_id, "model-rename", "CatBoost — Exact dataset — v1", "v1",
            "2026-10-05T10:00:00+00:00",
        ))
        service = ModelLibraryService(
            record_store=records, model_version_store=versions,
            integration_workflow_service=_Workflow(versions), experiment_artifact_store=_Artifacts(),
        )

        with pytest.raises(InvalidModelDisplayName):
            service.rename("model-rename", display_name)
