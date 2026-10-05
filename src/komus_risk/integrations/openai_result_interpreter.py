"""OpenAI Responses API adapter for result-interpreter text generation."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from komus_risk.hashing import canonical_json


class OpenAIResultInterpreterClient:
    """Adapt an OpenAI-compatible Responses client to the interpreter protocol."""

    def __init__(
        self,
        *,
        model: str,
        reasoning_effort: str = "low",
        max_output_tokens: int = 2400,
        client: Any | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("OpenAI result interpreter model must be a non-empty string.")
        if reasoning_effort not in {"none", "low", "medium", "high"}:
            raise ValueError("OpenAI result interpreter reasoning effort is unsupported.")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 1 <= max_output_tokens <= 100_000
        ):
            raise ValueError("OpenAI result interpreter max_output_tokens is invalid.")
        self._model = model.strip()
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._client = OpenAI() if client is None else client

    @property
    def interpreter_id(self) -> str:
        return "openai"

    @property
    def interpreter_model(self) -> str:
        return self._model

    def interpret(self, *, system_instruction: str, payload: dict[str, Any]) -> str:
        """Return non-empty output_text from one Responses API request."""
        response = self._client.responses.create(
            model=self._model,
            reasoning={"effort": self._reasoning_effort},
            max_output_tokens=self._max_output_tokens,
            input=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": canonical_json(payload)},
            ],
            # Privacy invariant: Result Interpreter responses are not stored by provider.
            store=False,
        )
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("OpenAI result interpreter response did not contain non-empty output_text.")
        return text
