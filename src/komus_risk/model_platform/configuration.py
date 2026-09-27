"""Backend-authoritative resolution of trusted model configuration."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any

from komus_risk.hashing import stable_hash

from .contracts import ModelParameter, ParameterValueType, _plain_json
from .registry import ModelPluginRegistry


class ModelConfigurationMode(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    ADVANCED = "ADVANCED"


class ModelConfigurationError(ValueError):
    """Stable application error boundary for rejected user configuration."""

    def __init__(self, code: str, path: str | None = None) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}{f': {path}' if path else ''}")


@dataclass(frozen=True, slots=True)
class ResolvedModelConfiguration:
    model_id: str
    model_version: str
    adapter_version: str
    schema_id: str
    schema_version: str
    schema_hash: str
    recommended_profile_id: str
    recommended_profile_hash: str
    mode: ModelConfigurationMode
    user_overrides: Mapping[str, Any]
    resolved_parameters: Mapping[str, Any]
    resolved_configuration_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_overrides", _freeze_mapping(self.user_overrides))
        object.__setattr__(
            self, "resolved_parameters", _freeze_mapping(self.resolved_parameters)
        )

    def resolved_parameters_dict(self) -> dict[str, Any]:
        return _plain_json(self.resolved_parameters)


class ModelConfigurationService:
    """Resolve sparse values only against schemas registered by trusted code."""

    def __init__(self, plugin_registry: ModelPluginRegistry) -> None:
        if not isinstance(plugin_registry, ModelPluginRegistry):
            raise TypeError("plugin_registry must be a ModelPluginRegistry.")
        self._plugin_registry = plugin_registry

    def resolve(
        self,
        *,
        model_id: str,
        mode: ModelConfigurationMode | str,
        user_overrides: Mapping[str, Any] | None = None,
    ) -> ResolvedModelConfiguration:
        try:
            plugin = self._plugin_registry.get(model_id)
        except (KeyError, ValueError) as error:
            raise ModelConfigurationError("UNKNOWN_MODEL") from error
        resolved_mode = self._mode(mode)
        overrides = self._overrides(user_overrides)
        if resolved_mode is ModelConfigurationMode.RECOMMENDED and overrides:
            raise ModelConfigurationError("LOCKED_PARAMETER")
        parameters = _plain_json(plugin.recommended_profile.payload)
        schema_by_path = {
            parameter.parameter_path: parameter
            for parameter in plugin.parameter_schema.parameters
        }
        normalized: dict[str, Any] = {}
        for raw_path, value in overrides.items():
            path = _normalize_path(raw_path)
            if path in normalized:
                raise ModelConfigurationError("INVALID_NESTED_PATH", path)
            parameter = schema_by_path.get(path)
            if parameter is None:
                raise ModelConfigurationError(
                    "INVALID_NESTED_PATH"
                    if _has_missing_parent(parameters, path)
                    else "UNKNOWN_PARAMETER",
                    path,
                )
            if not parameter.editable:
                raise ModelConfigurationError("LOCKED_PARAMETER", path)
            self._validate_value(parameter, value)
            normalized[path] = deepcopy(value)
        for path, value in normalized.items():
            _set_pointer(parameters, path, value)
        for path in normalized:
            condition = schema_by_path[path].visibility_condition
            if (
                condition is not None
                and _get_pointer(parameters, condition.parameter_path)
                != condition.equals_value
            ):
                raise ModelConfigurationError("DEPENDENCY_NOT_SATISFIED", path)
        try:
            if plugin.configuration_validator is not None:
                plugin.configuration_validator(deepcopy(parameters))
        except ModelConfigurationError:
            raise
        except Exception as error:
            raise ModelConfigurationError("CROSS_PARAMETER_CONFLICT") from error
        self._validate_complete(plugin, parameters)
        behavioral_identity = {
            "model_id": plugin.spec.model_id,
            "model_version": plugin.spec.version,
            "adapter_version": plugin.spec.adapter_version,
            "schema_hash": plugin.parameter_schema.schema_hash,
            "resolved_parameters": parameters,
        }
        profile = plugin.recommended_profile
        return ResolvedModelConfiguration(
            model_id=plugin.spec.model_id,
            model_version=plugin.spec.version,
            adapter_version=plugin.spec.adapter_version,
            schema_id=plugin.parameter_schema.schema_id,
            schema_version=plugin.parameter_schema.schema_version,
            schema_hash=plugin.parameter_schema.schema_hash,
            recommended_profile_id=profile.profile_id,
            recommended_profile_hash=profile.profile_hash,
            mode=resolved_mode,
            user_overrides=normalized,
            resolved_parameters=parameters,
            resolved_configuration_hash=stable_hash(behavioral_identity),
        )

    @staticmethod
    def _mode(value: ModelConfigurationMode | str) -> ModelConfigurationMode:
        try:
            return (
                value
                if isinstance(value, ModelConfigurationMode)
                else ModelConfigurationMode(value)
            )
        except (TypeError, ValueError) as error:
            raise ModelConfigurationError("PLUGIN_CONFIGURATION_INVALID") from error

    @staticmethod
    def _overrides(value: Mapping[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise ModelConfigurationError("PLUGIN_CONFIGURATION_INVALID")
        return dict(value)

    @staticmethod
    def _validate_value(parameter: ModelParameter, value: Any) -> None:
        if value is None:
            if not parameter.nullable:
                raise ModelConfigurationError(
                    "NULL_NOT_ALLOWED", parameter.parameter_path
                )
            return
        if parameter.value_type is ParameterValueType.INTEGER:
            correct = isinstance(value, int) and not isinstance(value, bool)
        elif parameter.value_type is ParameterValueType.FLOAT:
            correct = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif parameter.value_type is ParameterValueType.BOOLEAN:
            correct = isinstance(value, bool)
        else:
            correct = any(value == choice for choice in parameter.choices)
            if not correct:
                raise ModelConfigurationError("INVALID_ENUM", parameter.parameter_path)
        if not correct:
            raise ModelConfigurationError("WRONG_TYPE", parameter.parameter_path)
        if parameter.minimum is not None and (
            value < parameter.minimum
            or (parameter.minimum_exclusive and value == parameter.minimum)
        ):
            raise ModelConfigurationError("VALUE_BELOW_MIN", parameter.parameter_path)
        if parameter.maximum is not None and (
            value > parameter.maximum
            or (parameter.maximum_exclusive and value == parameter.maximum)
        ):
            raise ModelConfigurationError("VALUE_ABOVE_MAX", parameter.parameter_path)

    @staticmethod
    def _validate_complete(plugin, parameters: Mapping[str, Any]) -> None:
        for parameter in plugin.parameter_schema.parameters:
            try:
                value = _get_pointer(parameters, parameter.parameter_path)
            except KeyError as error:
                if parameter.required:
                    raise ModelConfigurationError(
                        "MISSING_REQUIRED_PARAMETER", parameter.parameter_path
                    ) from error
                continue
            ModelConfigurationService._validate_value(parameter, value)


def _normalize_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or path.endswith("/"):
        raise ModelConfigurationError("INVALID_NESTED_PATH")
    parts = path[1:].split("/")
    if not parts or any(not part for part in parts):
        raise ModelConfigurationError("INVALID_NESTED_PATH", path)
    decoded: list[str] = []
    for part in parts:
        index = 0
        while index < len(part):
            if part[index] == "~":
                if index + 1 == len(part) or part[index + 1] not in "01":
                    raise ModelConfigurationError("INVALID_NESTED_PATH", path)
                index += 2
            else:
                index += 1
        decoded.append(part.replace("~1", "/").replace("~0", "~"))
    return "/" + "/".join(
        item.replace("~", "~0").replace("/", "~1") for item in decoded
    )


def _get_pointer(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or key not in current:
            raise KeyError(path)
        current = current[key]
    return current


def _set_pointer(payload: dict[str, Any], path: str, value: Any) -> None:
    current: dict[str, Any] = payload
    parts = path[1:].split("/")
    for part in parts[:-1]:
        key = part.replace("~1", "/").replace("~0", "~")
        child = current.get(key)
        if not isinstance(child, dict):
            raise ModelConfigurationError("INVALID_NESTED_PATH", path)
        current = child
    key = parts[-1].replace("~1", "/").replace("~0", "~")
    if key not in current:
        raise ModelConfigurationError("INVALID_NESTED_PATH", path)
    current[key] = value


def _has_missing_parent(payload: Mapping[str, Any], path: str) -> bool:
    if len(path[1:].split("/")) == 1:
        return False
    try:
        _get_pointer(payload, "/" + "/".join(path[1:].split("/")[:-1]))
    except KeyError:
        return True
    return False


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    from types import MappingProxyType

    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({key: freeze(value) for key, value in item.items()})
        if isinstance(item, list):
            return tuple(freeze(value) for value in item)
        return deepcopy(item)

    return MappingProxyType({key: freeze(item) for key, item in value.items()})
