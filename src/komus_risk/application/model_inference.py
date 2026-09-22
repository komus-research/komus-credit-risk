"""Strict batch inference for a previously fitted, versioned model."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
import csv
from pathlib import Path

import numpy as np
import pandas as pd

from komus_risk.artifacts.model_store import LoadedModelVersion


_MAX_INPUT_BYTES = 200 * 1024 * 1024
_MAX_ROWS = 100_000
_LOOKALIKE = str.maketrans("АВЕКМНОРСТУХавекмнорстух", "ABEKMHOPCTYXabekmhopctyx")


@dataclass(frozen=True, slots=True)
class PredictionBatch:
    version_id: str
    source_sha256: str
    predictions: pd.DataFrame
    ignored_columns: tuple[str, ...]


def predict_uploaded_file(model: LoadedModelVersion, file_name: str, content: bytes) -> PredictionBatch:
    """Read CSV/XLSX/XLSB, validate exact feature names and values, then predict without fitting."""
    extension = Path(file_name).suffix.lower()
    if extension not in {".csv", ".xlsx", ".xlsb"}:
        raise ValueError("Для прогноза загрузите файл CSV, XLSX или XLSB.")
    if not content or len(content) > _MAX_INPUT_BYTES:
        raise ValueError("Файл прогноза пуст или превышает ограничение 200 МБ.")
    try:
        if extension == ".csv":
            decoded = content.decode("utf-8-sig")
            headers = next(csv.reader(StringIO(decoded)), [])
            if len(headers) != len(set(headers)):
                raise ValueError("В файле есть повторяющиеся имена столбцов.")
            frame = pd.read_csv(StringIO(decoded), dtype=str, keep_default_na=False, nrows=_MAX_ROWS + 1)
        else:
            engine = "openpyxl" if extension == ".xlsx" else "pyxlsb"
            frame = pd.read_excel(BytesIO(content), engine=engine, dtype=str, keep_default_na=False, nrows=_MAX_ROWS + 1)
    except (UnicodeDecodeError, pd.errors.ParserError, OSError, ImportError) as error:
        raise ValueError(f"Не удалось прочитать файл прогноза: {error}") from error
    if not frame.columns.is_unique:
        raise ValueError("В файле есть повторяющиеся имена столбцов.")
    if frame.empty or len(frame) > _MAX_ROWS:
        raise ValueError("Файл должен содержать от 1 до 100 000 строк данных.")
    identifier = model.dataset_contract.identifier_column
    feature_columns = tuple(spec.column_name for spec in model.feature_specs)
    required = (identifier, *feature_columns)
    missing = [name for name in required if name not in frame.columns]
    if missing:
        hints = []
        for name in missing:
            lookalikes = [column for column in frame.columns if column.translate(_LOOKALIKE) == name.translate(_LOOKALIKE)]
            if lookalikes:
                hints.append(f"«{name}» похоже на «{lookalikes[0]}» (проверьте алфавит букв)")
        detail = f" Возможные опечатки: {'; '.join(hints)}." if hints else ""
        raise ValueError(f"Не найдены обязательные столбцы: {', '.join(missing)}.{detail}")
    identifiers = frame[identifier].astype(str).str.strip()
    if not identifiers.str.fullmatch(r"(?:[0-9]{10}|[0-9]{12})").all() or identifiers.duplicated().any():
        raise ValueError("ИНН должны состоять из 10 или 12 цифр и не повторяться в файле прогноза.")
    numeric = pd.DataFrame(index=frame.index)
    for name in feature_columns:
        values = pd.to_numeric(frame[name], errors="coerce")
        invalid = ~np.isfinite(values.to_numpy(dtype=float))
        if invalid.any():
            examples = ", ".join(str(position + 2) for position in np.flatnonzero(invalid)[:5])
            raise ValueError(f"Признак «{name}» содержит пустые или нечисловые значения (строки файла: {examples}).")
        numeric[name] = values
    probability = model.predictor.predict_positive_proba(numeric.loc[:, list(feature_columns)])
    result = pd.DataFrame({
        identifier: identifiers.to_numpy(),
        "Вероятность события": probability,
        "Прогноз при пороге 0.5": np.where(probability >= 0.5, "Событие", "Нет события"),
    })
    return PredictionBatch(
        model.summary.version_id, sha256(content).hexdigest(), result,
        tuple(str(column) for column in frame.columns if column not in required),
    )
