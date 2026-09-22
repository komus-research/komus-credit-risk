"""New dataset OOF activation is separate from the accepted historical split."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.contracts import ExperimentConfig
from komus_risk.data import DatasetInspector, TabularReader
from komus_risk.experiments import ExperimentRunner
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.preparation import (
    ConfirmedDatasetRoles,
    DatasetPreparationAnalyzer,
    materialize_confirmed_dataset,
    prepare_oof_evaluation,
    suspected_temporal_columns,
)
from komus_risk.registries import ModelRegistry, ModelSpec


class _ConstantAdapter(BinaryClassifierAdapter):
    def fit(self, X_train, y_train) -> None:
        self.probability = float(y_train.mean())

    def predict_positive_proba(self, X_valid) -> np.ndarray:
        return np.full(len(X_valid), self.probability)


class _ConstantFactory(ModelAdapterFactory):
    model_id = "constant_test"
    model_version = "1"
    adapter_version = "1"

    def create(self, parameters, seed) -> BinaryClassifierAdapter:
        return _ConstantAdapter()


class NewDatasetOOFTests(unittest.TestCase):
    @staticmethod
    def _materialized(directory: str, *, with_period: bool = False):
        path = Path(directory) / "companies.csv"
        header = "INN,DefMark,A1,year\n" if with_period else "INN,DefMark,A1\n"
        rows = [
            f"{1000000000 + index},{index % 2},{index + 0.25}"
            + (f",{2020 + index % 3}" if with_period else "")
            for index in range(60)
        ]
        path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
        snapshot = TabularReader().read(path)
        inspection = DatasetInspector().inspect(snapshot)
        proposal = DatasetPreparationAnalyzer().analyze(inspection)
        roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1",))
        return materialize_confirmed_dataset(snapshot, inspection, proposal, roles)

    def test_new_file_runs_existing_oof_on_its_own_rows_and_persists_report(self) -> None:
        with TemporaryDirectory() as directory:
            materialized = self._materialized(directory)
            ready = prepare_oof_evaluation(materialized, confirm_no_time_axis=True)
            contract = ready.loaded_dataset.contract
            self.assertEqual(contract.validation_status, "validated")
            self.assertFalse(contract.final_test_locked)
            self.assertEqual(ready.population.partition_role, "full")
            self.assertEqual(ready.population.row_positions, tuple(range(60)))
            self.assertEqual(contract.dataset_fingerprint, materialized.loaded_dataset.contract.dataset_fingerprint)

            registry = ModelRegistry()
            registry.register(ModelSpec("constant_test", "Тестовая модель", "1", ("binary",), "Только тест.", {}, {}, "1"))
            config = ExperimentConfig(
                experiment_id="new-dataset-run", dataset_id=contract.dataset_id,
                dataset_fingerprint=contract.dataset_fingerprint, target="DefMark",
                feature_ids=("A1",), feature_set_hash=None, feature_groups=("confirmed_predictors",),
                model_id="constant_test", model_version="1", model_parameters={},
                protocol_id="stratified_kfold_oof", protocol_version="1", seed=42, folds=3,
                evaluation_level="oof", reference_result_id=None, changed_dimension=None, changed_elements=(),
            )
            output = ExperimentRunner(
                feature_registry=ready.feature_registry, model_registry=registry,
                adapter_factory=_ConstantFactory(), code_version="test",
            ).run(ready.loaded_dataset, config, ready.population)
            saved = ExperimentArtifactStore(Path(directory) / "artifacts").save(
                config=config, dataset_contract=contract, population=ready.population, run_output=output,
            )

            self.assertEqual(len(output.oof_positive_proba), 60)
            self.assertEqual(saved.run_output.result.model_id, "constant_test")
            self.assertIn("gini", saved.run_output.result.metrics)

    def test_no_time_confirmation_and_time_column_are_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            materialized = self._materialized(directory)
            with self.assertRaisesRegex(ValueError, "Подтвердите"):
                prepare_oof_evaluation(materialized, confirm_no_time_axis=False)
            materialized = self._materialized(directory, with_period=True)
            self.assertEqual(suspected_temporal_columns(materialized), ("year",))
            with self.assertRaisesRegex(ValueError, "временные столбцы"):
                prepare_oof_evaluation(materialized, confirm_no_time_axis=True)

    def test_changed_source_is_not_activated(self) -> None:
        with TemporaryDirectory() as directory:
            materialized = self._materialized(directory)
            materialized.loaded_dataset.source_path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "изменился"):
                prepare_oof_evaluation(materialized, confirm_no_time_axis=True)

    def test_small_dataset_is_not_activated_for_three_fold_oof(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "small.csv"
            path.write_text("INN,DefMark,A1\n1,0,1\n2,1,2\n3,0,3\n4,1,4\n", encoding="utf-8")
            snapshot = TabularReader().read(path)
            inspection = DatasetInspector().inspect(snapshot)
            proposal = DatasetPreparationAnalyzer().analyze(inspection)
            roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1",))
            materialized = materialize_confirmed_dataset(snapshot, inspection, proposal, roles)
            with self.assertRaisesRegex(ValueError, "не менее 60 строк"):
                prepare_oof_evaluation(materialized, confirm_no_time_axis=True)

    def test_configuration_id_changes_with_feature_model_and_seed(self) -> None:
        import app.streamlit_app as prototype

        request = SimpleNamespace(
            selected_feature_ids=("A1",), model_id="xgboost", protocol_id="stratified_kfold_oof",
            protocol_version="1", evaluation_level="oof", seed=42, folds=3,
        )
        plan = SimpleNamespace(
            request=request,
            dataset=SimpleNamespace(dataset_fingerprint="dataset-one"),
            population=SimpleNamespace(population_fingerprint="population-one"),
            model=SimpleNamespace(model_version="1", default_profile={"trees": 10}),
        )
        first = prototype._evaluation_configuration_id(plan)
        self.assertEqual(first, prototype._evaluation_configuration_id(plan))
        request.selected_feature_ids = ("A1", "B1")
        self.assertNotEqual(first, prototype._evaluation_configuration_id(plan))
        request.selected_feature_ids = ("A1",)
        request.seed = 43
        self.assertNotEqual(first, prototype._evaluation_configuration_id(plan))
        request.seed = 42
        request.model_id = "lightgbm"
        self.assertNotEqual(first, prototype._evaluation_configuration_id(plan))

    def test_streamlit_activation_exposes_new_context_to_feature_step(self) -> None:
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            materialized = self._materialized(directory)
            path = materialized.loaded_dataset.source_path
            info = path.stat()
            source = SimpleNamespace(source_kind="explicit_local", local_runtime_path=path, file_name=path.name)
            stub = SimpleNamespace(
                session_state={}, subheader=Mock(), info=Mock(), warning=Mock(),
                checkbox=Mock(return_value=True), button=Mock(return_value=True),
                rerun=Mock(), error=Mock(side_effect=AssertionError("unexpected error")),
            )
            with patch.object(prototype, "st", stub):
                prototype._render_new_dataset_oof_protocol(
                    source, (str(path), info.st_size, info.st_mtime_ns), materialized,
                )

            context = stub.session_state["dataset_context"]
            self.assertEqual(context.loaded_dataset.contract.validation_status, "validated")
            self.assertEqual(stub.session_state["dataset_source_preparation"].preparation_status, "user_oof_context_prepared")
            stub.rerun.assert_called_once()
