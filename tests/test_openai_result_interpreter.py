from __future__ import annotations

from dataclasses import dataclass
import unittest

from komus_risk.application import (
    LocalExplanationEvidence,
    LocalFeatureContribution,
    ResultInterpreterService,
)
from komus_risk.hashing import canonical_json, stable_hash
from komus_risk.integrations import OpenAIResultInterpreterClient


@dataclass
class FakeResponse:
    output_text: object


class FakeResponses:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeOpenAIClient:
    def __init__(self, result: object) -> None:
        self.responses = FakeResponses(result)


class OpenAIResultInterpreterClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = "configured-result-interpreter-model"
        self.instruction = "Use only the facts in the payload."
        self.payload = {
            "prediction": {"probability": 0.731},
            "top_features": [{"column_name": "income", "shap_value": -0.12}],
        }

    def test_returns_output_text_and_sends_only_instruction_and_canonical_payload(self) -> None:
        fake = FakeOpenAIClient(FakeResponse("Fact-based explanation."))
        adapter = OpenAIResultInterpreterClient(model=self.model, client=fake)

        text = adapter.interpret(system_instruction=self.instruction, payload=self.payload)

        self.assertEqual("Fact-based explanation.", text)
        self.assertEqual(1, len(fake.responses.calls))
        self.assertEqual(
            {
                "model": self.model,
                "input": [
                    {"role": "system", "content": self.instruction},
                    {"role": "user", "content": canonical_json(self.payload)},
                ],
            },
            fake.responses.calls[0],
        )

    def test_arbitrary_model_is_preserved_and_blank_model_fails(self) -> None:
        arbitrary_model = "any-provider-model-name"
        adapter = OpenAIResultInterpreterClient(
            model=arbitrary_model,
            client=FakeOpenAIClient(FakeResponse("text")),
        )
        self.assertEqual("openai", adapter.interpreter_id)
        self.assertEqual(arbitrary_model, adapter.interpreter_model)
        for model in ("", "   "):
            with self.subTest(model=model):
                with self.assertRaisesRegex(ValueError, "non-empty"):
                    OpenAIResultInterpreterClient(model=model, client=FakeOpenAIClient(FakeResponse("text")))

    def test_missing_or_invalid_output_text_fails_closed(self) -> None:
        for output_text in (None, "", "  ", ["text"], {"text": "text"}):
            with self.subTest(output_text=output_text):
                adapter = OpenAIResultInterpreterClient(
                    model=self.model,
                    client=FakeOpenAIClient(FakeResponse(output_text)),
                )
                with self.assertRaisesRegex(ValueError, "output_text"):
                    adapter.interpret(system_instruction=self.instruction, payload=self.payload)

        adapter = OpenAIResultInterpreterClient(
            model=self.model,
            client=FakeOpenAIClient(object()),
        )
        with self.assertRaisesRegex(ValueError, "output_text"):
            adapter.interpret(system_instruction=self.instruction, payload=self.payload)

    def test_provider_exception_propagates(self) -> None:
        provider_error = RuntimeError("provider unavailable")
        adapter = OpenAIResultInterpreterClient(
            model=self.model,
            client=FakeOpenAIClient(provider_error),
        )

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            adapter.interpret(system_instruction=self.instruction, payload=self.payload)

    def test_service_integration_preserves_core_hashes_and_identity(self) -> None:
        service = ResultInterpreterService()
        evidence = LocalExplanationEvidence(
            evidence_version="local-evidence-v1",
            evidence_hash="evidence-hash-1",
            model_version_id="model-version-1",
            experiment_artifact_id="experiment-1",
            dataset_id="dataset-1",
            dataset_fingerprint="dataset-fingerprint-1",
            feature_set_hash="feature-set-1",
            model_id="model-1",
            model_version="version-1",
            row_id="row-1",
            identifier_column="client_id",
            identifier_value="client-42",
            probability=0.731,
            shap_output_space="raw_margin",
            raw_model_output=1.0,
            base_value=0.2,
            features=(
                LocalFeatureContribution(
                    feature_id="income",
                    column_name="income",
                    raw_value=100.0,
                    shap_value=-0.12,
                    abs_rank=1,
                ),
            ),
            explainer_id="explainer-1",
            explainer_version="v1",
            created_at="2026-09-24T00:00:00+00:00",
        )
        fake = FakeOpenAIClient(FakeResponse("Fact-based explanation."))
        adapter = OpenAIResultInterpreterClient(model=self.model, client=fake)

        request = service.build_request(evidence=evidence)
        response = service.interpret_request(request=request, client=adapter)

        self.assertEqual(request.request_hash, response.request_hash)
        self.assertEqual("openai", response.interpreter_id)
        self.assertEqual(self.model, response.interpreter_model)
        self.assertEqual("Fact-based explanation.", response.text)
        self.assertEqual(
            stable_hash(
                {
                    "request_hash": request.request_hash,
                    "interpreter_id": "openai",
                    "interpreter_model": self.model,
                    "text": response.text,
                }
            ),
            response.response_hash,
        )
        self.assertEqual(1, len(fake.responses.calls))


if __name__ == "__main__":
    unittest.main()
