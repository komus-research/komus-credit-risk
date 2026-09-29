"""Configuration and composition boundary for external result interpretation."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from komus_risk.application import RedactedV1OutboundPolicy, ResultInterpreterRuntimeConfiguration
from komus_risk.application.result_interpreter_prompts import ResultInterpreterPromptLoader, ResultInterpreterPromptsError
from komus_risk.integrations.openai_result_interpreter import OpenAIResultInterpreterClient


@dataclass(frozen=True, slots=True)
class ResultInterpreterRuntime:
    configuration: ResultInterpreterRuntimeConfiguration
    client: Any | None
    outbound_policy: RedactedV1OutboundPolicy | None
    prompt_loader: ResultInterpreterPromptLoader


def compose_result_interpreter_runtime(*, environment: Mapping[str, str] | None = None, secrets: Mapping[str, Any] | None = None, factories: Mapping[str, Callable[[str, str], Any]] | None = None) -> ResultInterpreterRuntime:
    """Resolve env aliases, secrets, prompt files and the selected provider once."""
    if environment is None:
        _load_local_dotenv()
        environment = os.environ
    loader = ResultInterpreterPromptLoader()
    policy, conflict = _setting(environment, "AXION_EXTERNAL_DATA_POLICY", "KOMUS_EXTERNAL_DATA_POLICY")
    provider, provider_conflict = _setting(environment, "AXION_RESULT_INTERPRETER_PROVIDER", "KOMUS_RESULT_INTERPRETER_PROVIDER")
    model, model_conflict = _setting(environment, "AXION_RESULT_INTERPRETER_MODEL", "KOMUS_RESULT_INTERPRETER_MODEL")
    if conflict or provider_conflict or model_conflict:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode="INVALID", configuration_error="CONFIG_CONFLICT"), None, None, loader)
    if not policy or policy == "DISABLED":
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration.disabled(), None, None, loader)
    if policy != "REDACTED_V1":
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode="INVALID", configuration_error="EXTERNAL_DATA_POLICY_INVALID"), None, None, loader)
    if not provider:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy), None, None, loader)
    provider_registry = dict(factories or {"openai": _openai_factory})
    factory = provider_registry.get(provider)
    if factory is None:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy, provider_configured=True), None, None, loader)
    if not model:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy, provider_configured=True, provider_registered=True), None, None, loader)
    credential = _secret("OPENAI_API_KEY", secrets or {}, environment)
    if not credential:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy, provider_configured=True, provider_registered=True, model_configured=True), None, None, loader)
    try:
        for role in ("sales_manager", "credit_controller", "lawyer", "information_security"):
            loader.load(role)
    except ResultInterpreterPromptsError as error:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy, provider_configured=True, provider_registered=True, model_configured=True, credentials_configured=True, prompts_configured=False, configuration_error=error.code), None, None, loader)
    try:
        client = factory(model, credential)
    except Exception:
        return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy, provider_configured=True, provider_registered=True, model_configured=True, credentials_configured=True, configuration_error="RESULT_INTERPRETER_PROVIDER_INVALID"), None, None, loader)
    return ResultInterpreterRuntime(ResultInterpreterRuntimeConfiguration(policy_mode=policy, provider_configured=True, provider_registered=True, model_configured=True, credentials_configured=True), client, RedactedV1OutboundPolicy(), loader)


def _setting(environment: Mapping[str, str], canonical: str, legacy: str) -> tuple[str, bool]:
    canonical_value = str(environment.get(canonical, "")).strip()
    legacy_value = str(environment.get(legacy, "")).strip()
    return (canonical_value or legacy_value, bool(canonical_value and legacy_value and canonical_value != legacy_value))


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


def _openai_factory(model: str, credential: str) -> OpenAIResultInterpreterClient:
    from openai import OpenAI
    return OpenAIResultInterpreterClient(model=model, client=OpenAI(api_key=credential))
