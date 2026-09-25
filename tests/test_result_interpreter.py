from __future__ import annotations

from dataclasses import replace
import unittest

from komus_risk.application import (
    LocalExplanationEvidence,
    LocalFeatureContribution,
    ResultInterpreterService,
)


class FakeInterpreter:
    def __init__(self, output: object = "Только фактическое описание.") -> None:
        self.output = output
        self.received_instruction: str | None = None
        self.received_payload: dict | None = None
        self.interpreter_id_read = False
        self.interpreter_model_read = False
        self.interpret_called = False

    @property
    def interpreter_id(self) -> str:
        self.interpreter_id_read = True
        return "fake-interpreter"

    @property
    def interpreter_model(self) -> str:
        self.interpreter_model_read = True
        return "fake-model-v1"

    def interpret(self, *, system_instruction: str, payload: dict) -> str:
        self.interpret_called = True
        self.received_instruction = system_instruction
        self.received_payload = payload
        if isinstance(self.output, Exception):
            raise self.output
        return self.output  # type: ignore[return-value]


class ResultInterpreterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ResultInterpreterService()
        self.evidence = LocalExplanationEvidence(
            evidence_version="local-evidence-v1",
            evidence_hash="evidence-hash-1",
            model_version_id="arbitrary-model-version",
            experiment_artifact_id="experiment-1",
            dataset_id="dataset-1",
            dataset_fingerprint="dataset-fingerprint-1",
            feature_set_hash="feature-set-1",
            model_id="any-future-model",
            model_version="any-future-version",
            row_id="row-1",
            identifier_column="client_id",
            identifier_value="client-42",
            probability=0.731,
            shap_output_space="raw_margin",
            raw_model_output=1.0,
            base_value=0.2,
            features=tuple(
                LocalFeatureContribution(
                    feature_id=f"feature-{rank}",
                    column_name=f"technical_{rank}",
                    raw_value=rank / 10,
                    shap_value=(rank - 4) / 10,
                    abs_rank=rank,
                )
                for rank in range(1, 8)
            ),
            explainer_id="any-explainer",
            explainer_version="any-version",
            created_at="2026-09-24T00:00:00+00:00",
        )

    def test_request_copies_evidence_facts_and_uses_existing_top_five_ranks(self) -> None:
        request = self.service.build_request(evidence=self.evidence)
        self.assertEqual(self.evidence.probability, request.probability)
        self.assertEqual(self.evidence.raw_model_output, request.raw_model_output)
        self.assertEqual(self.evidence.base_value, request.base_value)
        self.assertEqual([1, 2, 3, 4, 5], [item.abs_rank for item in request.features])
        self.assertEqual(
            [item.shap_value for item in self.evidence.features[:5]],
            [item.shap_value for item in request.features],
        )

    def test_model_independence_and_descriptions(self) -> None:
        request = self.service.build_request(
            evidence=self.evidence,
            descriptions_by_feature_id={
                "feature-1": "Проверенное описание",
                "feature-2": "  ",
                "not-in-evidence": "Игнорируется",
            },
        )
        self.assertEqual("arbitrary-model-version", request.model_version_id)
        self.assertEqual("Проверенное описание", request.features[0].description_ru)
        self.assertIsNone(request.features[1].description_ru)
        self.assertIsNone(request.features[2].description_ru)

    def test_client_receives_json_compatible_minimal_payload_and_instruction_boundaries(self) -> None:
        client = FakeInterpreter()
        response = self.service.interpret(evidence=self.evidence, client=client)
        self.assertEqual("fake-interpreter", response.interpreter_id)
        self.assertEqual(
            {"identifier", "prediction", "explanation", "top_features", "provenance"},
            set(client.received_payload or {}),
        )
        self._assert_json_primitives(client.received_payload)
        instruction = (client.received_instruction or "").lower()
        for phrase in ("русском", "не пересчитывайте", "не доказывает причинность", "одобрить/отказать", "не придумывайте смысл"):
            self.assertIn(phrase, instruction)

    def test_request_hash_is_stable(self) -> None:
        descriptions = {"feature-1": "Описание"}
        first = self.service.build_request(evidence=self.evidence, descriptions_by_feature_id=descriptions)
        second = self.service.build_request(evidence=self.evidence, descriptions_by_feature_id=descriptions)
        self.assertEqual(first.request_hash, second.request_hash)

    def test_tampered_request_hash_fails_before_any_client_access(self) -> None:
        request = self.service.build_request(evidence=self.evidence)
        tampered_feature = replace(request.features[0], shap_value=request.features[0].shap_value + 0.01)
        cases = (
            replace(request, probability=request.probability + 0.01),
            replace(request, features=(tampered_feature, *request.features[1:])),
            replace(request, features=(replace(request.features[0], description_ru="Подменённое описание"), *request.features[1:])),
        )
        for tampered in cases:
            with self.subTest(tampered=tampered):
                client = FakeInterpreter()
                with self.assertRaisesRegex(ValueError, "hash integrity"):
                    self.service.interpret_request(request=tampered, client=client)
                self.assertFalse(client.interpreter_id_read)
                self.assertFalse(client.interpreter_model_read)
                self.assertFalse(client.interpret_called)

    def test_response_hash_is_stable_without_created_at(self) -> None:
        request = self.service.build_request(evidence=self.evidence)
        first = self.service.interpret_request(request=request, client=FakeInterpreter("Один текст."))
        second = self.service.interpret_request(request=request, client=FakeInterpreter("Один текст."))
        self.assertEqual(first.response_hash, second.response_hash)

    def test_client_exception_is_isolated(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "client failed"):
            self.service.interpret(evidence=self.evidence, client=FakeInterpreter(RuntimeError("network")))

    def test_invalid_client_output_fails_closed(self) -> None:
        for output in (None, "", "  ", ["text"], {"text": "text"}):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, "invalid text"):
                    self.service.interpret(evidence=self.evidence, client=FakeInterpreter(output))

    def test_invalid_rank_structure_fails_closed(self) -> None:
        duplicate = replace(
            self.evidence,
            features=(replace(self.evidence.features[0], abs_rank=2), *self.evidence.features[1:]),
        )
        malformed = replace(
            self.evidence,
            features=(replace(self.evidence.features[0], abs_rank=0), *self.evidence.features[1:]),
        )
        for evidence in (duplicate, malformed):
            with self.subTest(evidence=evidence.features[0].abs_rank):
                with self.assertRaisesRegex(ValueError, "abs_rank"):
                    self.service.build_request(evidence=evidence)

    @classmethod
    def _assert_json_primitives(cls, value: object) -> None:
        if value is None or isinstance(value, (str, int, float, bool)):
            return
        if isinstance(value, list):
            for item in value:
                cls._assert_json_primitives(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise AssertionError("Payload keys must be strings.")
                cls._assert_json_primitives(item)
            return
        raise AssertionError(f"Payload contains a non-JSON value: {type(value)!r}")


if __name__ == "__main__":
    unittest.main()
