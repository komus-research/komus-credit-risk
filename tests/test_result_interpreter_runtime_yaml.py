from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.result_interpreter_runtime import compose_result_interpreter_runtime


def _write_config(root: Path, *, model: str = "gpt-6-luna", effort: str = "low", enabled: bool = True) -> Path:
    path = root / "result_interpreter.yaml"
    path.write_text(
        f"""version: 1
result_interpreter:
  enabled: {str(enabled).lower()}
  external_data_policy: REDACTED_V1
  provider: test
  model: {model}
  api_key_env: OPENAI_API_KEY
  reasoning:
    effort: {effort}
  generation:
    max_output_tokens: 2400
  transport:
    timeout_seconds: 60
""",
        encoding="utf-8",
    )
    return path


def test_yaml_is_canonical_nonsecret_configuration() -> None:
    calls: list[tuple[str, str]] = []

    def factory(model: str, credential: str):
        calls.append((model, credential))
        return object()

    with TemporaryDirectory() as directory:
        config_path = _write_config(Path(directory))
        runtime = compose_result_interpreter_runtime(
            secrets={"OPENAI_API_KEY": "secret"},
            factories={"test": factory},
            config_path=config_path,
        )

    assert runtime.configuration.is_ready
    assert runtime.settings is not None
    assert runtime.settings.model == "gpt-6-luna"
    assert runtime.settings.reasoning_effort == "low"
    assert runtime.settings.max_output_tokens == 2400
    assert runtime.settings.timeout_seconds == 60
    assert calls == [("gpt-6-luna", "secret")]


def test_yaml_disabled_mode_never_creates_provider() -> None:
    calls: list[tuple[str, str]] = []

    def factory(model: str, credential: str):
        calls.append((model, credential))
        return object()

    with TemporaryDirectory() as directory:
        config_path = _write_config(Path(directory), enabled=False)
        runtime = compose_result_interpreter_runtime(
            secrets={"OPENAI_API_KEY": "secret"},
            factories={"test": factory},
            config_path=config_path,
        )

    assert runtime.configuration.policy_mode == "DISABLED"
    assert runtime.client is None
    assert calls == []


def test_invalid_yaml_reasoning_fails_closed_before_provider() -> None:
    calls: list[tuple[str, str]] = []

    def factory(model: str, credential: str):
        calls.append((model, credential))
        return object()

    with TemporaryDirectory() as directory:
        config_path = _write_config(Path(directory), effort="ultra")
        runtime = compose_result_interpreter_runtime(
            secrets={"OPENAI_API_KEY": "secret"},
            factories={"test": factory},
            config_path=config_path,
        )

    assert runtime.configuration.configuration_error == "RESULT_INTERPRETER_CONFIG_INVALID"
    assert runtime.client is None
    assert calls == []


def test_yaml_api_key_name_controls_secret_lookup() -> None:
    with TemporaryDirectory() as directory:
        config_path = _write_config(Path(directory))
        text = config_path.read_text(encoding="utf-8").replace("OPENAI_API_KEY", "AXION_TEST_KEY")
        config_path.write_text(text, encoding="utf-8")
        runtime = compose_result_interpreter_runtime(
            secrets={},
            environment=None,
            factories={"test": lambda model, credential: object()},
            config_path=config_path,
        )

    assert runtime.configuration.credentials_configured is False
    assert runtime.client is None
