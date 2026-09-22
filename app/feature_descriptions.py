"""Optional, versioned display glossary; never changes fitted model identity."""

from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import pandas as pd

from komus_risk.hashing import canonical_json, stable_hash


MISSING_DESCRIPTION = "Описание не указано"
_LOOKALIKE = str.maketrans("АВЕКМНОРСТУХавекмнорстух", "ABEKMHOPCTYXabekmhopctyx")
_HISTORICAL_ID = "komus-historical-data-final"
_RESEARCH_MAP = Path(__file__).resolve().parents[1] / "reports" / "generated" / "stage17_information_gap_map_V1.json"


def historical_descriptions(dataset_id: str) -> dict[str, str]:
    """Use only the 17 research-confirmed meanings for the accepted historical identity."""
    if dataset_id != _HISTORICAL_ID:
        return {}
    evidence = json.loads(_RESEARCH_MAP.read_text(encoding="utf-8"))
    return dict(evidence["business_semantics"]["confirmed_meanings"])


def parse_description_file(file_name: str, content: bytes, feature_columns: tuple[str, ...]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Match dictionary rows by exact column name; never guess or auto-rename features."""
    extension = Path(file_name).suffix.lower()
    if extension not in {".csv", ".xlsx", ".xlsb"}:
        raise ValueError("Словарь описаний должен быть файлом CSV, XLSX или XLSB.")
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError("Словарь описаний пуст или больше 5 МБ.")
    try:
        if extension == ".csv":
            decoded = content.decode("utf-8-sig")
            headers = next(csv.reader(StringIO(decoded)), [])
            if len(headers) != len(set(headers)):
                raise ValueError("В словаре повторяются названия столбцов.")
            frame = pd.read_csv(StringIO(decoded), dtype=str, keep_default_na=False)
        else:
            engine = "openpyxl" if extension == ".xlsx" else "pyxlsb"
            frame = pd.read_excel(BytesIO(content), engine=engine, dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError, OSError, ImportError) as error:
        raise ValueError(f"Не удалось прочитать словарь описаний: {error}") from error
    if not {"column_name", "description"}.issubset(frame.columns) or not frame.columns.is_unique:
        raise ValueError("Нужны уникальные заголовки column_name и description.")
    names = frame["column_name"].astype(str)
    if names.str.strip().eq("").any() or names.duplicated().any():
        raise ValueError("Имена признаков в словаре должны быть непустыми и уникальными.")
    expected = set(feature_columns)
    unknown = tuple(name for name in names if name not in expected)
    if unknown:
        hints = []
        for name in unknown:
            similar = next((item for item in feature_columns if item.translate(_LOOKALIKE) == name.translate(_LOOKALIKE)), None)
            if similar:
                hints.append(f"«{name}» похоже на «{similar}» — проверьте алфавит")
            elif name.strip() in expected:
                hints.append(f"«{name}» похоже на «{name.strip()}» — проверьте пробелы")
        suffix = f" Возможные опечатки: {'; '.join(hints)}." if hints else ""
        raise ValueError("В словаре неизвестные признаки: " + ", ".join(unknown) + "." + suffix)
    descriptions: dict[str, str] = {}
    for name, raw in zip(names, frame["description"], strict=True):
        value = str(raw).strip()
        if value and value != MISSING_DESCRIPTION:
            if len(value) > 500:
                raise ValueError(f"Описание «{name}» длиннее 500 символов.")
            descriptions[name] = value
    missing = tuple(name for name in feature_columns if name not in descriptions)
    return descriptions, missing


class FeatureDescriptionStore:
    """Keep separate revisions keyed by dataset identity, not by model weights."""

    def __init__(self, artifact_root: str | Path) -> None:
        self.root = Path(artifact_root) / "feature-descriptions"

    def load(self, dataset_fingerprint: str) -> dict[str, str]:
        directory = self._directory(dataset_fingerprint)
        pointer = directory / "active.json"
        if not pointer.is_file():
            return {}
        active = json.loads(pointer.read_text(encoding="utf-8"))
        revision = active["revision"]
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("Активная версия словаря повреждена.")
        data = json.loads((directory / f"{revision}.json").read_text(encoding="utf-8"))
        if data.get("dataset_fingerprint") != dataset_fingerprint or stable_hash(data) != revision:
            raise ValueError("Словарь описаний не соответствует датасету или повреждён.")
        descriptions = data["descriptions"]
        if not isinstance(descriptions, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in descriptions.items()):
            raise ValueError("Словарь описаний имеет некорректную структуру.")
        return descriptions

    def save(self, dataset_fingerprint: str, descriptions: Mapping[str, str], feature_columns: tuple[str, ...]) -> str:
        if not dataset_fingerprint or set(descriptions) - set(feature_columns):
            raise ValueError("Словарь содержит признаки другого датасета.")
        if any(not isinstance(value, str) or not value.strip() for value in descriptions.values()):
            raise ValueError("Сохранить можно только непустые описания.")
        directory = self._directory(dataset_fingerprint)
        directory.mkdir(parents=True, exist_ok=True)
        data = {"dataset_fingerprint": dataset_fingerprint, "descriptions": dict(descriptions)}
        revision = stable_hash(data)
        target = directory / f"{revision}.json"
        if not target.exists():
            temporary = directory / f".tmp-{uuid4().hex}.json"
            temporary.write_text(canonical_json(data), encoding="utf-8")
            temporary.replace(target)
        pointer = directory / "active.json"
        temporary_pointer = directory / f".tmp-{uuid4().hex}.json"
        temporary_pointer.write_text(canonical_json({"revision": revision}), encoding="utf-8")
        temporary_pointer.replace(pointer)
        return revision

    def _directory(self, dataset_fingerprint: str) -> Path:
        if not isinstance(dataset_fingerprint, str) or not dataset_fingerprint:
            raise ValueError("Нужен отпечаток датасета для словаря описаний.")
        return self.root / sha256(dataset_fingerprint.encode("utf-8")).hexdigest()
