"""Fail-closed loader for versioned result-interpreter prompt files."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


RESULT_INTERPRETER_PROMPT_ROLES = frozenset({"sales_manager", "credit_controller", "lawyer", "information_security"})


class ResultInterpreterPromptsError(ValueError):
    code = "RESULT_INTERPRETER_PROMPTS_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(message if message.startswith(self.code) else f"{self.code}: {message}")


@dataclass(frozen=True, slots=True)
class LoadedResultInterpreterPrompt:
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    system_instruction: str


def normalize_prompt(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def prompt_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class ResultInterpreterPromptLoader:
    """Loads a manifest package without template expansion or fallback strings."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[3] / "resources" / "prompts" / "result_interpreter"

    def load(self, recipient_role: str) -> LoadedResultInterpreterPrompt:
        if recipient_role not in RESULT_INTERPRETER_PROMPT_ROLES:
            raise ResultInterpreterPromptsError("Unknown result-interpreter prompt role.")
        manifest = self._manifest()
        prompt_id, prompt_version = manifest.get("prompt_set_id"), manifest.get("prompt_set_version")
        if not isinstance(prompt_id, str) or not prompt_id.strip() or not isinstance(prompt_version, str) or not prompt_version.strip():
            raise ResultInterpreterPromptsError("Prompt manifest identity is invalid.")
        roles = manifest.get("roles")
        if not isinstance(roles, dict) or set(roles) != RESULT_INTERPRETER_PROMPT_ROLES:
            raise ResultInterpreterPromptsError("Prompt manifest must declare exactly the protocol roles.")
        instruction = normalize_prompt(self._load_entry(manifest.get("base"), "base")) + "\n\n" + normalize_prompt(self._load_entry(roles[recipient_role], recipient_role))
        return LoadedResultInterpreterPrompt(f"{prompt_id.strip()}/{recipient_role}", prompt_version.strip(), prompt_hash(instruction), instruction)

    def _manifest(self) -> dict[str, Any]:
        try:
            manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResultInterpreterPromptsError("Prompt manifest is missing or invalid.") from error
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ResultInterpreterPromptsError("Prompt manifest schema is unsupported.")
        return manifest

    def _load_entry(self, entry: Any, label: str) -> str:
        if not isinstance(entry, dict):
            raise ResultInterpreterPromptsError(f"Prompt manifest entry {label!r} is invalid.")
        filename, expected_hash = entry.get("filename"), entry.get("hash")
        if not isinstance(filename, str) or not isinstance(expected_hash, str) or not expected_hash:
            raise ResultInterpreterPromptsError(f"Prompt manifest entry {label!r} is invalid.")
        candidate = Path(filename)
        if candidate.name != filename or filename in {"", ".", ".."}:
            raise ResultInterpreterPromptsError("Prompt filename contains a path traversal.")
        try:
            text = (self.root / candidate).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ResultInterpreterPromptsError(f"Prompt file {filename!r} is unavailable.") from error
        normalized = normalize_prompt(text)
        if not normalized or prompt_hash(normalized) != expected_hash:
            raise ResultInterpreterPromptsError(f"Prompt file {filename!r} is empty or its hash does not match the manifest.")
        return normalized
