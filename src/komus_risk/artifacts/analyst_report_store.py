"""Immutable canonical analyst-report artifacts and saved interpretations."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from komus_risk.hashing import stable_hash


class AnalystReportNotFoundError(ValueError):
    pass


class AnalystReportIntegrityError(ValueError):
    pass


class AnalystReportPersistenceError(RuntimeError):
    pass


class SavedInterpretationIntegrityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SavedInferenceInterpretationRecord:
    inference_result_id: str
    model_version_id: str
    row_id: str
    explanation_id: str
    evidence_hash: str
    role: str
    text: str
    created_at: str
    response_hash: str
    response_content: dict[str, str] | None = None
    record_hash: str | None = None


class SavedInferenceInterpretationStore:
    """Append-only trusted interpreter responses, indexed by immutable evidence."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, value: SavedInferenceInterpretationRecord) -> SavedInferenceInterpretationRecord:
        value = self._normalized(value)
        path = self._path(value.inference_result_id, value.row_id, value.role, value.record_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload(value)
        if path.exists():
            existing = self._read_path(path)
            if existing != value:
                raise SavedInterpretationIntegrityError()
            return existing
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            self._write_json(temporary, payload)
            os.replace(temporary, path)
            return value
        except OSError as error:
            raise AnalystReportPersistenceError() from error
        finally:
            temporary.unlink(missing_ok=True)

    def list_for_evidence(self, inference_result_id: str, row_id: str, *, model_version_id: str, explanation_id: str, evidence_hash: str) -> tuple[SavedInferenceInterpretationRecord, ...]:
        if not self._safe_path_part(inference_result_id) or not self._safe_path_part(row_id):
            raise SavedInterpretationIntegrityError()
        directory = self.root / inference_result_id / self._row_key(row_id)
        if not directory.exists():
            return ()
        try:
            values = tuple(self._read_path(path) for path in sorted(directory.glob("*/*.json")))
        except OSError as error:
            raise AnalystReportPersistenceError() from error
        if any(
            value.inference_result_id != inference_result_id or value.row_id != row_id or value.model_version_id != model_version_id
            or value.explanation_id != explanation_id or value.evidence_hash != evidence_hash
            for value in values
        ):
            raise SavedInterpretationIntegrityError()
        return values

    def _read_path(self, path: Path) -> SavedInferenceInterpretationRecord:
        try:
            with path.open(encoding="utf-8") as handle:
                value = SavedInferenceInterpretationRecord(**json.load(handle))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SavedInterpretationIntegrityError() from error
        self._validate(value)
        if (
            path.parent.name != value.role
            or path.stem != value.record_hash
            or path.parent.parent.name != self._row_key(value.row_id)
            or path.parent.parent.parent.name != value.inference_result_id
        ):
            raise SavedInterpretationIntegrityError()
        return value

    @staticmethod
    def _payload(value: SavedInferenceInterpretationRecord) -> dict[str, Any]:
        return {
            "inference_result_id": value.inference_result_id, "model_version_id": value.model_version_id,
            "row_id": value.row_id, "explanation_id": value.explanation_id,
            "evidence_hash": value.evidence_hash, "role": value.role, "text": value.text,
                "created_at": value.created_at, "response_hash": value.response_hash,
                "response_content": value.response_content,
                "record_hash": value.record_hash,
        }

    @classmethod
    def _normalized(cls, value: SavedInferenceInterpretationRecord) -> SavedInferenceInterpretationRecord:
        if not isinstance(value, SavedInferenceInterpretationRecord):
            raise SavedInterpretationIntegrityError()
        record_hash = stable_hash(cls._content(value))
        if value.record_hash is not None and value.record_hash != record_hash:
            raise SavedInterpretationIntegrityError()
        normalized = replace(value, record_hash=record_hash)
        cls._validate(normalized)
        return normalized

    @staticmethod
    def _content(value: SavedInferenceInterpretationRecord) -> dict[str, Any]:
        return {
            "inference_result_id": value.inference_result_id, "model_version_id": value.model_version_id,
            "row_id": value.row_id, "explanation_id": value.explanation_id,
            "evidence_hash": value.evidence_hash, "role": value.role, "text": value.text,
            "created_at": value.created_at, "response_hash": value.response_hash,
            "response_content": value.response_content,
        }

    @classmethod
    def _validate(cls, value: SavedInferenceInterpretationRecord) -> None:
        valid_timestamp = False
        try:
            valid_timestamp = datetime.fromisoformat(value.created_at.replace("Z", "+00:00")).tzinfo is not None
        except (AttributeError, ValueError):
            pass
        if (
            not all(isinstance(item, str) and item.strip() for item in (
                value.inference_result_id, value.model_version_id, value.row_id, value.explanation_id,
                value.evidence_hash, value.role, value.text, value.created_at, value.response_hash, value.record_hash,
            ))
            or len(value.inference_result_id) != 64
            or any(character not in "0123456789abcdef" for character in value.inference_result_id)
            or len(value.record_hash) != 64
            or any(character not in "0123456789abcdef" for character in value.record_hash)
            or not valid_timestamp
            or not isinstance(value.response_content, dict)
            or set(value.response_content) != {"request_hash", "prompt_id", "prompt_version", "prompt_hash", "interpreter_id", "interpreter_model", "text"}
            or not all(isinstance(item, str) and item.strip() for item in value.response_content.values())
            or value.response_content.get("text") != value.text
            or value.response_hash != stable_hash(value.response_content)
            or value.record_hash != stable_hash(cls._content(value))
        ):
            raise SavedInterpretationIntegrityError()

    def _path(self, inference_result_id: str, row_id: str, role: str, record_hash: str | None) -> Path:
        if not all(self._safe_path_part(item) for item in (inference_result_id, row_id, role, record_hash)):
            raise SavedInterpretationIntegrityError()
        return self.root / inference_result_id / self._row_key(row_id) / role / f"{record_hash}.json"

    @staticmethod
    def _row_key(row_id: str) -> str:
        # Row IDs may contain characters illegal in Windows paths, and the
        # full report-artifact root is already long.  This is an opaque shard
        # key, not an authority: payload and expected-row validation remain
        # mandatory on every read.
        return stable_hash({"row_id": row_id})[:16]

    @staticmethod
    def _safe_path_part(value: object) -> bool:
        return isinstance(value, str) and value not in {"", ".", ".."} and "/" not in value and "\\" not in value

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())


class AnalystReportStore:
    """Directory-per-report immutable JSON store under ``analyst_reports``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def semantic_snapshot(cls, report: object) -> dict[str, Any]:
        """Validate V1 and reconstruct the only hashable report meaning."""
        if not isinstance(report, dict) or set(report) != {
            "schema_version", "report_id", "content_hash", "created_at", "source",
            "decision_context", "selection", "companies",
        } or report.get("schema_version") != 1 or not cls._timestamp(report.get("created_at")):
            raise AnalystReportIntegrityError()
        source = report["source"]
        if not isinstance(source, dict) or set(source) != {
            "inference_result_id", "model_version_id", "experiment_artifact_id", "model_id",
            "model_version", "source_file_sha256", "inference_recipe_key",
        } or not all(cls._text(source.get(key)) for key in source):
            raise AnalystReportIntegrityError()
        if not all(cls._hash(source[key]) for key in ("inference_result_id", "source_file_sha256", "inference_recipe_key")):
            raise AnalystReportIntegrityError()
        decision = report["decision_context"]
        if not isinstance(decision, dict) or set(decision) != {"threshold", "threshold_source"} or not cls._probability(decision.get("threshold")) or decision.get("threshold_source") not in {"MODEL_DECISION", "TECHNICAL_DEFAULT"}:
            raise AnalystReportIntegrityError()
        selection = report["selection"]
        if not isinstance(selection, dict) or set(selection) != {"inference_result_id", "selected_row_ids", "selection_hash"} or selection.get("inference_result_id") != source["inference_result_id"] or not isinstance(selection.get("selected_row_ids"), list) or not selection["selected_row_ids"] or not all(cls._text(item) for item in selection["selected_row_ids"]) or len(set(selection["selected_row_ids"])) != len(selection["selected_row_ids"]) or selection.get("selection_hash") != stable_hash(selection["selected_row_ids"]):
            raise AnalystReportIntegrityError()
        companies = report["companies"]
        if not isinstance(companies, list) or len(companies) != len(selection["selected_row_ids"]):
            raise AnalystReportIntegrityError()
        for company, expected_row_id in zip(companies, selection["selected_row_ids"], strict=True):
            cls._company(company, source, decision, expected_row_id)
        snapshot = {
            "schema_version": 1, "source": source, "decision_context": decision,
            "selection": selection, "companies": companies,
        }
        content_hash = stable_hash(snapshot)
        if report.get("report_id") != content_hash or report.get("content_hash") != content_hash:
            raise AnalystReportIntegrityError()
        return snapshot

    @classmethod
    def _company(cls, company: object, source: dict[str, Any], decision: dict[str, Any], row_id: str) -> None:
        keys = {"row_id", "identifier", "subject_name", "score", "threshold", "position", "local_shap", "report_visible_contributions", "role_interpretations", "evidence"}
        if not isinstance(company, dict) or set(company) != keys or company.get("row_id") != row_id or not cls._text(company.get("identifier")) or (company.get("subject_name") is not None and not cls._text(company.get("subject_name"))) or not cls._probability(company.get("score")) or company.get("threshold") != decision["threshold"] or company.get("position") not in {"ABOVE", "BELOW"} or company["position"] != ("ABOVE" if company["score"] >= company["threshold"] else "BELOW"):
            raise AnalystReportIntegrityError()
        local = company["local_shap"]
        local_keys = {"explanation_id", "evidence_hash", "prediction_probability", "base_value", "explained_output_value", "output_space", "method", "provider", "features", "remainder"}
        if not isinstance(local, dict) or set(local) != local_keys or not all(cls._text(local.get(key)) for key in ("explanation_id", "evidence_hash", "output_space")) or not cls._probability(local.get("prediction_probability")) or local["prediction_probability"] != company["score"] or not all(cls._number(local.get(key)) for key in ("base_value", "explained_output_value")) or not cls._named_version(local.get("method")) or not cls._named_version(local.get("provider")) or not isinstance(local.get("features"), list) or not local["features"]:
            raise AnalystReportIntegrityError()
        features = local["features"]
        for contribution in features:
            cls._contribution(contribution)
        ranks = [item["abs_rank"] for item in features]
        if ranks != list(range(1, len(features) + 1)):
            raise AnalystReportIntegrityError()
        remainder = local["remainder"]
        if remainder is not None and (not isinstance(remainder, dict) or set(remainder) != {"feature_count", "shap_value", "direction"} or not isinstance(remainder.get("feature_count"), int) or remainder["feature_count"] < 1 or not cls._number(remainder.get("shap_value")) or remainder.get("direction") not in {"increases_output", "decreases_output", "neutral"}):
            raise AnalystReportIntegrityError()
        visible = company["report_visible_contributions"]
        if not isinstance(visible, list) or visible != [item for item in features if item["abs_rank"] <= 10]:
            raise AnalystReportIntegrityError()
        evidence = company["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {"source_file_sha256", "feature_binding_hash", "local_explanation_hash"} or evidence.get("source_file_sha256") != source["source_file_sha256"] or evidence.get("local_explanation_hash") != local["evidence_hash"] or not cls._hash(evidence.get("feature_binding_hash")):
            raise AnalystReportIntegrityError()
        if not isinstance(company["role_interpretations"], list):
            raise AnalystReportIntegrityError()
        for item in company["role_interpretations"]:
            cls._interpretation(item, source, row_id, local)

    @classmethod
    def _contribution(cls, value: object) -> None:
        if not isinstance(value, dict) or set(value) != {"feature_id", "column_name", "display_name_ru", "description_ru", "raw_value", "shap_value", "abs_rank", "direction"} or not cls._text(value.get("feature_id")) or not cls._text(value.get("column_name")) or (value.get("display_name_ru") is not None and not cls._text(value.get("display_name_ru"))) or (value.get("description_ru") is not None and not cls._text(value.get("description_ru"))) or not cls._number(value.get("raw_value")) or not cls._number(value.get("shap_value")) or isinstance(value.get("abs_rank"), bool) or not isinstance(value.get("abs_rank"), int) or value["abs_rank"] < 1 or value.get("direction") not in {"increases_output", "decreases_output", "neutral"}:
            raise AnalystReportIntegrityError()

    @classmethod
    def _interpretation(cls, item: object, source: dict[str, Any], row_id: str, local: dict[str, Any]) -> None:
        keys = {"role", "text", "created_at", "response_hash", "evidence_hash", "explanation_id", "record_hash", "response_content"}
        if not isinstance(item, dict) or set(item) != keys or not all(cls._text(item.get(key)) for key in ("role", "text", "response_hash", "evidence_hash", "explanation_id", "record_hash")) or not cls._timestamp(item.get("created_at")) or item["evidence_hash"] != local["evidence_hash"] or item["explanation_id"] != local["explanation_id"] or not cls._hash(item["record_hash"]):
            raise AnalystReportIntegrityError()
        response_content = item.get("response_content")
        if (not isinstance(response_content, dict) or set(response_content) != {"request_hash", "prompt_id", "prompt_version", "prompt_hash", "interpreter_id", "interpreter_model", "text"} or not all(cls._text(value) for value in response_content.values()) or response_content.get("text") != item["text"] or stable_hash(response_content) != item["response_hash"]):
            raise AnalystReportIntegrityError()
        expected = stable_hash({
            "inference_result_id": source["inference_result_id"], "model_version_id": source["model_version_id"],
            "row_id": row_id, "explanation_id": item["explanation_id"], "evidence_hash": item["evidence_hash"],
            "role": item["role"], "text": item["text"], "created_at": item["created_at"], "response_hash": item["response_hash"], "response_content": response_content,
        })
        if item["record_hash"] != expected:
            raise AnalystReportIntegrityError()

    @staticmethod
    def _text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _hash(value: object) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)

    @staticmethod
    def _number(value: object) -> bool:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(float(value))

    @classmethod
    def _probability(cls, value: object) -> bool:
        return cls._number(value) and 0 <= float(value) <= 1

    @classmethod
    def _named_version(cls, value: object) -> bool:
        return isinstance(value, dict) and set(value) == {"id", "version"} and cls._text(value.get("id")) and cls._text(value.get("version"))

    @staticmethod
    def _timestamp(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
        except ValueError:
            return False

    def read(self, report_id: str) -> dict[str, Any]:
        if not self._valid_id(report_id):
            raise AnalystReportNotFoundError()
        directory = self.root / report_id
        if not directory.is_dir():
            raise AnalystReportNotFoundError()
        try:
            report = self._read_json(directory / "report.json")
            manifest = self._read_json(directory / "manifest.json")
            self.semantic_snapshot(report)
            if (
                not isinstance(report, dict) or report.get("report_id") != report_id
                or report.get("content_hash") != report_id
                or not isinstance(manifest, dict) or set(manifest) != {"artifact_type", "schema_version", "report_id", "report_hash", "files"}
                or manifest.get("artifact_type") != "analyst_report" or manifest.get("schema_version") != 1
                or manifest.get("report_id") != report_id or manifest.get("report_hash") != stable_hash(report)
                or manifest.get("files") != {"report.json": {"sha256": self._file_hash(directory / "report.json"), "size_bytes": (directory / "report.json").stat().st_size}}
            ):
                raise ValueError
            return report
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AnalystReportIntegrityError() from error

    def publish(self, report: dict[str, Any]) -> tuple[dict[str, Any], str]:
        report_id = report.get("report_id")
        if not isinstance(report_id, str) or report.get("content_hash") != report_id or not self._valid_id(report_id):
            raise AnalystReportIntegrityError()
        self.semantic_snapshot(report)
        try:
            existing = self.read(report_id)
        except AnalystReportNotFoundError:
            existing = None
        if existing is not None:
            return existing, "REUSED"
        temporary: Path | None = None
        try:
            temporary = Path(mkdtemp(prefix=".analyst-report-", dir=self.root))
            self._write_json(temporary / "report.json", report)
            manifest = {
                "artifact_type": "analyst_report", "schema_version": 1, "report_id": report_id,
                "report_hash": stable_hash(report),
                "files": {"report.json": {"sha256": self._file_hash(temporary / "report.json"), "size_bytes": (temporary / "report.json").stat().st_size}},
            }
            self._write_json(temporary / "manifest.json", manifest)
            self.read_from(temporary, report_id)
            try:
                os.replace(temporary, self.root / report_id)
            except OSError:
                return self.read(report_id), "REUSED"
            return self.read(report_id), "CREATED"
        except AnalystReportIntegrityError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise AnalystReportPersistenceError() from error
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def read_from(self, directory: Path, report_id: str) -> dict[str, Any]:
        report = self._read_json(directory / "report.json")
        manifest = self._read_json(directory / "manifest.json")
        self.semantic_snapshot(report)
        if not isinstance(report, dict) or report.get("report_id") != report_id or manifest.get("report_hash") != stable_hash(report):
            raise AnalystReportIntegrityError()
        return report

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _file_hash(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _valid_id(value: object) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(item in "0123456789abcdef" for item in value)
