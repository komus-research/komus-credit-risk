"""Built-in MP-A declarations for the four already accepted GBDT integrations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from komus_risk.models.gbdt import (
    CATBOOST_EDITABLE_PARAMETERS,
    CATBOOST_MODEL_SPEC,
    CATBOOST_PROFILE,
    GBDT_MEAN_MODEL_SPEC,
    GBDT_MEAN_PROFILE,
    LIGHTGBM_EDITABLE_PARAMETERS,
    LIGHTGBM_MODEL_SPEC,
    LIGHTGBM_PROFILE,
    XGBOOST_EDITABLE_PARAMETERS,
    XGBOOST_MODEL_SPEC,
    XGBOOST_PROFILE,
    CatBoostFactory,
    GBDTMeanFactory,
    LightGBMFactory,
    XGBoostFactory,
)
from komus_risk.registries.model_registry import ModelSpec

from .contracts import (
    CapabilityDeclaration,
    CapabilityDomain,
    CapabilitySupport,
    ModelCapabilityManifest,
    ModelInputContract,
    ModelParameter,
    ModelParameterSchema,
    ModelPlugin,
    ParameterUiLevel,
    ParameterValueType,
    ProviderDescriptor,
    RecommendedModelProfile,
)
from .persistence import builtin_gbdt_persistence_providers
from .explainability import (
    BuiltinNativeExplanationProvider,
    GBDTMeanProbabilityExplanationProvider,
    ModelExplanationProviderRegistry,
)
from .registry import ModelPluginRegistry


def _persistence_provider(model_id: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        f"{model_id}_native_persistence",
        "1",
        "persistence",
        {
            "native_format": "trusted_gbdt_native",
            "model_id": model_id,
        },
    )


_CATBOOST_EXPLANATION_PROVIDER = ProviderDescriptor(
    "catboost_native_local_shap",
    "1",
    "local_explanation",
    {"implementation": "existing accepted Local SHAP path"},
)
_XGBOOST_EXPLANATION_PROVIDER = ProviderDescriptor(
    "xgboost_native_local_shap", "1", "local_explanation",
    {"implementation": "native XGBoost pred_contribs"},
)
_LIGHTGBM_EXPLANATION_PROVIDER = ProviderDescriptor(
    "lightgbm_native_local_shap", "1", "local_explanation",
    {"implementation": "native LightGBM pred_contrib"},
)
_GBDT_MEAN_EXPLANATION_PROVIDER = ProviderDescriptor(
    "gbdt_mean_probability_shap",
    "1",
    "local_explanation",
    {"implementation": "trusted model-agnostic probability SHAP", "output_space": "probability"},
)


def _value_type(value: Any) -> ParameterValueType:
    if isinstance(value, bool):
        return ParameterValueType.BOOLEAN
    if isinstance(value, int):
        return ParameterValueType.INTEGER
    if isinstance(value, float):
        return ParameterValueType.FLOAT
    raise TypeError(f"Unsupported parameter value in trusted schema: {value!r}")


def _parameter(
    path: str,
    name: str,
    value: Any,
    order: int,
    constraints: dict[str, tuple[type, int | float | None, int | float | None]],
) -> ModelParameter:
    _, minimum, maximum = constraints[name]
    return ModelParameter(
        parameter_path=path,
        display_name_ru=name,
        description_ru=f"Зафиксированное значение параметра {name}.",
        value_type=(
            ParameterValueType.FLOAT
            if constraints[name][0] is float
            else _value_type(value)
        ),
        required=True,
        nullable=False,
        editable=True,
        default_value=value,
        recommended_value=value,
        minimum=minimum,
        maximum=maximum,
        ui_level=ParameterUiLevel.ADVANCED,
        group_id="estimator",
        display_order=order,
    )


def _locked_enum(
    path: str, name: str, value: str, order: int, *, group_id: str = "composition"
) -> ModelParameter:
    return ModelParameter(
        parameter_path=path,
        display_name_ru=name,
        description_ru=f"Зафиксированная семантика: {name}.",
        value_type=ParameterValueType.ENUM,
        required=True,
        nullable=False,
        editable=False,
        default_value=value,
        recommended_value=value,
        choices=(value,),
        ui_level=ParameterUiLevel.ADVANCED,
        group_id=group_id,
        display_order=order,
    )


def _schema(
    spec: ModelSpec,
    profile: dict[str, Any],
    names: tuple[str, ...],
    constraints: dict[str, tuple[type, int | float | None, int | float | None]],
) -> ModelParameterSchema:
    return ModelParameterSchema(
        schema_id=f"{spec.model_id}_initial_estimator",
        schema_version="1",
        model_id=spec.model_id,
        model_version=spec.version,
        adapter_version=spec.adapter_version,
        parameters=tuple(
            _parameter(
                f"/estimator_params/{name}",
                name,
                profile["estimator_params"][name],
                order,
                constraints,
            )
            for order, name in enumerate(names)
        ),
    )


def _mean_schema() -> ModelParameterSchema:
    parameters: list[ModelParameter] = [
        _locked_enum(
            "/aggregation/method",
            "Метод агрегации",
            "arithmetic_mean_positive_probability",
            0,
        ),
    ]
    models = (
        (
            "catboost",
            CATBOOST_PROFILE,
            ("iterations", "learning_rate", "depth"),
            CATBOOST_EDITABLE_PARAMETERS,
        ),
        (
            "xgboost",
            XGBOOST_PROFILE,
            (
                "n_estimators",
                "learning_rate",
                "max_depth",
                "min_child_weight",
                "subsample",
                "colsample_bytree",
                "reg_alpha",
                "reg_lambda",
            ),
            XGBOOST_EDITABLE_PARAMETERS,
        ),
        (
            "lightgbm",
            LIGHTGBM_PROFILE,
            (
                "n_estimators",
                "learning_rate",
                "num_leaves",
                "max_depth",
                "min_child_samples",
                "subsample",
                "subsample_freq",
                "colsample_bytree",
                "reg_alpha",
                "reg_lambda",
            ),
            LIGHTGBM_EDITABLE_PARAMETERS,
        ),
    )
    order = 1
    for model_id, profile, names, constraints in models:
        component = GBDT_MEAN_PROFILE["components"][model_id]
        parameters.extend(
            (
                _locked_enum(
                    f"/components/{model_id}/model_version",
                    f"Версия {model_id}",
                    component["model_version"],
                    order,
                ),
                _locked_enum(
                    f"/components/{model_id}/adapter_version",
                    f"Версия адаптера {model_id}",
                    component["adapter_version"],
                    order + 1,
                ),
            )
        )
        order += 2
        for name in names:
            value = profile["estimator_params"][name]
            parameters.append(
                ModelParameter(
                    parameter_path=f"/components/{model_id}/profile/estimator_params/{name}",
                    display_name_ru=f"{model_id}: {name}",
                    description_ru=f"Параметр component {model_id}: {name}.",
                    value_type=(
                        ParameterValueType.FLOAT
                        if constraints[name][0] is float
                        else _value_type(value)
                    ),
                    required=True,
                    nullable=False,
                    editable=True,
                    default_value=value,
                    recommended_value=value,
                    minimum=constraints[name][1],
                    maximum=constraints[name][2],
                    ui_level=ParameterUiLevel.ADVANCED,
                    group_id=f"component_{model_id}",
                    display_order=order,
                )
            )
            order += 1
    return ModelParameterSchema(
        "gbdt_mean_initial_composite",
        "1",
        GBDT_MEAN_MODEL_SPEC.model_id,
        GBDT_MEAN_MODEL_SPEC.version,
        GBDT_MEAN_MODEL_SPEC.adapter_version,
        tuple(parameters),
    )


def _profile(spec: ModelSpec, payload: dict[str, Any]) -> RecommendedModelProfile:
    return RecommendedModelProfile(
        profile_id=f"{spec.model_id}_accepted_stage1_v2",
        profile_version="1",
        model_id=spec.model_id,
        model_version=spec.version,
        adapter_version=spec.adapter_version,
        payload=deepcopy(payload),
    )


def _input_contract(spec: ModelSpec) -> ModelInputContract:
    return ModelInputContract(
        spec.model_id,
        spec.version,
        spec.adapter_version,
        ("numeric", "boolean"),
        "float32",
        False,
        "disabled",
        "cpu",
    )


def _capabilities(
    spec: ModelSpec,
    persistence_provider: ProviderDescriptor,
    *,
    local_explanation_provider: ProviderDescriptor | None,
) -> ModelCapabilityManifest:
    explanation = CapabilitySupport.SUPPORTED if local_explanation_provider else CapabilitySupport.UNSUPPORTED
    return ModelCapabilityManifest(
        spec.model_id,
        spec.version,
        spec.adapter_version,
        (
            CapabilityDeclaration(
                CapabilityDomain.TRAINING, CapabilitySupport.SUPPORTED
            ),
            CapabilityDeclaration(
                CapabilityDomain.CONFIGURATION,
                CapabilitySupport.SUPPORTED,
            ),
            CapabilityDeclaration(
                CapabilityDomain.PERSISTENCE,
                CapabilitySupport.SUPPORTED,
                persistence_provider.provider_id,
            ),
            CapabilityDeclaration(
                CapabilityDomain.LOADING,
                CapabilitySupport.SUPPORTED,
                persistence_provider.provider_id,
            ),
            CapabilityDeclaration(
                CapabilityDomain.TARGETLESS_INFERENCE, CapabilitySupport.SUPPORTED
            ),
            CapabilityDeclaration(
                CapabilityDomain.LOCAL_EXPLANATION,
                explanation,
                local_explanation_provider.provider_id if local_explanation_provider else None,
            ),
            CapabilityDeclaration(
                CapabilityDomain.SMOKE_TEST,
                CapabilitySupport.SUPPORTED,
            ),
        ),
    )


def builtin_model_plugins() -> tuple[ModelPlugin, ...]:
    """Builds fresh, deterministic declarations without changing runtime composition."""
    catboost_provider = _persistence_provider("catboost")
    xgboost_provider = _persistence_provider("xgboost")
    lightgbm_provider = _persistence_provider("lightgbm")
    mean_provider = _persistence_provider("gbdt_mean")
    catboost = ModelPlugin(
        CATBOOST_MODEL_SPEC,
        _schema(
            CATBOOST_MODEL_SPEC,
            CATBOOST_PROFILE,
            ("iterations", "learning_rate", "depth"),
            CATBOOST_EDITABLE_PARAMETERS,
        ),
        _profile(CATBOOST_MODEL_SPEC, CATBOOST_PROFILE),
        CatBoostFactory(),
        _capabilities(CATBOOST_MODEL_SPEC, catboost_provider, local_explanation_provider=_CATBOOST_EXPLANATION_PROVIDER),
        _input_contract(CATBOOST_MODEL_SPEC),
        persistence_provider=catboost_provider,
        local_explanation_provider=_CATBOOST_EXPLANATION_PROVIDER,
    )
    xgboost = ModelPlugin(
        XGBOOST_MODEL_SPEC,
        _schema(
            XGBOOST_MODEL_SPEC,
            XGBOOST_PROFILE,
            (
                "n_estimators",
                "learning_rate",
                "max_depth",
                "min_child_weight",
                "subsample",
                "colsample_bytree",
                "reg_alpha",
                "reg_lambda",
            ),
            XGBOOST_EDITABLE_PARAMETERS,
        ),
        _profile(XGBOOST_MODEL_SPEC, XGBOOST_PROFILE),
        XGBoostFactory(),
        _capabilities(XGBOOST_MODEL_SPEC, xgboost_provider, local_explanation_provider=_XGBOOST_EXPLANATION_PROVIDER),
        _input_contract(XGBOOST_MODEL_SPEC),
        persistence_provider=xgboost_provider,
        local_explanation_provider=_XGBOOST_EXPLANATION_PROVIDER,
    )
    lightgbm = ModelPlugin(
        LIGHTGBM_MODEL_SPEC,
        _schema(
            LIGHTGBM_MODEL_SPEC,
            LIGHTGBM_PROFILE,
            (
                "n_estimators",
                "learning_rate",
                "num_leaves",
                "max_depth",
                "min_child_samples",
                "subsample",
                "subsample_freq",
                "colsample_bytree",
                "reg_alpha",
                "reg_lambda",
            ),
            LIGHTGBM_EDITABLE_PARAMETERS,
        ),
        _profile(LIGHTGBM_MODEL_SPEC, LIGHTGBM_PROFILE),
        LightGBMFactory(),
        _capabilities(LIGHTGBM_MODEL_SPEC, lightgbm_provider, local_explanation_provider=_LIGHTGBM_EXPLANATION_PROVIDER),
        _input_contract(LIGHTGBM_MODEL_SPEC),
        persistence_provider=lightgbm_provider,
        local_explanation_provider=_LIGHTGBM_EXPLANATION_PROVIDER,
    )
    mean_factory = GBDTMeanFactory(
        {
            "catboost": CatBoostFactory(),
            "xgboost": XGBoostFactory(),
            "lightgbm": LightGBMFactory(),
        }
    )
    mean = ModelPlugin(
        GBDT_MEAN_MODEL_SPEC,
        _mean_schema(),
        _profile(GBDT_MEAN_MODEL_SPEC, GBDT_MEAN_PROFILE),
        mean_factory,
        _capabilities(GBDT_MEAN_MODEL_SPEC, mean_provider, local_explanation_provider=_GBDT_MEAN_EXPLANATION_PROVIDER),
        _input_contract(GBDT_MEAN_MODEL_SPEC),
        persistence_provider=mean_provider,
        local_explanation_provider=_GBDT_MEAN_EXPLANATION_PROVIDER,
    )
    return catboost, xgboost, lightgbm, mean


def build_builtin_model_plugin_registry() -> ModelPluginRegistry:
    plugins = builtin_model_plugins()
    explanation_providers = []
    for plugin in plugins:
        descriptor = plugin.local_explanation_provider
        if descriptor is None:
            continue
        provider_type = (
            GBDTMeanProbabilityExplanationProvider
            if plugin.spec.model_id == "gbdt_mean"
            else BuiltinNativeExplanationProvider
        )
        explanation_providers.append(provider_type(
            descriptor, plugin.spec.model_id, plugin.spec.version, plugin.spec.adapter_version
        ))
    registry = ModelPluginRegistry(
        persistence_providers=builtin_gbdt_persistence_providers(plugins),
        explanation_providers=ModelExplanationProviderRegistry(explanation_providers),
    )
    for plugin in plugins:
        registry.register(plugin)
    return registry
