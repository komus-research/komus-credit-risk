"""Per-browser persistent upload history for the local Streamlit prototype."""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from collections.abc import MutableMapping, Sequence
from pathlib import Path
from typing import Any


HISTORY_QUERY_KEY = "komus_history"
_TOKEN_PATTERN = re.compile(r"[0-9a-f]{48}\Z")
_STORED_NAME_PATTERN = re.compile(r"[0-9a-f]{16}-.+\.(?:csv|xlsx|xlsb)\Z", re.IGNORECASE)
_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / ".streamlit-artifacts"


class UploadHistoryError(ValueError):
    """The persistent history cannot be read or written safely."""


def history_token(query_params: MutableMapping[str, Any]) -> str:
    """Keep a random, reload-stable history identity in the browser URL."""
    token = query_params.get(HISTORY_QUERY_KEY)
    if isinstance(token, str) and _TOKEN_PATTERN.fullmatch(token):
        return token
    token = secrets.token_hex(24)
    query_params[HISTORY_QUERY_KEY] = token
    return token


def load_upload_history(
    token: str, *, history_root: Path | None = None, upload_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Load only files recorded for this URL token and still present in upload storage."""
    history_path, uploads = _paths(token, history_root, upload_root)
    if not history_path.is_file():
        return []
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UploadHistoryError("Не удалось прочитать сохранённую историю файлов.") from error
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("files"), list):
        raise UploadHistoryError("Сохранённая история файлов имеет неподдерживаемый формат.")
    result = []
    seen = set()
    for raw in payload["files"][:10]:
        entry = _valid_entry(raw, uploads)
        if entry is not None and entry["path"] not in seen:
            result.append(entry)
            seen.add(entry["path"])
    return result


def save_upload_history(
    token: str, history: Sequence[dict[str, Any]], *,
    history_root: Path | None = None, upload_root: Path | None = None,
) -> None:
    """Atomically save a bounded history; never store arbitrary absolute paths."""
    history_path, uploads = _paths(token, history_root, upload_root)
    records = []
    seen = set()
    for item in history[:10]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = Path(item["path"])
        entry = _valid_entry({"name": item.get("name"), "stored_name": path.name, "size": item.get("size")}, uploads)
        if entry is None or Path(entry["path"]) != path.resolve() or entry["path"] in seen:
            continue
        seen.add(entry["path"])
        records.append({"name": entry["name"], "stored_name": path.name, "size": entry["size"]})
    temporary_path: Path | None = None
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix="history-", suffix=".tmp", dir=history_path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "files": records}, stream, ensure_ascii=False)
        os.replace(temporary_path, history_path)
    except OSError as error:
        raise UploadHistoryError("Не удалось сохранить историю файлов на диске.") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _paths(token: str, history_root: Path | None, upload_root: Path | None) -> tuple[Path, Path]:
    if not isinstance(token, str) or _TOKEN_PATTERN.fullmatch(token) is None:
        raise UploadHistoryError("Недопустимый идентификатор истории файлов.")
    return (
        (history_root or _DEFAULT_ROOT / "upload-history") / f"{token}.json",
        (upload_root or _DEFAULT_ROOT / "uploads").resolve(),
    )


def _valid_entry(raw: Any, uploads: Path) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name, stored_name, size = raw.get("name"), raw.get("stored_name"), raw.get("size")
    if not isinstance(name, str) or not name or Path(name).name != name:
        return None
    if not isinstance(stored_name, str) or _STORED_NAME_PATTERN.fullmatch(stored_name) is None:
        return None
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return None
    try:
        path = (uploads / stored_name).resolve()
        if path.parent != uploads or not path.is_file() or path.stat().st_size != size:
            return None
    except (OSError, RuntimeError):
        return None
    return {"name": name, "path": str(path), "size": size}
