"""Provider-neutral outbound boundary for result interpretation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from komus_risk.hashing import canonical_json, stable_hash

from .result_interpreter import ResultInterpreterClient, ResultInterpreterRequest


@dataclass(frozen=True, slots=True)
class ProviderDispatchReceipt:
    """Immutable audit link between a full request and its provider projection."""

    source_request_hash: str
    policy_id: str
    policy_version: int
    provider_payload_hash: str


@dataclass(frozen=True, slots=True)
class ProviderDispatch:
    """The only provider-safe payload and its independently retained receipt."""

    payload: dict[str, Any]
    receipt: ProviderDispatchReceipt


class OutboundInterpreterPolicy(Protocol):
    @property
    def policy_id(self) -> str: ...

    @property
    def policy_version(self) -> int: ...

    def project(self, request: ResultInterpreterRequest) -> ProviderDispatch: ...


class RedactedV1OutboundPolicy:
    """Allowlist-only projection for an external result interpreter."""

    policy_id = "REDACTED_V1"
    policy_version = 1

    def project(self, request: ResultInterpreterRequest) -> ProviderDispatch:
        # Construct from typed facts: this deliberately has no full-payload copy
        # or blacklist removal path for future request fields to leak through.
        payload = {
            "prediction": {"probability": request.probability},
            "explanation": {"shap_output_space": request.shap_output_space},
            "top_features": [
                {
                    "feature_id": feature.feature_id,
                    "column_name": feature.column_name,
                    "shap_value": feature.shap_value,
                    "abs_rank": feature.abs_rank,
                    "display_name_ru": feature.display_name_ru,
                    "description_ru": feature.description_ru,
                }
                for feature in request.features
            ],
        }
        # Return ordinary JSON primitives and a canonical key representation.
        provider_payload = json.loads(canonical_json(payload))
        provider_payload_hash = stable_hash(provider_payload)
        return ProviderDispatch(
            payload=provider_payload,
            receipt=ProviderDispatchReceipt(
                source_request_hash=request.request_hash,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                provider_payload_hash=provider_payload_hash,
            ),
        )


class PolicyBoundResultInterpreterClient:
    """Delegate to a provider while admitting only a prepared dispatch payload."""

    def __init__(
        self,
        *,
        underlying_client: ResultInterpreterClient,
        dispatch: ProviderDispatch,
    ) -> None:
        self._underlying_client = underlying_client
        self._dispatch = dispatch

    @property
    def interpreter_id(self) -> str:
        return self._underlying_client.interpreter_id

    @property
    def interpreter_model(self) -> str:
        return self._underlying_client.interpreter_model

    def interpret(self, *, system_instruction: str, payload: dict[str, Any]) -> str:
        # ``payload`` is the legacy full internal client payload made by the
        # service. It is intentionally never forwarded to the underlying client.
        return self._underlying_client.interpret(
            system_instruction=system_instruction,
            payload=self._dispatch.payload,
        )