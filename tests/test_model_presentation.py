from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from komus_risk.model_platform import (
    ModelCatalogComposition,
    ModelCatalogService,
    ModelConfigurationMode,
    ModelConfigurationRecord,
    ModelConfigurationService,
    ModelParameterPresentation,
    ModelPresentationError,
    ModelPresentationProfile,
    ModelPresentationRegistry,
    build_builtin_model_plugin_registry,
    builtin_model_presentation_registry,
)


def _profile(plugin, *, parameters=None, **changes):
    spec, schema = plugin.spec, plugin.parameter_schema
    return ModelPresentationProfile(
        "1",
        f"{spec.model_id}_ru",
        "1",
        "ru",
        spec.model_id,
        spec.version,
        spec.adapter_version,
        schema.schema_id,
        schema.schema_version,
        schema.schema_hash,
        tuple(
            parameters
            if parameters is not None
            else (
                ModelParameterPresentation(
                    item.parameter_path, "Новое название", "Описание параметра."
                )
                for item in schema.parameters
            )
        ),
        **changes,
    )


_BASELINE = {
    "catboost": (
        "catboost_initial_estimator",
        "1",
        "63c6a8bbe168da55d11108f2add621e5de51d519030a56396e078c366bd30004",
        "ebc1efc03da120ec99588ac064cf3e5dd9c3e41781406ccfba47bdd93c979d5f",
        "6c9b37cc1a78fcdf36145ef486c74218753a9200c2897fd7548034513225d0c9",
        "0b44323ea2d245292212618a50f77969f3edf83267a3dd36995a8d8e43996a01",
        "/estimator_params/iterations",
        901,
        "c26ea2dba8d1b4456786f90485568416e4b02e64e1aac43b933f153c2cf85aa1",
        "e3af3d84c0ace1caac083a8b737c54e49be603c4e5f44507a49548dc7a467b3d",
    ),
    "gbdt_mean": (
        "gbdt_mean_initial_composite",
        "1",
        "d6438e2e9b698c0b04227a5f543fa13c9def7c8dfd1b64744e519953e0d9f269",
        "1e40bd1632a4b5b472009326d53655352b846f0e727e2b2203068f2abe50434a",
        "a95a27a932889ce17ed471329c1fc6914311b6900ce1fab7e2e4c5363f00ebd9",
        "04b62065478bda0170929f67be7d99e6ceb61f32f96130af8832a773883b4beb",
        "/components/catboost/profile/estimator_params/iterations",
        901,
        "febf5b3276b186ed17967fdf87ec5361026af72a1536a53b81c6e481c50a27e0",
        "1b8ee40c69356f3539bea685dd6cae0f853fa66245af839f4765c8c1c2b16f16",
    ),
    "lightgbm": (
        "lightgbm_initial_estimator",
        "1",
        "356e8aa773a62cb07f9a8aa5966b59d8583fee41c0a18072c0b5ae15f8b1ecf7",
        "90a3f201f8c0d8ca4ae8c05a478b9d58e96ab49089f9191c37cb88158829d7e8",
        "ada7efc4a5611578586b267b12b665fa77411e61a56a657f39709857cc1643db",
        "c301e1159e4b8c46937963acb3a78ef2f69d829f0a7d133fe26e30dd2d7ce3f2",
        "/estimator_params/n_estimators",
        901,
        "ce851d1362e33829844ac1effa4384aced0c2cf75d368cd02e87ae44b44452e6",
        "cd5d88a11ad7477d7c24b6a2ebb681f93f9901c275085cff407be14fbdfc351f",
    ),
    "xgboost": (
        "xgboost_initial_estimator",
        "1",
        "e1d001cefa07ec73438b4046e33aafa8d41ec9253dd95cf1e446174375ea6861",
        "c17621c37ce1a836aecb73d2e35d8bd0cabc520d2b921b2dc9ed6e0b5734c6f4",
        "fa928fb4ed17b725f67ebc1d51903514df44f72fee8cca48579bebe74f2bebd7",
        "85c3b09165bfd9dac37df1c14db4f3c032814f255f7d800c5a7167a116de6d3e",
        "/estimator_params/n_estimators",
        901,
        "33d87394487be0c20aa129e0b7d798cd9712520b162b0d3088926c2defb5c6f1",
        "266b9b0e514a2bd18ef2caf089fe48ec272cc25fd31998f0b92fcf2c638aeb6f",
    ),
}
_PRESENTATION_BASELINE = {
    "catboost": (
        "1",
        "db68b950a5d97cc4bccb3fddaaf773276780164912ba6ffd1359b45d7163574e",
    ),
    "gbdt_mean": (
        "1",
        "4ff6557f540644131cd4b8d61070864f376664d12426f5d4b913ce611625b430",
    ),
    "lightgbm": (
        "1",
        "07e37d712ef2134afb6cee5f67db08ecf8edca20906a04fab5777b0578cafdad",
    ),
    "xgboost": (
        "1",
        "9d4ad12093bd0b38648831908e8dea06bb0d4ab6ece4cf675197e187fa3151fd",
    ),
}
_BEHAVIORAL_BINDINGS = {
    "catboost": ("accepted_stage1_v2", "1", "catboost_accepted_stage1_v2", "1"),
    "gbdt_mean": (
        "accepted_stage1_v2_equal_mean",
        "1",
        "gbdt_mean_accepted_stage1_v2",
        "1",
    ),
    "lightgbm": ("accepted_stage1_v2", "1", "lightgbm_accepted_stage1_v2", "1"),
    "xgboost": ("accepted_stage1_v2", "1", "xgboost_accepted_stage1_v2", "1"),
}


def test_builtin_behavioral_identity_freeze_and_independent_copy_identity():
    plugins = build_builtin_model_plugin_registry()
    presentations = builtin_model_presentation_registry(plugins)
    assert {
        profile.model_id: (
            profile.presentation_profile_version,
            profile.presentation_hash,
        )
        for profile in presentations.list()
    } == _PRESENTATION_BASELINE
    configuration = ModelConfigurationService(plugins)
    catalog = ModelCatalogService(
        plugins, presentations, package_version_resolver=lambda _: "unused"
    )
    baseline_rows = {
        plugin.spec.model_id: row
        for plugin, row in zip(plugins.list(), _BASELINE.values(), strict=True)
    }
    for plugin in plugins.list():
        model_id = plugin.spec.model_id
        schema = plugin.parameter_schema
        profile = plugin.recommended_profile
        assert (
            plugin.spec.version,
            plugin.spec.adapter_version,
            profile.profile_id,
            profile.profile_version,
        ) == _BEHAVIORAL_BINDINGS[model_id]
        (
            schema_id,
            schema_version,
            schema_hash,
            contract_hash,
            profile_hash,
            recommended_hash,
            advanced_path,
            advanced_value,
            advanced_hash,
            record_id,
        ) = baseline_rows[model_id]
        assert (schema.schema_id, schema.schema_version, schema.schema_hash) == (
            schema_id,
            schema_version,
            schema_hash,
        )
        assert plugin.plugin_contract_hash == contract_hash
        assert profile.profile_hash == profile_hash
        recommended = configuration.resolve(
            model_id=model_id, mode=ModelConfigurationMode.RECOMMENDED
        )
        advanced = configuration.resolve(
            model_id=model_id,
            mode=ModelConfigurationMode.ADVANCED,
            user_overrides={advanced_path: advanced_value},
        )
        record = ModelConfigurationRecord.from_resolved(recommended, plugin)
        assert recommended.resolved_configuration_hash == recommended_hash
        assert advanced.resolved_configuration_hash == advanced_hash
        assert record.configuration_record_id == record_id

    entry = catalog.get("catboost")
    old_hash = presentations.list()[0].presentation_hash
    edited = replace(
        presentations.list()[0],
        parameters=(
            replace(
                presentations.list()[0].parameters[0],
                display_name_ru="Только новое имя",
            ),
            *presentations.list()[0].parameters[1:],
        ),
        presentation_profile_version="2",
    )
    changed_registry = ModelPresentationRegistry((edited, *presentations.list()[1:]))
    changed = ModelCatalogService(
        plugins, changed_registry, package_version_resolver=lambda _: "unused"
    ).get("catboost")
    assert edited.presentation_hash != old_hash
    assert changed.parameters != entry.parameters
    assert changed.schema_hash == entry.schema_hash
    assert changed.plugin_contract_hash == entry.plugin_contract_hash
    assert changed.profile_hash == entry.profile_hash
    with pytest.raises(FrozenInstanceError):
        edited.locale = "en"


def test_hash_canonicalizes_parameter_and_registration_order():
    plugins = build_builtin_model_plugin_registry()
    profile = builtin_model_presentation_registry(plugins).list()[0]
    reverse = replace(profile, parameters=tuple(reversed(profile.parameters)))
    assert reverse.presentation_hash == profile.presentation_hash
    assert ModelPresentationRegistry((profile,)).list() == (profile,)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "unknown",
        "schema_hash",
        "model_id",
        "model_version",
        "adapter_version",
        "schema_id",
        "schema_version",
        "missing_profile",
        "duplicate_profile",
        "orphan",
    ],
)
def test_invalid_complete_composition_fails_closed(case):
    plugins = build_builtin_model_plugin_registry()
    good = builtin_model_presentation_registry(plugins).list()
    cat = plugins.get("catboost")
    bad = good[0]
    if case == "missing":
        bad = replace(bad, parameters=bad.parameters[:-1])
    elif case == "unknown":
        bad = replace(
            bad,
            parameters=(
                *bad.parameters[:-1],
                replace(bad.parameters[-1], parameter_path="/unknown"),
            ),
        )
    elif case == "schema_hash":
        bad = replace(bad, schema_hash="wrong")
    elif case == "model_id":
        bad = replace(bad, model_id="wrong")
    elif case == "model_version":
        bad = replace(bad, model_version="wrong")
    elif case == "adapter_version":
        bad = replace(bad, adapter_version="wrong")
    elif case == "schema_id":
        bad = replace(bad, schema_id="wrong")
    elif case == "schema_version":
        bad = replace(bad, schema_version="wrong")
    entries = list(good)
    entries[0] = bad
    if case == "missing_profile":
        entries = entries[1:]
    elif case == "duplicate_profile":
        entries.append(good[0])
    elif case == "orphan":
        entries.append(replace(good[0], model_id="orphan", schema_id="orphan"))
    with pytest.raises(
        ModelPresentationError, match="INVALID_MODEL_PRESENTATION_COMPOSITION"
    ):
        ModelCatalogComposition.compose(plugins, ModelPresentationRegistry(entries))
    assert plugins.get(cat.spec.model_id) is cat


def test_duplicate_parameter_path_is_rejected_during_profile_construction():
    plugins = build_builtin_model_plugin_registry()
    original = builtin_model_presentation_registry(plugins).list()[0]
    with pytest.raises(
        ModelPresentationError,
        match="INVALID_MODEL_PRESENTATION_COMPOSITION",
    ) as error:
        ModelPresentationProfile(
            original.presentation_schema_version,
            original.presentation_profile_id,
            original.presentation_profile_version,
            original.locale,
            original.model_id,
            original.model_version,
            original.adapter_version,
            original.schema_id,
            original.schema_version,
            original.schema_hash,
            (*original.parameters, original.parameters[0]),
        )
    assert error.value.code == "INVALID_MODEL_PRESENTATION_COMPOSITION"


def test_builtin_catalog_uses_russian_presentation_and_full_parameter_coverage():
    plugins = build_builtin_model_plugin_registry()
    catalog = ModelCatalogService(
        plugins,
        builtin_model_presentation_registry(plugins),
        package_version_resolver=lambda _: "unused",
    )
    for plugin in plugins.list():
        entry = catalog.get(plugin.spec.model_id)
        assert {item.parameter_path for item in entry.parameters} == {
            item.parameter_path for item in plugin.parameter_schema.parameters
        }
        assert all(
            item.display_name_ru and item.description_ru for item in entry.parameters
        )
    mean = catalog.get("gbdt_mean")
    assert any(
        item.display_name_ru.startswith("CatBoost —") for item in mean.parameters
    )
