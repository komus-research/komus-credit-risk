"""Deterministic technical configuration preflight (MP-C)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from komus_risk.contracts import FeatureUsageStatus
from komus_risk.hashing import stable_hash
from komus_risk.preparation import PreparedDatasetContext

from .configuration import ResolvedModelConfiguration
from .contracts import ModelPlugin, _plain_json
from .provenance import ModelConfigurationRecord


class SmokeStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SmokeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SmokePolicy:
    policy_id: str = "technical_stratified_bounded"
    policy_version: str = "1"
    max_rows: int = 128

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_version or self.max_rows < 2:
            raise ValueError("Smoke policy is invalid.")

    @property
    def policy_hash(self) -> str:
        return stable_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "max_rows": self.max_rows,
        }


DEFAULT_SMOKE_POLICY = SmokePolicy()


@dataclass(frozen=True, slots=True)
class SmokeEvidence:
    evidence_schema_version: str
    status: SmokeStatus
    smoke_identity: str
    context_id: str
    dataset_id: str
    dataset_fingerprint: str
    feature_registry_id: str
    feature_registry_hash: str
    population_id: str
    population_fingerprint: str
    population_row_positions_hash: str
    selected_feature_ids: tuple[str, ...]
    selected_feature_set_hash: str
    plugin_contract_hash: str
    resolved_configuration_hash: str
    configuration_record_id: str
    seed: int
    policy_id: str
    policy_version: str
    policy_hash: str
    sampled_row_positions: tuple[int, ...]
    sampled_rows_hash: str
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_schema_version != "1" or not isinstance(
            self.status, SmokeStatus
        ):
            raise ValueError("Smoke evidence schema is invalid.")
        object.__setattr__(
            self, "selected_feature_ids", tuple(self.selected_feature_ids)
        )
        object.__setattr__(
            self, "sampled_row_positions", tuple(self.sampled_row_positions)
        )
        if not self.selected_feature_ids or len(set(self.selected_feature_ids)) != len(
            self.selected_feature_ids
        ):
            raise ValueError("Smoke evidence feature identity is invalid.")
        if self.selected_feature_set_hash != stable_hash(
            {"ordered_feature_ids": list(self.selected_feature_ids)}
        ):
            raise ValueError("Smoke evidence feature hash is invalid.")
        if (
            not isinstance(self.population_row_positions_hash, str)
            or not self.population_row_positions_hash
        ):
            raise ValueError("Smoke evidence population identity is invalid.")
        if self.sampled_rows_hash != stable_hash(
            {"row_positions": list(self.sampled_row_positions)}
        ):
            raise ValueError("Smoke evidence sample hash is invalid.")
        if self.smoke_identity != stable_hash(self.identity_payload()):
            raise ValueError("Smoke evidence identity is invalid.")
        if self.status is SmokeStatus.PASS and self.failure_code is not None:
            raise ValueError("Smoke PASS cannot contain a failure code.")
        if self.status is SmokeStatus.FAIL and not self.failure_code:
            raise ValueError("Smoke FAIL requires a failure code.")

    def identity_payload(self) -> dict[str, Any]:
        value = self.to_dict()
        for key in (
            "smoke_identity",
            "status",
            "sampled_row_positions",
            "sampled_rows_hash",
            "failure_code",
        ):
            value.pop(key)
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_schema_version": self.evidence_schema_version,
            "status": self.status.value,
            "smoke_identity": self.smoke_identity,
            "context_id": self.context_id,
            "dataset_id": self.dataset_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "feature_registry_id": self.feature_registry_id,
            "feature_registry_hash": self.feature_registry_hash,
            "population_id": self.population_id,
            "population_fingerprint": self.population_fingerprint,
            "population_row_positions_hash": self.population_row_positions_hash,
            "selected_feature_ids": list(self.selected_feature_ids),
            "selected_feature_set_hash": self.selected_feature_set_hash,
            "plugin_contract_hash": self.plugin_contract_hash,
            "resolved_configuration_hash": self.resolved_configuration_hash,
            "configuration_record_id": self.configuration_record_id,
            "seed": self.seed,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "sampled_row_positions": list(self.sampled_row_positions),
            "sampled_rows_hash": self.sampled_rows_hash,
            "failure_code": self.failure_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmokeEvidence:
        payload = dict(value)
        payload["status"] = SmokeStatus(payload["status"])
        return cls(**payload)


class ModelConfigurationSmokeTestService:
    """Runs a bounded fit/predict check; it deliberately computes no quality metrics."""

    def __init__(self, policy: SmokePolicy = DEFAULT_SMOKE_POLICY) -> None:
        self.policy = policy

    def expected_identity(
        self,
        context: PreparedDatasetContext,
        selected_feature_ids: tuple[str, ...],
        record: ModelConfigurationRecord,
        seed: int,
    ) -> str:
        return stable_hash(
            self._identity_payload(context, selected_feature_ids, record, seed)
        )

    def run(
        self,
        context: PreparedDatasetContext,
        selected_feature_ids: tuple[str, ...],
        resolved_configuration: ResolvedModelConfiguration,
        seed: int,
        plugin: ModelPlugin,
    ) -> SmokeEvidence:
        record = ModelConfigurationRecord.from_resolved(resolved_configuration, plugin)
        selected = tuple(selected_feature_ids)
        sampled: tuple[int, ...] = ()
        try:
            columns, frame, y = self._validate_and_frame(
                context, selected, plugin, record
            )
            sampled = self._sample_rows(context.population.row_positions, y, seed)
            smoke_frame = frame.iloc[list(sampled)].loc[:, columns]
            smoke_y = y.iloc[list(sampled)]
            adapter = plugin.factory.create(
                _plain_json(record.resolved_parameters),
                seed,
            )
            adapter.fit(smoke_frame, smoke_y)
            values = np.asarray(
                adapter.predict_positive_proba(smoke_frame), dtype=float
            )
            if values.ndim != 1 or len(values) != len(smoke_frame):
                raise SmokeError("INVALID_PREDICTION_SHAPE")
            if not np.isfinite(values).all():
                raise SmokeError("INVALID_PREDICTION_NON_FINITE")
            if (values < 0).any() or (values > 1).any():
                raise SmokeError("INVALID_PREDICTION_RANGE")
            return self._evidence(
                SmokeStatus.PASS, context, selected, record, seed, sampled, None
            )
        except SmokeError as error:
            return self._evidence(
                SmokeStatus.FAIL, context, selected, record, seed, sampled, error.code
            )
        except Exception:  # noqa: BLE001 - model adapters are third-party boundaries
            return self._evidence(
                SmokeStatus.FAIL,
                context,
                selected,
                record,
                seed,
                sampled,
                "SMOKE_RUNTIME_FAILURE",
            )

    def _validate_and_frame(self, context, selected, plugin, record):
        contract = context.loaded_dataset.contract
        frame = context.loaded_dataset.dataframe
        if (
            contract.validation_status != "validated"
            or len(frame) != contract.row_count
        ):
            raise SmokeError("INVALID_DATASET_CONTEXT")
        if (
            contract.feature_registry_id != context.feature_registry.registry_id
            or contract.feature_registry_hash != context.feature_registry.registry_hash
        ):
            raise SmokeError("INVALID_DATASET_CONTEXT")
        if (
            contract.final_test_locked
            and context.population.partition_role != "working"
        ):
            raise SmokeError("INVALID_EVALUATION_POPULATION")
        if any(position >= len(frame) for position in context.population.row_positions):
            raise SmokeError("INVALID_EVALUATION_POPULATION")
        if plugin.plugin_contract_hash != record.plugin_contract_hash:
            raise SmokeError("PLUGIN_CONTRACT_MISMATCH")
        specs = context.feature_registry.resolve(selected)
        if any(
            spec.usage_status is not FeatureUsageStatus.MODEL_ALLOWED for spec in specs
        ):
            raise SmokeError("INVALID_FEATURE_SELECTION")
        columns = [spec.column_name for spec in specs]
        if not columns or any(column not in frame.columns for column in columns):
            raise SmokeError("INVALID_FEATURE_SELECTION")
        if contract.target_column in columns or contract.identifier_column in columns:
            raise SmokeError("INVALID_FEATURE_SELECTION")
        y = frame[contract.target_column].eq(contract.positive_class).astype(int)
        working_y = y.iloc[list(context.population.row_positions)]
        if working_y.nunique() != 2:
            raise SmokeError("INVALID_EVALUATION_POPULATION")
        return columns, frame, y

    def _sample_rows(self, population_rows, y: pd.Series, seed: int) -> tuple[int, ...]:
        positions = np.asarray(tuple(population_rows), dtype=int)
        labels = y.iloc[positions].to_numpy()
        rng = np.random.default_rng(seed)
        cap = min(len(positions), self.policy.max_rows)
        chosen: list[int] = []
        for label in (0, 1):
            group = positions[labels == label]
            count = min(len(group), max(1, cap // 2))
            chosen.extend(rng.permutation(group)[:count].tolist())
        if len(chosen) < cap:
            remaining = np.asarray(
                [row for row in positions if row not in set(chosen)], dtype=int
            )
            chosen.extend(rng.permutation(remaining)[: cap - len(chosen)].tolist())
        return tuple(sorted(chosen))

    def _identity_payload(self, context, selected, record, seed):
        contract = context.loaded_dataset.contract
        return {
            "evidence_schema_version": "1",
            "context_id": context.context_id,
            "dataset_id": contract.dataset_id,
            "dataset_fingerprint": contract.dataset_fingerprint,
            "feature_registry_id": context.feature_registry.registry_id,
            "feature_registry_hash": context.feature_registry.registry_hash,
            "population_id": context.population.population_id,
            "population_fingerprint": context.population.population_fingerprint,
            "population_row_positions_hash": stable_hash(
                {"row_positions": list(context.population.row_positions)}
            ),
            "selected_feature_ids": list(selected),
            "selected_feature_set_hash": stable_hash(
                {"ordered_feature_ids": list(selected)}
            ),
            "plugin_contract_hash": record.plugin_contract_hash,
            "resolved_configuration_hash": record.resolved_configuration_hash,
            "configuration_record_id": record.configuration_record_id,
            "seed": seed,
            "policy_id": self.policy.policy_id,
            "policy_version": self.policy.policy_version,
            "policy_hash": self.policy.policy_hash,
        }

    def _evidence(self, status, context, selected, record, seed, sampled, failure):
        payload = self._identity_payload(context, selected, record, seed)
        return SmokeEvidence(
            **payload,
            status=status,
            smoke_identity=stable_hash(payload),
            sampled_row_positions=sampled,
            sampled_rows_hash=stable_hash({"row_positions": list(sampled)}),
            failure_code=failure,
        )
