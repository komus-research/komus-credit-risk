"""Focused MP-A contract and trusted-plugin registry tests."""

from __future__ import annotations

import unittest
from dataclasses import replace

from komus_risk.model_platform import (
    CapabilityDeclaration,
    CapabilityDomain,
    CapabilitySupport,
    ModelCapabilityManifest,
    ModelExplanationProviderRegistry,
    ModelInputContract,
    ModelParameter,
    ModelParameterSchema,
    ModelPersistenceProviderRegistry,
    ModelPlugin,
    ModelPluginRegistry,
    BuiltinNativeExplanationProvider,
    NativeGBDTPersistenceProvider,
    ParameterUiLevel,
    ParameterValueType,
    ProviderDescriptor,
    RecommendedModelProfile,
    build_builtin_model_plugin_registry,
    builtin_gbdt_persistence_providers,
    builtin_model_plugins,
)
from komus_risk.models.base import BinaryClassifierAdapter, ModelAdapterFactory
from komus_risk.models.gbdt import (
    CATBOOST_PROFILE,
    GBDT_MEAN_PROFILE,
    LIGHTGBM_PROFILE,
    XGBOOST_PROFILE,
)
from komus_risk.registries import ModelSpec


class _DummyAdapter(BinaryClassifierAdapter):
    def fit(self, X_train, y_train) -> None:  # pragma: no cover - contract-only plugin
        return None

    def predict_positive_proba(
        self, X_valid
    ):  # pragma: no cover - contract-only plugin
        raise RuntimeError("not used by MP-A")


class _DummyFactory(ModelAdapterFactory):
    model_id = "dummy"
    model_version = "1"
    adapter_version = "1"

    def create(self, parameters, seed):
        return _DummyAdapter()


def _all_capabilities(
    *, persistence: CapabilitySupport = CapabilitySupport.UNSUPPORTED
) -> ModelCapabilityManifest:
    return ModelCapabilityManifest(
        "dummy",
        "1",
        "1",
        tuple(
            CapabilityDeclaration(
                domain,
                persistence
                if domain is CapabilityDomain.PERSISTENCE
                else CapabilitySupport.UNSUPPORTED,
            )
            for domain in CapabilityDomain
        ),
    )


def _dummy_plugin() -> ModelPlugin:
    spec = ModelSpec(
        "dummy",
        "Тестовая модель",
        "1",
        ("binary",),
        "Только тестовый trusted plugin.",
        {"estimator_params": {"rounds": 3}},
        {"device": "cpu"},
        "1",
    )
    parameter = ModelParameter(
        "/estimator_params/rounds",
        "Итерации",
        "Количество итераций.",
        ParameterValueType.INTEGER,
        True,
        False,
        True,
        3,
        3,
        minimum=1,
    )
    schema = ModelParameterSchema("dummy_schema", "1", "dummy", "1", "1", (parameter,))
    profile = RecommendedModelProfile(
        "dummy_profile", "1", "dummy", "1", "1", spec.default_profile
    )
    return ModelPlugin(
        spec,
        schema,
        profile,
        _DummyFactory(),
        _all_capabilities(),
        ModelInputContract(
            "dummy", "1", "1", ("numeric",), "float32", False, "disabled", "cpu"
        ),
    )


class ParameterSchemaTests(unittest.TestCase):
    def test_valid_value_types_and_deterministic_schema_hash(self) -> None:
        parameters = (
            ModelParameter(
                "/integer",
                "Целый",
                "Описание.",
                ParameterValueType.INTEGER,
                True,
                False,
                True,
                2,
                2,
                minimum=1,
            ),
            ModelParameter(
                "/float",
                "Дробный",
                "Описание.",
                ParameterValueType.FLOAT,
                True,
                False,
                True,
                0.5,
                0.5,
                minimum=0.0,
            ),
            ModelParameter(
                "/boolean",
                "Флаг",
                "Описание.",
                ParameterValueType.BOOLEAN,
                True,
                False,
                True,
                True,
                True,
            ),
            ModelParameter(
                "/enum",
                "Режим",
                "Описание.",
                ParameterValueType.ENUM,
                True,
                False,
                True,
                "fast",
                "fast",
                choices=("fast", "safe"),
                ui_level=ParameterUiLevel.BASIC,
            ),
        )
        first = ModelParameterSchema("schema", "1", "model", "1", "1", parameters)
        second = ModelParameterSchema("schema", "1", "model", "1", "1", parameters)
        self.assertEqual(first.schema_hash, second.schema_hash)

    def test_invalid_parameter_declarations_fail_closed(self) -> None:
        common = {
            "display_name_ru": "Имя",
            "description_ru": "Описание.",
            "value_type": ParameterValueType.INTEGER,
            "required": True,
            "nullable": False,
            "editable": True,
            "default_value": 1,
            "recommended_value": 1,
        }
        with self.assertRaises(ValueError):
            ModelParameter("", **common)
        with self.assertRaises(ValueError):
            ModelParameter("/bad/~x", **common)
        with self.assertRaises(ValueError):
            ModelParameter("/x", minimum=2, maximum=1, **common)
        with self.assertRaises(ValueError):
            ModelParameter("/x", choices=(1,), **common)
        with self.assertRaises(TypeError):
            ModelParameter("/x", ui_level="hidden", **common)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ModelParameter("/x", **{**common, "value_type": ParameterValueType.ENUM})

    def test_recommended_values_match_profile_paths(self) -> None:
        plugin = _dummy_plugin()
        registry = ModelPluginRegistry()
        self.assertIs(registry.register(plugin), plugin)

        mismatching_parameter = replace(
            plugin.parameter_schema.parameters[0], recommended_value=2
        )
        mismatching_schema = replace(
            plugin.parameter_schema, parameters=(mismatching_parameter,)
        )
        with self.assertRaisesRegex(ValueError, "does not match schema"):
            ModelPluginRegistry().register(
                replace(plugin, parameter_schema=mismatching_schema)
            )

        missing_parameter = replace(
            plugin.parameter_schema.parameters[0],
            parameter_path="/estimator_params/missing",
        )
        missing_schema = replace(
            plugin.parameter_schema, parameters=(missing_parameter,)
        )
        with self.assertRaisesRegex(ValueError, "misses parameter"):
            ModelPluginRegistry().register(
                replace(plugin, parameter_schema=missing_schema)
            )

    def test_nested_recommended_value_path_passes_for_composite_plugin(self) -> None:
        builtin = build_builtin_model_plugin_registry()
        mean_plugin = builtin.get("gbdt_mean")
        self.assertIs(
            ModelPluginRegistry(
                persistence_providers=builtin_gbdt_persistence_providers((mean_plugin,)),
                explanation_providers=builtin.explanation_providers,
            ).register(mean_plugin),
            mean_plugin,
        )


class ContractImmutabilityTests(unittest.TestCase):
    def test_nested_mutable_set_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "JSON-shaped"):
            RecommendedModelProfile(
                "profile", "1", "model", "1", "1", {"nested": {"bad": {1, 2}}}
            )

    def test_nested_mapping_list_tuple_is_frozen_and_source_mutation_cannot_change_hash(
        self,
    ) -> None:
        source = {"nested": [{"value": ("accepted", 2)}]}
        profile = RecommendedModelProfile("profile", "1", "model", "1", "1", source)
        profile_hash = profile.profile_hash
        source["nested"][0]["value"] = ("mutated", 3)

        self.assertEqual(profile.profile_hash, profile_hash)
        self.assertEqual(profile.payload["nested"][0]["value"], ("accepted", 2))
        with self.assertRaises(TypeError):
            profile.payload["nested"][0]["value"] = "mutated"  # type: ignore[index]


class PluginRegistryTests(unittest.TestCase):
    def test_supported_persistence_requires_matching_executable_provider(self) -> None:
        builtin = build_builtin_model_plugin_registry()
        plugin = builtin.get("catboost")
        with self.assertRaisesRegex(ValueError, "executable trusted provider"):
            ModelPluginRegistry().register(plugin)
        with self.assertRaisesRegex(ValueError, "not registered"):
            ModelPluginRegistry(
                persistence_providers=ModelPersistenceProviderRegistry()
            ).register(plugin)
        providers = builtin_gbdt_persistence_providers((plugin,))
        self.assertIs(
            ModelPluginRegistry(
                persistence_providers=providers,
                explanation_providers=builtin.explanation_providers,
            ).register(plugin),
            plugin,
        )
        wrong = NativeGBDTPersistenceProvider(
            plugin.persistence_provider,
            plugin.spec.model_id,
            "wrong-version",
            plugin.spec.adapter_version,
        )
        with self.assertRaisesRegex(ValueError, "incompatible"):
            ModelPluginRegistry(
                persistence_providers=ModelPersistenceProviderRegistry((wrong,)),
                explanation_providers=builtin.explanation_providers,
            ).register(plugin)

    def test_supported_local_explanation_requires_matching_executable_provider(self) -> None:
        builtin = build_builtin_model_plugin_registry()
        plugin = builtin.get("catboost")
        persistence = builtin_gbdt_persistence_providers((plugin,))
        with self.assertRaisesRegex(ValueError, "executable trusted provider registry"):
            ModelPluginRegistry(persistence_providers=persistence).register(plugin)

        descriptor = plugin.local_explanation_provider
        self.assertIsNotNone(descriptor)
        mismatched = BuiltinNativeExplanationProvider(
            descriptor, plugin.spec.model_id, "wrong-version", plugin.spec.adapter_version
        )
        with self.assertRaisesRegex(ValueError, "incompatible"):
            ModelPluginRegistry(
                persistence_providers=persistence,
                explanation_providers=ModelExplanationProviderRegistry((mismatched,)),
            ).register(plugin)

    def test_builtin_profiles_are_exact_frozen_profiles(self) -> None:
        plugins = {plugin.spec.model_id: plugin for plugin in builtin_model_plugins()}
        self.assertEqual(
            plugins["catboost"].recommended_profile.payload, CATBOOST_PROFILE
        )
        self.assertEqual(
            plugins["xgboost"].recommended_profile.payload, XGBOOST_PROFILE
        )
        self.assertEqual(
            plugins["lightgbm"].recommended_profile.payload, LIGHTGBM_PROFILE
        )
        self.assertEqual(
            plugins["gbdt_mean"].recommended_profile.payload, GBDT_MEAN_PROFILE
        )
        self.assertEqual(
            plugins["catboost"].recommended_profile.profile_hash,
            builtin_model_plugins()[0].recommended_profile.profile_hash,
        )

    def test_registers_current_four_and_contract_hash_is_deterministic(self) -> None:
        first = build_builtin_model_plugin_registry()
        second = build_builtin_model_plugin_registry()
        self.assertEqual(
            tuple(plugin.spec.model_id for plugin in first.list()),
            ("catboost", "gbdt_mean", "lightgbm", "xgboost"),
        )
        self.assertEqual(
            [plugin.plugin_contract_hash for plugin in first.list()],
            [plugin.plugin_contract_hash for plugin in second.list()],
        )
        for plugin in first.list():
            with self.subTest(model_id=plugin.spec.model_id):
                provider = first.explanation_providers.validate_plugin_provider(plugin)
                self.assertEqual(plugin.local_explanation_provider, provider.descriptor)

    def test_factory_identity_and_duplicate_conflicts_are_rejected(self) -> None:
        plugin = _dummy_plugin()
        registry = ModelPluginRegistry()
        with self.assertRaisesRegex(ValueError, "registry key"):
            registry.register(plugin, registry_key="other")
        with self.assertRaisesRegex(ValueError, "factory identity"):
            registry.register(replace(plugin, factory=replace_factory("other")))
        registry.register(plugin)
        changed_spec = ModelSpec(
            "dummy",
            "Другая",
            "1",
            ("binary",),
            "Другая.",
            {"estimator_params": {"rounds": 3}},
            {"device": "cpu"},
            "1",
        )
        changed = replace(plugin, spec=changed_spec)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            registry.register(changed)

    def test_missing_provider_and_malformed_capability_are_rejected(self) -> None:
        plugin = _dummy_plugin()
        required_provider = replace(
            plugin,
            capability_manifest=_all_capabilities(
                persistence=CapabilitySupport.SUPPORTED
            ),
        )
        with self.assertRaisesRegex(ValueError, "persistence"):
            ModelPluginRegistry().register(required_provider)
        with self.assertRaises(ValueError):
            ModelCapabilityManifest(
                "dummy",
                "1",
                "1",
                (
                    CapabilityDeclaration(
                        CapabilityDomain.TRAINING, CapabilitySupport.SUPPORTED
                    ),
                ),
            )

    def test_provider_capability_links_are_bidirectional_and_exact(self) -> None:
        plugin = _dummy_plugin()
        provider = ProviderDescriptor("local-provider", "1", "local_explanation")
        with self.assertRaisesRegex(ValueError, "unsupported local explanation"):
            ModelPluginRegistry().register(
                replace(plugin, local_explanation_provider=provider)
            )

        supported_without_id = _replace_capability(
            plugin,
            CapabilityDomain.LOCAL_EXPLANATION,
            support=CapabilitySupport.SUPPORTED,
            provider_id=None,
        )
        with self.assertRaisesRegex(ValueError, "invalid provider identity"):
            ModelPluginRegistry().register(
                replace(supported_without_id, local_explanation_provider=provider)
            )

        supported_wrong_id = _replace_capability(
            plugin,
            CapabilityDomain.LOCAL_EXPLANATION,
            support=CapabilitySupport.CONDITIONAL,
            provider_id="another-provider",
        )
        with self.assertRaisesRegex(ValueError, "invalid provider identity"):
            ModelPluginRegistry().register(
                replace(supported_wrong_id, local_explanation_provider=provider)
            )

    def test_profile_invalid_against_schema_is_rejected(self) -> None:
        plugin = _dummy_plugin()
        invalid_spec = ModelSpec(
            "dummy",
            "Тестовая модель",
            "1",
            ("binary",),
            "Только тестовый trusted plugin.",
            {"estimator_params": {"rounds": 0}},
            {"device": "cpu"},
            "1",
        )
        invalid_profile = RecommendedModelProfile(
            "dummy_profile", "1", "dummy", "1", "1", invalid_spec.default_profile
        )
        with self.assertRaisesRegex(ValueError, "below the minimum"):
            ModelPluginRegistry().register(
                replace(plugin, spec=invalid_spec, recommended_profile=invalid_profile)
            )

    def test_dummy_plugin_registers_without_a_model_id_branch(self) -> None:
        registry = ModelPluginRegistry()
        plugin = _dummy_plugin()
        self.assertIs(registry.register(plugin), plugin)
        self.assertIs(registry.get("dummy"), plugin)

    def test_configuration_validator_identity_has_only_two_valid_states(self) -> None:
        plugin = _dummy_plugin()

        def validator(_: object) -> None:
            return None

        with self.assertRaises(ValueError):
            replace(plugin, configuration_validator=validator, validator_id=None)
        with self.assertRaises(ValueError):
            replace(plugin, configuration_validator=validator, validator_id="")
        with self.assertRaises(ValueError):
            replace(plugin, configuration_validator=None, validator_id="validator-v1")
        with self.assertRaises(TypeError):
            replace(
                plugin, configuration_validator=object(), validator_id="validator-v1"
            )

        valid = replace(
            plugin, configuration_validator=validator, validator_id="validator-v1"
        )
        self.assertIs(ModelPluginRegistry().register(valid), valid)


def replace_factory(model_id: str) -> ModelAdapterFactory:
    factory = _DummyFactory()
    factory.model_id = model_id
    return factory


def _replace_capability(
    plugin: ModelPlugin,
    domain: CapabilityDomain,
    *,
    support: CapabilitySupport,
    provider_id: str | None,
) -> ModelPlugin:
    capabilities = tuple(
        replace(capability, support=support, provider_id=provider_id)
        if capability.domain is domain
        else capability
        for capability in plugin.capability_manifest.capabilities
    )
    return replace(
        plugin,
        capability_manifest=replace(
            plugin.capability_manifest, capabilities=capabilities
        ),
    )
