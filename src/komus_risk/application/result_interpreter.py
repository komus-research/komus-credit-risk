"""Model-independent boundary for interpreting completed local evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from komus_risk.hashing import canonical_json, stable_hash

from .local_explanation import LocalExplanationEvidence

REQUEST_VERSION = "result_interpreter_v1"
TOP_N = 5
SYSTEM_INSTRUCTION = """Отвечайте только на русском языке и используйте исключительно факты из payload.
Probability — это уже готовый результат модели: не пересчитывайте и не изменяйте его.
Не пересчитывайте и не изменяйте SHAP. Объясняйте SHAP только в указанном shap_output_space:
положительный SHAP повышает model score положительного класса, отрицательный SHAP снижает его.
SHAP не доказывает причинность. Не придумывайте смысл признака без description_ru; если описания нет,
используйте только technical column_name. Не принимайте решение «одобрить/отказать», не выбирайте
threshold, не давайте нормативных кредитных рекомендаций и не утверждайте, что дефолт или событие
обязательно произойдёт. Не изменяйте числа из payload."""


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
    description_ru: str | None


@dataclass(frozen=True, slots=True)
class ResultInterpreterRequest:
    request_version: str
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
    interpreter_id: str
    interpreter_model: str
    text: str
    created_at: str
    response_hash: str


class ResultInterpreterService:
    """Creates deterministic requests and delegates text generation to an injected client."""

    def build_request(
        self,
        *,
        evidence: LocalExplanationEvidence,
        descriptions_by_feature_id: Mapping[str, str] | None = None,
    ) -> ResultInterpreterRequest:
        if not isinstance(evidence, LocalExplanationEvidence):
            raise ValueError("Result interpreter requires LocalExplanationEvidence.")
        descriptions = self._descriptions(descriptions_by_feature_id)
        features = self._top_features(evidence, descriptions)
        payload = {
            "request_version": REQUEST_VERSION,
            "evidence_hash": evidence.evidence_hash,
            "model_version_id": evidence.model_version_id,
            "row_id": evidence.row_id,
            "identifier_column": evidence.identifier_column,
            "identifier_value": evidence.identifier_value,
            "probability": evidence.probability,
            "shap_output_space": evidence.shap_output_space,
            "raw_model_output": evidence.raw_model_output,
            "base_value": evidence.base_value,
            "features": features,
        }
        self._require_json_compatible(payload, "Result interpreter request")
        return ResultInterpreterRequest(**payload, request_hash=stable_hash(payload))

    def interpret(
        self,
        *,
        evidence: LocalExplanationEvidence,
        client: ResultInterpreterClient,
        descriptions_by_feature_id: Mapping[str, str] | None = None,
    ) -> ResultInterpreterResponse:
        return self.interpret_request(
            request=self.build_request(evidence=evidence, descriptions_by_feature_id=descriptions_by_feature_id),
            client=client,
        )

    def interpret_request(
        self,
        *,
        request: ResultInterpreterRequest,
        client: ResultInterpreterClient,
    ) -> ResultInterpreterResponse:
        if not isinstance(request, ResultInterpreterRequest):
            raise ValueError("Result interpreter requires a ResultInterpreterRequest.")
        payload = self._client_payload(request)
        try:
            interpreter_id = client.interpreter_id
            interpreter_model = client.interpreter_model
            text = client.interpret(system_instruction=SYSTEM_INSTRUCTION, payload=payload)
        except Exception as error:
            raise RuntimeError("Result interpreter client failed.") from error
        self._validate_client_identity(interpreter_id, "interpreter_id")
        self._validate_client_identity(interpreter_model, "interpreter_model")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Result interpreter client returned invalid text.")
        semantic_response = {
            "request_hash": request.request_hash,
            "interpreter_id": interpreter_id,
            "interpreter_model": interpreter_model,
            "text": text,
        }
        return ResultInterpreterResponse(
            **semantic_response,
            created_at=datetime.now(timezone.utc).isoformat(),
            response_hash=stable_hash(semantic_response),
        )

    @staticmethod
    def _descriptions(value: Mapping[str, str] | None) -> Mapping[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("descriptions_by_feature_id must be a mapping or None.")
        normalized: dict[str, str] = {}
        for feature_id, description in value.items():
            if not isinstance(feature_id, str) or not isinstance(description, str):
                raise ValueError("Feature descriptions must use string feature IDs and text values.")
            if description.strip():
                normalized[feature_id] = description
        return normalized

    @staticmethod
    def _top_features(
        evidence: LocalExplanationEvidence,
        descriptions: Mapping[str, str],
    ) -> tuple[InterpreterFeatureFact, ...]:
        source = tuple(evidence.features)
        if not source:
            raise ValueError("LocalExplanationEvidence must contain feature contributions.")
        expected_ranks = set(range(1, len(source) + 1))
        ranks = [item.abs_rank for item in source]
        if (any(not isinstance(rank, int) or isinstance(rank, bool) for rank in ranks)
                or set(ranks) != expected_ranks or len(set(ranks)) != len(ranks)):
            raise ValueError("LocalExplanationEvidence feature abs_rank values must be unique and contiguous.")
        by_rank = {item.abs_rank: item for item in source}
        selected_count = min(TOP_N, len(source))
        try:
            selected = tuple(by_rank[rank] for rank in range(1, selected_count + 1))
        except KeyError as error:
            raise ValueError("LocalExplanationEvidence does not contain the expected top feature ranks.") from error
        return tuple(
            InterpreterFeatureFact(
                feature_id=item.feature_id,
                column_name=item.column_name,
                raw_value=item.raw_value,
                shap_value=item.shap_value,
                abs_rank=item.abs_rank,
                description_ru=descriptions.get(item.feature_id),
            )
            for item in selected
        )

    @staticmethod
    def _client_payload(request: ResultInterpreterRequest) -> dict[str, Any]:
        payload = {
            "identifier": {"column": request.identifier_column, "value": request.identifier_value},
            "prediction": {"probability": request.probability},
            "explanation": {
                "shap_output_space": request.shap_output_space,
                "raw_model_output": request.raw_model_output,
                "base_value": request.base_value,
            },
            "top_features": [
                {
                    "feature_id": item.feature_id,
                    "column_name": item.column_name,
                    "raw_value": item.raw_value,
                    "shap_value": item.shap_value,
                    "abs_rank": item.abs_rank,
                    "description_ru": item.description_ru,
                }
                for item in request.features
            ],
            "provenance": {
                "evidence_hash": request.evidence_hash,
                "model_version_id": request.model_version_id,
                "row_id": request.row_id,
            },
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
