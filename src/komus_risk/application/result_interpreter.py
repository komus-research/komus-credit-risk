"""Model-independent, auditable interpretation of completed local evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from komus_risk.hashing import canonical_json, stable_hash

from .local_explanation import LocalExplanationEvidence
from .result_interpreter_prompts import ResultInterpreterPromptLoader, ResultInterpreterPromptsError

REQUEST_VERSION = "result_interpreter_v3"
TOP_N = 5
RESULT_INTERPRETER_ROLES = ("sales_manager", "credit_controller", "lawyer", "information_security")


class ResultInterpreterClient(Protocol):
    @property
    def interpreter_id(self) -> str: ...

    @property
    def interpreter_model(self) -> str: ...

    def interpret(self, *, system_instruction: str, payload: dict[str, Any]) -> str: ...


@dataclass(frozen=True, slots=True)
class InterpreterFeatureFact:
    feature_id: str
    column_name: str
    raw_value: float
    shap_value: float
    abs_rank: int
    display_name_ru: str | None
    description_ru: str | None


@dataclass(frozen=True, slots=True)
class ResultInterpreterRequest:
    request_version: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    recipient_role: str
    evidence_hash: str
    model_version_id: str
    row_id: str
    identifier_column: str
    identifier_value: Any
    probability: float
    shap_output_space: str
    raw_model_output: float
    base_value: float
    features: tuple[InterpreterFeatureFact, ...]
    request_hash: str


@dataclass(frozen=True, slots=True)
class ResultInterpreterResponse:
    request_hash: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    interpreter_id: str
    interpreter_model: str
    text: str
    created_at: str
    response_hash: str


class ResultInterpreterService:
    """Creates deterministic requests and delegates text generation to a client."""

    def __init__(self, prompt_loader: ResultInterpreterPromptLoader | None = None) -> None:
        self._prompt_loader = prompt_loader or ResultInterpreterPromptLoader()

    def build_request(self, *, evidence: LocalExplanationEvidence, recipient_role: str = "credit_controller", display_names_by_feature_id: Mapping[str, str] | None = None, descriptions_by_feature_id: Mapping[str, str] | None = None) -> ResultInterpreterRequest:
        if not isinstance(evidence, LocalExplanationEvidence):
            raise ValueError("Result interpreter requires LocalExplanationEvidence.")
        self._validate_role(recipient_role)
        prompt = self._load_prompt(recipient_role)
        features = self._top_features(evidence, self._text_map(display_names_by_feature_id, "display_names_by_feature_id"), self._text_map(descriptions_by_feature_id, "descriptions_by_feature_id"))
        payload = {
            "request_version": REQUEST_VERSION, "prompt_id": prompt.prompt_id, "prompt_version": prompt.prompt_version, "prompt_hash": prompt.prompt_hash,
            "recipient_role": recipient_role, "evidence_hash": evidence.evidence_hash, "model_version_id": evidence.model_version_id,
            "row_id": evidence.row_id, "identifier_column": evidence.identifier_column, "identifier_value": evidence.identifier_value,
            "probability": evidence.probability, "shap_output_space": evidence.shap_output_space, "raw_model_output": evidence.raw_model_output,
            "base_value": evidence.base_value, "features": features,
        }
        self._require_json_compatible(payload, "Result interpreter request")
        return ResultInterpreterRequest(**payload, request_hash=stable_hash(payload))

    def interpret(self, *, evidence: LocalExplanationEvidence, client: ResultInterpreterClient, recipient_role: str = "credit_controller", display_names_by_feature_id: Mapping[str, str] | None = None, descriptions_by_feature_id: Mapping[str, str] | None = None) -> ResultInterpreterResponse:
        return self.interpret_request(request=self.build_request(evidence=evidence, recipient_role=recipient_role, display_names_by_feature_id=display_names_by_feature_id, descriptions_by_feature_id=descriptions_by_feature_id), client=client)

    def interpret_request(self, *, request: ResultInterpreterRequest, client: ResultInterpreterClient) -> ResultInterpreterResponse:
        self.validate_request(request)
        prompt = self._load_prompt(request.recipient_role)
        if (prompt.prompt_id, prompt.prompt_version, prompt.prompt_hash) != (request.prompt_id, request.prompt_version, request.prompt_hash):
            raise ResultInterpreterPromptsError("RESULT_INTERPRETER_PROMPTS_INVALID: prompt identity changed after request creation.")
        try:
            interpreter_id, interpreter_model = client.interpreter_id, client.interpreter_model
            text = client.interpret(system_instruction=prompt.system_instruction, payload=self._client_payload(request))
        except ResultInterpreterPromptsError:
            raise
        except Exception as error:
            raise RuntimeError("Result interpreter client failed.") from error
        self._validate_client_identity(interpreter_id, "interpreter_id")
        self._validate_client_identity(interpreter_model, "interpreter_model")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Result interpreter client returned invalid text.")
        semantic_response = {"request_hash": request.request_hash, "prompt_id": request.prompt_id, "prompt_version": request.prompt_version, "prompt_hash": request.prompt_hash, "interpreter_id": interpreter_id, "interpreter_model": interpreter_model, "text": text}
        return ResultInterpreterResponse(**semantic_response, created_at=datetime.now(timezone.utc).isoformat(), response_hash=stable_hash(semantic_response))

    def validate_request(self, request: ResultInterpreterRequest) -> None:
        if not isinstance(request, ResultInterpreterRequest):
            raise ValueError("Result interpreter requires a ResultInterpreterRequest.")
        self._validate_role(request.recipient_role)
        semantic = {
            "request_version": request.request_version, "prompt_id": request.prompt_id, "prompt_version": request.prompt_version, "prompt_hash": request.prompt_hash,
            "recipient_role": request.recipient_role, "evidence_hash": request.evidence_hash, "model_version_id": request.model_version_id,
            "row_id": request.row_id, "identifier_column": request.identifier_column, "identifier_value": request.identifier_value,
            "probability": request.probability, "shap_output_space": request.shap_output_space, "raw_model_output": request.raw_model_output,
            "base_value": request.base_value, "features": request.features,
        }
        self._require_json_compatible(semantic, "Result interpreter request")
        if request.request_version != REQUEST_VERSION or stable_hash(semantic) != request.request_hash:
            raise ValueError("Result interpreter request hash integrity check failed.")

    def _load_prompt(self, recipient_role: str):
        try:
            return self._prompt_loader.load(recipient_role)
        except ResultInterpreterPromptsError:
            raise
        except Exception as error:
            raise ResultInterpreterPromptsError("RESULT_INTERPRETER_PROMPTS_INVALID") from error

    @staticmethod
    def _text_map(value: Mapping[str, str] | None, field_name: str) -> Mapping[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError(f"{field_name} must be a mapping or None.")
        normalized: dict[str, str] = {}
        for feature_id, text in value.items():
            if not isinstance(feature_id, str) or not isinstance(text, str):
                raise ValueError("Feature metadata must use string feature IDs and text values.")
            if text.strip():
                normalized[feature_id] = text.strip()
        return normalized

    @staticmethod
    def _validate_role(recipient_role: str) -> None:
        if recipient_role not in RESULT_INTERPRETER_ROLES:
            raise ValueError("Unknown result interpreter recipient role.")

    @staticmethod
    def _top_features(evidence: LocalExplanationEvidence, display_names: Mapping[str, str], descriptions: Mapping[str, str]) -> tuple[InterpreterFeatureFact, ...]:
        source = tuple(evidence.features)
        ranks = [item.abs_rank for item in source]
        if not source or any(not isinstance(rank, int) or isinstance(rank, bool) for rank in ranks) or set(ranks) != set(range(1, len(source) + 1)):
            raise ValueError("LocalExplanationEvidence feature abs_rank values must be unique and contiguous.")
        by_rank = {item.abs_rank: item for item in source}
        selected = (by_rank[rank] for rank in range(1, min(TOP_N, len(source)) + 1))
        return tuple(InterpreterFeatureFact(item.feature_id, item.column_name, item.raw_value, item.shap_value, item.abs_rank, display_names.get(item.feature_id), descriptions.get(item.feature_id)) for item in selected)

    @staticmethod
    def _client_payload(request: ResultInterpreterRequest) -> dict[str, Any]:
        payload = {
            "recipient_role": request.recipient_role, "identifier": {"column": request.identifier_column, "value": request.identifier_value},
            "prediction": {"probability": request.probability}, "explanation": {"shap_output_space": request.shap_output_space, "raw_model_output": request.raw_model_output, "base_value": request.base_value},
            "top_features": [{"feature_id": item.feature_id, "column_name": item.column_name, "raw_value": item.raw_value, "shap_value": item.shap_value, "abs_rank": item.abs_rank, "display_name_ru": item.display_name_ru, "description_ru": item.description_ru} for item in request.features],
            "provenance": {"evidence_hash": request.evidence_hash, "model_version_id": request.model_version_id, "row_id": request.row_id},
        }
        ResultInterpreterService._require_json_compatible(payload, "Result interpreter client payload")
        return json.loads(canonical_json(payload))

    @staticmethod
    def _require_json_compatible(value: Any, label: str) -> None:
        try:
            canonical_json(value)
        except ValueError as error:
            raise ValueError(f"{label} must contain only JSON-compatible facts.") from error

    @staticmethod
    def _validate_client_identity(value: Any, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Result interpreter client {field_name} must be a non-empty string.")
