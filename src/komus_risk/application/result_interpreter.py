"""Model-independent boundary for interpreting completed local evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from komus_risk.hashing import canonical_json, stable_hash

from .local_explanation import LocalExplanationEvidence

REQUEST_VERSION = "result_interpreter_v2"
TOP_N = 5
RESULT_INTERPRETER_ROLES = (
    "sales_manager",
    "credit_controller",
    "lawyer",
    "information_security",
)

_BASE_SYSTEM_INSTRUCTION = """Отвечайте только на русском языке и используйте исключительно факты из payload.
Probability — уже рассчитанный результат модели: не пересчитывайте и не изменяйте его.
Не пересчитывайте и не изменяйте SHAP. Положительный SHAP повышает model score положительного класса,
отрицательный SHAP снижает его. SHAP описывает поведение модели и не доказывает причинность.
Если у признака есть display_name_ru/description_ru, используйте их. Если полезного описания нет,
называйте только technical column_name и прямо говорите, что предметный смысл не задан.
Не принимайте решение «одобрить/отказать», не выбирайте threshold, не давайте нормативных кредитных
или юридических рекомендаций и не утверждайте, что событие обязательно произойдёт.
Пишите человеческим языком: не объясняйте raw_margin и внутреннюю механику SHAP, если роль этого не требует."""

_ROLE_INSTRUCTIONS = {
    "sales_manager": """Аудитория — менеджер по продажам.
Дайте короткое понятное резюме в 3–5 предложениях: что показала модель и какие 2–3 фактора сильнее всего
сдвинули её оценку вверх или вниз. Избегайте формул и технических терминов. Завершите одной фразой о том,
что это объяснение модели, а не самостоятельное кредитное решение.""",
    "credit_controller": """Аудитория — кредитный контролёр.
Кратко зафиксируйте probability и затем разберите наиболее значимые факторы по направлению влияния.
Отделяйте факты модели от интерпретации, отмечайте отсутствие предметного описания признака и не вводите
неутверждённый threshold или business decision. Завершите ограничениями SHAP.""",
    "lawyer": """Аудитория — юрист.
Сформулируйте аккуратное фактическое объяснение происхождения результата: probability рассчитана моделью,
а перечисленные факторы — локальные SHAP-вклады. Явно укажите, что SHAP не устанавливает причинность,
интерпретация не является юридическим или кредитным решением и не добавляет фактов, которых нет в payload.""",
    "information_security": """Аудитория — специалист по информационной безопасности.
Кратко объясните модельный результат, затем опишите только категории данных, фактически присутствующие в
полученном payload. Если идентификатор организации, row identity или raw feature values отсутствуют,
можно прямо указать их отсутствие. Не делайте выводов о хранении данных, retention или Zero Data Retention.""",
}


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
    interpreter_id: str
    interpreter_model: str
    text: str
    created_at: str
    response_hash: str


def _semantic_request_payload(
    *,
    request_version: str,
    recipient_role: str,
    evidence_hash: str,
    model_version_id: str,
    row_id: str,
    identifier_column: str,
    identifier_value: Any,
    probability: float,
    shap_output_space: str,
    raw_model_output: float,
    base_value: float,
    features: tuple[InterpreterFeatureFact, ...],
) -> dict[str, Any]:
    """Return the complete canonical semantic representation of a request."""
    return {
        "request_version": request_version,
        "recipient_role": recipient_role,
        "evidence_hash": evidence_hash,
        "model_version_id": model_version_id,
        "row_id": row_id,
        "identifier_column": identifier_column,
        "identifier_value": identifier_value,
        "probability": probability,
        "shap_output_space": shap_output_space,
        "raw_model_output": raw_model_output,
        "base_value": base_value,
        "features": features,
    }


class ResultInterpreterService:
    """Creates deterministic requests and delegates text generation to an injected client."""

    def build_request(
        self,
        *,
        evidence: LocalExplanationEvidence,
        recipient_role: str = "credit_controller",
        display_names_by_feature_id: Mapping[str, str] | None = None,
        descriptions_by_feature_id: Mapping[str, str] | None = None,
    ) -> ResultInterpreterRequest:
        if not isinstance(evidence, LocalExplanationEvidence):
            raise ValueError("Result interpreter requires LocalExplanationEvidence.")
        self._validate_role(recipient_role)
        display_names = self._text_map(display_names_by_feature_id, "display_names_by_feature_id")
        descriptions = self._text_map(descriptions_by_feature_id, "descriptions_by_feature_id")
        features = self._top_features(evidence, display_names, descriptions)
        payload = _semantic_request_payload(
            request_version=REQUEST_VERSION,
            recipient_role=recipient_role,
            evidence_hash=evidence.evidence_hash,
            model_version_id=evidence.model_version_id,
            row_id=evidence.row_id,
            identifier_column=evidence.identifier_column,
            identifier_value=evidence.identifier_value,
            probability=evidence.probability,
            shap_output_space=evidence.shap_output_space,
            raw_model_output=evidence.raw_model_output,
            base_value=evidence.base_value,
            features=features,
        )
        self._require_json_compatible(payload, "Result interpreter request")
        return ResultInterpreterRequest(**payload, request_hash=stable_hash(payload))

    def interpret(
        self,
        *,
        evidence: LocalExplanationEvidence,
        client: ResultInterpreterClient,
        recipient_role: str = "credit_controller",
        display_names_by_feature_id: Mapping[str, str] | None = None,
        descriptions_by_feature_id: Mapping[str, str] | None = None,
    ) -> ResultInterpreterResponse:
        return self.interpret_request(
            request=self.build_request(
                evidence=evidence,
                recipient_role=recipient_role,
                display_names_by_feature_id=display_names_by_feature_id,
                descriptions_by_feature_id=descriptions_by_feature_id,
            ),
            client=client,
        )

    def interpret_request(
        self,
        *,
        request: ResultInterpreterRequest,
        client: ResultInterpreterClient,
    ) -> ResultInterpreterResponse:
        self.validate_request(request)
        payload = self._client_payload(request)
        try:
            interpreter_id = client.interpreter_id
            interpreter_model = client.interpreter_model
            text = client.interpret(
                system_instruction=self._system_instruction(request.recipient_role),
                payload=payload,
            )
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

    def validate_request(self, request: ResultInterpreterRequest) -> None:
        """Validate the full internal request before any external projection."""
        if not isinstance(request, ResultInterpreterRequest):
            raise ValueError("Result interpreter requires a ResultInterpreterRequest.")
        self._validate_role(request.recipient_role)
        semantic_request = _semantic_request_payload(
            request_version=request.request_version,
            recipient_role=request.recipient_role,
            evidence_hash=request.evidence_hash,
            model_version_id=request.model_version_id,
            row_id=request.row_id,
            identifier_column=request.identifier_column,
            identifier_value=request.identifier_value,
            probability=request.probability,
            shap_output_space=request.shap_output_space,
            raw_model_output=request.raw_model_output,
            base_value=request.base_value,
            features=request.features,
        )
        self._require_json_compatible(semantic_request, "Result interpreter request")
        if stable_hash(semantic_request) != request.request_hash:
            raise ValueError("Result interpreter request hash integrity check failed.")

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
    def _system_instruction(recipient_role: str) -> str:
        ResultInterpreterService._validate_role(recipient_role)
        return _BASE_SYSTEM_INSTRUCTION + "\n\n" + _ROLE_INSTRUCTIONS[recipient_role]

    @staticmethod
    def _top_features(
        evidence: LocalExplanationEvidence,
        display_names: Mapping[str, str],
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
                display_name_ru=display_names.get(item.feature_id),
                description_ru=descriptions.get(item.feature_id),
            )
            for item in selected
        )

    @staticmethod
    def _client_payload(request: ResultInterpreterRequest) -> dict[str, Any]:
        payload = {
            "recipient_role": request.recipient_role,
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
                    "display_name_ru": item.display_name_ru,
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