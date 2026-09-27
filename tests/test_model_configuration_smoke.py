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
from komus_risk.data import DatasetInspector, LoadedDataset, TabularReader
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
from komus_risk.preparation import (
    ConfirmedColumnDecision,
    ConfirmedColumnStatus,
    ConfirmedDatasetPreparation,
    DatasetPreparationAnalyzer,
    KomusDatasetPreparationService,
    PopulationPolicyV1,
    PreparedDatasetContext,
    PreparedDatasetContextAuthority,
    PreparedDatasetContextAuthorityError,
)
from komus_risk.preparation.materializer import inspection_report_hash, proposal_hash
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

    def __init__(self):
        self.create_calls = 0

    def create(self, parameters, seed):
        self.create_calls += 1
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


def _register_context(service, dataset, features, population):
    context = _context(dataset, features, population)
    return service._prepared_context_authority.register(context)


def _prepare_generic_context(service, root):
    path = Path(root) / "generic.csv"
    path.write_text(
        "id,target,a,b\n"
        "id-0,0,0.1,0.9\n"
        "id-1,1,0.9,0.1\n"
        "id-2,0,0.2,0.8\n"
        "id-3,1,0.8,0.2\n"
        "id-4,0,0.3,0.7\n"
        "id-5,1,0.7,0.3\n",
        encoding="utf-8",
    )
    snapshot = TabularReader().read(path)
    report = DatasetInspector().inspect(snapshot)
    proposal = DatasetPreparationAnalyzer().analyze(report)
    report_hash = inspection_report_hash(report)
    confirmation = ConfirmedDatasetPreparation(
        "1",
        snapshot.fingerprint,
        report_hash,
        proposal_hash(proposal, report_hash),
        proposal.policy_id,
        proposal.policy_version,
        proposal.policy_hash,
        "Generic",
        "target",
        1,
        "id",
        (
            ConfirmedColumnDecision("id", ConfirmedColumnStatus.IDENTIFIER),
            ConfirmedColumnDecision("target", ConfirmedColumnStatus.TARGET),
            ConfirmedColumnDecision("a", ConfirmedColumnStatus.MODEL_ALLOWED),
            ConfirmedColumnDecision("b", ConfirmedColumnStatus.MODEL_ALLOWED),
        ),
        PopulationPolicyV1.FULL_OOF_NO_PROTECTED_FINAL_TEST,
    )
    return KomusDatasetPreparationService(
        context_authority=service._prepared_context_authority
    ).prepare(snapshot, report, proposal, confirmation)[0]


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
        context = _register_context(service, dataset, features, population)
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
        context = _register_context(service, dataset, features, population_a)
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


def test_context_authority_rejects_forged_locked_context_before_smoke_or_artifact():
    with TemporaryDirectory() as root:
        service = _service(root)
        dataset, features, _population = _dataset()
        authoritative_population = EvaluationPopulation(
            tuple(range(10)), "working", "working-fp", "working"
        )
        trusted = _register_context(
            service, dataset, features, authoritative_population
        )
        request = _request()
        service.run_configuration_smoke(
            loaded_dataset=dataset,
            feature_registry=features,
            population=authoritative_population,
            request=request,
            prepared_context_id=trusted.context_id,
        )
        calls_after_trusted_smoke = service.model_factories["catboost"].create_calls
        forged_population = EvaluationPopulation(
            tuple(range(10, 20)), "working", "working-fp", "working"
        )
        forged = PreparedDatasetContext(
            "forged-authoritative-context", "Dataset", dataset, features, forged_population
        )
        for action in (service.run_configuration_smoke, service.run_experiment):
            try:
                action(
                    loaded_dataset=dataset,
                    feature_registry=features,
                    population=forged_population,
                    request=request,
                    prepared_context=forged,
                )
            except SmokeGateError as error:
                assert error.code == "TRUSTED_CONTEXT_NOT_FOUND"
            else:
                raise AssertionError("unregistered forged context must fail closed")
        assert service.model_factories["catboost"].create_calls == calls_after_trusted_smoke
        assert not list(Path(root).glob("*.json"))


def test_context_authority_rejects_reused_id_changed_rows_unknown_ids_and_conflicts():
    with TemporaryDirectory() as root:
        service = _service(root)
        dataset, features, population = _dataset()
        trusted = _register_context(service, dataset, features, population)
        forged_population = EvaluationPopulation(
            tuple(reversed(population.row_positions)),
            population.population_id,
            population.population_fingerprint,
            population.partition_role,
        )
        forged = PreparedDatasetContext(
            trusted.context_id, "Dataset", dataset, features, forged_population
        )
        try:
            service.run_configuration_smoke(
                loaded_dataset=dataset,
                feature_registry=features,
                population=forged_population,
                request=_request(),
                prepared_context=forged,
            )
        except SmokeGateError as error:
            assert error.code == "PREPARED_CONTEXT_MISMATCH"
        else:
            raise AssertionError("reused context id must not replace trusted rows")
        try:
            service.run_configuration_smoke(
                loaded_dataset=dataset,
                feature_registry=features,
                population=population,
                request=_request(),
                prepared_context_id="unknown-context",
            )
        except SmokeGateError as error:
            assert error.code == "TRUSTED_CONTEXT_NOT_FOUND"
        else:
            raise AssertionError("unknown reference must fail closed")
        authority = PreparedDatasetContextAuthority()
        authority.register(trusted)
        try:
            authority.register(forged)
        except PreparedDatasetContextAuthorityError as error:
            assert error.code == "CONFLICTING_CONTEXT_REGISTRATION"
        else:
            raise AssertionError("conflicting authority registration must fail")


def test_application_cannot_publish_unlocked_caller_data():
    with TemporaryDirectory() as root:
        service = _service(root)
        dataset, features, _population = _dataset()
        unlocked = replace(
            dataset, contract=replace(dataset.contract, final_test_locked=False)
        )
        caller_population = EvaluationPopulation(
            tuple(range(10, 20)), "caller-pop", "caller-fp", "working"
        )
        for action in (service.run_configuration_smoke, service.run_experiment):
            try:
                action(
                    loaded_dataset=unlocked,
                    feature_registry=features,
                    population=caller_population,
                    request=_request(),
                )
            except SmokeGateError as error:
                assert error.code == "TRUSTED_CONTEXT_NOT_FOUND"
            else:
                raise AssertionError("application must not issue caller context trust")
        assert service.model_factories["catboost"].create_calls == 0
        assert service._smoke_evidence == {}
        assert not list(Path(root).glob("*.json"))


def test_trusted_generic_preparation_allows_smoke_and_full_run():
    with TemporaryDirectory() as root:
        service = _service(root)
        trusted = _prepare_generic_context(service, root)
        smoke = service.run_configuration_smoke(
            loaded_dataset=trusted.loaded_dataset,
            feature_registry=trusted.feature_registry,
            population=trusted.population,
            request=_request(),
            prepared_context_id=trusted.context_id,
        )
        assert smoke.status is SmokeStatus.PASS
        artifact = service.run_experiment(
            loaded_dataset=trusted.loaded_dataset,
            feature_registry=trusted.feature_registry,
            population=trusted.population,
            request=_request(),
            prepared_context_id=trusted.context_id,
        )
        assert artifact.manifest["artifact_schema_version"] == "2"
