"""MP-C provenance, technical smoke and application-gate regressions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from komus_risk.application import (
    ExperimentApplicationService,
    RunExperimentRequest,
    SmokeGateError,
)
from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.contracts import (
    DatasetContract,
    FeatureGroup,
    FeatureSpec,
    FeatureUsageStatus,
)
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.model_platform import (
    CapabilityDomain,
    CapabilitySupport,
    ModelConfigurationRecord,
    ModelConfigurationService,
    ModelPluginRegistry,
    SmokeStatus,
    build_builtin_model_plugin_registry,
)
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.preparation import PreparedDatasetContext
from komus_risk.registries import FeatureRegistry, ModelRegistry


class _Adapter(BinaryClassifierAdapter):
    def fit(self, X_train, y_train):
        self.columns = tuple(X_train.columns)

    def predict_positive_proba(self, X_valid):
        return np.full(len(X_valid), 0.5)


class _Factory(ModelAdapterFactory):
    model_id = "catboost"
    model_version = "2.0"
    adapter_version = "gbdt-adapter-v1"

    def create(self, parameters, seed):
        return _Adapter()


def _request(**changes):
    value = {
        "selected_feature_ids": ("a", "b"),
        "model_id": "catboost",
        "protocol_id": "stratified_kfold_oof",
        "protocol_version": "1",
        "seed": 17,
        "folds": 2,
        "evaluation_level": "oof",
        "reference_artifact_id": None,
        "changed_dimension": None,
        "changed_elements": (),
    }
    value.update(changes)
    return RunExperimentRequest(**value)


def _dataset():
    dataframe = pd.DataFrame(
        {
            "id": range(20),
            "target": [0, 1] * 10,
            "a": np.linspace(0.1, 0.9, 20),
            "b": np.linspace(0.9, 0.1, 20),
        }
    )
    specs = (
        FeatureSpec(
            "a",
            "a",
            "A",
            "A",
            "g",
            "float",
            "numeric",
            "t",
            FeatureUsageStatus.MODEL_ALLOWED,
            None,
            None,
            None,
            1,
        ),
        FeatureSpec(
            "b",
            "b",
            "B",
            "B",
            "g",
            "float",
            "numeric",
            "t",
            FeatureUsageStatus.MODEL_ALLOWED,
            None,
            None,
            None,
            2,
        ),
    )
    features = FeatureRegistry(
        "features", specs, (FeatureGroup("g", "G", "G", 1, "t", ("a", "b")),)
    )
    contract = DatasetContract(
        "dataset",
        "1",
        "Dataset",
        "ready_csv",
        "fp",
        len(dataframe),
        len(dataframe.columns),
        "target",
        1,
        "id",
        features.registry_id,
        features.registry_hash,
        "validated",
        True,
    )
    return (
        LoadedDataset(dataframe, contract, Path("synthetic.csv"), "csv", "source"),
        features,
        EvaluationPopulation(tuple(range(20)), "working", "working-fp", "working"),
    )


def _service(root):
    builtin = build_builtin_model_plugin_registry().get("catboost")
    registry = ModelPluginRegistry()
    factory = _Factory()
    factory.model_version = builtin.spec.version
    factory.adapter_version = builtin.spec.adapter_version
    registry.register(replace(builtin, factory=factory))
    models = ModelRegistry()
    models.register(builtin.spec)
    return ExperimentApplicationService(
        model_registry=models,
        model_factories={"catboost": factory},
        artifact_store=ExperimentArtifactStore(root),
        comparison_service=ExperimentComparisonService(),
        code_version="test",
        model_plugin_registry=registry,
    )


def _context(dataset, features, population):
    return PreparedDatasetContext(
        "authoritative-context", "Dataset", dataset, features, population
    )


def test_configuration_record_is_deterministic_and_deep_immutable():
    registry = build_builtin_model_plugin_registry()
    resolved = ModelConfigurationService(registry).resolve(
        model_id="catboost", mode="RECOMMENDED"
    )
    first = ModelConfigurationRecord.from_resolved(resolved, registry.get("catboost"))
    second = ModelConfigurationRecord.from_resolved(resolved, registry.get("catboost"))
    assert first.configuration_record_id == second.configuration_record_id
    assert first.resolved_configuration_hash == resolved.resolved_configuration_hash
    try:
        first.resolved_parameters["estimator_params"]["depth"] = 99
    except TypeError:
        pass
    else:
        raise AssertionError("record must deep-freeze resolved parameters")


def test_smoke_gate_and_v2_provenance_round_trip():
    with TemporaryDirectory() as root:
        service = _service(root)
        dataset, features, population = _dataset()
        context = _context(dataset, features, population)
        request = _request()
        try:
            service.run_experiment(
                loaded_dataset=dataset,
                feature_registry=features,
                population=population,
                request=request,
                prepared_context=context,
            )
        except SmokeGateError as error:
            assert error.code == "SMOKE_REQUIRED"
        else:
            raise AssertionError("full experiment must require smoke")
        smoke = service.run_configuration_smoke(
            loaded_dataset=dataset,
            feature_registry=features,
            population=population,
            request=request,
            prepared_context=context,
        )
        assert smoke.status is SmokeStatus.PASS
        assert set(smoke.sampled_row_positions).issubset(set(population.row_positions))
        assert len(smoke.sampled_row_positions) <= 128
        artifact = service.run_experiment(
            loaded_dataset=dataset,
            feature_registry=features,
            population=population,
            request=request,
            prepared_context=context,
        )
        assert artifact.manifest["artifact_schema_version"] == "2"
        assert (
            artifact.configuration_record is not None
            and artifact.smoke_evidence is not None
        )
        advanced = _request(
            configuration_mode="ADVANCED", user_overrides={"/estimator_params/depth": 8}
        )
        try:
            service.run_experiment(
                loaded_dataset=dataset,
                feature_registry=features,
                population=population,
                request=advanced,
                prepared_context=context,
            )
        except SmokeGateError as error:
            assert error.code == "SMOKE_REQUIRED"
        else:
            raise AssertionError(
                "recommended smoke must not authorize advanced configuration"
            )


def test_locked_population_row_identity_and_authoritative_context_are_required():
    with TemporaryDirectory() as root:
        service = _service(root)
        dataset, features, population_a = _dataset()
        context = _context(dataset, features, population_a)
        request = _request()
        smoke = service.run_configuration_smoke(
            loaded_dataset=dataset,
            feature_registry=features,
            population=population_a,
            request=request,
            prepared_context=context,
        )
        assert smoke.status is SmokeStatus.PASS
        population_b = EvaluationPopulation(
            tuple(range(10, 20)), "working", "working-fp", "working"
        )
        for changed_population in (
            population_b,
            EvaluationPopulation(
                tuple(reversed(population_a.row_positions)),
                "working",
                "working-fp",
                "working",
            ),
        ):
            try:
                service.run_experiment(
                    loaded_dataset=dataset,
                    feature_registry=features,
                    population=changed_population,
                    request=request,
                    prepared_context=context,
                )
            except SmokeGateError as error:
                assert error.code == "PREPARED_CONTEXT_MISMATCH"
            else:
                raise AssertionError(
                    "a smoke PASS cannot authorize changed population rows"
                )
        try:
            service.run_configuration_smoke(
                loaded_dataset=dataset,
                feature_registry=features,
                population=population_a,
                request=request,
            )
        except SmokeGateError as error:
            assert error.code == "AUTHORITATIVE_CONTEXT_REQUIRED"
        else:
            raise AssertionError("locked data requires an authoritative context")


def test_no_registry_full_run_is_rejected_and_smoke_capabilities_are_truthful():
    with TemporaryDirectory() as root:
        configured = _service(root)
        unconfigured = ExperimentApplicationService(
            model_registry=configured.model_registry,
            model_factories=configured.model_factories,
            artifact_store=ExperimentArtifactStore(root),
            comparison_service=ExperimentComparisonService(),
            code_version="test",
        )
        dataset, features, population = _dataset()
        for request in (
            _request(),
            _request(
                configuration_mode="ADVANCED",
                user_overrides={"/estimator_params/depth": 8},
            ),
        ):
            try:
                unconfigured.run_experiment(
                    loaded_dataset=dataset,
                    feature_registry=features,
                    population=population,
                    request=request,
                    prepared_context=_context(dataset, features, population),
                )
            except SmokeGateError as error:
                assert error.code == "MODEL_PLATFORM_REQUIRED"
            else:
                raise AssertionError(
                    "unconfigured application service must fail closed"
                )
    registry = build_builtin_model_plugin_registry()
    for model_id in ("catboost", "xgboost", "lightgbm", "gbdt_mean"):
        assert (
            registry.get(model_id)
            .capability_manifest.get(CapabilityDomain.SMOKE_TEST)
            .support
            is CapabilitySupport.SUPPORTED
        )
