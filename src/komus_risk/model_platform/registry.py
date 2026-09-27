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
        persistence_declarations = tuple(
            manifest.get(domain)
            for domain in (CapabilityDomain.PERSISTENCE, CapabilityDomain.LOADING)
        )
        ModelPluginRegistry._validate_shared_provider_claims(
            declarations=persistence_declarations,
            descriptor=plugin.persistence_provider,
            expected_kind="persistence",
            capability_label="persistence/loading",
        )
        ModelPluginRegistry._validate_single_provider_claim(
            declaration=manifest.get(CapabilityDomain.LOCAL_EXPLANATION),
            descriptor=plugin.local_explanation_provider,
            expected_kind="local_explanation",
            capability_label="local explanation",
        )

    @staticmethod
    def _validate_shared_provider_claims(
        *, declarations, descriptor, expected_kind: str, capability_label: str
    ) -> None:
        active = tuple(
            declaration
            for declaration in declarations
            if declaration.support is not CapabilitySupport.UNSUPPORTED
        )
        if active and descriptor is None:
            raise ValueError(
                f"{capability_label} capability requires a provider descriptor."
            )
        if not active and descriptor is not None:
            raise ValueError(
                f"unsupported {capability_label} capability cannot declare a provider."
            )
        if descriptor is None:
            return
        if descriptor.provider_kind != expected_kind:
            raise ValueError(
                f"{capability_label} provider has an invalid provider kind."
            )
        for declaration in declarations:
            if declaration.support is CapabilitySupport.UNSUPPORTED:
                if declaration.provider_id is not None:
                    raise ValueError(
                        f"unsupported {capability_label} capability cannot declare provider_id."
                    )
            elif declaration.provider_id != descriptor.provider_id:
                raise ValueError(
                    f"{capability_label} capability references an invalid provider identity."
                )

    @staticmethod
    def _validate_single_provider_claim(
        *, declaration, descriptor, expected_kind: str, capability_label: str
    ) -> None:
        ModelPluginRegistry._validate_shared_provider_claims(
            declarations=(declaration,),
            descriptor=descriptor,
            expected_kind=expected_kind,
            capability_label=capability_label,
        )
