from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from komus_risk.data import DatasetInspector, TabularReader
from komus_risk.preparation import (
    ConfirmedColumnDecision, ConfirmedDatasetPreparation, KomusDatasetPreparationService,
    PopulationPolicyV1,
)
from komus_risk.preparation.contracts import ConfirmedColumnStatus, DatasetPreparationError
from komus_risk.preparation.identity import identity_hash
from komus_risk.preparation.materializer import inspection_report_hash, proposal_hash
from komus_risk.preparation.service import DatasetPreparationAnalyzer


class DatasetPreparationMaterializationTests(unittest.TestCase):
    def _parts(
        self,
        predictor_name: str = "score",
        positive_class: object = 1,
        rows: str = "a,0,0.1,1\nb,1,0.9,2\nc,0,0.2,3\nd,1,0.8,4",
    ):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "dataset.csv"
        path.write_text(f"entity_id,target,{predictor_name},diagnostic\n{rows}\n", encoding="utf-8")
        snapshot = TabularReader().read(path)
        report = DatasetInspector().inspect(snapshot)
        proposal = DatasetPreparationAnalyzer().analyze(report)
        report_hash = inspection_report_hash(report)
        confirmation = ConfirmedDatasetPreparation(
            "1", snapshot.fingerprint, report_hash, proposal_hash(proposal, report_hash), proposal.policy_id,
            proposal.policy_version, proposal.policy_hash, "Test dataset", "target", positive_class, "entity_id",
            (
                ConfirmedColumnDecision("entity_id", ConfirmedColumnStatus.IDENTIFIER),
                ConfirmedColumnDecision("target", ConfirmedColumnStatus.TARGET),
                ConfirmedColumnDecision(predictor_name, ConfirmedColumnStatus.MODEL_ALLOWED),
                ConfirmedColumnDecision("diagnostic", ConfirmedColumnStatus.DIAGNOSTIC_ONLY),
            ),
            PopulationPolicyV1.FULL_OOF_NO_PROTECTED_FINAL_TEST,
        )
        return snapshot, report, proposal, confirmation

    def test_materializes_full_population_and_manifest(self) -> None:
        context, manifest = KomusDatasetPreparationService().prepare(*self._parts())
        self.assertEqual((0, 1, 2, 3), context.population.row_positions)
        self.assertFalse(context.loaded_dataset.contract.final_test_locked)
        self.assertEqual("target", context.loaded_dataset.contract.target_column)
        self.assertEqual(manifest.context_id, context.context_id)
        self.assertEqual("MODEL_ALLOWED", manifest.confirmed_preparation.column_decisions[2].status)

    def test_identity_decimal_normalizes_trailing_zeroes(self) -> None:
        self.assertEqual(identity_hash(Decimal("1.0")), identity_hash(Decimal("1.00")))
        self.assertEqual(identity_hash(Decimal("100")), identity_hash(Decimal("1E+2")))

    def test_numpy_positive_class_becomes_python_int_in_runtime_and_manifest(self) -> None:
        context, manifest = KomusDatasetPreparationService().prepare(*self._parts(positive_class=np.int64(1)))
        self.assertIs(type(context.loaded_dataset.contract.positive_class), int)
        self.assertEqual(1, context.loaded_dataset.contract.positive_class)
        self.assertIs(type(manifest.confirmed_preparation.positive_class), int)
        json.dumps(manifest.to_dict())

    def test_second_target_decision_is_rejected(self) -> None:
        snapshot, report, proposal, confirmation = self._parts()
        invalid = replace(confirmation, column_decisions=confirmation.column_decisions[:-1] + (
            ConfirmedColumnDecision("diagnostic", ConfirmedColumnStatus.TARGET),
        ))
        with self.assertRaises(DatasetPreparationError) as error:
            KomusDatasetPreparationService().prepare(snapshot, report, proposal, invalid)
        self.assertEqual("INCOMPLETE_CONFIRMATION", error.exception.code)

    def test_second_identifier_decision_is_rejected(self) -> None:
        snapshot, report, proposal, confirmation = self._parts()
        invalid = replace(confirmation, column_decisions=confirmation.column_decisions[:-1] + (
            ConfirmedColumnDecision("diagnostic", ConfirmedColumnStatus.IDENTIFIER),
        ))
        with self.assertRaises(DatasetPreparationError) as error:
            KomusDatasetPreparationService().prepare(snapshot, report, proposal, invalid)
        self.assertEqual("INCOMPLETE_CONFIRMATION", error.exception.code)

    def test_mutated_snapshot_cannot_hide_non_finite_source_predictor(self) -> None:
        rows = "\n".join(
            f"entity-{index},{index % 2},{float(index + 1)},1" for index in range(51)
        ) + "\nentity-51,1,inf,1"
        snapshot, report, proposal, confirmation = self._parts(rows=rows)
        snapshot.dataframe.loc[51, "score"] = 0.5
        with self.assertRaises(DatasetPreparationError) as error:
            KomusDatasetPreparationService().prepare(snapshot, report, proposal, confirmation)
        self.assertEqual("NON_FINITE_PREDICTOR", error.exception.code)

    def test_mutated_snapshot_cannot_hide_three_class_source_target(self) -> None:
        rows = "a,0,0.1,1\nb,1,0.9,2\nc,2,0.2,3\nd,0,0.8,4\ne,1,0.3,5\nf,2,0.7,6"
        snapshot, report, proposal, confirmation = self._parts(rows=rows)
        snapshot.dataframe.loc[snapshot.dataframe["target"] == 2, "target"] = 1
        with self.assertRaises(DatasetPreparationError) as error:
            KomusDatasetPreparationService().prepare(snapshot, report, proposal, confirmation)
        self.assertEqual("INVALID_TARGET", error.exception.code)

    def test_manifest_delta_is_immutable_and_to_dict_is_detached(self) -> None:
        _context, manifest = KomusDatasetPreparationService().prepare(*self._parts())
        delta = manifest.proposal_confirmation_delta
        with self.assertRaises(FrozenInstanceError):
            delta.confirmed_target.column_name = "changed"
        with self.assertRaises(FrozenInstanceError):
            delta.column_decisions[0].confirmed_usage_status = "changed"
        serialized = manifest.to_dict()
        serialized["proposal_confirmation_delta"]["confirmed_target"]["column_name"] = "changed"
        self.assertEqual("target", delta.confirmed_target.column_name)
        self.assertEqual(
            identity_hash({
                "context_id": manifest.context_id,
                "confirmation_hash": manifest.confirmation_hash,
                "delta": delta.to_dict(),
            }),
            manifest.materialization_identity,
        )

    def test_numeric_q_b1_norm_can_be_explicitly_model_allowed(self) -> None:
        context, _manifest = KomusDatasetPreparationService().prepare(*self._parts("Q_B1_norm"))
        self.assertEqual(
            ConfirmedColumnStatus.MODEL_ALLOWED.value.lower(),
            context.feature_registry.get("Q_B1_norm").usage_status,
        )


if __name__ == "__main__":
    unittest.main()
