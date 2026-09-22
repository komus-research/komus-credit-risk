"""Explicit, fail-closed materialization of a user-confirmed tabular dataset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

from komus_risk.contracts import DatasetContract, FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import DatasetInspectionReport, LoadedDataset, TabularSnapshot
from komus_risk.experiments import EvaluationPopulation
from komus_risk.hashing import stable_hash
from komus_risk.registries import FeatureRegistry

from .contracts import DatasetPreparationProposal


@dataclass(frozen=True, slots=True)
class ConfirmedDatasetRoles:
    """User choices, not automatic assignments inferred from column names."""

    snapshot_fingerprint: str
    target_column: str
    positive_class: str | int | float | bool
    identifier_column: str
    allowed_feature_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaterializedDataset:
    """Confirmed contracts held separately from the historical run-ready context."""

    loaded_dataset: LoadedDataset
    feature_registry: FeatureRegistry
    population: EvaluationPopulation
    roles: ConfirmedDatasetRoles


def materialize_confirmed_dataset(
    snapshot: TabularSnapshot,
    inspection: DatasetInspectionReport,
    proposal: DatasetPreparationProposal,
    roles: ConfirmedDatasetRoles,
) -> MaterializedDataset:
    """Create new contracts only after explicit choices and strict data checks."""
    if not (
        snapshot.fingerprint == inspection.snapshot_fingerprint
        == proposal.snapshot_fingerprint == roles.snapshot_fingerprint
    ):
        raise ValueError("Анализ, предложения и подтверждение относятся к разным версиям файла.")
    frame = snapshot.dataframe
    columns = tuple(frame.columns)
    if not columns or not frame.columns.is_unique or any(not isinstance(name, str) or not name.strip() for name in columns):
        raise ValueError("Нужны однозначные непустые названия столбцов.")
    if snapshot.row_count != len(frame) or snapshot.column_count != len(columns):
        raise ValueError("Размер таблицы не совпадает с прочитанным источником.")
    if tuple(item.column_name for item in inspection.columns) != columns:
        raise ValueError("Анализ столбцов не соответствует прочитанному файлу.")
    if roles.target_column not in columns or roles.identifier_column not in columns:
        raise ValueError("Выбранные цель и идентификатор отсутствуют в файле.")
    if roles.target_column == roles.identifier_column:
        raise ValueError("Цель и идентификатор должны быть разными столбцами.")

    target = frame[roles.target_column]
    if target.isna().any() or target.nunique(dropna=False) != 2:
        raise ValueError("Целевая колонка должна содержать ровно два класса без пропусков.")
    if not target.eq(roles.positive_class).any():
        raise ValueError("Подтверждённое значение события отсутствует в целевой колонке.")
    if int(target.value_counts().min()) < 2:
        raise ValueError("Для каждого класса нужно минимум две строки для последующей проверки модели.")

    identifiers = frame[roles.identifier_column]
    if identifiers.isna().any() or identifiers.astype(str).str.strip().eq("").any():
        raise ValueError("Идентификатор не должен содержать пустые значения.")
    if not identifiers.is_unique:
        raise ValueError("Идентификатор повторяется. Для нескольких периодов одного ИНН нужен отдельный протокол.")

    allowed = tuple(roles.allowed_feature_columns)
    if not allowed or len(allowed) != len(set(allowed)):
        raise ValueError("Подтвердите непустой список признаков без повторов.")
    if any(name not in columns or name in {roles.target_column, roles.identifier_column} for name in allowed):
        raise ValueError("Цель, идентификатор и отсутствующие колонки нельзя разрешать как признаки.")
    blocked_proxy = {
        warning.column_name for warning in proposal.warnings
        if warning.code in {"potential_target_proxy", "potential_deterministic_target_proxy"}
        and warning.column_name is not None
    }
    if blocked_proxy.intersection(allowed):
        raise ValueError("Признаки с предупреждением о возможной утечке цели нельзя подтверждать автоматически.")
    for name in allowed:
        series = frame[name]
        if not (is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype)) or is_complex_dtype(series.dtype):
            raise ValueError(f"Признак «{name}» должен быть числовым или булевым.")
        if not np.isfinite(series.to_numpy(dtype=np.float64)).all():
            raise ValueError(f"Признак «{name}» содержит пропуски или бесконечные значения.")

    roles_identity: dict[str, Any] = {
        "snapshot_fingerprint": snapshot.fingerprint,
        "target_column": roles.target_column,
        "positive_class": roles.positive_class,
        "identifier_column": roles.identifier_column,
        "allowed_feature_columns": sorted(allowed),
    }
    confirmation_hash = stable_hash(roles_identity)
    registry_id = f"confirmed-features-{confirmation_hash[:16]}"
    allowed_set = set(allowed)
    specs = []
    group_members: dict[str, list[str]] = {
        "confirmed_predictors": [], "protected_columns": [], "excluded_columns": [],
    }
    for position, name in enumerate(columns):
        if name == roles.target_column:
            group_id, usage, reason = "protected_columns", FeatureUsageStatus.TARGET, None
        elif name == roles.identifier_column:
            group_id, usage, reason = "protected_columns", FeatureUsageStatus.IDENTIFIER, None
        elif name in allowed_set:
            group_id, usage, reason = "confirmed_predictors", FeatureUsageStatus.MODEL_ALLOWED, None
        else:
            group_id, usage, reason = "excluded_columns", FeatureUsageStatus.BLOCKED, "Не подтверждён как признак."
        group_members[group_id].append(name)
        specs.append(FeatureSpec(
            name, name, name, "Роль подтверждена пользователем при подготовке нового набора данных.",
            group_id, str(frame[name].dtype), "numeric" if name in allowed_set else usage.value,
            "user_confirmed_v1", usage, reason, snapshot.fingerprint, None, position,
        ))
    group_labels = {
        "confirmed_predictors": "Разрешённые признаки",
        "protected_columns": "Цель и идентификатор",
        "excluded_columns": "Исключённые столбцы",
    }
    groups = tuple(
        FeatureGroup(group_id, group_labels[group_id], "Подтверждённые роли столбцов.", order,
                     "user_confirmed_v1", tuple(group_members[group_id]))
        for order, group_id in enumerate(group_members) if group_members[group_id]
    )
    registry = FeatureRegistry(registry_id, specs, groups)
    dataset_fingerprint = stable_hash(roles_identity)
    contract = DatasetContract(
        dataset_id=f"user-dataset-{snapshot.fingerprint[:16]}",
        dataset_version="confirmed-v1",
        dataset_name=snapshot.source_path.name,
        source_type=f"ready_{snapshot.source_format}",
        dataset_fingerprint=dataset_fingerprint,
        row_count=len(frame),
        column_count=len(columns),
        target_column=roles.target_column,
        positive_class=roles.positive_class,
        identifier_column=roles.identifier_column,
        feature_registry_id=registry.registry_id,
        feature_registry_hash=registry.registry_hash,
        validation_status="confirmed_pending_protocol",
        final_test_locked=False,
    )
    population = EvaluationPopulation(
        tuple(range(len(frame))),
        f"user-full-{confirmation_hash[:16]}",
        stable_hash({"dataset_fingerprint": dataset_fingerprint, "row_count": len(frame), "role": "full"}),
        "full",
    )
    loaded = LoadedDataset(frame, contract, snapshot.source_path, snapshot.source_format, snapshot.source_file_sha256)
    return MaterializedDataset(loaded, registry, population, roles)
