"""YAML configuration and composition boundary for external result interpretation."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from komus_risk.application import RedactedV1OutboundPolicy, ResultInterpreterRuntimeConfiguration
from komus_risk.application.result_interpreter_prompts import (
    ResultInterpreterPromptLoader,
    ResultInterpreterPromptsError,
)
from komus_risk.integrations.openai_result_interpreter import OpenAIResultInterpreterClient


_ALLOWED_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high"})


class _LegacyConfigConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResultInterpreterSettings:
    """Validated non-secret settings loaded from one YAML file."""

    enabled: bool
    external_data_policy: str
    provider: str
    model: str
    api_key_env: str
    reasoning_effort: str
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ResultInterpreterRuntime:
    configuration: ResultInterpreterRuntimeConfiguration
    client: Any | None
    outbound_policy: RedactedV1OutboundPolicy | None
    prompt_loader: ResultInterpreterPromptLoader
    settings: ResultInterpreterSettings | None


def compose_result_interpreter_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
    factories: Mapping[str, Callable[[str, str], Any]] | None = None,
    config_path: str | Path | None = None,
) -> ResultInterpreterRuntime:
    """Use YAML in normal runtime; explicit environment input remains a legacy test/compatibility path."""
    legacy_environment_mode = environment is not None
    if environment is None:
        _load_local_dotenv()
        environment = os.environ

    loader = ResultInterpreterPromptLoader()
    try:
        settings = (
            _load_legacy_environment_settings(environment)
            if legacy_environment_mode
            else _load_settings(config_path)
        )
    except _LegacyConfigConflict:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode="INVALID",
                configuration_error="CONFIG_CONFLICT",
            ),
            None,
            None,
            loader,
            None,
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError, TypeError):
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode="INVALID",
                configuration_error="RESULT_INTERPRETER_CONFIG_INVALID",
            ),
            None,
            None,
            loader,
            None,
        )

    if not settings.enabled:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration.disabled(),
            None,
            None,
            loader,
            settings,
        )
    if settings.external_data_policy != "REDACTED_V1":
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode="INVALID",
                configuration_error="EXTERNAL_DATA_POLICY_INVALID",
            ),
            None,
            None,
            loader,
            settings,
        )

    if not settings.provider:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode=settings.external_data_policy,
            ),
            None,
            None,
            loader,
            settings,
        )

    provider_registry = dict(factories or {})
    if factories is None and settings.provider == "openai":
        factory: Callable[..., Any] | None = _openai_factory
        factory_uses_settings = True
    else:
        factory = provider_registry.get(settings.provider)
        factory_uses_settings = False
    if factory is None:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode=settings.external_data_policy,
                provider_configured=True,
            ),
            None,
            None,
            loader,
            settings,
        )
    if not settings.model:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode=settings.external_data_policy,
                provider_configured=True,
                provider_registered=True,
            ),
            None,
            None,
            loader,
            settings,
        )

    credential = _secret(settings.api_key_env, secrets if secrets is not None else {}, environment)
    if not credential:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode=settings.external_data_policy,
                provider_configured=True,
                provider_registered=True,
                model_configured=True,
            ),
            None,
            None,
            loader,
            settings,
        )

    try:
        for role in ("sales_manager", "credit_controller", "lawyer", "information_security"):
            loader.load(role)
    except ResultInterpreterPromptsError as error:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode=settings.external_data_policy,
                provider_configured=True,
                provider_registered=True,
                model_configured=True,
                credentials_configured=True,
                prompts_configured=False,
                configuration_error=error.code,
            ),
            None,
            None,
            loader,
            settings,
        )

    try:
        client = (
            factory(settings, credential)
            if factory_uses_settings
            else factory(settings.model, credential)
        )
    except Exception:
        return ResultInterpreterRuntime(
            ResultInterpreterRuntimeConfiguration(
                policy_mode=settings.external_data_policy,
                provider_configured=True,
                provider_registered=True,
                model_configured=True,
                credentials_configured=True,
                configuration_error="RESULT_INTERPRETER_PROVIDER_INVALID",
            ),
            None,
            None,
            loader,
            settings,
        )

    return ResultInterpreterRuntime(
        ResultInterpreterRuntimeConfiguration(
            policy_mode=settings.external_data_policy,
            provider_configured=True,
            provider_registered=True,
            model_configured=True,
            credentials_configured=True,
        ),
        client,
        RedactedV1OutboundPolicy(),
        loader,
        settings,
    )


def _load_legacy_environment_settings(environment: Mapping[str, str]) -> ResultInterpreterSettings:
    """Backward-compatible non-production path for old AXION/KOMUS environment tests."""
    policy, conflict = _legacy_setting(environment, "AXION_EXTERNAL_DATA_POLICY", "KOMUS_EXTERNAL_DATA_POLICY")
    provider, provider_conflict = _legacy_setting(environment, "AXION_RESULT_INTERPRETER_PROVIDER", "KOMUS_RESULT_INTERPRETER_PROVIDER")
    model, model_conflict = _legacy_setting(environment, "AXION_RESULT_INTERPRETER_MODEL", "KOMUS_RESULT_INTERPRETER_MODEL")
    if conflict or provider_conflict or model_conflict:
        raise _LegacyConfigConflict("Conflicting legacy interpreter settings.")
    if not policy:
        policy = "DISABLED"
    return ResultInterpreterSettings(
        enabled=policy != "DISABLED",
        external_data_policy=policy,
        provider=provider,
        model=model,
        api_key_env="OPENAI_API_KEY",
        reasoning_effort="low",
        max_output_tokens=2400,
        timeout_seconds=60.0,
    )


def _legacy_setting(environment: Mapping[str, str], canonical: str, legacy: str) -> tuple[str, bool]:
    canonical_value = str(environment.get(canonical, "")).strip()
    legacy_value = str(environment.get(legacy, "")).strip()
    return (
        canonical_value or legacy_value,
        bool(canonical_value and legacy_value and canonical_value != legacy_value),
    )


def _load_settings(config_path: str | Path | None) -> ResultInterpreterSettings:
    path = (
        Path(config_path)
        if config_path is not None
        else Path(__file__).resolve().parents[1] / "config" / "result_interpreter.yaml"
    )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("Unsupported Result Interpreter config version.")

    section = raw.get("result_interpreter")
    if not isinstance(section, dict):
        raise ValueError("Missing result_interpreter configuration.")

    enabled = section.get("enabled")
    policy = section.get("external_data_policy")
    provider = section.get("provider")
    model = section.get("model")
    api_key_env = section.get("api_key_env")
    reasoning = section.get("reasoning")
    generation = section.get("generation")
    transport = section.get("transport")

    if not isinstance(enabled, bool):
        raise ValueError("result_interpreter.enabled must be boolean.")
    for label, value in (
        ("external_data_policy", policy),
        ("provider", provider),
        ("model", model),
        ("api_key_env", api_key_env),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"result_interpreter.{label} must be a non-empty string.")

    if not isinstance(reasoning, dict):
        raise ValueError("result_interpreter.reasoning must be a mapping.")
    reasoning_effort = reasoning.get("effort")
    if reasoning_effort not in _ALLOWED_REASONING_EFFORTS:
        raise ValueError("Unsupported reasoning effort.")

    if not isinstance(generation, dict):
        raise ValueError("result_interpreter.generation must be a mapping.")
    max_output_tokens = generation.get("max_output_tokens")
    if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 100_000:
        raise ValueError("max_output_tokens must be an integer from 1 to 100000.")

    if not isinstance(transport, dict):
        raise ValueError("result_interpreter.transport must be a mapping.")
    timeout_seconds = transport.get("timeout_seconds")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be numeric.")
    timeout_seconds = float(timeout_seconds)
    if not 0 < timeout_seconds <= 600:
        raise ValueError("timeout_seconds must be greater than 0 and at most 600.")

    return ResultInterpreterSettings(
        enabled=enabled,
        external_data_policy=policy.strip(),
        provider=provider.strip(),
        model=model.strip(),
        api_key_env=api_key_env.strip(),
        reasoning_effort=str(reasoning_effort),
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
    )


def _secret(name: str, secrets: Mapping[str, Any], environment: Mapping[str, str]) -> str:
    value: Any = None
    try:
        value = secrets.get(name)
    except Exception:
        value = None
    if value is None:
        value = environment.get(name)
    return str(value).strip() if value is not None else ""


def _load_local_dotenv() -> None:
    """Small dependency-free .env loader; process environment always wins."""
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _openai_factory(settings: ResultInterpreterSettings, credential: str) -> OpenAIResultInterpreterClient:
    from openai import OpenAI

    return OpenAIResultInterpreterClient(
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
        max_output_tokens=settings.max_output_tokens,
        client=OpenAI(api_key=credential, timeout=settings.timeout_seconds),
    )
