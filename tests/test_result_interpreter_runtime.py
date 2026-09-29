from __future__ import annotations

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app.result_interpreter_runtime import compose_result_interpreter_runtime


class ResultInterpreterRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.factories = {"test": lambda model, credential: self.calls.append((model, credential)) or object()}

    def _env(self, prefix: str) -> dict[str, str]:
        return {
            f"{prefix}_EXTERNAL_DATA_POLICY": "REDACTED_V1",
            f"{prefix}_RESULT_INTERPRETER_PROVIDER": "test",
            f"{prefix}_RESULT_INTERPRETER_MODEL": "test-model",
        }

    def test_axion_legacy_and_matching_aliases_are_accepted(self) -> None:
        cases = (
            self._env("AXION"),
            self._env("KOMUS"),
            {**self._env("AXION"), **self._env("KOMUS")},
        )
        for env in cases:
            with self.subTest(env=env):
                runtime = compose_result_interpreter_runtime(environment=env, secrets={"OPENAI_API_KEY": "secret"}, factories=self.factories)
                self.assertTrue(runtime.configuration.is_ready)
                self.assertIsNotNone(runtime.client)
                self.assertIsNotNone(runtime.outbound_policy)
        self.assertEqual([("test-model", "secret")] * 3, self.calls)

    def test_conflicting_aliases_fail_closed_and_disabled_stays_disabled(self) -> None:
        conflict = {**self._env("AXION"), **self._env("KOMUS")}
        conflict["KOMUS_RESULT_INTERPRETER_MODEL"] = "different-model"
        runtime = compose_result_interpreter_runtime(environment=conflict, secrets={"OPENAI_API_KEY": "secret"}, factories=self.factories)
        self.assertEqual("CONFIG_CONFLICT", runtime.configuration.configuration_error)
        self.assertIsNone(runtime.client)
        disabled = compose_result_interpreter_runtime(environment={"AXION_EXTERNAL_DATA_POLICY": "DISABLED"}, secrets={"OPENAI_API_KEY": "secret"}, factories=self.factories)
        self.assertEqual("DISABLED", disabled.configuration.policy_mode)
        self.assertFalse(disabled.configuration.is_ready)
        self.assertEqual([], self.calls)

    def test_openai_key_is_separate_secret_and_neutral_runtime_has_no_streamlit_import(self) -> None:
        runtime = compose_result_interpreter_runtime(environment=self._env("AXION"), secrets={"OPENAI_API_KEY": "separate-secret"}, factories=self.factories)
        self.assertTrue(runtime.configuration.credentials_configured)
        self.assertEqual([("test-model", "separate-secret")], self.calls)
        tree = ast.parse(Path("app/result_interpreter_runtime.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported.update(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
        self.assertFalse(any(name and name.split(".")[0] == "streamlit" for name in imported))

    def test_dotenv_values_do_not_override_process_environment(self) -> None:
        from app import result_interpreter_runtime as module
        with patch.dict(os.environ, {"AXION_EXTERNAL_DATA_POLICY": "PROCESS_VALUE"}, clear=False):
            with patch.object(Path, "read_text", return_value="AXION_EXTERNAL_DATA_POLICY=DOTENV_VALUE\n"):
                module._load_local_dotenv()
            self.assertEqual("PROCESS_VALUE", os.environ["AXION_EXTERNAL_DATA_POLICY"])


if __name__ == "__main__":
    unittest.main()
