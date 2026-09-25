from __future__ import annotations

from dataclasses import replace
import unittest

from komus_risk.application import (
    LocalExplanationEvidence,
    LocalFeatureContribution,
    PolicyBoundResultInterpreterClient,
    RedactedV1OutboundPolicy,
    ResultInterpreterService,
)
from komus_risk.hashing import stable_hash


class _UnderlyingClient:
    def __init__(self, output: object = "Ответ.") -> None:
        self.output = output
        self.calls: list[dict] = []
        self.identity_reads = 0

    @property
    def interpreter_id(self) -> str:
        self.identity_reads += 1
        return "underlying"

    @property
    def interpreter_model(self) -> str:
        self.identity_reads += 1
        return "underlying-v1"

    def interpret(self, *, system_instruction: str, payload: dict) -> str:
        self.calls.append({"system_instruction": system_instruction, "payload": payload})
        if isinstance(self.output, Exception):
            raise self.output
        return self.output  # type: ignore[return-value]


class _CountingPolicy(RedactedV1OutboundPolicy):
    def __init__(self) -> None:
        self.calls = 0

    def project(self, request):
        self.calls += 1
        return super().project(request)


class InterpreterPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ResultInterpreterService()
        evidence = LocalExplanationEvidence(
            evidence_version="local-evidence-v1", evidence_hash="evidence-hash",
            model_version_id="model-version", experiment_artifact_id="experiment",
            dataset_id="dataset", dataset_fingerprint="fingerprint", feature_set_hash="features",
            model_id="model", model_version="v1", row_id="row-secret",
            identifier_column="client_id", identifier_value="client-secret", probability=0.731,
            shap_output_space="raw_margin", raw_model_output=1.0, base_value=0.2,
            features=tuple(
                LocalFeatureContribution(
                    feature_id=f"feature-{rank}", column_name=f"technical_{rank}",
                    raw_value=rank / 10, shap_value=(rank - 4) / 10, abs_rank=rank,
                )
                for rank in range(1, 7)
            ),
            explainer_id="explainer", explainer_version="v1", created_at="2026-09-24T00:00:00+00:00",
        )
        self.request = self.service.build_request(
            evidence=evidence, descriptions_by_feature_id={"feature-1": "Проверенное описание"},
        )
        self.policy = RedactedV1OutboundPolicy()

    def test_redacted_v1_payload_is_exact_allowlist(self) -> None:
        dispatch = self.policy.project(self.request)
        payload = dispatch.payload

        self.assertEqual({"prediction", "explanation", "top_features"}, set(payload))
        self.assertEqual({"probability"}, set(payload["prediction"]))
        self.assertEqual({"shap_output_space"}, set(payload["explanation"]))
        self.assertEqual(
            {"feature_id", "column_name", "shap_value", "abs_rank", "description_ru"},
            set(payload["top_features"][0]),
        )
        self.assertEqual("Проверенное описание", payload["top_features"][0]["description_ru"])
        self.assertIsNone(payload["top_features"][1]["description_ru"])
        forbidden = {
            "identifier", "identifier_column", "identifier_value", "row_id", "raw_value",
            "evidence_hash", "model_version_id", "provenance", "raw_model_output", "base_value",
            "experiment_artifact_id", "dataset_id",
        }
        self.assertTrue(forbidden.isdisjoint(self._all_keys(payload)))

    def test_dispatch_hash_and_receipt_are_deterministic_and_bound_to_full_request(self) -> None:
        first = self.policy.project(self.request)
        second = self.policy.project(self.request)

        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.receipt.provider_payload_hash, stable_hash(first.payload))
        self.assertEqual(first.receipt.provider_payload_hash, second.receipt.provider_payload_hash)
        self.assertEqual(first.receipt.source_request_hash, self.request.request_hash)
        self.assertEqual((first.receipt.policy_id, first.receipt.policy_version), ("REDACTED_V1", 1))

    def test_policy_bound_client_forwards_only_sanitized_dispatch(self) -> None:
        dispatch = self.policy.project(self.request)
        underlying = _UnderlyingClient()
        response = self.service.interpret_request(
            request=self.request,
            client=PolicyBoundResultInterpreterClient(underlying_client=underlying, dispatch=dispatch),
        )

        self.assertEqual(response.interpreter_id, "underlying")
        self.assertEqual(underlying.calls[0]["payload"], dispatch.payload)
        self.assertNotIn("identifier", underlying.calls[0]["payload"])
        self.assertNotIn("raw_value", self._all_keys(underlying.calls[0]["payload"]))

    def test_tampering_fails_before_policy_or_client_access(self) -> None:
        for request in (
            replace(self.request, probability=self.request.probability + 0.01),
            replace(self.request, features=(replace(self.request.features[0], shap_value=1.1), *self.request.features[1:])),
        ):
            with self.subTest(request=request):
                policy = _CountingPolicy()
                client = _UnderlyingClient()
                with self.assertRaisesRegex(ValueError, "hash integrity"):
                    self.service.validate_request(request)
                self.assertEqual(policy.calls, 0)
                self.assertEqual(client.identity_reads, 0)
                self.assertEqual(client.calls, [])

    def test_provider_failure_leaves_full_request_unchanged(self) -> None:
        dispatch = self.policy.project(self.request)
        client = _UnderlyingClient(RuntimeError("network"))
        with self.assertRaisesRegex(RuntimeError, "client failed"):
            self.service.interpret_request(
                request=self.request,
                client=PolicyBoundResultInterpreterClient(underlying_client=client, dispatch=dispatch),
            )
        self.assertEqual(self.request, self.service.build_request(
            evidence=LocalExplanationEvidence(
                evidence_version="local-evidence-v1", evidence_hash="evidence-hash",
                model_version_id="model-version", experiment_artifact_id="experiment",
                dataset_id="dataset", dataset_fingerprint="fingerprint", feature_set_hash="features",
                model_id="model", model_version="v1", row_id="row-secret",
                identifier_column="client_id", identifier_value="client-secret", probability=0.731,
                shap_output_space="raw_margin", raw_model_output=1.0, base_value=0.2,
                features=tuple(LocalFeatureContribution(f"feature-{rank}", f"technical_{rank}", rank / 10, (rank - 4) / 10, rank) for rank in range(1, 7)),
                explainer_id="explainer", explainer_version="v1", created_at="2026-09-24T00:00:00+00:00",
            ), descriptions_by_feature_id={"feature-1": "Проверенное описание"},
        ))

    @classmethod
    def _all_keys(cls, value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(cls._all_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(cls._all_keys(item) for item in value))
        return set()


if __name__ == "__main__":
    unittest.main()
