"""Immutable declarative contracts for trusted model plugins.

No object in this module resolves user overrides, loads a provider, or executes a
model.  It only validates metadata that trusted application code has registered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any

from komus_risk.hashing import stable_hash
from komus_risk.models.base import ModelAdapterFactory
from komus_risk.registries.model_registry import ModelSpec


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")


def _frozen_json(value: Any) -> Any:
    """Copies only explicit JSON-shaped data into an immutable representation."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings.")
        return MappingProxyType(
            {key: _frozen_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise TypeError("contract payload must contain only JSON-shaped values.")


def _plain_json(value: Any) -> Any:
    """Returns a detached plain payload for consumers which need a dict/list."""
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return deepcopy(value)


def _is_json_pointer(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith("/") or value.endswith("/"):
        return False
    segments = value[1:].split("/")
    return all(segment and _valid_pointer_segment(segment) for segment in segments)


def _valid_pointer_segment(segment: str) -> bool:
    index = 0
    while index < len(segment):
        if segment[index] == "~":
            if index + 1 == len(segment) or segment[index + 1] not in "01":
                return False
            index += 2
        else:
            index += 1
    return True


def _pointer_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for segment in path[1:].split("/"):
        segment = segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or segment not in current:
            raise KeyError(path)
        current = current[segment]
    return current


class ParameterValueType(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"


class ParameterUiLevel(str, Enum):
    BASIC = "basic"
    ADVANCED = "advanced"


@dataclass(frozen=True, slots=True)
class VisibilityCondition:
    """A deliberately small, non-executable visibility condition."""

    parameter_path: str
    equals_value: Any

    def __post_init__(self) -> None:
        if not _is_json_pointer(self.parameter_path):
            raise ValueError("visibility condition has an invalid parameter path.")
        stable_hash(self.equals_value)
        object.__setattr__(self, "equals_value", _frozen_json(self.equals_value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "equals_value": _plain_json(self.equals_value),
        }


@dataclass(frozen=True, slots=True)
class ModelParameter:
    parameter_path: str
    display_name_ru: str
    description_ru: str
    value_type: ParameterValueType
    required: bool
    nullable: bool
    editable: bool
    default_value: Any
    recommended_value: Any
    minimum: int | float | None = None
    maximum: int | float | None = None
    minimum_exclusive: bool = False
    maximum_exclusive: bool = False
    choices: tuple[Any, ...] = ()
    ui_level: ParameterUiLevel = ParameterUiLevel.ADVANCED
    group_id: str = "estimator"
    display_order: int = 0
    visibility_condition: VisibilityCondition | None = None

    def __post_init__(self) -> None:
        if not _is_json_pointer(self.parameter_path):
            raise ValueError("parameter_path must be a non-empty JSON-pointer path.")
        for name in ("display_name_ru", "description_ru", "group_id"):
            _required_text(name, getattr(self, name))
        if not isinstance(self.value_type, ParameterValueType):
            raise TypeError("value_type is unsupported.")
        if not isinstance(self.ui_level, ParameterUiLevel):
            raise TypeError("ui_level is unsupported.")
        if (
            not isinstance(self.required, bool)
            or not isinstance(self.nullable, bool)
            or not isinstance(self.editable, bool)
        ):
            raise TypeError("parameter flags must be boolean.")
        if (
            not isinstance(self.display_order, int)
            or isinstance(self.display_order, bool)
            or self.display_order < 0
        ):
            raise ValueError("display_order must be a non-negative integer.")
        choices = tuple(self.choices)
        if self.value_type is ParameterValueType.ENUM and not choices:
            raise ValueError("enum parameter requires non-empty choices.")
        if self.value_type is not ParameterValueType.ENUM and choices:
            raise ValueError("choices are allowed only for enum parameters.")
        if len({stable_hash(choice) for choice in choices}) != len(choices):
            raise ValueError("parameter choices must be unique.")
        if self.minimum is not None and (
            not isinstance(self.minimum, (int, float)) or isinstance(self.minimum, bool)
        ):
            raise ValueError("minimum must be numeric when declared.")
        if self.maximum is not None and (
            not isinstance(self.maximum, (int, float)) or isinstance(self.maximum, bool)
        ):
            raise ValueError("maximum must be numeric when declared.")
        if (
            self.minimum is not None
            and self.maximum is not None
            and (
                self.minimum > self.maximum
                or (
                    self.minimum == self.maximum
                    and (self.minimum_exclusive or self.maximum_exclusive)
                )
            )
        ):
            raise ValueError("parameter bounds are invalid.")
        if (self.minimum_exclusive and self.minimum is None) or (
            self.maximum_exclusive and self.maximum is None
        ):
            raise ValueError("exclusive bound requires its corresponding bound.")
        self.validate_value(self.default_value, field_name="default_value")
        self.validate_value(self.recommended_value, field_name="recommended_value")
        object.__setattr__(self, "default_value", _frozen_json(self.default_value))
        object.__setattr__(
            self, "recommended_value", _frozen_json(self.recommended_value)
        )
        object.__setattr__(
            self, "choices", tuple(_frozen_json(value) for value in choices)
        )

    def validate_value(self, value: Any, *, field_name: str = "value") -> None:
        if value is None:
            if not self.nullable:
                raise ValueError(f"{field_name} cannot be null.")
            return
        if self.value_type is ParameterValueType.INTEGER:
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif self.value_type is ParameterValueType.FLOAT:
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif self.value_type is ParameterValueType.BOOLEAN:
            valid = isinstance(value, bool)
        else:
            valid = any(value == choice for choice in self.choices)
        if not valid:
            raise ValueError(f"{field_name} has an invalid value type or choice.")
        if self.minimum is not None and (
            value < self.minimum or (self.minimum_exclusive and value == self.minimum)
        ):
            raise ValueError(f"{field_name} is below the minimum.")
        if self.maximum is not None and (
            value > self.maximum or (self.maximum_exclusive and value == self.maximum)
        ):
            raise ValueError(f"{field_name} is above the maximum.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "display_name_ru": self.display_name_ru,
            "description_ru": self.description_ru,
            "value_type": self.value_type.value,
            "required": self.required,
            "nullable": self.nullable,
            "editable": self.editable,
            "default_value": _plain_json(self.default_value),
            "recommended_value": _plain_json(self.recommended_value),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "minimum_exclusive": self.minimum_exclusive,
            "maximum_exclusive": self.maximum_exclusive,
            "choices": [_plain_json(value) for value in self.choices],
            "ui_level": self.ui_level.value,
            "group_id": self.group_id,
            "display_order": self.display_order,
            "visibility_condition": self.visibility_condition.to_dict()
            if self.visibility_condition
            else None,
        }


@dataclass(frozen=True, slots=True)
class ModelParameterSchema:
    schema_id: str
    schema_version: str
    model_id: str
    model_version: str
    adapter_version: str
    parameters: tuple[ModelParameter, ...]

    def __post_init__(self) -> None:
        for name in (
            "schema_id",
            "schema_version",
            "model_id",
            "model_version",
            "adapter_version",
        ):
            _required_text(name, getattr(self, name))
        parameters = tuple(self.parameters)
        if not parameters:
            raise ValueError("parameter schema must contain at least one parameter.")
        if len({item.parameter_path for item in parameters}) != len(parameters):
            raise ValueError("parameter schema contains duplicate paths.")
        if any(not isinstance(item, ModelParameter) for item in parameters):
            raise TypeError("parameter schema contains an invalid parameter.")
        object.__setattr__(self, "parameters", parameters)

    @property
    def schema_hash(self) -> str:
        return stable_hash(self.to_dict())

    def validate_recommended_payload(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError("recommended profile payload must be a mapping.")
        for parameter in self.parameters:
            try:
                value = _pointer_value(payload, parameter.parameter_path)
            except KeyError:
                raise ValueError(
                    f"recommended profile misses parameter {parameter.parameter_path}."
                ) from None
            parameter.validate_value(
                value, field_name=f"recommended profile {parameter.parameter_path}"
            )
            if stable_hash(value) != stable_hash(parameter.recommended_value):
                raise ValueError(
                    f"recommended profile value does not match schema at {parameter.parameter_path}."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
        }


@dataclass(frozen=True, slots=True)
class RecommendedModelProfile:
    profile_id: str
    profile_version: str
    model_id: str
    model_version: str
    adapter_version: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "profile_version",
            "model_id",
            "model_version",
            "adapter_version",
        ):
            _required_text(name, getattr(self, name))
        if not isinstance(self.payload, Mapping):
            raise TypeError("recommended profile payload must be a mapping.")
        object.__setattr__(self, "payload", _frozen_json(self.payload))

    @property
    def profile_hash(self) -> str:
        return stable_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "payload": _plain_json(self.payload),
        }


class CapabilityDomain(str, Enum):
    TRAINING = "training"
    CONFIGURATION = "configuration"
    PERSISTENCE = "persistence"
    LOADING = "loading"
    TARGETLESS_INFERENCE = "targetless_inference"
    LOCAL_EXPLANATION = "local_explanation"
    SMOKE_TEST = "smoke_test"


class CapabilitySupport(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONDITIONAL = "CONDITIONAL"


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    provider_version: str
    provider_kind: str
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        for name in ("provider_id", "provider_version", "provider_kind"):
            _required_text(name, getattr(self, name))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("provider metadata must be a mapping.")
        object.__setattr__(self, "metadata", _frozen_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_kind": self.provider_kind,
            "metadata": _plain_json(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    domain: CapabilityDomain
    support: CapabilitySupport
    provider_id: str | None = None
    requirements: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.domain, CapabilityDomain) or not isinstance(
            self.support, CapabilitySupport
        ):
            raise TypeError("capability domain or support is malformed.")
        if self.provider_id is not None:
            _required_text("provider_id", self.provider_id)
        if not isinstance(self.requirements, Mapping):
            raise TypeError("capability requirements must be a mapping.")
        object.__setattr__(self, "requirements", _frozen_json(self.requirements))

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "support": self.support.value,
            "provider_id": self.provider_id,
            "requirements": _plain_json(self.requirements),
        }


@dataclass(frozen=True, slots=True)
class ModelCapabilityManifest:
    model_id: str
    model_version: str
    adapter_version: str
    capabilities: tuple[CapabilityDeclaration, ...]

    def __post_init__(self) -> None:
        for name in ("model_id", "model_version", "adapter_version"):
            _required_text(name, getattr(self, name))
        capabilities = tuple(self.capabilities)
        if len(capabilities) != len(CapabilityDomain) or {
            item.domain for item in capabilities
        } != set(CapabilityDomain):
            raise ValueError(
                "capability manifest must declare every domain exactly once."
            )
        if any(not isinstance(item, CapabilityDeclaration) for item in capabilities):
            raise TypeError("capability manifest contains an invalid declaration.")
        object.__setattr__(self, "capabilities", capabilities)

    def get(self, domain: CapabilityDomain) -> CapabilityDeclaration:
        return next(item for item in self.capabilities if item.domain is domain)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "capabilities": [
                item.to_dict()
                for item in sorted(
                    self.capabilities, key=lambda item: item.domain.value
                )
            ],
        }


@dataclass(frozen=True, slots=True)
class ModelInputContract:
    model_id: str
    model_version: str
    adapter_version: str
    prepared_predictor_kinds: tuple[str, ...]
    prepared_dtype: str
    missing_values_supported: bool
    categorical_handling: str
    runtime_kind: str

    def __post_init__(self) -> None:
        for name in (
            "model_id",
            "model_version",
            "adapter_version",
            "prepared_dtype",
            "categorical_handling",
            "runtime_kind",
        ):
            _required_text(name, getattr(self, name))
        kinds = tuple(self.prepared_predictor_kinds)
        if not kinds or any(
            not isinstance(kind, str) or not kind.strip() for kind in kinds
        ):
            raise ValueError(
                "input contract requires at least one declared predictor kind."
            )
        if not isinstance(self.missing_values_supported, bool):
            raise TypeError("missing_values_supported must be boolean.")
        object.__setattr__(self, "prepared_predictor_kinds", kinds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "prepared_predictor_kinds": list(self.prepared_predictor_kinds),
            "prepared_dtype": self.prepared_dtype,
            "missing_values_supported": self.missing_values_supported,
            "categorical_handling": self.categorical_handling,
            "runtime_kind": self.runtime_kind,
        }


@dataclass(frozen=True, slots=True)
class ModelPlugin:
    """One trusted registration unit; user-supplied plugins are intentionally unsupported."""

    spec: ModelSpec
    parameter_schema: ModelParameterSchema
    recommended_profile: RecommendedModelProfile
    factory: ModelAdapterFactory
    capability_manifest: ModelCapabilityManifest
    input_contract: ModelInputContract
    validator_id: str | None = None
    configuration_validator: Callable[[Mapping[str, Any]], None] | None = None
    persistence_provider: ProviderDescriptor | None = None
    local_explanation_provider: ProviderDescriptor | None = None
    smoke_test_metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.spec, ModelSpec) or not isinstance(
            self.parameter_schema, ModelParameterSchema
        ):
            raise TypeError("plugin spec and parameter schema are required contracts.")
        if not isinstance(
            self.recommended_profile, RecommendedModelProfile
        ) or not isinstance(self.capability_manifest, ModelCapabilityManifest):
            raise TypeError("plugin profile and capabilities are required contracts.")
        if not isinstance(self.input_contract, ModelInputContract) or not isinstance(
            self.factory, ModelAdapterFactory
        ):
            raise TypeError("plugin input contract and factory are required.")
        if self.configuration_validator is None:
            if self.validator_id is not None:
                raise ValueError(
                    "validator_id requires a trusted configuration validator."
                )
        elif not callable(self.configuration_validator):
            raise TypeError("configuration_validator must be callable.")
        elif (
            not isinstance(self.validator_id, str)
            or not self.validator_id
            or self.validator_id != self.validator_id.strip()
        ):
            raise ValueError(
                "trusted configuration validator requires a normalized stable validator_id."
            )
        if not isinstance(self.smoke_test_metadata, Mapping):
            raise TypeError("smoke_test_metadata must be a mapping.")
        object.__setattr__(
            self, "smoke_test_metadata", _frozen_json(self.smoke_test_metadata)
        )

    @property
    def plugin_contract_hash(self) -> str:
        return stable_hash(self.declarative_payload())

    def declarative_payload(self) -> dict[str, Any]:
        """Callable implementation details are deliberately excluded from identity."""
        return {
            "spec": self.spec.to_dict(),
            "parameter_schema": self.parameter_schema.to_dict(),
            "recommended_profile": self.recommended_profile.to_dict(),
            "factory_identity": {
                "model_id": self.factory.model_id,
                "model_version": self.factory.model_version,
                "adapter_version": self.factory.adapter_version,
            },
            "capability_manifest": self.capability_manifest.to_dict(),
            "input_contract": self.input_contract.to_dict(),
            "validator_id": self.validator_id,
            "persistence_provider": self.persistence_provider.to_dict()
            if self.persistence_provider
            else None,
            "local_explanation_provider": self.local_explanation_provider.to_dict()
            if self.local_explanation_provider
            else None,
            "smoke_test_metadata": _plain_json(self.smoke_test_metadata),
        }
