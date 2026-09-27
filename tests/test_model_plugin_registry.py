"""Focused MP-A contract and trusted-plugin registry tests."""

from __future__ import annotations

import unittest
from dataclasses import replace

from komus_risk.model_platform import (
    CapabilityDeclaration,
    CapabilityDomain,
    CapabilitySupport,
    ModelCapabilityManifest,
    ModelInputContract,
    ModelParameter,
    ModelParameterSchema,
    ModelPlugin,
    ModelPluginRegistry,
    ParameterUiLevel,
    ParameterValueType,
    RecommendedModelProfile,
    build_builtin_model_plugin_registry,
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


class PluginRegistryTests(unittest.TestCase):
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


def replace_factory(model_id: str) -> ModelAdapterFactory:
    factory = _DummyFactory()
    factory.model_id = model_id
    return factory
