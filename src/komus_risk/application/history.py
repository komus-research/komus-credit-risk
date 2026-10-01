"""Read-only application projection over immutable experiment artifacts."""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import isfinite
from numbers import Real
from types import MappingProxyType
from typing import Any, Mapping

from komus_risk.artifacts import ExperimentArtifactMetadata, ExperimentArtifactStore


_MAX_LIMIT = 100
_SORTS = frozenset({"CREATED_DESC", "CREATED_ASC"})


class AnalysisHistoryError(ValueError):
    """Stable application error for History requests."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AnalysisHistoryItem:
    artifact_id: str
    result_id: str
    created_at: str
    dataset_name: str
    dataset_id: str
    model_id: str
    model_version: str
    feature_count: int
    folds: int
    evaluation_level: str
    gini: float
    result_access: str


@dataclass(frozen=True, slots=True)
class AnalysisHistoryPage:
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    returned_count: int
    items: tuple[AnalysisHistoryItem, ...]


@dataclass(frozen=True, slots=True)
class AnalysisHistoryDetail(AnalysisHistoryItem):
    dataset_version: str
    dataset_fingerprint: str
    protocol_id: str
    protocol_version: str
    config_hash: str
    feature_set_hash: str
    metrics: Mapping[str, Any]
    confusion: Mapping[str, Any]
    fold_metrics: tuple[Mapping[str, Any], ...]
    runtime_seconds: float | None
    limitations: tuple[str, ...]
    code_version: str


class AnalysisHistoryService:
    """Lists trusted artifact metadata and opens a full validated artifact on demand."""

    def __init__(self, artifact_store: ExperimentArtifactStore) -> None:
        self.artifact_store = artifact_store

    def list(
        self,
        offset: int,
        limit: int,
        search: str | None = None,
        model_id: str | None = None,
        sort: str = "CREATED_DESC",
    ) -> AnalysisHistoryPage:
        self._validate_query(offset, limit, search, model_id, sort)
        try:
            metadata = self.artifact_store.browse_metadata()
            items = tuple(self._item(entry) for entry in metadata)
        except AnalysisHistoryError:
            raise
        except Exception as error:
            raise AnalysisHistoryError("HISTORY_STORE_INVALID") from error

        needle = search.casefold() if search else None
        filtered = [
            item for item in items
            if (model_id is None or item.model_id == model_id)
            and (
                needle is None
                or needle in item.dataset_name.casefold()
                or needle in item.model_id.casefold()
            )
        ]
        filtered.sort(key=lambda item: item.artifact_id)
        filtered.sort(
            key=lambda item: item.created_at,
            reverse=(sort == "CREATED_DESC"),
        )
        page_items = tuple(filtered[offset : offset + limit])
        return AnalysisHistoryPage(
            total_count=len(items),
            filtered_count=len(filtered),
            offset=offset,
            limit=limit,
            returned_count=len(page_items),
            items=page_items,
        )

    def detail(self, artifact_id: str) -> AnalysisHistoryDetail:
        try:
            artifact = self.artifact_store.load(artifact_id)
            result = artifact.run_output.result
            item = self._item(
                ExperimentArtifactMetadata(
                    artifact.artifact_id,
                    str(artifact.manifest["artifact_schema_version"]),
                    artifact.config,
                    artifact.dataset_contract,
                    result,
                    artifact.population.population_id,
                    artifact.population.population_fingerprint,
                    len(artifact.population.row_positions),
                )
            )
            return AnalysisHistoryDetail(
                **{field.name: getattr(item, field.name) for field in fields(AnalysisHistoryItem)},
                dataset_version=artifact.dataset_contract.dataset_version,
                dataset_fingerprint=artifact.dataset_contract.dataset_fingerprint,
                protocol_id=artifact.config.protocol_id,
                protocol_version=artifact.config.protocol_version,
                config_hash=artifact.config.config_hash,
                feature_set_hash=result.feature_set_hash,
                metrics=_freeze(result.metrics),
                confusion=_freeze(result.confusion),
                fold_metrics=tuple(_freeze(row) for row in result.fold_metrics),
                runtime_seconds=result.runtime_seconds,
                limitations=tuple(result.limitations),
                code_version=result.code_version,
            )
        except AnalysisHistoryError:
            raise
        except Exception as error:
            raise AnalysisHistoryError("ARTIFACT_NOT_FOUND_OR_INVALID") from error

    @staticmethod
    def _validate_query(
        offset: int,
        limit: int,
        search: str | None,
        model_id: str | None,
        sort: str,
    ) -> None:
        if (
            isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_LIMIT
            or (search is not None and not isinstance(search, str))
            or (model_id is not None and (not isinstance(model_id, str) or not model_id.strip()))
            or not isinstance(sort, str) or sort not in _SORTS
        ):
            raise AnalysisHistoryError("INVALID_QUERY")

    @staticmethod
    def _item(metadata: ExperimentArtifactMetadata) -> AnalysisHistoryItem:
        gini = metadata.result.metrics.get("gini")
        if isinstance(gini, bool) or not isinstance(gini, Real) or not isfinite(float(gini)):
            raise AnalysisHistoryError("HISTORY_STORE_INVALID")
        schema_version = metadata.artifact_schema_version
        if schema_version not in {"1", "2", "3"}:
            raise AnalysisHistoryError("HISTORY_STORE_INVALID")
        return AnalysisHistoryItem(
            artifact_id=metadata.artifact_id,
            result_id=metadata.result.result_id,
            created_at=metadata.result.created_at,
            dataset_name=metadata.dataset_contract.dataset_name,
            dataset_id=metadata.dataset_contract.dataset_id,
            model_id=metadata.config.model_id,
            model_version=metadata.config.model_version,
            feature_count=len(metadata.config.feature_ids),
            folds=metadata.config.folds,
            evaluation_level=metadata.config.evaluation_level,
            gini=float(gini),
            result_access="FULL_RESULT_V2" if schema_version == "3" else "LEGACY_SUMMARY_ONLY",
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value
