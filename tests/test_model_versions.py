"""Stage 4: final fit, native model versions and fail-closed disk restoration."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier

from komus_risk.application import FinalModelTrainingService
from komus_risk.application.model_inference import predict_uploaded_file
from komus_risk.artifacts import ExperimentArtifactStore, ModelVersionStore
from komus_risk.contracts import ExperimentConfig
from komus_risk.data import DatasetInspector, TabularReader
from komus_risk.experiments import EvaluationPopulation, ExperimentRunner
from komus_risk.hashing import stable_hash
from komus_risk.models import XGBOOST_MODEL_SPEC, XGBoostFactory
from komus_risk.models.gbdt.catboost import CATBOOST_PROFILE, CatBoostAdapter
from komus_risk.models.gbdt.lightgbm import LIGHTGBM_PROFILE, LightGBMAdapter
from komus_risk.models.gbdt.mean import GBDTMeanAdapter
from komus_risk.models.gbdt.native import load_native_predictor, save_fitted_native
from komus_risk.models.gbdt.xgboost import XGBOOST_PROFILE, XGBoostAdapter
from komus_risk.preparation import (
    ConfirmedDatasetRoles, DatasetPreparationAnalyzer, materialize_confirmed_dataset, prepare_oof_evaluation,
)
from komus_risk.registries import ModelRegistry


class ModelVersionTests(unittest.TestCase):
    @staticmethod
    def _ready(directory: str):
        path = Path(directory) / "companies.csv"
        rows = [f"{1000000000 + i},{i % 2},{(i % 10) + 0.1},{(i % 7) + 0.2}" for i in range(60)]
        path.write_text("INN,DefMark,A1,A2\n" + "\n".join(rows) + "\n", encoding="utf-8")
        snapshot = TabularReader().read(path)
        inspection = DatasetInspector().inspect(snapshot)
        proposal = DatasetPreparationAnalyzer().analyze(inspection)
        roles = ConfirmedDatasetRoles(snapshot.fingerprint, "DefMark", 1, "INN", ("A1", "A2"))
        return prepare_oof_evaluation(
            materialize_confirmed_dataset(snapshot, inspection, proposal, roles), confirm_no_time_axis=True,
        )

    @staticmethod
    def _evaluate(ready, root: Path, feature_ids: tuple[str, ...]):
        registry = ModelRegistry()
        registry.register(XGBOOST_MODEL_SPEC)
        factory = XGBoostFactory()
        config = ExperimentConfig(
            experiment_id="test-" + "-".join(feature_ids),
            dataset_id=ready.loaded_dataset.contract.dataset_id,
            dataset_fingerprint=ready.loaded_dataset.contract.dataset_fingerprint,
            target="DefMark", feature_ids=feature_ids, feature_set_hash=None,
            feature_groups=("confirmed_predictors",), model_id="xgboost",
            model_version=XGBOOST_MODEL_SPEC.version,
            model_parameters=XGBOOST_MODEL_SPEC.default_profile,
            protocol_id="stratified_kfold_oof", protocol_version="1", seed=42, folds=3,
            evaluation_level="oof", reference_result_id=None, changed_dimension=None, changed_elements=(),
        )
        output = ExperimentRunner(
            feature_registry=ready.feature_registry, model_registry=registry,
            adapter_factory=factory, code_version="test-v1",
        ).run(ready.loaded_dataset, config, ready.population)
        artifact_store = ExperimentArtifactStore(root)
        artifact = artifact_store.save(
            config=config, dataset_contract=ready.loaded_dataset.contract,
            population=ready.population, run_output=output,
        )
        model_store = ModelVersionStore(root, code_version="test-v1")
        service = FinalModelTrainingService(
            experiment_store=artifact_store, model_store=model_store,
            model_registry=registry, model_factories={"xgboost": factory}, code_version="test-v1",
        )
        return service, model_store, artifact

    def test_final_model_is_separate_from_oof_and_survives_restart(self) -> None:
        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            root = Path(directory) / "artifacts"
            service, store, artifact = self._evaluate(ready, root, ("A1",))
            self.assertEqual(store.catalog(), ((), ()))
            stages = []
            saved = service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
                progress_listener=stages.append,
            )
            self.assertEqual(stages, ["verifying_source", "fitting_final_model", "saving_model", "completed"])
            self.assertEqual(saved.feature_count, 1)
            self.assertEqual(saved.experiment_artifact_id, artifact.artifact_id)
            self.assertEqual(len(store.catalog()[0]), 1)

            restored = ModelVersionStore(root, code_version="test-v1").load(saved.version_id)
            X = ready.loaded_dataset.dataframe.loc[:, ["A1"]].iloc[:4]
            probabilities = restored.predictor.predict_positive_proba(X)
            self.assertEqual(probabilities.shape, (4,))
            self.assertTrue(np.isfinite(probabilities).all())
            self.assertEqual(restored.metadata["population"]["partition_role"], "full")
            self.assertEqual(restored.feature_specs[0].column_name, "A1")
            self.assertEqual(restored.summary.version_id, saved.version_id)
            with self.assertRaisesRegex(ValueError, "схемой"):
                restored.predictor.predict_positive_proba(X.rename(columns={"A1": "А1"}))
            with self.assertRaisesRegex(ValueError, "Версия кода"):
                ModelVersionStore(root, code_version="another-version").load(saved.version_id)
            repeated = service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            self.assertNotEqual(repeated.version_id, saved.version_id)
            self.assertEqual(len(store.catalog()[0]), 2)

    def test_different_features_produce_separate_versions_and_changed_source_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            root = Path(directory) / "artifacts"
            one_service, store, one_artifact = self._evaluate(ready, root, ("A1",))
            one = one_service.train_and_save(
                experiment_artifact_id=one_artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            two_service, _, two_artifact = self._evaluate(ready, root, ("A1", "A2"))
            two = two_service.train_and_save(
                experiment_artifact_id=two_artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            self.assertNotEqual(one.version_id, two.version_id)
            self.assertNotEqual(one.feature_set_hash, two.feature_set_hash)
            self.assertEqual(len(store.catalog()[0]), 2)

            ready.loaded_dataset.source_path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "изменился"):
                one_service.train_and_save(
                    experiment_artifact_id=one_artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                    feature_registry=ready.feature_registry, population=ready.population,
                )
            self.assertEqual(len(store.catalog()[0]), 2)

    def test_corrupt_native_file_is_not_loaded_or_listed(self) -> None:
        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            root = Path(directory) / "artifacts"
            service, store, artifact = self._evaluate(ready, root, ("A1",))
            saved = service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            with (root / "models" / saved.version_id / "xgboost.json").open("ab") as target:
                target.write(b"corrupt")
            with self.assertRaisesRegex(ValueError, "целостности"):
                store.load(saved.version_id)
            self.assertEqual(store.catalog(), ((), (saved.version_id,)))
            with self.assertRaisesRegex(ValueError, "идентификатор"):
                store.load("../outside")

    def test_final_fit_rejects_another_dataset_context(self) -> None:
        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            root = Path(directory) / "artifacts"
            service, store, artifact = self._evaluate(ready, root, ("A1",))
            other_contract = replace(ready.loaded_dataset.contract, dataset_fingerprint="other-dataset")
            other_loaded = replace(ready.loaded_dataset, contract=other_contract)
            with self.assertRaisesRegex(ValueError, "не совпадают"):
                service.train_and_save(
                    experiment_artifact_id=artifact.artifact_id, loaded_dataset=other_loaded,
                    feature_registry=ready.feature_registry, population=ready.population,
                )
            self.assertEqual(store.catalog(), ((), ()))

    def test_locked_historical_contract_trains_only_working_population(self) -> None:
        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            locked = replace(ready.loaded_dataset, contract=replace(ready.loaded_dataset.contract, final_test_locked=True))
            positions = tuple(range(45))
            working = EvaluationPopulation(positions, "historical-working", stable_hash(positions), "working")
            context = SimpleNamespace(loaded_dataset=locked, feature_registry=ready.feature_registry, population=working)
            root = Path(directory) / "artifacts"
            service, store, artifact = self._evaluate(context, root, ("A1",))
            saved = service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=locked,
                feature_registry=ready.feature_registry, population=working,
            )
            metadata = store.load(saved.version_id).metadata
            self.assertEqual(metadata["population"]["population_size"], 45)
            self.assertEqual(metadata["population"]["partition_role"], "working")
            self.assertTrue(metadata["dataset"]["final_test_locked"])

    def test_native_codecs_restore_all_supported_algorithms(self) -> None:
        frame = pd.DataFrame({"A1": np.arange(60, dtype=float), "A2": np.arange(60, dtype=float) % 7})
        target = pd.Series(np.arange(60) % 2)
        cat = CatBoostAdapter(CATBOOST_PROFILE, 42)
        cat.refit_estimator = CatBoostClassifier(iterations=6, depth=2, verbose=False, allow_writing_files=False)
        cat.refit_estimator.fit(frame, target)
        cat.best_iteration = 6
        xgb = XGBoostAdapter(XGBOOST_PROFILE, 42)
        xgb.refit_estimator = XGBClassifier(n_estimators=6, max_depth=2, eval_metric="logloss")
        xgb.refit_estimator.fit(frame, target)
        xgb.best_iteration = 6
        lgb = LightGBMAdapter(LIGHTGBM_PROFILE, 42)
        lgb.refit_estimator = LGBMClassifier(n_estimators=6, max_depth=2, min_child_samples=2, verbosity=-1)
        lgb.refit_estimator.fit(frame, target)
        lgb.best_iteration = 6
        components = {"catboost": cat, "xgboost": xgb, "lightgbm": lgb}
        mean = GBDTMeanAdapter(components)
        mean._fitted = True
        with TemporaryDirectory() as directory:
            for model_id, adapter in [*components.items(), ("gbdt_mean", mean)]:
                path = Path(directory) / model_id
                path.mkdir()
                self.assertTrue(save_fitted_native(adapter, model_id, path))
                restored = load_native_predictor(model_id, path, tuple(frame.columns))
                np.testing.assert_allclose(
                    restored.predict_positive_proba(frame.iloc[:5]),
                    adapter.predict_positive_proba(frame.iloc[:5]),
                    rtol=1e-5, atol=1e-5,
                )

    def test_saved_model_predicts_uploaded_inns_without_training_and_rejects_bad_schema(self) -> None:
        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            service, store, artifact = self._evaluate(ready, Path(directory) / "artifacts", ("A1",))
            saved = service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            restored = store.load(saved.version_id)
            batch = predict_uploaded_file(
                restored, "new.csv", b"INN,A1,Unused\n9999999999,1.5,x\n8888888888,2.5,y\n",
            )
            self.assertEqual(list(batch.predictions["INN"]), ["9999999999", "8888888888"])
            self.assertEqual(batch.version_id, saved.version_id)
            self.assertEqual(batch.ignored_columns, ("Unused",))
            self.assertTrue(batch.predictions["Вероятность события"].between(0, 1).all())
            workbook = BytesIO()
            pd.DataFrame({"INN": ["9999999999", "8888888888"], "A1": [1.5, 2.5]}).to_excel(workbook, index=False)
            xlsx_batch = predict_uploaded_file(restored, "new.xlsx", workbook.getvalue())
            self.assertEqual(list(xlsx_batch.predictions["INN"]), ["9999999999", "8888888888"])
            np.testing.assert_allclose(xlsx_batch.predictions["Вероятность события"], batch.predictions["Вероятность события"])
            with self.assertRaisesRegex(ValueError, "проверьте алфавит"):
                predict_uploaded_file(restored, "new.csv", "INN,А1\n9999999999,1.5\n".encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "ИНН должны"):
                predict_uploaded_file(restored, "new.csv", b"INN,A1\n9999999999,1.5\n9999999999,2.5\n")
            with self.assertRaisesRegex(ValueError, "ИНН должны"):
                predict_uploaded_file(restored, "new.csv", b"INN,A1\n=1+1,1.5\n")
            with self.assertRaisesRegex(ValueError, "нечисловые"):
                predict_uploaded_file(restored, "new.csv", b"INN,A1\n9999999999,not-a-number\n")

    def test_saved_versions_are_visible_in_data_step_after_restart(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            root = Path(directory) / "artifacts"
            service, store, artifact = self._evaluate(ready, root, ("A1",))
            service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            reopened = ModelVersionStore(root, code_version="test-v1")
            stub = SimpleNamespace(
                subheader=Mock(), dataframe=Mock(return_value=SimpleNamespace(selection=SimpleNamespace(rows=[]))),
                caption=Mock(), warning=Mock(),
            )
            with patch.object(prototype, "st", stub):
                prototype._render_saved_model_catalog(SimpleNamespace(model_store=reopened))
            stub.dataframe.assert_called_once()
            self.assertEqual(stub.dataframe.call_args.args[0][0]["Алгоритм"], "xgboost")
            self.assertRegex(stub.dataframe.call_args.args[0][0]["Дата"], r"^\d{2}\.\d{2}\.\d{2}$")
            self.assertEqual(prototype._format_saved_model_date("2026-09-21T22:30:00+00:00"), "22.09.26")
            class SessionState(dict):
                __getattr__ = dict.__getitem__

                def __setattr__(self, name, value):
                    self[name] = value

            stub.session_state = SessionState(current_step=0, highest_reached_step=0)
            stub.rerun = Mock()
            stub.dataframe.return_value.selection.rows = [0]
            with patch.object(prototype, "st", stub):
                prototype._render_saved_model_catalog(SimpleNamespace(model_store=reopened))
            self.assertEqual(stub.session_state.selected_model_version_id, reopened.catalog()[0][0].version_id)
            self.assertEqual(stub.session_state.current_step, 6)
            stub.rerun.assert_called_once()

    def test_prediction_screen_lists_required_features_and_runs_saved_version(self) -> None:
        from unittest.mock import Mock, patch
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            service, store, artifact = self._evaluate(ready, Path(directory) / "artifacts", ("A1",))
            saved = service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            class SessionState(dict):
                __getattr__ = dict.__getitem__

            stub = SimpleNamespace(
                session_state=SessionState(selected_model_version_id=saved.version_id),
                header=Mock(), success=Mock(), caption=Mock(), subheader=Mock(), write=Mock(), markdown=Mock(),
                dataframe=Mock(), download_button=Mock(), error=Mock(), warning=Mock(),
                selectbox=Mock(return_value="A1"), expander=Mock(),
                file_uploader=Mock(side_effect=lambda label, **_: None if label.startswith("Загрузить описания") else SimpleNamespace(
                    name="new.csv", getvalue=lambda: b"INN,A1\n9999999999,1.5\n",
                )),
                button=Mock(side_effect=lambda label, **_: label == "Получить прогноз"),
            )
            with patch.object(prototype, "st", stub), patch.object(prototype, "_navigation_button"):
                prototype._render_prediction_step(SimpleNamespace(model_store=store))
            self.assertEqual(stub.dataframe.call_args_list[0].args[0].data.iloc[0]["Столбец"], "A1")
            self.assertEqual(stub.dataframe.call_args_list[0].args[0].data.iloc[0]["Описание"], "Описание не указано")
            missing_style = stub.dataframe.call_args_list[0].args[0]._compute().ctx[(0, 2)]
            self.assertIn(("color", "#ff6b6b"), missing_style)
            self.assertIn(":red[Описание не указано]", stub.markdown.call_args.args[0])
            stub.expander.assert_not_called()
            self.assertEqual(stub.selectbox.call_args.args[1], ("A1",))
            self.assertEqual(stub.session_state[prototype._PREDICTION_RESULT_KEY].predictions.iloc[0]["INN"], "9999999999")
            self.assertEqual(stub.download_button.call_count, 3)
            stub.error.assert_not_called()

    def test_result_disables_training_for_saved_version_and_offers_navigation(self) -> None:
        from contextlib import nullcontext
        from unittest.mock import Mock, patch
        import app.streamlit_app as prototype

        with TemporaryDirectory() as directory:
            ready = self._ready(directory)
            service, store, artifact = self._evaluate(ready, Path(directory) / "artifacts", ("A1",))
            service.train_and_save(
                experiment_artifact_id=artifact.artifact_id, loaded_dataset=ready.loaded_dataset,
                feature_registry=ready.feature_registry, population=ready.population,
            )
            columns = [Mock() for _ in range(3)]
            stub = SimpleNamespace(
                container=Mock(return_value=nullcontext()), subheader=Mock(), columns=Mock(return_value=columns),
                success=Mock(), info=Mock(), caption=Mock(), warning=Mock(), error=Mock(), button=Mock(),
            )
            runtime = SimpleNamespace(model_store=store, model_registry=service.model_registry)
            with patch.object(prototype, "st", stub), patch.object(prototype, "_navigation_button") as navigate:
                self.assertTrue(prototype._render_final_model_section(runtime, artifact))
            stub.button.assert_called_once_with(
                "Обучение завершено", disabled=True, type="primary", key="prototype_final_model_saved",
            )
            self.assertEqual([call.args[1] for call in navigate.call_args_list],
                             ["Исторический SHAP →", "Вернуться в начало"])
            self.assertIn("SHAP именно этой сохранённой версии пока не рассчитан", stub.info.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
