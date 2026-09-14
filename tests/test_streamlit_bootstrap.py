"""Targeted tests for Streamlit composition without a real ML run."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import app.bootstrap as bootstrap
from app.bootstrap import HistoricalDatasetProvider, PreparedDatasetContext, list_available_contexts, resolve_context
from komus_risk.contracts import DatasetContract, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.registries import FeatureRegistry


class FakeProvider:
    context_id = "synthetic"
    display_name = "Синтетический контекст"
    upload_capable = False

    def __init__(self) -> None:
        spec = FeatureSpec(
            "dynamic_feature", "value", "Динамический признак", "Synthetic", "group", "float", "numeric", "test",
            FeatureUsageStatus.MODEL_ALLOWED, None, None, None, 0,
        )
        registry = FeatureRegistry("synthetic-v1", (spec,), (FeatureGroup("group", "Группа", "Synthetic", 0, "test", ("dynamic_feature",)),))
        contract = DatasetContract(
            "synthetic", "1", "Synthetic", "ready_csv", "sha256:synthetic", 4, 3, "target", 1, "entity",
            registry.registry_id, registry.registry_hash, "validated", False,
        )
        dataset = LoadedDataset(pd.DataFrame({"entity": [1, 2, 3, 4], "target": [0, 1, 0, 1], "value": [0.1, 0.9, 0.2, 0.8]}), contract, Path("synthetic.csv"), "csv", "source")
        self.context = PreparedDatasetContext("synthetic", self.display_name, dataset, registry, EvaluationPopulation((0, 1, 2, 3), "working", "sha256:working", "working"))
        self.received_upload = None

    def resolve(self, optional_uploaded_file=None) -> PreparedDatasetContext:
        self.received_upload = optional_uploaded_file
        return self.context


class StreamlitBootstrapTests(unittest.TestCase):
    def test_accepted_stage1_evidence_provides_exact_working_population(self) -> None:
        split = bootstrap._load_accepted_working_split()
        full_target = np.zeros(bootstrap._ACCEPTED_FULL_ROW_COUNT, dtype=np.int8)
        full_target[np.asarray(split.row_positions, dtype=np.int64)] = split.target
        contract = DatasetContract(
            "accepted", "1", "Data_final", "ready_xlsb", "fingerprint", bootstrap._ACCEPTED_FULL_ROW_COUNT, 52,
            "DefMark", 1, "INN", "registry", "hash", "validated", True,
        )
        loaded = LoadedDataset(
            pd.DataFrame({"DefMark": full_target}), contract, Path("Data_final.xlsb"), "xlsb", bootstrap._ACCEPTED_DATASET_SHA256,
        )

        with patch("app.bootstrap.ReadyDatasetAdapter.load", return_value=loaded):
            context = HistoricalDatasetProvider().resolve()

        positions = np.asarray(context.population.row_positions, dtype=np.int64)
        in_working = np.zeros(bootstrap._ACCEPTED_FULL_ROW_COUNT, dtype=bool)
        in_working[positions] = True
        self.assertEqual(context.loaded_dataset.contract.row_count, 362_018)
        self.assertEqual(len(positions), 289_614)
        self.assertEqual(context.population.population_fingerprint, "80430ce6290d0982d3641621ba1ed62f6fb495e8d32f7d23d9fca00091aadb45")
        self.assertEqual(bootstrap._sha256_int64(positions), context.population.population_fingerprint)
        self.assertEqual(int((~in_working).sum()), 72_404)
        self.assertFalse(in_working.all())

    def test_supported_protocol_is_defined_once_in_composition(self) -> None:
        protocol = bootstrap.SUPPORTED_PROTOCOL

        self.assertIsNone(bootstrap.validate_supported_protocol({
            "protocol_id": protocol.protocol_id,
            "protocol_version": protocol.protocol_version,
            "evaluation_level": protocol.evaluation_level,
            "folds": protocol.minimum_folds,
        }))
        self.assertIn("фолдов", bootstrap.validate_supported_protocol({
            "protocol_id": protocol.protocol_id,
            "protocol_version": protocol.protocol_version,
            "evaluation_level": protocol.evaluation_level,
            "folds": 1,
        }))
        self.assertIn("только", bootstrap.validate_supported_protocol({
            "protocol_id": "unsupported",
            "protocol_version": protocol.protocol_version,
            "evaluation_level": protocol.evaluation_level,
            "folds": protocol.minimum_folds,
        }))

    def test_provider_list_and_resolution_return_a_complete_context(self) -> None:
        provider = FakeProvider()
        providers = {provider.context_id: provider}

        options = list_available_contexts(providers)
        context = resolve_context("synthetic", providers=providers)

        self.assertEqual(options[0].display_name, "Синтетический контекст")
        self.assertFalse(options[0].upload_capable)
        self.assertIs(context, provider.context)
        self.assertEqual(context.loaded_dataset.contract.feature_registry_hash, context.feature_registry.registry_hash)
        self.assertEqual(context.population.partition_role, "working")

    def test_generic_upload_and_unknown_context_are_rejected(self) -> None:
        provider = FakeProvider()
        providers = {provider.context_id: provider}

        with self.assertRaises(ValueError):
            resolve_context("missing", providers=providers)
        with self.assertRaises(ValueError):
            resolve_context("synthetic", object(), providers=providers)
        self.assertIsNone(provider.received_upload)

    def test_streamlit_module_is_importable_and_has_no_backend_shortcuts(self) -> None:
        import app.streamlit_app as prototype

        source = Path(prototype.__file__).read_text(encoding="utf-8")
        self.assertTrue(callable(prototype.main))
        for forbidden in ("ExperimentRunner", "ExperimentArtifactStore", "FeatureRegistry._", "CatBoost", "XGBoost"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
