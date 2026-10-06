"""Focused contracts for canonical immutable analyst reports."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from komus_risk.application.analyst_report import AnalystReportError, AnalystReportService
from komus_risk.application.model_inference import PredictionBatch, PredictionRow, PreparedInferenceInput
from komus_risk.application.saved_model_inference import SavedModelInferenceError
from komus_risk.artifacts.analyst_report_store import (
    AnalystReportStore,
    SavedInferenceInterpretationRecord,
    SavedInferenceInterpretationStore,
)
from komus_risk.artifacts.inference_result_store import SavedModelInferenceResultStore
from komus_risk.artifacts.inference_view_store import SavedInferenceReportDraft, SavedInferenceReportDraftStore
from komus_risk.hashing import stable_hash


class _Explanations:
    def __init__(self, result_id: str, scores: dict[str, float]) -> None:
        self.result_id = result_id
        self.scores = scores
        self.fail = False

    def explain(self, inference_result_id: str, row_id: str):
        if self.fail:
            raise SavedModelInferenceError("INFERENCE_LOCAL_EXPLANATION_FAILED")
        assert inference_result_id == self.result_id
        score = self.scores[row_id]
        evidence_hash = stable_hash({"result": inference_result_id, "row": row_id, "score": score})
        return SimpleNamespace(
            inference_result_id=inference_result_id, model_version_id="model-v1", row_id=row_id,
            explanation_id=stable_hash({"row": row_id, "evidence": evidence_hash}), evidence_hash=evidence_hash,
            prediction_probability=score, base_value=0.0, explained_output_value=0.0,
            output_space="raw_margin", explanation_method_id="provider", explanation_method_version="1",
            explanation_provider_id="provider", explanation_provider_version="1", remainder=None,
            features=(
                SimpleNamespace(feature_id="f-1", column_name="first", display_name_ru=None, description_ru=None, raw_value=1.0, shap_value=0.4, abs_rank=1, direction="increases_output"),
                SimpleNamespace(feature_id="f-2", column_name="second", display_name_ru=None, description_ru=None, raw_value=2.0, shap_value=-0.1, abs_rank=2, direction="decreases_output"),
            ),
        )


def _service(root: Path):
    results = SavedModelInferenceResultStore(root / "inference_results")
    prepared = PreparedInferenceInput(
        model_version_id="model-v1", source_sha256="a" * 64, source_fingerprint="source",
        physical_headers_hash="headers", row_count=2, column_count=3, identifier_column="id",
        identifier_values=("Alpha", "Beta"), source_row_positions=(7, 8),
        required_feature_columns=("first", "second"), validated_feature_values=((1.0, 2.0), (3.0, 4.0)),
        ignored_columns=(),
    )

    batch = PredictionBatch(
        "model-v1", "a" * 64, "id", ("first", "second"),
        (PredictionRow("row-a", 7, "Alpha", 0.8), PredictionRow("row-b", 8, "Beta", 0.2)),
        (), ((1.0, 2.0), (3.0, 4.0)),
    )
    result = results.create(
        model_version_id="model-v1", experiment_artifact_id="artifact-v1", source_display_name="input.csv",
        source_format="csv", prepared=prepared, prediction_batch=batch,
    )
    drafts = SavedInferenceReportDraftStore(root / "inference_report_drafts")
    drafts.save(SavedInferenceReportDraft(
        1, result.inference_result_id, ("row-a", "row-b"),
        "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
    ))
    explanations = _Explanations(result.inference_result_id, {"row-a": 0.8, "row-b": 0.2})
    interpretations = SavedInferenceInterpretationStore(root / "inference_interpretations")
    library = SimpleNamespace(load_for_inference=lambda model_id: (
        SimpleNamespace(model_version_id=model_id, experiment_artifact_id="artifact-v1", decision_threshold=0.5, decision_threshold_state="USER_APPLIED"),
        SimpleNamespace(summary=SimpleNamespace(model_id="catboost", model_version="1")),
    ))
    return (
        AnalystReportService(
            result_store=results, draft_store=drafts, explanation_service=explanations,
            model_library_service=library, interpretation_store=interpretations,
            report_store=AnalystReportStore(root / "analyst_reports"),
        ), result, drafts, explanations, interpretations, root / "analyst_reports",
    )


def _record(result, explanation, *, row_id: str, evidence_hash: str | None = None):
    content = {"request_hash": "request", "prompt_id": "prompt", "prompt_version": "1", "prompt_hash": "prompt-hash", "interpreter_id": "interpreter", "interpreter_model": "model", "text": "trusted"}
    return SavedInferenceInterpretationRecord(
        result.inference_result_id, "model-v1", row_id, explanation.explanation_id,
        evidence_hash or explanation.evidence_hash, "lawyer", "trusted", "2026-01-03T00:00:00+00:00",
        stable_hash(content), content,
    )


def test_report_snapshot_is_ordered_immutable_and_idempotent():
    with TemporaryDirectory() as temp:
        service, result, drafts, explanations, interpretations, reports_root = _service(Path(temp))
        report, state = service.generate(result.inference_result_id)
        assert state == "CREATED"
        assert [item["row_id"] for item in report["companies"]] == ["row-a", "row-b"]
        assert [item["position"] for item in report["companies"]] == ["ABOVE", "BELOW"]
        assert report["companies"][0]["subject_name"] is None
        assert len(report["companies"][0]["report_visible_contributions"]) == 2
        report_path = reports_root / report["report_id"] / "report.json"
        before = report_path.read_bytes()

        same, repeated = service.generate(result.inference_result_id)
        assert repeated == "REUSED" and same["report_id"] == report["report_id"]

        drafts.save(replace(
            drafts.read(result.inference_result_id), selected_row_ids=("row-b",),
            updated_at="2026-01-02T00:00:00+00:00",
        ))
        explanation = explanations.explain(result.inference_result_id, "row-b")
        interpretations.save(_record(result, explanation, row_id="row-b"))
        changed, changed_state = service.generate(result.inference_result_id)
        assert changed_state == "CREATED" and changed["report_id"] != report["report_id"]
        assert changed["companies"][0]["role_interpretations"][0]["role"] == "lawyer"
        assert report_path.read_bytes() == before


def test_report_fails_closed_for_missing_local_evidence_without_publication():
    with TemporaryDirectory() as temp:
        service, result, _drafts, explanations, _interpretations, reports_root = _service(Path(temp))
        explanations.fail = True
        with pytest.raises(AnalystReportError, match="ANALYST_REPORT_LOCAL_EXPLANATION_UNAVAILABLE"):
            service.generate(result.inference_result_id)
        assert list(reports_root.iterdir()) == []


def test_report_fails_closed_for_persisted_interpretation_bound_to_foreign_evidence():
    with TemporaryDirectory() as temp:
        service, result, _drafts, explanations, interpretations, reports_root = _service(Path(temp))
        explanation = explanations.explain(result.inference_result_id, "row-a")
        interpretations.save(_record(result, explanation, row_id="row-a", evidence_hash="foreign-evidence"))
        with pytest.raises(AnalystReportError, match="ANALYST_REPORT_INTERPRETATION_INTEGRITY_ERROR"):
            service.generate(result.inference_result_id)
        assert list(reports_root.iterdir()) == []


def test_report_api_generates_then_returns_the_canonical_preview_document():
    from app.api.main import create_app

    report = {
        "schema_version": 1, "report_id": "a" * 64, "content_hash": "a" * 64,
        "created_at": "2026-01-01T00:00:00+00:00", "source": {},
        "decision_context": {"threshold": 0.5, "threshold_source": "TECHNICAL_DEFAULT"},
        "selection": {"selected_row_ids": ["row-a"]}, "companies": [],
    }
    service = SimpleNamespace(
        generate=lambda inference_result_id: (report, "CREATED"),
        get=lambda report_id: report,
    )
    client = TestClient(create_app(analyst_report_service=service))
    generated = client.post("/api/v1/inference-results/result/report")
    assert generated.status_code == 200
    assert generated.json() == {
        "report_id": "a" * 64, "created_at": report["created_at"], "generation_state": "CREATED",
    }
    preview = client.get(f"/api/v1/analyst-reports/{'a' * 64}")
    assert preview.status_code == 200
    assert preview.json() == report


def test_report_exports_are_valid_and_keep_artifact_company_order():
    from app.api.main import create_app

    with TemporaryDirectory() as temp:
        service, result, _drafts, _explanations, _interpretations, _reports_root = _service(Path(temp))
        report, _ = service.generate(result.inference_result_id)
        client = TestClient(create_app(analyst_report_service=service))

        pdf = client.get(f"/api/v1/analyst-reports/{report['report_id']}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF-") and len(pdf.content) > 100

        docx = client.get(f"/api/v1/analyst-reports/{report['report_id']}/docx")
        assert docx.status_code == 200
        assert docx.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert len(docx.content) > 100
        with ZipFile(BytesIO(docx.content)) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        assert document.index("Alpha") < document.index("Beta")


def test_report_export_missing_or_corrupt_report_fails_closed():
    from app.api.main import create_app

    with TemporaryDirectory() as temp:
        service, result, _drafts, _explanations, _interpretations, reports_root = _service(Path(temp))
        report, _ = service.generate(result.inference_result_id)
        client = TestClient(create_app(analyst_report_service=service))
        assert client.get("/api/v1/analyst-reports/missing/pdf").status_code == 404
        report_path = reports_root / report["report_id"] / "report.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        payload["companies"][0]["score"] = 0.7
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        _rewrite_manifest(report_path)
        assert client.get(f"/api/v1/analyst-reports/{report['report_id']}/docx").status_code == 409


def _rewrite_manifest(report_path: Path) -> None:
    directory = report_path.parent
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    manifest["report_hash"] = stable_hash(report)
    manifest["files"] = {"report.json": {"sha256": sha256(encoded).hexdigest(), "size_bytes": len(encoded)}}
    report_path.write_bytes(encoded)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")


@pytest.mark.parametrize("mutate", [
    lambda report: report["companies"][0].__setitem__("score", 0.7),
    lambda report: report["companies"][0]["local_shap"]["features"][0].__setitem__("shap_value", 0.9),
    lambda report: report["selection"].__setitem__("selected_row_ids", ["row-b", "row-a"]),
])
def test_report_rejects_semantic_corruption_even_with_a_recomputed_manifest(mutate):
    with TemporaryDirectory() as temp:
        service, result, _drafts, _explanations, _interpretations, reports_root = _service(Path(temp))
        report, _ = service.generate(result.inference_result_id)
        report_path = reports_root / report["report_id"] / "report.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        mutate(payload)
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        _rewrite_manifest(report_path)
        with pytest.raises(AnalystReportError, match="ANALYST_REPORT_INTEGRITY_ERROR"):
            service.get(report["report_id"])


@pytest.mark.parametrize("mutate", [
    lambda report: report["companies"][0].pop("evidence"),
    lambda report: report.__setitem__("schema_version", 2),
])
def test_report_rejects_missing_or_wrong_v1_schema(mutate):
    with TemporaryDirectory() as temp:
        service, result, _drafts, _explanations, _interpretations, reports_root = _service(Path(temp))
        report, _ = service.generate(result.inference_result_id)
        report_path = reports_root / report["report_id"] / "report.json"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        mutate(payload)
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        _rewrite_manifest(report_path)
        with pytest.raises(AnalystReportError, match="ANALYST_REPORT_INTEGRITY_ERROR"):
            service.get(report["report_id"])


@pytest.mark.parametrize("field, value", [("model_version_id", "foreign-model"), ("text", "tampered")])
def test_report_rejects_corrupt_persisted_interpretation(field, value):
    with TemporaryDirectory() as temp:
        service, result, _drafts, explanations, interpretations, _reports_root = _service(Path(temp))
        explanation = explanations.explain(result.inference_result_id, "row-a")
        interpretations.save(_record(result, explanation, row_id="row-a"))
        path = next(iter(interpretations.root.rglob("*.json")))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[field] = value
        content = {key: payload[key] for key in payload if key != "record_hash"}
        payload["record_hash"] = stable_hash(content)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(AnalystReportError, match="ANALYST_REPORT_INTERPRETATION_INTEGRITY_ERROR"):
            service.generate(result.inference_result_id)


def test_report_rejects_interpretation_role_payload_path_mismatch():
    with TemporaryDirectory() as temp:
        service, result, _drafts, explanations, interpretations, _reports_root = _service(Path(temp))
        explanation = explanations.explain(result.inference_result_id, "row-a")
        interpretations.save(_record(result, explanation, row_id="row-a"))
        path = next(iter(interpretations.root.rglob("*.json")))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["role"] = "credit_controller"
        content = {key: payload[key] for key in payload if key != "record_hash"}
        payload["record_hash"] = stable_hash(content)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(AnalystReportError, match="ANALYST_REPORT_INTERPRETATION_INTEGRITY_ERROR"):
            service.generate(result.inference_result_id)
