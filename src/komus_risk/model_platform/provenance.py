"""Immutable, trusted provenance for resolved model configurations (MP-C)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from komus_risk.hashing import stable_hash

from .configuration import ResolvedModelConfiguration
from .contracts import ModelPlugin, _frozen_json, _plain_json


@dataclass(frozen=True, slots=True)
class ModelConfigurationRecord:
    """Serializable evidence derived only from a trusted plugin and resolution."""

    record_schema_version: str
    model_id: str
    model_version: str
    adapter_version: str
    plugin_contract_hash: str
    schema_id: str
    schema_version: str
    schema_hash: str
    recommended_profile_id: str
    recommended_profile_hash: str
    mode: str
    user_overrides: Mapping[str, Any]
    resolved_parameters: Mapping[str, Any]
    resolved_configuration_hash: str
    configuration_record_id: str

    def __post_init__(self) -> None:
        if self.record_schema_version != "1":
            raise ValueError("Unsupported model configuration record schema.")
        for field in (
            "model_id",
            "model_version",
            "adapter_version",
            "plugin_contract_hash",
            "schema_id",
            "schema_version",
            "schema_hash",
            "recommended_profile_id",
            "recommended_profile_hash",
            "mode",
            "resolved_configuration_hash",
            "configuration_record_id",
        ):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise ValueError(
                    "Model configuration record contains an invalid identity."
                )
        object.__setattr__(self, "user_overrides", _frozen_json(self.user_overrides))
        object.__setattr__(
            self, "resolved_parameters", _frozen_json(self.resolved_parameters)
        )
        if self.configuration_record_id != stable_hash(self._identity_payload()):
            raise ValueError("Model configuration record identity is invalid.")

    @classmethod
    def from_resolved(
        cls, resolved: ResolvedModelConfiguration, plugin: ModelPlugin
    ) -> ModelConfigurationRecord:
        if not isinstance(resolved, ResolvedModelConfiguration) or not isinstance(
            plugin, ModelPlugin
        ):
            raise TypeError("Resolved configuration and trusted plugin are required.")
        expected = (
            plugin.spec.model_id,
            plugin.spec.version,
            plugin.spec.adapter_version,
            plugin.parameter_schema.schema_id,
            plugin.parameter_schema.schema_version,
            plugin.parameter_schema.schema_hash,
            plugin.recommended_profile.profile_id,
            plugin.recommended_profile.profile_hash,
        )
        actual = (
            resolved.model_id,
            resolved.model_version,
            resolved.adapter_version,
            resolved.schema_id,
            resolved.schema_version,
            resolved.schema_hash,
            resolved.recommended_profile_id,
            resolved.recommended_profile_hash,
        )
        if actual != expected:
            raise ValueError(
                "Resolved configuration is incompatible with trusted plugin identity."
            )
        behavioral_hash = stable_hash(
            {
                "model_id": plugin.spec.model_id,
                "model_version": plugin.spec.version,
                "adapter_version": plugin.spec.adapter_version,
                "schema_hash": plugin.parameter_schema.schema_hash,
                "resolved_parameters": resolved.resolved_parameters_dict(),
            }
        )
        if resolved.resolved_configuration_hash != behavioral_hash:
            raise ValueError("Resolved configuration behavioral identity is invalid.")
        payload = {
            "record_schema_version": "1",
            "model_id": resolved.model_id,
            "model_version": resolved.model_version,
            "adapter_version": resolved.adapter_version,
            "plugin_contract_hash": plugin.plugin_contract_hash,
            "schema_id": resolved.schema_id,
            "schema_version": resolved.schema_version,
            "schema_hash": resolved.schema_hash,
            "recommended_profile_id": resolved.recommended_profile_id,
            "recommended_profile_hash": resolved.recommended_profile_hash,
            "mode": resolved.mode.value,
            "user_overrides": _plain_json(resolved.user_overrides),
            "resolved_parameters": resolved.resolved_parameters_dict(),
            "resolved_configuration_hash": resolved.resolved_configuration_hash,
        }
        return cls(**payload, configuration_record_id=stable_hash(payload))

    def _identity_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("configuration_record_id")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_schema_version": self.record_schema_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "adapter_version": self.adapter_version,
            "plugin_contract_hash": self.plugin_contract_hash,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "recommended_profile_id": self.recommended_profile_id,
            "recommended_profile_hash": self.recommended_profile_hash,
            "mode": self.mode,
            "user_overrides": _plain_json(self.user_overrides),
            "resolved_parameters": _plain_json(self.resolved_parameters),
            "resolved_configuration_hash": self.resolved_configuration_hash,
            "configuration_record_id": self.configuration_record_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModelConfigurationRecord:
        if not isinstance(value, Mapping):
            raise TypeError("Model configuration record must be an object.")
        return cls(**dict(value))
