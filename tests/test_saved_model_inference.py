from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.upload_staging import StagedUpload
from komus_risk.application import ModelInferenceService, SavedModelInferenceError, SavedModelInferenceService
from komus_risk.artifacts import LoadedModelVersion, ModelLibraryRecord, ModelVersionSummary, SavedInferenceResultViewConfigurationStore, SavedModelInferenceResultStore
from komus_risk.data import TabularSnapshot
from komus_risk.hashing import stable_hash


class _Predictor:
    def __init__(self): self.calls = 0; self.values = None
    def predict_positive_proba(self, frame):
        self.calls += 1; self.values = frame.to_numpy().copy(); return np.array([.2, .8])


class _Library:
    def __init__(self, predictor):
        self.record = ModelLibraryRecord(1, "exp", "model", "Model", "v1", "2026-01-01T00:00:00+00:00")
        self.loaded = LoadedModelVersion(ModelVersionSummary("model", "exp", "m", "1", ("a", "b")), {"dataset_contract": {"identifier_column": "id"}, "feature_columns": ["a", "b"]}, {}, predictor)
        self.fail_detail = False
    def load_for_inference(self, identifier): return self.record, self.loaded
    def detail(self, identifier):
        if self.fail_detail:
            raise RuntimeError("detail failed")
        return SimpleNamespace(value={
            "model_version_id": "model", "experiment_artifact_id": "exp",
            "display_name": "Model", "display_version": "v1",
            "algorithm": {"model_display_name": "M"}, "dataset": {"dataset_name": "train"},
        })


def test_preflight_never_predicts_and_deduplicated_retry_uses_exact_prepared_matrix():
    with TemporaryDirectory() as temp:
        predictor = _Predictor(); library = _Library(predictor)
        service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=SavedModelInferenceResultStore(Path(temp) / "results"), cleanup_upload=lambda _: None)
        frame = pd.DataFrame({"b": [10, 20], "id": ["x", "y"], "extra": [1, 2], "a": [3, 4]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 2, 4, frame, tuple(frame.columns))
        staged = StagedUpload(Path(temp) / "input.csv", "input.csv", "a" * 64, Path(temp))
        first = service.preflight(session_owner="owner", model_version_id="model", staged_upload=staged, snapshot=snapshot)
        assert predictor.calls == 0
        assert first.required_feature_columns == ("a", "b")
        created = service.run(session_owner="owner", model_version_id="model", preparation_id=first.preparation_id)
        assert created.run_state == "CREATED" and predictor.calls == 1
        assert predictor.values.tolist() == [[3.0, 10.0], [4.0, 20.0]]
        second = service.preflight(session_owner="owner", model_version_id="model", staged_upload=staged, snapshot=snapshot)
        reused = service.run(session_owner="owner", model_version_id="model", preparation_id=second.preparation_id)
        assert reused.run_state == "REUSED" and reused.inference_result_id == created.inference_result_id and predictor.calls == 1
        assert service.run(session_owner="owner", model_version_id="model", preparation_id=second.preparation_id).run_state == "REUSED"


def test_distinct_preparations_for_same_recipe_are_serialized_across_service_instances():
    with TemporaryDirectory() as temp:
        predictor = _Predictor(); library = _Library(predictor); root = Path(temp) / "results"
        first_service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=SavedModelInferenceResultStore(root), cleanup_upload=lambda _: None)
        second_service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=SavedModelInferenceResultStore(root), cleanup_upload=lambda _: None)
        frame = pd.DataFrame({"b": [10, 20], "id": ["x", "y"], "a": [3, 4]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 2, 3, frame, tuple(frame.columns))
        staged = StagedUpload(Path(temp) / "input.csv", "input.csv", "a" * 64, Path(temp))
        one = first_service.preflight(session_owner="one", model_version_id="model", staged_upload=staged, snapshot=snapshot)
        two = second_service.preflight(session_owner="two", model_version_id="model", staged_upload=staged, snapshot=snapshot)
        calls = ((first_service, "one", one.preparation_id), (second_service, "two", two.preparation_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda item: item[0].run(session_owner=item[1], model_version_id="model", preparation_id=item[2]), calls))
        assert predictor.calls == 1
        assert {item.run_state for item in outcomes} == {"CREATED", "REUSED"}
        assert len({item.inference_result_id for item in outcomes}) == 1


def test_failed_replacement_preserves_previous_preparation():
    with TemporaryDirectory() as temp:
        predictor = _Predictor(); library = _Library(predictor); cleaned = []
        service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=SavedModelInferenceResultStore(Path(temp) / "results"), cleanup_upload=lambda upload: cleaned.append(upload.display_name))
        frame = pd.DataFrame({"id": ["x", "y"], "a": [3, 4], "b": [10, 20]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 2, 3, frame, tuple(frame.columns))
        old_staged = StagedUpload(Path(temp) / "old.csv", "old.csv", "a" * 64, Path(temp))
        new_staged = StagedUpload(Path(temp) / "new.csv", "new.csv", "a" * 64, Path(temp))
        old = service.preflight(session_owner="owner", model_version_id="model", staged_upload=old_staged, snapshot=snapshot)
        library.fail_detail = True
        with pytest.raises(RuntimeError):
            service.preflight(session_owner="owner", model_version_id="model", staged_upload=new_staged, snapshot=snapshot)
        assert cleaned == []
        library.fail_detail = False
        result = service.run(session_owner="owner", model_version_id="model", preparation_id=old.preparation_id)
        assert result.run_state == "CREATED"
        assert predictor.calls == 1


def test_manifest_schema_and_experiment_tampering_fail_closed():
    with TemporaryDirectory() as temp:
        root = Path(temp) / "results"; predictor = _Predictor(); library = _Library(predictor)
        service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=SavedModelInferenceResultStore(root), cleanup_upload=lambda _: None)
        frame = pd.DataFrame({"id": ["x", "y"], "a": [3, 4], "b": [10, 20]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 2, 3, frame, tuple(frame.columns))
        staged = StagedUpload(Path(temp) / "input.csv", "input.csv", "a" * 64, Path(temp))
        result = service.run(session_owner="one", model_version_id="model", preparation_id=service.preflight(session_owner="one", model_version_id="model", staged_upload=staged, snapshot=snapshot).preparation_id)
        directory = root / result.inference_result_id
        manifest_path = directory / "manifest.json"; result_path = directory / "result.json"
        original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bad_manifest = dict(original_manifest); bad_manifest["schema_version"] = 999
        manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            service.result_store.read(result.inference_result_id)
        manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
        payload = json.loads(result_path.read_text(encoding="utf-8")); payload["experiment_artifact_id"] = "other-exp"
        result_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        tampered_manifest = dict(original_manifest); tampered_manifest["files"] = dict(original_manifest["files"])
        result_bytes = result_path.read_bytes()
        tampered_manifest["result_hash"] = stable_hash(payload)
        tampered_manifest["files"]["result.json"] = {"sha256": sha256(result_bytes).hexdigest(), "size_bytes": len(result_bytes)}
        manifest_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            service.result_store.read(result.inference_result_id)


def test_persistence_os_error_has_stable_persistence_code(monkeypatch):
    with TemporaryDirectory() as temp:
        predictor = _Predictor(); library = _Library(predictor); store = SavedModelInferenceResultStore(Path(temp) / "results")
        service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=store, cleanup_upload=lambda _: None)
        frame = pd.DataFrame({"id": ["x", "y"], "a": [3, 4], "b": [10, 20]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 2, 3, frame, tuple(frame.columns))
        staged = StagedUpload(Path(temp) / "input.csv", "input.csv", "a" * 64, Path(temp))
        prepared = service.preflight(session_owner="owner", model_version_id="model", staged_upload=staged, snapshot=snapshot)
        monkeypatch.setattr(store, "_write_json", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("disk denied")))
        with pytest.raises(SavedModelInferenceError) as captured:
            service.run(session_owner="owner", model_version_id="model", preparation_id=prepared.preparation_id)
        assert captured.value.code == "INFERENCE_RESULT_PERSISTENCE_FAILED"


def test_unsupported_predictor_is_rejected_by_preflight_without_prediction():
    with TemporaryDirectory() as temp:
        class _Unsupported: pass
        library = _Library(_Unsupported())
        service = SavedModelInferenceService(model_library_service=library, model_inference_service=ModelInferenceService(), result_store=SavedModelInferenceResultStore(Path(temp) / "results"), cleanup_upload=lambda _: None)
        frame = pd.DataFrame({"id": ["x"], "a": [1], "b": [2]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 1, 3, frame, tuple(frame.columns))
        staged = StagedUpload(Path(temp) / "input.csv", "input.csv", "a" * 64, Path(temp))
        with pytest.raises(Exception) as captured:
            service.preflight(session_owner="one", model_version_id="model", staged_upload=staged, snapshot=snapshot)
        assert getattr(captured.value, "code", None) == "MODEL_INFERENCE_UNSUPPORTED"


def test_result_read_and_view_configuration_survive_restart_without_prediction():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        predictor = _Predictor(); library = _Library(predictor)
        results = SavedModelInferenceResultStore(root / "inference_results")
        views = SavedInferenceResultViewConfigurationStore(root / "inference_view_configurations")
        service = SavedModelInferenceService(
            model_library_service=library, model_inference_service=ModelInferenceService(), result_store=results,
            view_store=views, cleanup_upload=lambda _: None,
        )
        frame = pd.DataFrame({"id": ["Alpha", "beta"], "a": [3, 4], "b": [10, 20]})
        snapshot = TabularSnapshot(Path("input.csv"), "csv", {}, "a" * 64, "fp", 2, 3, frame, tuple(frame.columns))
        staged = StagedUpload(root / "input.csv", "input.csv", "a" * 64, root)
        run = service.run(session_owner="owner", model_version_id="model", preparation_id=service.preflight(session_owner="owner", model_version_id="model", staged_upload=staged, snapshot=snapshot).preparation_id)
        before = (root / "inference_results" / run.inference_result_id / "manifest.json").read_bytes()
        assert predictor.calls == 1

        summary = service.summary(run.inference_result_id, threshold=.5)
        assert summary.above_threshold_count == 1 and len(summary.histogram) == 20
        objects = service.objects(run.inference_result_id, threshold=.5, offset=0, limit=1, search="BETA", sort="SCORE_DESC")
        assert objects.total_count == 2 and objects.filtered_count == 1 and objects.items[0]["identifier_display"] == "beta"
        defaults = service.get_view_configuration(run.inference_result_id)
        assert defaults.saved is False and defaults.configuration["inference_result_id"] == run.inference_result_id
        saved = service.put_view_configuration(run.inference_result_id, threshold=.4, min_score=.1, max_score=.9, position_filter="ALL", sort="SOURCE_ASC", search="beta")
        repeated = service.put_view_configuration(run.inference_result_id, threshold=.4, min_score=.1, max_score=.9, position_filter="ALL", sort="SOURCE_ASC", search="beta")
        assert saved.saved is True and repeated.configuration["updated_at"] == saved.configuration["updated_at"]

        restarted = SavedModelInferenceService(
            model_library_service=library, model_inference_service=ModelInferenceService(),
            result_store=SavedModelInferenceResultStore(root / "inference_results"),
            view_store=SavedInferenceResultViewConfigurationStore(root / "inference_view_configurations"), cleanup_upload=lambda _: None,
        )
        assert restarted.summary(run.inference_result_id).score_max == .8
        assert restarted.get_view_configuration(run.inference_result_id).configuration["search"] == "beta"
        assert predictor.calls == 1

        config_path = root / "inference_view_configurations" / f"{run.inference_result_id}.json"
        config_path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SavedModelInferenceError, match="INFERENCE_VIEW_CONFIGURATION_INTEGRITY_ERROR"):
            restarted.get_view_configuration(run.inference_result_id)
        assert restarted.delete_view_configuration(run.inference_result_id).saved is False
        assert not config_path.exists()

        restarted.put_view_configuration(
            run.inference_result_id, threshold=.4, min_score=.1, max_score=.9,
            position_filter="ALL", sort="SOURCE_ASC", search="beta",
        )
        config_path.write_bytes(b"\xff\xfe\xfd")
        with pytest.raises(SavedModelInferenceError, match="INFERENCE_VIEW_CONFIGURATION_INTEGRITY_ERROR"):
            restarted.get_view_configuration(run.inference_result_id)
        assert restarted.delete_view_configuration(run.inference_result_id).saved is False
        assert not config_path.exists()
        assert (root / "inference_results" / run.inference_result_id / "manifest.json").read_bytes() == before
