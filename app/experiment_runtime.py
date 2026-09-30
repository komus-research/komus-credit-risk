"""Shared model registry and factory composition for experiment runtimes."""

from __future__ import annotations

from dataclasses import dataclass

from komus_risk.model_platform import ModelPluginRegistry, build_builtin_model_plugin_registry
from komus_risk.models import ModelAdapterFactory
from komus_risk.registries import ModelRegistry


@dataclass(frozen=True, slots=True)
class ExperimentModelRuntime:
    plugin_registry: ModelPluginRegistry
    model_registry: ModelRegistry
    model_factories: dict[str, ModelAdapterFactory]


def compose_experiment_models() -> ExperimentModelRuntime:
    """Build the canonical plugin registry, scientific model registry, and factories."""
    plugins = build_builtin_model_plugin_registry()
    entries = plugins.list()
    registry = ModelRegistry()
    for plugin in entries:
        registry.register(plugin.spec)
    return ExperimentModelRuntime(
        plugin_registry=plugins,
        model_registry=registry,
        model_factories={plugin.spec.model_id: plugin.factory for plugin in entries},
    )
