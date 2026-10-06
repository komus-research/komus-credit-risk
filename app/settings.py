"""Local, secret-safe Settings V1 services.

This module deliberately keeps preferences separate from AXION artifacts and
never serializes credentials.  The operating-system credential vault is the
only local credential backend.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from app.result_interpreter_runtime import ResultInterpreterRuntime, compose_result_interpreter_runtime
from komus_risk.application import ResultInterpreterRuntimeConfiguration


ROLES = ("credit_controller", "sales_manager", "lawyer", "information_security")


@dataclass(frozen=True, slots=True)
class LocalPreferences:
    technical_details_expanded: bool = False
    interpreter_enabled: bool = True
    default_role: str = "credit_controller"


class LocalPreferencesStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "settings" / "preferences.json"

    def get(self) -> LocalPreferences:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # First application start: normal product defaults are safe.
            return LocalPreferences()
        except (OSError, UnicodeDecodeError):
            return self._fail_closed()
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict) or set(raw) != {
                "technical_details_expanded", "interpreter_enabled", "default_role",
            }:
                raise ValueError("Invalid preferences shape.")
            technical_details_expanded = raw["technical_details_expanded"]
            interpreter_enabled = raw["interpreter_enabled"]
            default_role = raw["default_role"]
            if type(technical_details_expanded) is not bool or type(interpreter_enabled) is not bool:
                raise ValueError("Preferences booleans must be strict.")
            if default_role not in ROLES:
                raise ValueError("Unsupported interpreter role.")
            return LocalPreferences(technical_details_expanded, interpreter_enabled, default_role)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self._fail_closed()

    @staticmethod
    def _fail_closed() -> LocalPreferences:
        return LocalPreferences(technical_details_expanded=False, interpreter_enabled=False)

    def update(self, **values: Any) -> LocalPreferences:
        current = asdict(self.get())
        current.update({key: value for key, value in values.items() if value is not None})
        if not isinstance(current["technical_details_expanded"], bool) or not isinstance(current["interpreter_enabled"], bool):
            raise ValueError("Preferences must be boolean.")
        if current["default_role"] not in ROLES:
            raise ValueError("Unsupported interpreter role.")
        preference = LocalPreferences(**current)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(preference), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)
        return preference


class CredentialStore(Protocol):
    def configured(self) -> bool: ...
    def get(self) -> str | None: ...
    def set(self, secret: str) -> None: ...
    def delete(self) -> None: ...


class KeyringCredentialStore:
    """Fail-closed adapter around keyring; no filesystem fallback exists."""
    service_name = "AXION Result Interpreter"
    username = "local-provider-credential"

    def _backend(self):
        try:
            import keyring
            backend = keyring.get_keyring()
            if backend.priority <= 0:
                return None
            return keyring
        except Exception:
            return None

    def configured(self) -> bool:
        return bool(self.get())

    def get(self) -> str | None:
        keyring = self._backend()
        if keyring is None:
            return None
        try:
            value = keyring.get_password(self.service_name, self.username)
            return value.strip() if isinstance(value, str) and value.strip() else None
        except Exception:
            return None

    def set(self, secret: str) -> None:
        if not isinstance(secret, str) or not secret.strip():
            raise ValueError("Credential is required.")
        keyring = self._backend()
        if keyring is None:
            raise RuntimeError("SECURE_CREDENTIAL_STORE_UNAVAILABLE")
        try:
            keyring.set_password(self.service_name, self.username, secret.strip())
        except Exception as error:
            raise RuntimeError("SECURE_CREDENTIAL_STORE_UNAVAILABLE") from error

    def delete(self) -> None:
        keyring = self._backend()
        if keyring is None:
            raise RuntimeError("SECURE_CREDENTIAL_STORE_UNAVAILABLE")
        try:
            keyring.delete_password(self.service_name, self.username)
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as error:
            raise RuntimeError("SECURE_CREDENTIAL_STORE_UNAVAILABLE") from error


class ResultInterpreterSettingsService:
    def __init__(self, root: Path, credential_store: CredentialStore | None = None) -> None:
        self.preferences = LocalPreferencesStore(root)
        self.credentials = credential_store or KeyringCredentialStore()

    def _system_managed(self, runtime: ResultInterpreterRuntime) -> bool:
        return bool(runtime.settings and os.environ.get(runtime.settings.api_key_env, "").strip())

    def runtime(self) -> ResultInterpreterRuntime:
        base = compose_result_interpreter_runtime()
        if base.settings is None or self._system_managed(base):
            return base
        secret = self.credentials.get()
        return compose_result_interpreter_runtime(secrets={base.settings.api_key_env: secret} if secret else {})

    def state(self) -> dict[str, Any]:
        runtime = self.runtime()
        prefs = self.preferences.get()
        settings = runtime.settings
        provider = settings.provider if settings else None
        model = settings.model if settings else None
        managed = self._system_managed(runtime)
        return {
            "technical_details_expanded": prefs.technical_details_expanded,
            "interpreter_enabled": prefs.interpreter_enabled,
            "interpreter_toggle_editable": runtime.configuration.policy_mode != "DISABLED",
            "default_role": prefs.default_role,
            "roles": list(ROLES),
            "providers": [{"provider_id": provider, "display_name": provider.title()}] if provider else [],
            "selected_provider_id": provider,
            "models": [{"model_id": model, "display_name": model, "provider_id": provider, "status": "SUPPORTED"}] if model and provider else [],
            "selected_model_id": model,
            "external_data_policy": runtime.configuration.policy_mode,
            "credential": {"configured": bool(os.environ.get(settings.api_key_env, "").strip()) if managed and settings else self.credentials.configured(), "managed_by_system": managed, "secure_store_available": managed or self.credentials.get() is not None or KeyringCredentialStore()._backend() is not None},
            "runtime": {"available": runtime.configuration.is_ready and prefs.interpreter_enabled, "reason": self._reason(runtime.configuration, prefs.interpreter_enabled)},
        }

    @staticmethod
    def _reason(configuration: ResultInterpreterRuntimeConfiguration, local_enabled: bool) -> str:
        if configuration.policy_mode == "DISABLED": return "EXTERNAL_DATA_POLICY_DISABLED"
        if not local_enabled: return "LOCAL_PREFERENCE_DISABLED"
        if not configuration.provider_configured: return "RESULT_INTERPRETER_PROVIDER_MISSING"
        if not configuration.model_configured: return "RESULT_INTERPRETER_MODEL_MISSING"
        if not configuration.credentials_configured: return "RESULT_INTERPRETER_CREDENTIALS_MISSING"
        if not configuration.prompts_configured: return configuration.configuration_error or "RESULT_INTERPRETER_PROMPTS_INVALID"
        return "RESULT_INTERPRETER_READY"

    def apply_to(self, workflow: Any) -> ResultInterpreterRuntime:
        runtime = self.runtime()
        preference = self.preferences.get()
        config = runtime.configuration
        workflow.result_interpreter_runtime = ResultInterpreterRuntimeConfiguration(
            policy_mode=config.policy_mode, provider_configured=config.provider_configured,
            provider_registered=config.provider_registered, model_configured=config.model_configured,
            credentials_configured=config.credentials_configured, prompts_configured=config.prompts_configured,
            configuration_error=config.configuration_error, local_enabled=preference.interpreter_enabled,
        )
        workflow.result_interpreter_client = runtime.client
        workflow.outbound_interpreter_policy = runtime.outbound_policy
        return runtime

    def update_preferences(self, **values: Any) -> dict[str, Any]:
        self.preferences.update(**values)
        return self.state()

    def set_credential(self, secret: str) -> None:
        runtime = self.runtime()
        if self._system_managed(runtime):
            raise PermissionError("CREDENTIAL_MANAGED_BY_SYSTEM")
        self.credentials.set(secret)

    def delete_credential(self) -> None:
        runtime = self.runtime()
        if self._system_managed(runtime):
            raise PermissionError("CREDENTIAL_MANAGED_BY_SYSTEM")
        self.credentials.delete()

    def check_connection(self) -> bool:
        runtime = self.runtime()
        prefs = self.preferences.get()
        if not (runtime.configuration.is_ready and prefs.interpreter_enabled and runtime.client):
            raise RuntimeError(self._reason(runtime.configuration, prefs.interpreter_enabled))
        # Synthetic payload only: no customer, dataset, score, model or SHAP facts.
        runtime.client.interpret(system_instruction="AXION connection check. Reply with OK.", payload={"kind": "settings_connection_check", "message": "ping"})
        return True
