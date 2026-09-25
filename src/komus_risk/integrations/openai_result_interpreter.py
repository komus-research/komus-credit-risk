"""OpenAI Responses API adapter for result-interpreter text generation."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from komus_risk.hashing import canonical_json


class OpenAIResultInterpreterClient:
    """Adapt an OpenAI-compatible Responses client to ``ResultInterpreterClient``.

    The application service owns request construction and failure isolation.  This
    adapter only serializes its received payload, invokes the provider, and
    extracts the provider's final text.
    """

    def __init__(self, *, model: str, client: Any | None = None) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("OpenAI result interpreter model must be a non-empty string.")
        self._model = model
        self._client = OpenAI() if client is None else client

    @property
    def interpreter_id(self) -> str:
        return "openai"

    @property
    def interpreter_model(self) -> str:
        return self._model

    def interpret(self, *, system_instruction: str, payload: dict[str, Any]) -> str:
        """Return non-empty ``output_text`` from one Responses API request."""
        response = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": canonical_json(payload)},
            ],
        )
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("OpenAI result interpreter response did not contain non-empty output_text.")
        return text
