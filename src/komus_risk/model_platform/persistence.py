"""Trusted executable persistence providers for ModelVersion V2.

Providers are runtime code registered by the composition root.  They are never
constructed from a user payload, class name, or import path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from komus_risk.models.base import BinaryClassifierAdapter
from komus_risk.models.gbdt.native import (
    NativePredictor,
    load_native_predictor,
    native_model_files,
    save_native_model,
    validate_fitted_adapter_recipe,
)

from .contracts import ProviderDescriptor


class ModelPersistenceProvider(Protocol):
    """Small trusted boundary used by the generic ModelVersionStore."""

    descriptor: ProviderDescriptor
    model_id: str
    model_version: str
    adapter_version: str

    def native_files(self) -> tuple[str, ...]: ...

    def validate_fitted(
        self, adapter: BinaryClassifierAdapter, *, parameters: dict, seed: int
    ) -> None: ...

    def save(
        self, adapter: BinaryClassifierAdapter, directory: Path
    ) -> tuple[str, ...]: ...

    def load(
        self, directory: Path, feature_columns: tuple[str, ...]
    ) -> NativePredictor: ...


@dataclass(frozen=True, slots=True)
class NativeGBDTPersistenceProvider:
    """One fixed native provider per accepted GBDT integration."""

    descriptor: ProviderDescriptor
    model_id: str
    model_version: str
    adapter_version: str

    def __post_init__(self) -> None:
        if self.descriptor.provider_kind != "persistence":
            raise ValueError("Persistence provider has an invalid provider kind.")
        # The declaration is closed over by trusted code, so validate it once.
        native_model_files(self.model_id)

    def native_files(self) -> tuple[str, ...]:
        return native_model_files(self.model_id)

    def validate_fitted(
        self, adapter: BinaryClassifierAdapter, *, parameters: dict, seed: int
    ) -> None:
        validate_fitted_adapter_recipe(self.model_id, adapter, parameters, seed)

    def save(
        self, adapter: BinaryClassifierAdapter, directory: Path
    ) -> tuple[str, ...]:
        names = save_native_model(self.model_id, adapter, directory)
        if names != self.native_files():
            raise ValueError(
                "Persistence provider wrote an undeclared native file set."
            )
        return names

    def load(
        self, directory: Path, feature_columns: tuple[str, ...]
    ) -> NativePredictor:
        return load_native_predictor(self.model_id, directory, feature_columns)


class ModelPersistenceProviderRegistry:
    """Fail-closed registry of executable providers supplied by trusted code."""

    def __init__(self, providers: Iterable[ModelPersistenceProvider] = ()) -> None:
        self._providers: dict[str, ModelPersistenceProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ModelPersistenceProvider) -> ModelPersistenceProvider:
        descriptor = getattr(provider, "descriptor", None)
        if (
            not isinstance(descriptor, ProviderDescriptor)
            or descriptor.provider_kind != "persistence"
        ):
            raise TypeError("Only a trusted persistence provider can be registered.")
        identity = (
            getattr(provider, "model_id", None),
            getattr(provider, "model_version", None),
            getattr(provider, "adapter_version", None),
        )
        if not all(isinstance(value, str) and value for value in identity):
            raise ValueError("Persistence provider has an invalid model identity.")
        names = provider.native_files()
        if (
            not names
            or len(names) != len(set(names))
            or any(
                not isinstance(name, str) or "/" in name or "\\" in name
                for name in names
            )
        ):
            raise ValueError("Persistence provider native file declaration is invalid.")
        existing = self._providers.get(descriptor.provider_id)
        if existing is not None:
            if (
                existing.descriptor != descriptor
                or (existing.model_id, existing.model_version, existing.adapter_version)
                != identity
                or existing.native_files() != names
            ):
                raise ValueError(
                    "Persistence provider is already registered incompatibly."
                )
            return existing
        self._providers[descriptor.provider_id] = provider
        return provider

    def get(self, provider_id: str) -> ModelPersistenceProvider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError("Trusted persistence provider is not registered.") from error

    def validate_plugin_provider(self, plugin) -> ModelPersistenceProvider:
        descriptor = plugin.persistence_provider
        if descriptor is None:
            raise ValueError("Plugin has no persistence provider descriptor.")
        provider = self.get(descriptor.provider_id)
        if provider.descriptor != descriptor:
            raise ValueError(
                "Plugin persistence provider identity does not match executable provider."
            )
        if (provider.model_id, provider.model_version, provider.adapter_version) != (
            plugin.spec.model_id,
            plugin.spec.version,
            plugin.spec.adapter_version,
        ):
            raise ValueError(
                "Plugin model identity is incompatible with persistence provider."
            )
        return provider


def builtin_gbdt_persistence_providers(
    plugins: Iterable,
) -> ModelPersistenceProviderRegistry:
    """Build executable providers directly from the four trusted plugin descriptors."""
    providers = []
    for plugin in plugins:
        descriptor = plugin.persistence_provider
        if descriptor is None:
            continue
        providers.append(
            NativeGBDTPersistenceProvider(
                descriptor,
                plugin.spec.model_id,
                plugin.spec.version,
                plugin.spec.adapter_version,
            )
        )
    return ModelPersistenceProviderRegistry(providers)
