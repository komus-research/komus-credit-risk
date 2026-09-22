"""Activate an explicitly confirmed, non-temporal dataset for exploratory OOF."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from pandas.api.types import is_datetime64_any_dtype

from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.registries import FeatureRegistry

from .materialization import MaterializedDataset


@dataclass(frozen=True, slots=True)
class EvaluationReadyDataset:
    """New-file OOF context, deliberately without a locked final test or saved model."""

    loaded_dataset: LoadedDataset
    feature_registry: FeatureRegistry
    population: EvaluationPopulation
    protocol_id: str = "stratified_kfold_oof"
    protocol_version: str = "1"


def suspected_temporal_columns(materialized: MaterializedDataset) -> tuple[str, ...]:
    """Conservatively flag date/period columns that need a different evaluation protocol."""
    frame = materialized.loaded_dataset.dataframe
    protected = {materialized.roles.target_column, materialized.roles.identifier_column}
    indicators = ("date", "period", "year", "дата", "период", "год")
    found = []
    for name in frame.columns:
        if name in protected:
            continue
        words = name.lower().replace("-", "_").replace(" ", "_").split("_")
        if is_datetime64_any_dtype(frame[name].dtype) or any(word in indicators for word in words):
            found.append(name)
    return tuple(found)


def prepare_oof_evaluation(
    materialized: MaterializedDataset, *, confirm_no_time_axis: bool,
) -> EvaluationReadyDataset:
    """Promote only a same-file, one-row-per-ID snapshot to the existing OOF runner."""
    if not isinstance(materialized, MaterializedDataset):
        raise TypeError("Нужен подтверждённый датасет нового файла.")
    loaded = materialized.loaded_dataset
    contract = loaded.contract
    frame = loaded.dataframe
    roles = materialized.roles
    if not confirm_no_time_axis:
        raise ValueError("Подтвердите, что строки не образуют временную последовательность наблюдений.")
    if contract.validation_status != "confirmed_pending_protocol" or contract.final_test_locked:
        raise ValueError("Протокол можно утвердить только для подтверждённого нового датасета.")
    if contract.target_column != roles.target_column or contract.identifier_column != roles.identifier_column:
        raise ValueError("Роли столбцов не соответствуют паспорту датасета.")
    if contract.feature_registry_id != materialized.feature_registry.registry_id or contract.feature_registry_hash != materialized.feature_registry.registry_hash:
        raise ValueError("Реестр признаков не соответствует паспорту датасета.")
    if len(frame) != contract.row_count or materialized.population.row_positions != tuple(range(len(frame))):
        raise ValueError("Популяция нового файла должна содержать каждую строку ровно один раз.")
    if materialized.population.partition_role != "full":
        raise ValueError("Для нового OOF-протокола требуется полная популяция файла.")
    if suspected := suspected_temporal_columns(materialized):
        raise ValueError("Обнаружены возможные временные столбцы: " + ", ".join(suspected) + ". Нужен отдельный временной протокол.")
    identifiers = frame[roles.identifier_column]
    if identifiers.isna().any() or not identifiers.is_unique:
        raise ValueError("Для этого OOF-протокола нужен один непустой ИНН на строку без повторов.")
    target = frame[roles.target_column]
    if target.isna().any() or target.nunique(dropna=False) != 2 or not target.eq(roles.positive_class).any():
        raise ValueError("Для OOF нужна подтверждённая бинарная цель без пропусков.")
    if len(frame) < 60 or int(target.value_counts().min()) < 30:
        raise ValueError("Для OOF и внутренней проверки бустинга нужно не менее 60 строк и 30 наблюдений каждого класса.")
    if not loaded.source_path.is_file():
        raise ValueError("Исходный файл больше не найден; проверьте источник повторно.")
    digest = sha256()
    with loaded.source_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != loaded.source_file_sha256:
        raise ValueError("Исходный файл изменился после подтверждения; изучите его повторно.")
    validated = replace(contract, validation_status="validated")
    return EvaluationReadyDataset(
        replace(loaded, contract=validated), materialized.feature_registry, materialized.population,
    )
