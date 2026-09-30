"""Trusted, declarative model-plugin contracts (MP-A).

This package is intentionally not wired into the existing experiment path yet.
"""

from .catalog import (
    CatalogCapability,
    CatalogParameter,
    ModelCatalogEntry,
    ModelCatalogService,
    RuntimeAvailabilityState,
)
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
from .explainability import (
    BuiltinNativeExplanationProvider,
    GBDTMeanProbabilityExplanationProvider,
    ModelExplanationProvider,
    ModelExplanationProviderRegistry,
    TrustedExplanationContext,
)
from .plugins import build_builtin_model_plugin_registry, builtin_model_plugins
from .presentation import (
    ModelCatalogComposition,
    ModelParameterPresentation,
    ModelPresentationError,
    ModelPresentationProfile,
    ModelPresentationRegistry,
    builtin_model_presentation_registry,
)
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
    "CatalogCapability",
    "CatalogParameter",
    "ModelCapabilityManifest",
    "ModelCatalogEntry",
    "ModelCatalogService",
    "ModelCatalogComposition",
    "ModelConfigurationError",
    "ModelConfigurationMode",
    "ModelConfigurationRecord",
    "ModelConfigurationService",
    "ModelConfigurationSmokeTestService",
    "ModelInputContract",
    "ModelParameter",
    "ModelParameterPresentation",
    "ModelParameterSchema",
    "ModelPersistenceProvider",
    "ModelPersistenceProviderRegistry",
    "ModelExplanationProvider",
    "ModelExplanationProviderRegistry",
    "TrustedExplanationContext",
    "ModelPlugin",
    "ModelPluginRegistry",
    "ModelPresentationError",
    "ModelPresentationProfile",
    "ModelPresentationRegistry",
    "NativeGBDTPersistenceProvider",
    "BuiltinNativeExplanationProvider",
    "GBDTMeanProbabilityExplanationProvider",
    "ParameterUiLevel",
    "ParameterValueType",
    "ProviderDescriptor",
    "RecommendedModelProfile",
    "ResolvedModelConfiguration",
    "RuntimeAvailabilityState",
    "SmokeError",
    "SmokeEvidence",
    "SmokePolicy",
    "SmokeStatus",
    "VisibilityCondition",
    "build_builtin_model_plugin_registry",
    "builtin_gbdt_persistence_providers",
    "builtin_model_plugins",
    "builtin_model_presentation_registry",
]
