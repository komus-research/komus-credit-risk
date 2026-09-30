"""MP-E catalog safety, runtime availability and generic fifth-plugin regression."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
import pandas as pd
import pytest

from komus_risk.application import ExperimentApplicationService, RunExperimentRequest
from komus_risk.application.service import to_planning_request_metadata
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
    CapabilityDeclaration,
    CapabilityDomain,
    CapabilitySupport,
    ModelCapabilityManifest,
    ModelCatalogService,
    ModelConfigurationMode,
    ModelConfigurationService,
    ModelInputContract,
    ModelParameter,
    ModelParameterPresentation,
    ModelParameterSchema,
    ModelPlugin,
    ModelPluginRegistry,
    ProviderDescriptor,
    ModelPresentationError,
    ModelPresentationProfile,
    ModelPresentationRegistry,
    ParameterValueType,
    RecommendedModelProfile,
    RuntimeAvailabilityState,
    build_builtin_model_plugin_registry,
    builtin_model_presentation_registry,
)
from komus_risk.models import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.models.gbdt.native import NativePredictor
from komus_risk.planning import ExperimentPlanningService
from komus_risk.preparation import (
    PreparedDatasetContext,
    PreparedDatasetContextAuthority,
)
from komus_risk.registries import FeatureRegistry, ModelRegistry, ModelSpec


class DummyCatalogAdapter(BinaryClassifierAdapter):
    def fit(self, X_train, y_train) -> None:
        self.probability = float(np.asarray(y_train, dtype=float).mean())

    def predict_positive_proba(self, X_valid):
        return np.full(len(X_valid), self.probability, dtype=float)


class DummyCatalogFactory(ModelAdapterFactory):
    model_id = "dummy_catalog"
    model_version = "1"
    adapter_version = "1"

    def create(self, parameters, seed):
        return DummyCatalogAdapter()


_DUMMY_PERSISTENCE = ProviderDescriptor("dummy_catalog_test_persistence", "1", "persistence", {"model_id": "dummy_catalog"})


class DummyCatalogPersistenceProvider:
    descriptor = _DUMMY_PERSISTENCE
    model_id = "dummy_catalog"
    model_version = "1"
    adapter_version = "1"

    def native_files(self):
        return ("model.bin",)

    def validate_fitted(self, adapter, *, parameters, seed):
        if not isinstance(adapter, DummyCatalogAdapter):
            raise ValueError("wrong adapter")

    def save(self, adapter, directory):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "model.bin").write_bytes(b"dummy")
        return self.native_files()

    def load(self, directory, feature_columns):
        return NativePredictor("dummy_catalog", feature_columns, lambda X: np.full(len(X), 0.5))


def dummy_plugin(runtime_requirements: dict[str, Any] | None = None, *, with_persistence: bool = False) -> ModelPlugin:
    spec = ModelSpec(
        "dummy_catalog",
        "Тестовая пятая модель",
        "1",
        ("binary",),
        "Детерминированная тестовая интеграция MP-E.",
        {"estimator_params": {"rounds": 3}},
        runtime_requirements or {"device": "cpu"},
        "1",
    )
    parameter = ModelParameter(
        "/estimator_params/rounds",
        "Количество итераций",
        "Безопасный редактируемый тестовый параметр.",
        ParameterValueType.INTEGER,
        True,
        False,
        True,
        3,
        3,
        minimum=1,
        maximum=20,
        display_order=4,
    )
    schema = ModelParameterSchema(
        "dummy_catalog_schema", "1", "dummy_catalog", "1", "1", (parameter,)
    )
    profile = RecommendedModelProfile(
        "dummy_catalog_profile", "1", "dummy_catalog", "1", "1", spec.default_profile
    )
    manifest = ModelCapabilityManifest(
        "dummy_catalog",
        "1",
        "1",
        tuple(
            CapabilityDeclaration(
                domain,
                CapabilitySupport.SUPPORTED
                if domain
                in {
                    CapabilityDomain.TRAINING,
                    CapabilityDomain.CONFIGURATION,
                    CapabilityDomain.TARGETLESS_INFERENCE,
                    CapabilityDomain.SMOKE_TEST,
                    *({CapabilityDomain.PERSISTENCE, CapabilityDomain.LOADING} if with_persistence else set()),
                }
                else CapabilitySupport.UNSUPPORTED,
                provider_id=(_DUMMY_PERSISTENCE.provider_id if with_persistence and domain in {CapabilityDomain.PERSISTENCE, CapabilityDomain.LOADING} else None),
            )
            for domain in CapabilityDomain
        ),
    )
    return ModelPlugin(
        spec,
        schema,
        profile,
        DummyCatalogFactory(),
        manifest,
        ModelInputContract(
            "dummy_catalog", "1", "1", ("numeric",), "float32", False, "disabled", "cpu"
        ),
        persistence_provider=_DUMMY_PERSISTENCE if with_persistence else None,
    )


def _registry_with_dummy() -> ModelPluginRegistry:
    registry = build_builtin_model_plugin_registry()
    assert registry.persistence_providers is not None
    registry.persistence_providers.register(DummyCatalogPersistenceProvider())
    registry.register(dummy_plugin(with_persistence=True))
    return registry


def _presentation_registry(registry: ModelPluginRegistry) -> ModelPresentationRegistry:
    registered_ids = {plugin.spec.model_id for plugin in registry.list()}
    profiles = [
        profile
        for profile in builtin_model_presentation_registry(
            build_builtin_model_plugin_registry()
        ).list()
        if profile.model_id in registered_ids
    ]
    for plugin in registry.list():
        if plugin.spec.model_id in {profile.model_id for profile in profiles}:
            continue
        schema = plugin.parameter_schema
        entries = tuple(
            ModelParameterPresentation(
                item.parameter_path, "Тестовый параметр", "Тестовое описание параметра."
            )
            for item in schema.parameters
        )
        profiles.append(
            ModelPresentationProfile(
                "1",
                f"{plugin.spec.model_id}_ru",
                "1",
                "ru",
                plugin.spec.model_id,
                plugin.spec.version,
                plugin.spec.adapter_version,
                schema.schema_id,
                schema.schema_version,
                schema.schema_hash,
                entries,
            )
        )
    return ModelPresentationRegistry(profiles)


class TestModelCatalog:
    def test_catalog_keeps_the_exact_plugin_snapshot_validated_at_construction(
        self,
    ) -> None:
        registry = build_builtin_model_plugin_registry()
        original_ids = {plugin.spec.model_id for plugin in registry.list()}
        presentations = builtin_model_presentation_registry(registry)
        catalog = ModelCatalogService(
            registry, presentations, package_version_resolver=lambda _: "unused"
        )
        assert {item.model_id for item in catalog.list_models()} == original_ids

        fifth_plugin = dummy_plugin()
        registry.register(fifth_plugin)
        assert "dummy_catalog" in {item.spec.model_id for item in registry.list()}
        assert {item.model_id for item in catalog.list_models()} == original_ids
        with pytest.raises(KeyError):
            catalog.get("dummy_catalog")

        expanded_catalog = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda _: "unused",
        )
        assert {item.model_id for item in expanded_catalog.list_models()} == (
            original_ids | {"dummy_catalog"}
        )
        assert (
            expanded_catalog.get("dummy_catalog").parameters[0].display_name_ru
            == "Тестовый параметр"
        )

    def test_catalog_is_deterministic_safe_and_manifest_truthful(self) -> None:
        registry = _registry_with_dummy()
        catalog = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda _: "unused",
        )
        first, second = catalog.list_models(), catalog.list_models()
        assert [item.model_id for item in first] == sorted(
            item.model_id for item in first
        )
        assert first == second
        dummy = catalog.get("dummy_catalog")
        payload = dummy.to_dict()
        _assert_declarative(payload)
        payload["default_profile"]["estimator_params"]["rounds"] = 19
        assert (
            registry.get("dummy_catalog").recommended_profile.payload[
                "estimator_params"
            ]["rounds"]
            == 3
        )
        expected = registry.get("dummy_catalog").capability_manifest.to_dict()[
            "capabilities"
        ]
        assert payload["capabilities"] == expected
        assert [item.display_order for item in dummy.parameters] == [4]
        assert dummy.state == RuntimeAvailabilityState.AVAILABLE
        assert dummy.reason_code == "MODEL_RUNTIME_READY"
        try:
            catalog.get("unregistered")
        except KeyError:
            pass
        else:  # pragma: no cover - assertion boundary
            raise AssertionError("Unregistered plugin appeared in catalog.")

    def test_runtime_availability_is_generic_and_checks_nested_requirements(
        self,
    ) -> None:
        plugin = dummy_plugin(
            {
                "components": {
                    "one": {"package": "one", "version": "1"},
                    "two": {"package": "two", "version": "2"},
                }
            }
        )
        registry = ModelPluginRegistry()
        registry.register(plugin)
        missing = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda _: None,
        ).get("dummy_catalog")
        assert (missing.state, missing.reason_code) == (
            RuntimeAvailabilityState.UNAVAILABLE,
            "RUNTIME_PACKAGE_MISSING",
        )
        wrong = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda _: "wrong",
        ).get("dummy_catalog")
        assert (wrong.state, wrong.reason_code) == (
            RuntimeAvailabilityState.MISCONFIGURED,
            "RUNTIME_VERSION_MISMATCH",
        )
        ready = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda name: {"one": "1", "two": "2"}[name],
        ).get("dummy_catalog")
        assert (ready.state, ready.reason_code) == (
            RuntimeAvailabilityState.AVAILABLE,
            "MODEL_RUNTIME_READY",
        )
        duplicate = replace(
            plugin,
            spec=replace(
                plugin.spec,
                runtime_requirements={
                    "a": {"package": "one", "version": "1"},
                    "b": {"package": "one", "version": "1"},
                },
            ),
        )
        invalid_registry = ModelPluginRegistry()
        invalid_registry.register(duplicate)
        invalid = ModelCatalogService(
            invalid_registry,
            _presentation_registry(invalid_registry),
            package_version_resolver=lambda _: "1",
        ).get("dummy_catalog")
        assert (invalid.state, invalid.reason_code) == (
            RuntimeAvailabilityState.MISCONFIGURED,
            "RUNTIME_REQUIREMENTS_INVALID",
        )

    def test_gbdt_mean_nested_component_requirements_are_all_checked(self) -> None:
        registry = build_builtin_model_plugin_registry()
        ready = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda name: {
                "catboost": "1.2.10",
                "xgboost": "3.4.1",
                "lightgbm": "4.7.0",
            }[name],
        ).get("gbdt_mean")
        assert (ready.state, ready.reason_code) == (
            RuntimeAvailabilityState.AVAILABLE,
            "MODEL_RUNTIME_READY",
        )
        missing_component = ModelCatalogService(
            registry,
            _presentation_registry(registry),
            package_version_resolver=lambda name: (
                None
                if name == "lightgbm"
                else {"catboost": "1.2.10", "xgboost": "3.4.1"}[name]
            ),
        ).get("gbdt_mean")
        assert (missing_component.state, missing_component.reason_code) == (
            RuntimeAvailabilityState.UNAVAILABLE,
            "RUNTIME_PACKAGE_MISSING",
        )

    def test_dummy_plugin_full_generic_chain_to_v2_artifact(self) -> None:
        registry = _registry_with_dummy()
        configuration = ModelConfigurationService(registry)
        recommended = configuration.resolve(
            model_id="dummy_catalog",
            mode=ModelConfigurationMode.RECOMMENDED,
            user_overrides={},
        )
        advanced = configuration.resolve(
            model_id="dummy_catalog",
            mode=ModelConfigurationMode.ADVANCED,
            user_overrides={"/estimator_params/rounds": 5},
        )
        assert recommended.resolved_parameters_dict()["estimator_params"]["rounds"] == 3
        assert advanced.resolved_parameters_dict()["estimator_params"]["rounds"] == 5
        dataset, features, population = _dataset()
        planner = ExperimentPlanningService(
            model_plugin_registry=registry,
            model_presentation_registry=_presentation_registry(registry),
        )
        plan = planner.build_plan(
            to_planning_request_metadata(_request()),
            loaded_dataset=dataset,
            feature_registry=features,
            population=population,
        )
        assert plan.is_valid
        assert plan.model is not None and plan.model.model_id == "dummy_catalog"
        assert plan.model.parameters[0].display_name_ru == "Тестовый параметр"
        models = ModelRegistry()
        models.register(registry.get("dummy_catalog").spec)
        with TemporaryDirectory() as root:
            authority = PreparedDatasetContextAuthority()
            context = authority.register(
                PreparedDatasetContext(
                    "dummy-context", "Dummy", dataset, features, population
                )
            )
            service = ExperimentApplicationService(
                model_registry=models,
                model_factories={
                    "dummy_catalog": registry.get("dummy_catalog").factory
                },
                artifact_store=ExperimentArtifactStore(root),
                comparison_service=ExperimentComparisonService(),
                code_version="test",
                model_plugin_registry=registry,
                prepared_context_authority=authority,
            )
            smoke = service.run_configuration_smoke(
                loaded_dataset=dataset,
                feature_registry=features,
                population=population,
                request=_request(),
                prepared_context_id=context.context_id,
            )
            assert smoke.status.value == "PASS"
            artifact = service.run_experiment(
                loaded_dataset=dataset,
                feature_registry=features,
                population=population,
                request=_request(),
                prepared_context_id=context.context_id,
            )
        assert artifact.configuration_record is not None
        assert artifact.smoke_evidence is not None
        assert artifact.configuration_record.model_id == "dummy_catalog"
        assert artifact.smoke_evidence.smoke_identity == smoke.smoke_identity

    def test_missing_fifth_plugin_presentation_blocks_catalog_only(self) -> None:
        registry = _registry_with_dummy()
        with pytest.raises(
            ModelPresentationError,
            match="INVALID_MODEL_PRESENTATION_COMPOSITION",
        ):
            ModelCatalogService(
                registry,
                builtin_model_presentation_registry(registry),
                package_version_resolver=lambda _: "unused",
            )
        resolved = ModelConfigurationService(registry).resolve(
            model_id="dummy_catalog", mode=ModelConfigurationMode.RECOMMENDED
        )
        assert resolved.resolved_parameters_dict()["estimator_params"]["rounds"] == 3


def _request() -> RunExperimentRequest:
    return RunExperimentRequest(
        ("a", "b"),
        "dummy_catalog",
        "stratified_kfold_oof",
        "1",
        17,
        2,
        "oof",
        None,
        None,
        (),
        "ADVANCED",
        {"/estimator_params/rounds": 5},
    )


def _dataset() -> tuple[LoadedDataset, FeatureRegistry, EvaluationPopulation]:
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
            "test",
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
            "test",
            FeatureUsageStatus.MODEL_ALLOWED,
            None,
            None,
            None,
            2,
        ),
    )
    features = FeatureRegistry(
        "dummy-features", specs, (FeatureGroup("g", "G", "G", 1, "test", ("a", "b")),)
    )
    contract = DatasetContract(
        "dummy-dataset",
        "1",
        "Dummy",
        "ready_csv",
        "dummy-fp",
        20,
        4,
        "target",
        1,
        "id",
        features.registry_id,
        features.registry_hash,
        "validated",
        False,
    )
    return (
        LoadedDataset(dataframe, contract, Path("dummy.csv"), "csv", "dummy"),
        features,
        EvaluationPopulation(
            tuple(range(20)), "working", "dummy-population", "working"
        ),
    )


def _assert_declarative(value: Any) -> None:
    assert not callable(value)
    assert not isinstance(value, type)
    if isinstance(value, dict):
        for item in value.values():
            _assert_declarative(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_declarative(item)
