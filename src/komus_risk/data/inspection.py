"""Deterministic factual inspection; this module never proposes ML semantics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import re
from statistics import median
from typing import Any
import unicodedata

import numpy as np
import pandas as pd

from .tabular import TabularSnapshot


def _value(value: Any) -> Any:
    if isinstance(value, np.generic): value = value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)): return value.isoformat()
    return value


@dataclass(frozen=True, slots=True)
class ValueCount: value: Any; count: int
@dataclass(frozen=True, slots=True)
class RepresentationProfile:
    observed_value_type_families: tuple[str, ...]; mixed_value_types: bool
    numeric_all_integral: bool | None; numeric_has_fractional_values: bool | None
    string_all_digits: bool | None; median_string_length: float | None
@dataclass(frozen=True, slots=True)
class ColumnInspection:
    column_name: str; column_position: int; physical_dtype: str; inferred_logical_type: str; logical_type_evidence: tuple[str, ...]
    non_null_count: int; missing_count: int; missing_fraction: float; unique_non_null_count: int; unique_fraction: float
    is_unique: bool; is_constant: bool; is_near_unique: bool; is_all_missing: bool
    value_counts: tuple[ValueCount, ...] | None; representation_profile: RepresentationProfile
    safe_examples: tuple[Any, ...]; examples_redacted: bool; column_warnings: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class JointCount: source_value: Any; reference_value: Any; count: int
@dataclass(frozen=True, slots=True)
class PairwiseRelationInspection:
    binary_reference_column: str; source_column: str; overlap_non_null_rows: int; coverage_fraction: float
    joint_counts: tuple[JointCount, ...]; source_value_counts_on_overlap: tuple[ValueCount, ...]; reference_value_counts_on_overlap: tuple[ValueCount, ...]
@dataclass(frozen=True, slots=True)
class DatasetInspectionReport:
    snapshot_fingerprint: str; inspection_policy_version: str; row_count: int; column_count: int
    columns: tuple[ColumnInspection, ...]; relation_blocks: tuple[PairwiseRelationInspection, ...]; physical_warnings: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, Any]: return asdict(self)


class DatasetInspector:
    inspection_policy_version = "1"
    _identifier_tokens = frozenset({"id", "identifier", "key", "uuid", "guid", "inn", "ogrn", "snils", "ид", "идентификатор", "ключ", "инн", "огрн"})
    def inspect(self, snapshot: TabularSnapshot) -> DatasetInspectionReport:
        frame = snapshot.dataframe
        columns = tuple(self._column(str(name), index, frame.iloc[:, index]) for index, name in enumerate(frame.columns))
        by_name = {item.column_name: item for item in columns}
        blocks: list[PairwiseRelationInspection] = []
        for reference in columns:
            if reference.unique_non_null_count != 2: continue
            ref_series = frame.iloc[:, reference.column_position]
            for source in columns:
                if source.column_name == reference.column_name or not 2 <= source.unique_non_null_count <= 50: continue
                src = frame.iloc[:, source.column_position]; mask = src.notna() & ref_series.notna(); overlap = int(mask.sum())
                pairs = pd.DataFrame({"s": src[mask], "r": ref_series[mask]}).value_counts(sort=False)
                joint = tuple(JointCount(_value(s), _value(r), int(n)) for (s, r), n in sorted(pairs.items(), key=lambda x: (repr(_value(x[0][0])), repr(_value(x[0][1])))))
                sc = self._counts(src[mask]); rc = self._counts(ref_series[mask])
                blocks.append(PairwiseRelationInspection(reference.column_name, source.column_name, overlap, overlap / len(frame) if len(frame) else 0.0, joint, sc, rc))
        return DatasetInspectionReport(snapshot.fingerprint, self.inspection_policy_version, len(frame), len(frame.columns), columns, tuple(blocks))

    def _column(self, name: str, position: int, series: pd.Series) -> ColumnInspection:
        non_null = series.dropna(); n = len(series); nn = len(non_null); unique = int(non_null.nunique(dropna=True)); missing = n - nn
        logical, evidence = self._logical(series, non_null)
        profile = self._profile(non_null)
        all_missing = nn == 0; constant = nn > 0 and unique == 1; unique_flag = nn > 0 and unique == nn
        near = nn >= 20 and unique * 100 >= 98 * nn
        counts = self._counts(non_null) if unique <= 50 else None
        redact = unique >= 50 or near or logical == "text" or self._identifier_like_name(name)
        examples = () if redact else tuple(_value(x) for x in non_null.drop_duplicates().head(5))
        warnings = []
        if all_missing: warnings.append("all_missing_column")
        elif constant: warnings.append("constant_column")
        if near: warnings.append("near_unique_column")
        if missing: warnings.append("missing_values_present" if missing / n < .5 else "high_missingness" if missing / n < .9 else "almost_empty_column")
        if profile.mixed_value_types: warnings.append("mixed_value_types")
        if logical == "unknown": warnings.append("unknown_logical_type")
        return ColumnInspection(name, position, str(series.dtype), logical, evidence, nn, missing, missing / n if n else 0.0, unique, unique / nn if nn else 0.0, unique_flag, constant, near, all_missing, counts, profile, examples, redact, tuple(warnings))

    @classmethod
    def _identifier_like_name(cls, name: str) -> bool:
        normalized = unicodedata.normalize("NFKC", name).strip()
        normalized = re.sub(r"(?<=[a-zа-я])(?=[A-ZА-Я])", " ", normalized)
        normalized = re.sub(r"(?<=[A-Za-zА-Яа-я])(?=\d)|(?<=\d)(?=[A-Za-zА-Яа-я])", " ", normalized)
        return bool(cls._identifier_tokens.intersection(token for token in re.split(r"[_\-./\\\s]+", normalized.casefold()) if token))

    @staticmethod
    def _counts(series: pd.Series) -> tuple[ValueCount, ...]:
        counts = series.value_counts(dropna=True, sort=False)
        return tuple(ValueCount(_value(k), int(v)) for k, v in sorted(counts.items(), key=lambda x: repr(_value(x[0]))))

    @staticmethod
    def _logical(series: pd.Series, values: pd.Series) -> tuple[str, tuple[str, ...]]:
        if pd.api.types.is_bool_dtype(series): return "boolean", ("physical_boolean",)
        if pd.api.types.is_datetime64_any_dtype(series): return "datetime", ("physical_datetime",)
        if pd.api.types.is_numeric_dtype(series): return "numeric", ("physical_numeric",)
        if pd.api.types.is_string_dtype(series) or series.dtype == object:
            if values.empty: return "unknown", ("no_non_null_values",)
            families = {"string" if isinstance(x, str) else "numeric" if isinstance(x, (int, float, np.number)) else type(x).__name__ for x in values}
            if len(families) > 1: return "unknown", ("mixed_runtime_types",)
            if "string" in families: return ("categorical" if values.nunique() <= 50 else "text"), ("string_values",)
        return "unknown", ("unrecognized_representation",)

    @staticmethod
    def _profile(values: pd.Series) -> RepresentationProfile:
        raw = list(values); families = tuple(sorted({"string" if isinstance(x, str) else "bool" if isinstance(x, bool) else "numeric" if isinstance(x, (int, float, np.number)) else "datetime" if isinstance(x, (date, datetime, pd.Timestamp)) else type(x).__name__ for x in raw}))
        numeric = [x for x in raw if isinstance(x, (int, float, np.number)) and not isinstance(x, bool)]
        strings = [x for x in raw if isinstance(x, str)]
        return RepresentationProfile(families, len(families) > 1, (all(float(x).is_integer() for x in numeric) if numeric and len(numeric) == len(raw) else None), (any(not float(x).is_integer() for x in numeric) if numeric and len(numeric) == len(raw) else None), (all(x.strip().isdigit() for x in strings) if strings and len(strings) == len(raw) else None), (float(median([len(x) for x in strings])) if strings and len(strings) == len(raw) else None))
