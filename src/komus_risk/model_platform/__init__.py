"""Trusted, declarative model-plugin contracts (MP-A).

This package is intentionally not wired into the existing experiment path yet.
"""

from .configuration import (
    ModelConfigurationError,
    ModelConfigurationMode,
    ModelConfigurationService,
    ResolvedModelConfiguration,
)
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
    VisibilityCondition,
)
from .persistence import (
    ModelPersistenceProvider,
    ModelPersistenceProviderRegistry,
    NativeGBDTPersistenceProvider,
    builtin_gbdt_persistence_providers,
)
from .plugins import build_builtin_model_plugin_registry, builtin_model_plugins
from .provenance import ModelConfigurationRecord
from .registry import ModelPluginRegistry
from .smoke import (
    DEFAULT_SMOKE_POLICY,
    ModelConfigurationSmokeTestService,
    SmokeError,
    SmokeEvidence,
    SmokePolicy,
    SmokeStatus,
)

__all__ = [
    "DEFAULT_SMOKE_POLICY",
    "CapabilityDeclaration",
    "CapabilityDomain",
    "CapabilitySupport",
    "ModelCapabilityManifest",
    "ModelConfigurationError",
    "ModelConfigurationMode",
    "ModelConfigurationRecord",
    "ModelConfigurationService",
    "ModelConfigurationSmokeTestService",
    "ModelInputContract",
    "ModelParameter",
    "ModelParameterSchema",
    "ModelPersistenceProvider",
    "ModelPersistenceProviderRegistry",
    "ModelPlugin",
    "ModelPluginRegistry",
    "NativeGBDTPersistenceProvider",
    "ParameterUiLevel",
    "ParameterValueType",
    "ProviderDescriptor",
    "RecommendedModelProfile",
    "ResolvedModelConfiguration",
    "SmokeError",
    "SmokeEvidence",
    "SmokePolicy",
    "SmokeStatus",
    "VisibilityCondition",
    "build_builtin_model_plugin_registry",
    "builtin_gbdt_persistence_providers",
    "builtin_model_plugins",
]
