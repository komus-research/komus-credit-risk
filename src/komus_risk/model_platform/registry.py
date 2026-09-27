"""Fail-closed registry for trusted ``ModelPlugin`` declarations."""

from __future__ import annotations

from komus_risk.model_platform.contracts import (
    CapabilityDomain,
    CapabilitySupport,
    ModelPlugin,
)


class ModelPluginRegistry:
    """Stores compatible plugin registrations without replacing ``ModelRegistry``."""

    def __init__(self) -> None:
        self._plugins: dict[str, ModelPlugin] = {}

    def register(
        self, plugin: ModelPlugin, *, registry_key: str | None = None
    ) -> ModelPlugin:
        if not isinstance(plugin, ModelPlugin):
            raise TypeError("only a trusted ModelPlugin can be registered.")
        self._validate(plugin)
        model_id = plugin.spec.model_id
        if registry_key is not None and registry_key != model_id:
            raise ValueError("registry key does not match ModelSpec model_id.")
        existing = self._plugins.get(model_id)
        if existing is not None:
            if existing.plugin_contract_hash != plugin.plugin_contract_hash:
                raise ValueError(
                    f"model_id '{model_id}' is already registered with an incompatible plugin."
                )
            return existing
        self._plugins[model_id] = plugin
        return plugin

    def get(self, model_id: str) -> ModelPlugin:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("model_id must be a non-empty string.")
        try:
            return self._plugins[model_id]
        except KeyError as error:
            raise KeyError(f"model plugin '{model_id}' is not registered.") from error

    def list(self) -> tuple[ModelPlugin, ...]:
        return tuple(self._plugins[model_id] for model_id in sorted(self._plugins))

    @staticmethod
    def _validate(plugin: ModelPlugin) -> None:
        spec = plugin.spec
        identity = (spec.model_id, spec.version, spec.adapter_version)
        if any(not item.strip() for item in identity):
            raise ValueError("plugin has an invalid model identity.")
        if (
            plugin.factory.model_id,
            plugin.factory.model_version,
            plugin.factory.adapter_version,
        ) != identity:
            raise ValueError("factory identity does not match ModelSpec.")
        for name, contract_identity in (
            (
                "parameter schema",
                (
                    plugin.parameter_schema.model_id,
                    plugin.parameter_schema.model_version,
                    plugin.parameter_schema.adapter_version,
                ),
            ),
            (
                "recommended profile",
                (
                    plugin.recommended_profile.model_id,
                    plugin.recommended_profile.model_version,
                    plugin.recommended_profile.adapter_version,
                ),
            ),
            (
                "capability manifest",
                (
                    plugin.capability_manifest.model_id,
                    plugin.capability_manifest.model_version,
                    plugin.capability_manifest.adapter_version,
                ),
            ),
            (
                "input contract",
                (
                    plugin.input_contract.model_id,
                    plugin.input_contract.model_version,
                    plugin.input_contract.adapter_version,
                ),
            ),
        ):
            if contract_identity != identity:
                raise ValueError(f"{name} identity does not match ModelSpec.")
        if plugin.recommended_profile.to_dict()["payload"] != spec.default_profile:
            raise ValueError(
                "recommended profile must exactly match the frozen ModelSpec default_profile."
            )
        plugin.parameter_schema.validate_recommended_payload(
            plugin.recommended_profile.payload
        )
        ModelPluginRegistry._validate_provider_claims(plugin)

    @staticmethod
    def _validate_provider_claims(plugin: ModelPlugin) -> None:
        manifest = plugin.capability_manifest
        persistence_required = any(
            manifest.get(domain).support is not CapabilitySupport.UNSUPPORTED
            for domain in (CapabilityDomain.PERSISTENCE, CapabilityDomain.LOADING)
        )
        explanation_required = (
            manifest.get(CapabilityDomain.LOCAL_EXPLANATION).support
            is not CapabilitySupport.UNSUPPORTED
        )
        if persistence_required and plugin.persistence_provider is None:
            raise ValueError(
                "persistence/loading capability requires a persistence provider descriptor."
            )
        if explanation_required and plugin.local_explanation_provider is None:
            raise ValueError(
                "local explanation capability requires a provider descriptor."
            )
        if (
            plugin.persistence_provider is not None
            and plugin.persistence_provider.provider_kind != "persistence"
        ):
            raise ValueError("persistence provider has an invalid provider kind.")
        if (
            plugin.local_explanation_provider is not None
            and plugin.local_explanation_provider.provider_kind != "local_explanation"
        ):
            raise ValueError("local explanation provider has an invalid provider kind.")
        for domain, descriptor in (
            (CapabilityDomain.PERSISTENCE, plugin.persistence_provider),
            (CapabilityDomain.LOADING, plugin.persistence_provider),
            (CapabilityDomain.LOCAL_EXPLANATION, plugin.local_explanation_provider),
        ):
            declaration = manifest.get(domain)
            if declaration.provider_id is not None and (
                descriptor is None or declaration.provider_id != descriptor.provider_id
            ):
                raise ValueError(
                    f"capability {domain.value} references an invalid provider identity."
                )
