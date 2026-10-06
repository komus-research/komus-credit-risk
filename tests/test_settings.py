from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from app.api.main import create_app
from app.settings import LocalPreferencesStore, ResultInterpreterSettingsService
from komus_risk.application import ResultInterpreterRuntimeConfiguration


class _CredentialStore:
    def __init__(self) -> None:
        self.value: str | None = None
        self.set_calls = 0

    def configured(self) -> bool:
        return self.value is not None

    def get(self) -> str | None:
        return self.value

    def set(self, secret: str) -> None:
        self.set_calls += 1
        self.value = secret

    def delete(self) -> None:
        self.value = None


class _Workflow:
    result_interpreter_runtime = ResultInterpreterRuntimeConfiguration.disabled()
    result_interpreter_client = None
    outbound_interpreter_policy = None


class SettingsTests(unittest.TestCase):
    def _api_client(self, root: Path, credentials: _CredentialStore) -> TestClient:
        service = ResultInterpreterSettingsService(root, credentials)
        service._system_managed = lambda runtime: False  # type: ignore[method-assign]
        return TestClient(create_app(settings_service=service))

    def test_preferences_persist_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LocalPreferencesStore(Path(temporary))
            store.update(technical_details_expanded=True, interpreter_enabled=False, default_role="lawyer")
            restored = LocalPreferencesStore(Path(temporary)).get()
            self.assertTrue(restored.technical_details_expanded)
            self.assertFalse(restored.interpreter_enabled)
            self.assertEqual(restored.default_role, "lawyer")

    def test_credential_is_not_in_preferences_or_settings_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            credentials = _CredentialStore()
            service = ResultInterpreterSettingsService(Path(temporary), credentials)
            service._system_managed = lambda runtime: False  # type: ignore[method-assign]
            service.update_preferences(default_role="lawyer")
            service.set_credential("secret-value-that-must-not-leak")
            service.set_credential("replacement-secret")
            self.assertEqual(credentials.get(), "replacement-secret")
            state = service.state()
            self.assertTrue(state["credential"]["configured"])
            self.assertNotIn("secret-value-that-must-not-leak", repr(state))
            self.assertNotIn("replacement-secret", repr(state))
            self.assertNotIn("secret-value-that-must-not-leak", (Path(temporary) / "settings" / "preferences.json").read_text(encoding="utf-8"))
            service.delete_credential()
            self.assertFalse(credentials.configured())

    def test_local_disable_is_applied_to_interpreter_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = ResultInterpreterSettingsService(Path(temporary), _CredentialStore())
            service.update_preferences(interpreter_enabled=False)
            workflow = _Workflow()
            service.apply_to(workflow)
            self.assertFalse(workflow.result_interpreter_runtime.local_enabled)
            self.assertFalse(ResultInterpreterRuntimeConfiguration(
                policy_mode="REDACTED_V1", provider_configured=True, provider_registered=True,
                model_configured=True, credentials_configured=True, local_enabled=False,
            ).is_ready)

    def test_settings_api_never_returns_credential_value(self) -> None:
        payload = TestClient(create_app()).get("/api/v1/settings").json()
        self.assertEqual(set(payload["credential"]), {"configured", "managed_by_system", "secure_store_available"})

    def test_existing_invalid_preferences_fail_closed(self) -> None:
        invalid_values = [
            "{not json",
            '{"technical_details_expanded": false, "interpreter_enabled": "false", "default_role": "credit_controller"}',
            '{"technical_details_expanded": false, "interpreter_enabled": true, "default_role": "unknown"}',
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings"
            path.mkdir()
            for value in invalid_values:
                (path / "preferences.json").write_text(value, encoding="utf-8")
                self.assertFalse(LocalPreferencesStore(Path(temporary)).get().interpreter_enabled)

    def test_invalid_utf8_preferences_fail_closed_and_disable_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings"
            path.mkdir()
            (path / "preferences.json").write_bytes(b'\xff\xfe\x80')
            preferences = LocalPreferencesStore(Path(temporary)).get()
            self.assertFalse(preferences.interpreter_enabled)
            self.assertFalse(preferences.technical_details_expanded)
            self.assertEqual(preferences.default_role, "credit_controller")
            workflow = _Workflow()
            ResultInterpreterSettingsService(Path(temporary), _CredentialStore()).apply_to(workflow)
            self.assertFalse(workflow.result_interpreter_runtime.local_enabled)

    def test_preferences_api_rejects_non_strict_booleans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = self._api_client(Path(temporary), _CredentialStore())
            self.assertEqual(client.patch("/api/v1/settings/preferences", json={"interpreter_enabled": "false"}).status_code, 422)
            self.assertEqual(client.patch("/api/v1/settings/preferences", json={"technical_details_expanded": 1}).status_code, 422)

    def test_credential_validation_never_echoes_secret_or_calls_store(self) -> None:
        marker = "SETTINGS_SECRET_MARKER_7f5275"
        with tempfile.TemporaryDirectory() as temporary:
            credentials = _CredentialStore()
            client = self._api_client(Path(temporary), credentials)
            response = client.put("/api/v1/settings/credential", json={"credential": marker + "x" * 4097})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(marker, response.text)
            self.assertEqual(credentials.set_calls, 0)
            self.assertEqual(client.put("/api/v1/settings/credential", json={"credential": 1}).status_code, 422)
            malformed = client.put("/api/v1/settings/credential", content=b'{"credential":', headers={"content-type": "application/json"})
            self.assertEqual(malformed.status_code, 422)

    def test_delayed_technical_blocks_use_explicit_lifecycle_boundary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        component = (root / "frontend" / "src" / "components" / "TechnicalDetails.tsx").read_text(encoding="utf-8")
        application = (root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("useLayoutEffect", component)
        self.assertIn("reference.current.open = preference.expanded", component)
        self.assertNotIn("querySelectorAll<HTMLDetailsElement>", application)
        for page in ("ResultPage", "ObjectDetailPage", "SavedInferenceObjectDetailPage", "AnalystReportPage", "ModelVersionDetailPage", "GlobalExplanationPage"):
            self.assertIn("<TechnicalDetails", (root / "frontend" / "src" / "pages" / f"{page}.tsx").read_text(encoding="utf-8"))
