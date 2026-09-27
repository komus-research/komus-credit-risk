"""Trusted, declarative model-plugin contracts (MP-A).

This package is intentionally not wired into the existing experiment path yet.
"""

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
from .plugins import build_builtin_model_plugin_registry, builtin_model_plugins
from .registry import ModelPluginRegistry
from .configuration import ModelConfigurationError, ModelConfigurationMode, ModelConfigurationService, ResolvedModelConfiguration

__all__ = [
    "CapabilityDeclaration",
    "CapabilityDomain",
    "CapabilitySupport",
    "ModelCapabilityManifest",
    "ModelInputContract",
    "ModelParameter",
    "ModelParameterSchema",
    "ModelPlugin",
    "ModelPluginRegistry",
    "ModelConfigurationError", "ModelConfigurationMode", "ModelConfigurationService",
    "ParameterUiLevel",
    "ParameterValueType",
    "ProviderDescriptor",
    "RecommendedModelProfile",
    "ResolvedModelConfiguration",
    "VisibilityCondition",
    "build_builtin_model_plugin_registry",
    "builtin_model_plugins",
]
