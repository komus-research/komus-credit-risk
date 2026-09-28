"""Read-only catalog projection of trusted model plugins.

The catalog is deliberately a boundary: it copies declarative values out of the
trusted registry and never exposes factories, providers, callables, classes, or
runtime estimator objects.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from types import MappingProxyType
from typing import Any

from .presentation import (
    ModelCatalogComposition,
    ModelPresentationRegistry,
)
from .registry import ModelPluginRegistry

PackageVersionResolver = Callable[[str], str | None]


class RuntimeAvailabilityState:
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"


def _freeze(value: Any) -> Any:
    """Detach a JSON-shaped value into an immutable structure."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("catalog metadata keys must be strings.")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("catalog metadata must be declarative JSON-shaped data.")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return deepcopy(value)


def _default_package_version(package: str) -> str | None:
    try:
        return installed_version(package)
    except PackageNotFoundError:
        return None


def _package_requirements(value: Any) -> tuple[tuple[str, str], ...]:
    """Find explicit package/version pairs and reject ambiguous declarations."""
    found: dict[str, str] = {}

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            has_package = "package" in item
            has_version = "version" in item
            if has_package or has_version:
                if not has_package or not has_version:
                    raise ValueError("RUNTIME_REQUIREMENTS_INVALID")
                package, required_version = item["package"], item["version"]
                if (
                    not isinstance(package, str)
                    or not package.strip()
                    or not isinstance(required_version, str)
                    or not required_version.strip()
                    or package in found
                ):
                    raise ValueError("RUNTIME_REQUIREMENTS_INVALID")
                found[package] = required_version
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(sorted(found.items()))


@dataclass(frozen=True, slots=True)
class CatalogCapability:
    domain: str
    support: str
    provider_id: str | None
    requirements: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "support": self.support,
            "provider_id": self.provider_id,
            "requirements": _plain(self.requirements),
        }


@dataclass(frozen=True, slots=True)
class CatalogParameter:
    parameter_path: str
    display_name_ru: str
    description_ru: str
    value_type: str
    required: bool
    nullable: bool
    editable: bool
    default_value: Any
    recommended_value: Any
    bounds: Mapping[str, int | float | bool | None]
    choices: tuple[Any, ...]
    ui_level: str
    group_id: str
    display_order: int
    visibility_condition: Mapping[str, Any] | None

    @classmethod
    def from_parameter(cls, parameter, presentation) -> CatalogParameter:
        return cls(
            parameter.parameter_path,
            presentation.display_name_ru,
            presentation.description_ru,
            parameter.value_type.value,
            parameter.required,
            parameter.nullable,
            parameter.editable,
            _freeze(parameter.default_value),
            _freeze(parameter.recommended_value),
            _freeze(
                {
                    "minimum": parameter.minimum,
                    "maximum": parameter.maximum,
                    "minimum_exclusive": parameter.minimum_exclusive,
                    "maximum_exclusive": parameter.maximum_exclusive,
                }
            ),
            tuple(_freeze(choice) for choice in parameter.choices),
            parameter.ui_level.value,
            parameter.group_id,
            parameter.display_order,
            _freeze(parameter.visibility_condition.to_dict())
            if parameter.visibility_condition is not None
            else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "display_name_ru": self.display_name_ru,
            "description_ru": self.description_ru,
            "value_type": self.value_type,
            "required": self.required,
            "nullable": self.nullable,
            "editable": self.editable,
            "default_value": _plain(self.default_value),
            "recommended_value": _plain(self.recommended_value),
            "bounds": _plain(self.bounds),
            "choices": _plain(self.choices),
            "ui_level": self.ui_level,
            "group_id": self.group_id,
            "display_order": self.display_order,
            "visibility_condition": _plain(self.visibility_condition)
            if self.visibility_condition is not None
            else None,
        }


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    model_id: str
    display_name_ru: str
    model_version: str
    adapter_version: str
    task_types: tuple[str, ...]
    description_ru: str
    state: str
    reason_code: str
    capabilities: tuple[CatalogCapability, ...]
    prepared_predictor_kinds: tuple[str, ...]
    prepared_dtype: str
    missing_values_supported: bool
    categorical_handling: str
    runtime_kind: str
    schema_id: str
    schema_version: str
    schema_hash: str
    parameters: tuple[CatalogParameter, ...]
    profile_id: str
    profile_version: str
    profile_hash: str
    runtime_requirements: Mapping[str, Any]
    plugin_contract_hash: str
    default_profile: Mapping[str, Any]

    @property
    def runnable(self) -> bool:
        """Compatibility presentation flag; availability remains authoritative."""
        return self.state == RuntimeAvailabilityState.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name_ru": self.display_name_ru,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "task_types": list(self.task_types),
            "description_ru": self.description_ru,
            "state": self.state,
            "reason_code": self.reason_code,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "input_contract": {
                "prepared_predictor_kinds": list(self.prepared_predictor_kinds),
                "prepared_dtype": self.prepared_dtype,
                "missing_values_supported": self.missing_values_supported,
                "categorical_handling": self.categorical_handling,
                "runtime_kind": self.runtime_kind,
            },
            "parameter_schema": {
                "schema_id": self.schema_id,
                "schema_version": self.schema_version,
                "schema_hash": self.schema_hash,
                "parameters": [item.to_dict() for item in self.parameters],
            },
            "recommended_profile": {
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "profile_hash": self.profile_hash,
            },
            "runtime_requirements": _plain(self.runtime_requirements),
            "plugin_contract_hash": self.plugin_contract_hash,
            "default_profile": _plain(self.default_profile),
        }


class ModelCatalogService:
    """Projects only registered trusted plugins into deterministic DTOs."""

    def __init__(
        self,
        registry: ModelPluginRegistry,
        presentation_registry: ModelPresentationRegistry,
        *,
        package_version_resolver: PackageVersionResolver | None = None,
    ) -> None:
        if not isinstance(registry, ModelPluginRegistry):
            raise TypeError("registry must be a ModelPluginRegistry.")
        if not isinstance(presentation_registry, ModelPresentationRegistry):
            raise TypeError(
                "presentation_registry must be a ModelPresentationRegistry."
            )
        self._registry = registry
        self._composition = ModelCatalogComposition.compose(
            registry, presentation_registry
        )
        self._package_version_resolver = (
            package_version_resolver or _default_package_version
        )

    def list_models(self) -> tuple[ModelCatalogEntry, ...]:
        return tuple(
            self._entry(plugin)
            for plugin in sorted(
                self._registry.list(), key=lambda item: item.spec.model_id
            )
        )

    def get(self, model_id: str) -> ModelCatalogEntry:
        return self._entry(self._registry.get(model_id))

    def _entry(self, plugin) -> ModelCatalogEntry:
        spec = plugin.spec
        state, reason_code = self._availability(spec.runtime_requirements)
        schema = plugin.parameter_schema
        profile = plugin.recommended_profile
        input_contract = plugin.input_contract
        capabilities = tuple(
            CatalogCapability(
                declaration.domain.value,
                declaration.support.value,
                declaration.provider_id,
                _freeze(declaration.requirements),
            )
            for declaration in sorted(
                plugin.capability_manifest.capabilities,
                key=lambda item: item.domain.value,
            )
        )
        parameters = tuple(
            CatalogParameter.from_parameter(
                parameter,
                self._composition.parameter(spec.model_id, parameter.parameter_path),
            )
            for parameter in sorted(
                schema.parameters,
                key=lambda item: (item.display_order, item.parameter_path),
            )
        )
        return ModelCatalogEntry(
            spec.model_id,
            spec.display_name_ru,
            spec.version,
            spec.adapter_version,
            tuple(spec.task_types),
            spec.description_ru,
            state,
            reason_code,
            capabilities,
            tuple(input_contract.prepared_predictor_kinds),
            input_contract.prepared_dtype,
            input_contract.missing_values_supported,
            input_contract.categorical_handling,
            input_contract.runtime_kind,
            schema.schema_id,
            schema.schema_version,
            schema.schema_hash,
            parameters,
            profile.profile_id,
            profile.profile_version,
            profile.profile_hash,
            _freeze(spec.runtime_requirements),
            plugin.plugin_contract_hash,
            _freeze(profile.payload),
        )

    def _availability(self, runtime_requirements: Mapping[str, Any]) -> tuple[str, str]:
        try:
            requirements = _package_requirements(runtime_requirements)
        except ValueError:
            return (
                RuntimeAvailabilityState.MISCONFIGURED,
                "RUNTIME_REQUIREMENTS_INVALID",
            )
        for package, required_version in requirements:
            actual_version = self._package_version_resolver(package)
            if actual_version is None:
                return RuntimeAvailabilityState.UNAVAILABLE, "RUNTIME_PACKAGE_MISSING"
            if actual_version != required_version:
                return (
                    RuntimeAvailabilityState.MISCONFIGURED,
                    "RUNTIME_VERSION_MISMATCH",
                )
        return RuntimeAvailabilityState.AVAILABLE, "MODEL_RUNTIME_READY"
