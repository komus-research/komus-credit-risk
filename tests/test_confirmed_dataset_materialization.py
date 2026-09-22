"""Confirmed new-dataset contracts must be separate from historical Stage 3 identity."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from komus_risk.data import DatasetInspector, TabularReader
from komus_risk.preparation import (
    ConfirmedDatasetRoles,
    DatasetPreparationAnalyzer,
    ProposalWarning,
    WarningSeverity,
    materialize_confirmed_dataset,
)


class ConfirmedDatasetMaterializationTests(unittest.TestCase):
    def _analyze(self, directory: str, rows: str):
        path = Path(directory) / "companies.csv"
        path.write_text(rows, encoding="utf-8")
        snapshot = TabularReader().read(path)
        inspection = DatasetInspector().inspect(snapshot)
        proposal = DatasetPreparationAnalyzer().analyze(inspection)
        return snapshot, inspection, proposal

    def test_confirmation_creates_distinct_contracts_for_different_feature_sets(self) -> None:
        with TemporaryDirectory() as directory:
            snapshot, inspection, proposal = self._analyze(
                directory,
                "INN,DefMark,A1,B1\n111,0,1,5\n222,1,2,6\n333,0,3,7\n444,1,4,8\n",
            )
            first_roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1", "B1"))
            second_roles = replace(first_roles, allowed_feature_columns=("A1",))

            first = materialize_confirmed_dataset(snapshot, inspection, proposal, first_roles)
            second = materialize_confirmed_dataset(snapshot, inspection, proposal, second_roles)

        self.assertEqual(first.population.partition_role, "full")
        self.assertEqual(first.population.row_positions, (0, 1, 2, 3))
        self.assertFalse(first.loaded_dataset.contract.final_test_locked)
        self.assertEqual(first.loaded_dataset.contract.validation_status, "confirmed_pending_protocol")
        self.assertNotEqual(first.loaded_dataset.contract.dataset_fingerprint, second.loaded_dataset.contract.dataset_fingerprint)
        self.assertNotEqual(first.feature_registry.registry_hash, second.feature_registry.registry_hash)
        self.assertEqual(first.feature_registry.get("DefMark").usage_status.value, "target")
        self.assertEqual(second.feature_registry.get("B1").usage_status.value, "blocked")

    def test_confirmation_rejects_wrong_identity_and_protected_columns(self) -> None:
        with TemporaryDirectory() as directory:
            snapshot, inspection, proposal = self._analyze(
                directory, "INN,DefMark,A1\n111,0,1\n222,1,2\n333,0,3\n444,1,4\n",
            )
            roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1",))
            with self.assertRaisesRegex(ValueError, "разным версиям"):
                materialize_confirmed_dataset(snapshot, inspection, proposal, replace(roles, snapshot_fingerprint="wrong"))
            with self.assertRaisesRegex(ValueError, "Цель, идентификатор"):
                materialize_confirmed_dataset(snapshot, inspection, proposal, replace(roles, allowed_feature_columns=("INN",)))

    def test_confirmation_rejects_duplicate_identifier_and_missing_feature(self) -> None:
        with TemporaryDirectory() as directory:
            snapshot, inspection, proposal = self._analyze(
                directory, "INN,DefMark,A1\n111,0,1\n111,1,2\n333,0,3\n444,1,4\n",
            )
            roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1",))
            with self.assertRaisesRegex(ValueError, "Идентификатор повторяется"):
                materialize_confirmed_dataset(snapshot, inspection, proposal, roles)

            snapshot, inspection, proposal = self._analyze(
                directory, "INN,DefMark,A1\n111,0,1\n222,1,\n333,0,3\n444,1,4\n",
            )
            roles = replace(roles, snapshot_fingerprint=snapshot.fingerprint)
            with self.assertRaisesRegex(ValueError, "пропуски"):
                materialize_confirmed_dataset(snapshot, inspection, proposal, roles)

    def test_confirmation_blocks_target_proxy_warning(self) -> None:
        with TemporaryDirectory() as directory:
            snapshot, inspection, proposal = self._analyze(
                directory, "INN,DefMark,A1\n111,0,1\n222,1,2\n333,0,3\n444,1,4\n",
            )
            warning = ProposalWarning(
                "potential_target_proxy", WarningSeverity.WARNING, "A1", 2, ("Похож на утечку цели.",), {}, True,
            )
            proposal = replace(proposal, warnings=(*proposal.warnings, warning))
            roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1",))
            with self.assertRaisesRegex(ValueError, "утечке цели"):
                materialize_confirmed_dataset(snapshot, inspection, proposal, roles)

    def test_streamlit_confirmation_keeps_new_context_out_of_historical_runner(self) -> None:
        import app.streamlit_app as prototype

        class StreamlitStub:
            def __init__(self) -> None:
                self.session_state = {}

            def subheader(self, *_args): pass
            def caption(self, *_args): pass
            def write(self, *_args): pass
            def dataframe(self, *_args, **_kwargs): pass
            def success(self, *_args): pass
            def info(self, *_args): pass
            def warning(self, *_args): pass
            def error(self, message): raise AssertionError(message)
            def expander(self, *_args, **_kwargs): return self
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def status(self, *_args, **_kwargs): return SimpleNamespace(write=lambda *_a: None, update=lambda **_k: None)
            def button(self, label, **_kwargs): return label in {"Изучить данные и предложить роли", "Подтвердить подготовку"}
            def selectbox(self, label, options, **_kwargs):
                if label == "Целевая колонка": return "DefMark"
                if label.startswith("Колонка идентификатора"): return "INN"
                return 1
            def multiselect(self, _label, options, **_kwargs): return ("A1",)
            def checkbox(self, *_args, **_kwargs): return True

        with TemporaryDirectory() as directory:
            path = Path(directory) / "companies.csv"
            path.write_text("INN,DefMark,A1\n111,0,1\n222,1,2\n333,0,3\n444,1,4\n", encoding="utf-8")
            stub = StreamlitStub()
            with patch.object(prototype, "st", stub):
                prototype._render_new_dataset_confirmation(SimpleNamespace(local_runtime_path=path))

        self.assertIn(prototype._NEW_DATASET_CONFIRMATION_KEY, stub.session_state)
        self.assertNotIn("dataset_context", stub.session_state)
