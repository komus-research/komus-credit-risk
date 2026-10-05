"""Idempotent orchestration of final fit and its persistent library binding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from threading import Lock, RLock
from typing import Any

from komus_risk.artifacts import ModelLibraryRecord, ModelLibraryRecordStore, ModelVersionStore

from .integration_workflow import IntegrationWorkflowService
from .model_save_errors import (
    ModelSaveBindingConflict,
    ModelSaveContextNotReady,
    ModelSaveError,
    ModelSaveIncompatible,
)
from .model_library_errors import (
    InvalidModelDisplayName,
    InvalidModelLibraryQuery,
    ModelSourceResultUnavailable,
    ModelVersionIntegrityError,
    ModelVersionNotFound,
)


_model_locks: dict[tuple[str, str], Lock] = {}
_model_locks_guard = RLock()


@dataclass(frozen=True, slots=True)
class SavedModelResult:
    save_state: str
    record: ModelLibraryRecord


@dataclass(frozen=True, slots=True)
class ModelLibraryPage:
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ModelLibraryDetail:
    value: dict[str, Any]


class ModelLibraryService:
    """Owns the one-artifact/one-model invariant in a native process."""

    def __init__(
        self,
        *,
        record_store: ModelLibraryRecordStore,
        model_version_store: ModelVersionStore,
        integration_workflow_service: IntegrationWorkflowService,
        experiment_artifact_store: Any | None = None,
    ) -> None:
        self.record_store = record_store
        self.model_version_store = model_version_store
        self.integration_workflow_service = integration_workflow_service
        self.experiment_artifact_store = experiment_artifact_store
        self._locks: dict[str, Lock] = {}
        self._locks_guard = RLock()

    def find_for_experiment(self, experiment_artifact_id: str) -> ModelLibraryRecord | None:
        try:
            record = self.record_store.find_by_experiment_artifact_id(experiment_artifact_id)
            if record is None:
                return None
            self._verified_model(record)
            return record
        except ModelSaveError:
            raise
        except ValueError as error:
            raise ModelSaveBindingConflict() from error

    def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        search: str | None = None,
        model_id: str | None = None,
        dataset_id: str | None = None,
        saved_from: str | None = None,
        saved_to: str | None = None,
        sort: str = "SAVED_DESC",
    ) -> ModelLibraryPage:
        if (
            isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100
            or sort != "SAVED_DESC"
        ):
            raise InvalidModelLibraryQuery()
        start, end = self._parse_dates(saved_from, saved_to)
        if search is not None and (not isinstance(search, str) or not search.strip()):
            raise InvalidModelLibraryQuery()
        if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in (model_id, dataset_id)):
            raise InvalidModelLibraryQuery()
        records = self._records()
        total_count = len(records)
        items = [self._list_item(record) for record in records]
        needle = search.casefold().strip() if search else None
        filtered = [
            item for item in items
            if (model_id is None or item["model_id"] == model_id)
            and (dataset_id is None or item["dataset_id"] == dataset_id)
            and (start is None or self._date(item["saved_at"]) >= start)
            and (end is None or self._date(item["saved_at"]) <= end)
            and (needle is None or needle in " ".join((item["display_name"], item["model_display_name"], item["dataset_name"])).casefold())
        ]
        filtered.sort(key=lambda item: item["saved_at"], reverse=True)
        return ModelLibraryPage(total_count, len(filtered), offset, limit, tuple(filtered[offset : offset + limit]))

    def detail(self, model_version_id: str) -> ModelLibraryDetail:
        if not isinstance(model_version_id, str) or not model_version_id.strip():
            raise ModelVersionNotFound()
        record = next((item for item in self._records() if item.model_version_id == model_version_id), None)
        if record is None:
            raise ModelVersionNotFound()
        metadata, artifact = self._trusted_join(record)
        model = metadata.metadata
        config = model["config"]
        dataset = model["dataset_contract"]
        population = model["population"]
        configuration = model.get("configuration_record", {})
        result = artifact.result
        adapter_version = self._adapter_version(model)
        capabilities = self._capabilities(config["model_id"], adapter_version)
        technical_provenance = {
            "config_hash": model["config_hash"], "feature_set_hash": model["feature_set_hash"],
            "feature_registry_id": model["feature_registry"]["registry_id"], "feature_registry_hash": model["feature_registry"]["registry_hash"],
            "source_file_sha256": model["source_file_sha256"], "code_version": model["code_version"],
            "runtime": model["runtime"], "persistence_provider": model.get("persistence_provider"),
            "native_hashes": model["native_hashes"],
        }
        for key in ("plugin_contract_hash", "configuration_record_id"):
            if key in configuration:
                technical_provenance[key] = configuration[key]
        return ModelLibraryDetail({
            "model_version_id": record.model_version_id,
            "experiment_artifact_id": record.experiment_artifact_id,
            "display_name": record.display_name,
            "display_version": record.display_version,
            "saved_at": record.saved_at,
            "status": "SAVED",
            "algorithm": {
                "model_id": config["model_id"],
                "model_display_name": self._display_name(config["model_id"]),
                "algorithm_version": config["model_version"],
                "adapter_version": adapter_version,
                "source": model.get("persistence_provider"),
                "capabilities": capabilities,
            },
            "dataset": {
                "dataset_id": dataset["dataset_id"], "dataset_name": dataset["dataset_name"],
                "dataset_version": dataset["dataset_version"], "dataset_fingerprint": dataset["dataset_fingerprint"],
            },
            "population": {
                "population_id": population["population_id"], "population_fingerprint": population["population_fingerprint"],
                "population_role": population["partition_role"], "population_row_count": len(population["row_positions"]),
            },
            "target": dataset["target_column"], "positive_class": dataset["positive_class"], "identifier": dataset["identifier_column"],
            "features": [
                {"feature_id": item["feature_id"], "column_name": item["column_name"],
                 "display_name": item["display_name_ru"], "description": item["description_ru"],
                 "logical_type": item["semantic_type"], "usage_status": item["usage_status"]}
                for item in model["feature_specs"]
            ],
            "configuration": {
                "configuration_mode": configuration.get("mode"),
                "user_overrides": configuration.get("user_overrides"),
                "resolved_parameters": configuration.get("resolved_parameters", config["model_parameters"]),
                "seed": config["seed"], "folds": config["folds"],
                "protocol_id": config["protocol_id"], "protocol_version": config["protocol_version"],
                "evaluation_level": config["evaluation_level"],
            },
            "oof_quality": self._quality(result.metrics),
            "source_result": {"experiment_artifact_id": record.experiment_artifact_id, "result_id": result.result_id, "experiment_created_at": result.created_at},
            "technical_provenance": technical_provenance,
        })

    def rename(self, model_version_id: str, display_name: str) -> ModelLibraryRecord:
        if not isinstance(model_version_id, str) or not model_version_id.strip():
            raise ModelVersionNotFound()
        normalized = self._normalize_display_name(display_name)
        record = next((item for item in self._records() if item.model_version_id == model_version_id), None)
        if record is None:
            raise ModelVersionNotFound()
        with self._lock_for(record.experiment_artifact_id):
            try:
                current = self.record_store.find_by_experiment_artifact_id(record.experiment_artifact_id)
            except ValueError as error:
                raise ModelVersionIntegrityError() from error
            if current is None or current.model_version_id != model_version_id:
                raise ModelVersionIntegrityError()
            self._trusted_join(current)
            if current.display_name == normalized:
                return current
            try:
                return self.record_store.update_display_name(
                    experiment_artifact_id=current.experiment_artifact_id,
                    model_version_id=current.model_version_id,
                    display_name=normalized,
                )
            except ValueError as error:
                raise ModelVersionIntegrityError() from error

    @staticmethod
    def _normalize_display_name(value: str) -> str:
        if not isinstance(value, str):
            raise InvalidModelDisplayName()
        normalized = value.strip()
        if not normalized or len(normalized) > 160 or any(character in normalized for character in ("\r", "\n", "\x00")):
            raise InvalidModelDisplayName()
        return normalized

    def _records(self) -> tuple[ModelLibraryRecord, ...]:
        try:
            return self.record_store.list()
        except ValueError as error:
            raise ModelVersionIntegrityError() from error

    def _list_item(self, record: ModelLibraryRecord) -> dict[str, Any]:
        metadata, artifact = self._trusted_join(record)
        model = metadata.metadata
        dataset = model["dataset_contract"]
        return {
            "model_version_id": record.model_version_id, "experiment_artifact_id": record.experiment_artifact_id,
            "display_name": record.display_name, "display_version": record.display_version, "saved_at": record.saved_at,
            "model_id": model["model_id"], "model_display_name": self._display_name(model["model_id"]),
            "algorithm_version": model["model_version"], "dataset_id": dataset["dataset_id"],
            "dataset_name": dataset["dataset_name"], "feature_count": len(model["feature_ids"]),
            **self._quality(artifact.result.metrics, abbreviated=True),
        }

    def _trusted_join(self, record: ModelLibraryRecord):
        if self.experiment_artifact_store is None:
            raise ModelSourceResultUnavailable()
        try:
            metadata = self.model_version_store.inspect_metadata(record.model_version_id)
            bound_versions = self.model_version_store.find_by_experiment_artifact_id(
                record.experiment_artifact_id
            )
            if (
                len(bound_versions) != 1
                or bound_versions[0].model_version_id != record.model_version_id
                or metadata.summary.experiment_artifact_id != record.experiment_artifact_id
            ):
                raise ValueError
        except Exception as error:
            raise ModelVersionIntegrityError() from error
        try:
            artifact = self.experiment_artifact_store.read_metadata(record.experiment_artifact_id)
        except Exception as error:
            raise ModelSourceResultUnavailable() from error
        if artifact.artifact_id != record.experiment_artifact_id:
            raise ModelSourceResultUnavailable()
        return metadata, artifact

    @staticmethod
    def _quality(metrics: dict[str, Any], *, abbreviated: bool = False) -> dict[str, float]:
        names = ("gini", "roc_auc", "pr_auc") if abbreviated else ("gini", "roc_auc", "pr_auc", "precision_at_0_5", "recall_at_0_5", "f1_at_0_5")
        value: dict[str, float] = {}
        for name in names:
            raw = metrics.get(name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(float(raw)):
                raise ModelSourceResultUnavailable()
            value[("oof_" + name) if abbreviated else name] = float(raw)
        return value

    @staticmethod
    def _date(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    def _parse_dates(self, saved_from: str | None, saved_to: str | None):
        try:
            start = self._date(saved_from) if saved_from is not None else None
            end = self._date(saved_to) if saved_to is not None else None
        except (TypeError, ValueError) as error:
            raise InvalidModelLibraryQuery() from error
        if start is not None and end is not None and start > end:
            raise InvalidModelLibraryQuery()
        return start, end

    def _capabilities(self, model_id: str, adapter_version: Any) -> Any:
        registry = getattr(self.model_version_store, "_model_plugin_registry", None)
        if registry is None:
            return None
        try:
            plugin = registry.get(model_id)
            if plugin.spec.adapter_version != adapter_version:
                return None
            return plugin.capability_manifest.to_dict()["capabilities"]
        except (KeyError, ValueError, AttributeError):
            return None

    def _display_name(self, model_id: str) -> str:
        try:
            return self.model_version_store.display_name_for(model_id)
        except (AttributeError, KeyError, ValueError) as error:
            raise ModelVersionIntegrityError() from error

    @staticmethod
    def _adapter_version(model: dict[str, Any]) -> str:
        value = model.get("adapter_version")
        if value is None:
            recipe = model.get("model_recipe")
            value = recipe.get("adapter_version") if isinstance(recipe, dict) else None
        if not isinstance(value, str) or not value:
            raise ModelVersionIntegrityError()
        return value

    def ensure_saved(self, *, experiment_artifact_id: str, prepared_dataset_context: Any) -> SavedModelResult:
        if prepared_dataset_context is None:
            raise ModelSaveContextNotReady()
        try:
            return self._ensure_saved(
                experiment_artifact_id=experiment_artifact_id,
                prepared_dataset_context=prepared_dataset_context,
            )
        except ModelSaveError:
            raise
        except ValueError as error:
            raise ModelSaveBindingConflict() from error

    def _ensure_saved(self, *, experiment_artifact_id: str, prepared_dataset_context: Any) -> SavedModelResult:
        with self._lock_for(experiment_artifact_id):
            record = self.record_store.find_by_experiment_artifact_id(experiment_artifact_id)
            if record is not None:
                self._verified_model(record)
                return SavedModelResult("ALREADY_SAVED", record)

            versions = self.model_version_store.find_by_experiment_artifact_id(experiment_artifact_id)
            if len(versions) > 1:
                raise ModelSaveBindingConflict()
            if len(versions) == 1:
                loaded = self._verified_summary(versions[0], experiment_artifact_id)
                return SavedModelResult(
                    "ALREADY_SAVED",
                    self._allocate_and_save_record(loaded, prepared_dataset_context),
                )

            try:
                loaded = self.integration_workflow_service.save_model(
                    experiment_artifact_id=experiment_artifact_id,
                    prepared_dataset_context=prepared_dataset_context,
                )
            except ModelSaveError:
                raise
            except ValueError as error:
                raise ModelSaveIncompatible() from error
            verified = self.model_version_store.find_by_experiment_artifact_id(experiment_artifact_id)
            if len(verified) != 1 or verified[0].model_version_id != loaded.summary.model_version_id:
                raise ModelSaveBindingConflict()
            loaded = self._verified_summary(verified[0], experiment_artifact_id)
            return SavedModelResult(
                "CREATED",
                self._allocate_and_save_record(loaded, prepared_dataset_context),
            )

    def _allocate_and_save_record(self, loaded: Any, context: Any) -> ModelLibraryRecord:
        """Allocate and persist vN as one critical section per library/model."""
        with self._model_lock_for(loaded.summary.model_id):
            return self._save_record(self._new_record(loaded, context))

    def _save_record(self, record: ModelLibraryRecord) -> ModelLibraryRecord:
        try:
            return self.record_store.save(record)
        except ValueError as error:
            if str(error) == ModelSaveBindingConflict.code:
                raise ModelSaveBindingConflict() from error
            raise

    def _verified_model(self, record: ModelLibraryRecord):
        summaries = self.model_version_store.find_by_experiment_artifact_id(record.experiment_artifact_id)
        if len(summaries) != 1 or summaries[0].model_version_id != record.model_version_id:
            raise ModelSaveBindingConflict()
        return self._verified_summary(summaries[0], record.experiment_artifact_id)

    def _verified_summary(self, summary: Any, experiment_artifact_id: str):
        try:
            loaded = self.model_version_store.load(summary.model_version_id)
        except Exception as error:
            raise ModelSaveBindingConflict() from error
        if loaded.summary.experiment_artifact_id != experiment_artifact_id:
            raise ModelSaveBindingConflict()
        return loaded

    def _new_record(self, loaded: Any, context: Any) -> ModelLibraryRecord:
        try:
            dataset_name = context.display_name
            if not isinstance(dataset_name, str) or not dataset_name.strip():
                raise ValueError
        except (AttributeError, ValueError) as error:
            raise ModelSaveContextNotReady() from error
        try:
            model_name = self.model_version_store.display_name_for(loaded.summary.model_id)
        except (AttributeError, KeyError, ValueError) as error:
            raise ModelSaveIncompatible() from error
        display_version = self._next_display_version(loaded.summary.model_id)
        return ModelLibraryRecord(
            schema_version=1,
            experiment_artifact_id=loaded.summary.experiment_artifact_id,
            model_version_id=loaded.summary.model_version_id,
            display_name=f"{model_name} — {dataset_name} — {display_version}",
            display_version=display_version,
            saved_at=self.record_store.now(),
        )

    def _next_display_version(self, model_id: str) -> str:
        largest = 0
        for record in self.record_store.list():
            summaries = self.model_version_store.find_by_experiment_artifact_id(record.experiment_artifact_id)
            if len(summaries) != 1:
                raise ModelSaveBindingConflict()
            if summaries[0].model_id == model_id:
                largest = max(largest, int(record.display_version[1:]))
        return f"v{largest + 1}"

    def _lock_for(self, experiment_artifact_id: str) -> Lock:
        with self._locks_guard:
            return self._locks.setdefault(experiment_artifact_id, Lock())

    def _model_lock_for(self, model_id: str) -> Lock:
        key = (str(self.record_store.root.resolve()), model_id)
        with _model_locks_guard:
            return _model_locks.setdefault(key, Lock())
