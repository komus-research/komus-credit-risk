"""Generic fail-closed Dataset Preparation V1 materialization."""
from __future__ import annotations

from dataclasses import asdict
import math
from typing import Any

import numpy as np
import pandas as pd

from komus_risk.contracts import FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import ReadyDatasetAdapter, TabularSnapshot
from komus_risk.data.inspection import DatasetInspectionReport
from komus_risk.experiments import EvaluationPopulation
from komus_risk.registries import FeatureRegistry
from .context import PreparedDatasetContext
from .contracts import (
    ConfirmedColumnDecision, ConfirmedColumnStatus, ConfirmedDatasetPreparation,
    DatasetPreparationError, PopulationPolicyV1,
)
from .identity import CanonicalValueError, identity_hash
from .manifest import (
    CandidateConfirmationDelta, ColumnDecisionDelta, DatasetPreparationManifest,
    ProposalConfirmationDelta,
)

_STATUS_TO_USAGE = {
    ConfirmedColumnStatus.TARGET: FeatureUsageStatus.TARGET,
    ConfirmedColumnStatus.IDENTIFIER: FeatureUsageStatus.IDENTIFIER,
    ConfirmedColumnStatus.MODEL_ALLOWED: FeatureUsageStatus.MODEL_ALLOWED,
    ConfirmedColumnStatus.DIAGNOSTIC_ONLY: FeatureUsageStatus.DIAGNOSTIC_ONLY,
    ConfirmedColumnStatus.BLOCKED: FeatureUsageStatus.BLOCKED,
}


def inspection_report_hash(report: DatasetInspectionReport) -> str:
    return identity_hash({"inspection_report_v1": asdict(report)})


def proposal_hash(proposal: Any, report_hash: str) -> str:
    return identity_hash({"proposal_v1": asdict(proposal), "inspection_report_hash": report_hash})


def confirmation_hash(confirmation: ConfirmedDatasetPreparation) -> str:
    return identity_hash({"confirmation_v1": asdict(confirmation)})


class DatasetPreparationMaterializer:
    version = "1"

    def materialize(
        self,
        snapshot: TabularSnapshot,
        inspection_report: DatasetInspectionReport,
        proposal: Any,
        confirmation: ConfirmedDatasetPreparation,
    ) -> tuple[PreparedDatasetContext, DatasetPreparationManifest]:
        headers = tuple(snapshot.physical_headers)
        if not headers or tuple(snapshot.dataframe.columns) != headers:
            raise DatasetPreparationError("STALE_SNAPSHOT")
        if inspection_report.snapshot_fingerprint != snapshot.fingerprint or inspection_report.row_count != snapshot.row_count or inspection_report.column_count != snapshot.column_count:
            raise DatasetPreparationError("REPORT_IDENTITY_MISMATCH")
        actual_report_hash = inspection_report_hash(inspection_report)
        if confirmation.inspection_report_hash != actual_report_hash:
            raise DatasetPreparationError("REPORT_IDENTITY_MISMATCH")
        if proposal.snapshot_fingerprint != snapshot.fingerprint or proposal.inspection_policy_version != inspection_report.inspection_policy_version:
            raise DatasetPreparationError("PROPOSAL_IDENTITY_MISMATCH")
        actual_proposal_hash = proposal_hash(proposal, actual_report_hash)
        if confirmation.proposal_hash != actual_proposal_hash:
            raise DatasetPreparationError("PROPOSAL_IDENTITY_MISMATCH")
        if (confirmation.snapshot_fingerprint != snapshot.fingerprint or confirmation.proposal_policy_id != proposal.policy_id or
                confirmation.proposal_policy_version != proposal.policy_version or confirmation.proposal_policy_hash != proposal.policy_hash):
            raise DatasetPreparationError("CONFIRMATION_IDENTITY_MISMATCH")
        actual_confirmation_hash = confirmation_hash(confirmation)
        decisions = self._validate_confirmation(snapshot, confirmation)
        registry = self._registry(snapshot, inspection_report, decisions, actual_confirmation_hash)
        loaded = self._reload(snapshot, confirmation, registry)
        if loaded.contract.dataset_fingerprint != snapshot.fingerprint or loaded.source_file_sha256 != snapshot.source_file_sha256:
            raise DatasetPreparationError("STALE_SNAPSHOT")
        self._validate_semantics(loaded.dataframe, confirmation, decisions)
        self._validate_predictors(loaded.dataframe, decisions)
        population = self._population(loaded.contract.dataset_fingerprint, loaded.contract.row_count)
        dataset_id = loaded.contract.dataset_id
        context_id = identity_hash({
            "dataset_id": dataset_id, "dataset_version": loaded.contract.dataset_version,
            "dataset_fingerprint": loaded.contract.dataset_fingerprint, "feature_registry_id": registry.registry_id,
            "feature_registry_hash": registry.registry_hash, "population_id": population.population_id,
            "population_fingerprint": population.population_fingerprint,
        })
        context = PreparedDatasetContext(context_id, confirmation.dataset_name, loaded, registry, population)
        delta = self._delta(proposal, confirmation)
        materialization_identity = identity_hash({"context_id": context_id, "confirmation_hash": actual_confirmation_hash, "delta": delta.to_dict()})
        manifest = DatasetPreparationManifest(
            "1", self.version, snapshot.fingerprint, actual_report_hash, actual_proposal_hash, confirmation,
            actual_confirmation_hash, delta, dataset_id, loaded.contract.dataset_version,
            loaded.contract.dataset_fingerprint, registry.registry_id, registry.registry_hash,
            population.population_id, population.population_fingerprint, context_id, materialization_identity,
        )
        return context, manifest

    def _validate_confirmation(self, snapshot: TabularSnapshot, confirmation: ConfirmedDatasetPreparation) -> dict[str, ConfirmedColumnDecision]:
        if confirmation.population_policy is not PopulationPolicyV1.FULL_OOF_NO_PROTECTED_FINAL_TEST:
            raise DatasetPreparationError("PROTECTED_FINAL_TEST_NOT_SUPPORTED_V1")
        decisions = {item.column_name: item for item in confirmation.column_decisions}
        if len(decisions) != len(confirmation.column_decisions) or set(decisions) != set(snapshot.physical_headers):
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        if confirmation.target_column not in decisions or confirmation.identifier_column not in decisions:
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        if decisions[confirmation.target_column].status is not ConfirmedColumnStatus.TARGET:
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        if decisions[confirmation.identifier_column].status is not ConfirmedColumnStatus.IDENTIFIER:
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        target_decisions = [item for item in decisions.values() if item.status is ConfirmedColumnStatus.TARGET]
        identifier_decisions = [item for item in decisions.values() if item.status is ConfirmedColumnStatus.IDENTIFIER]
        if (len(target_decisions) != 1 or target_decisions[0].column_name != confirmation.target_column or
                len(identifier_decisions) != 1 or identifier_decisions[0].column_name != confirmation.identifier_column):
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        if not any(item.status is ConfirmedColumnStatus.MODEL_ALLOWED for item in decisions.values()):
            raise DatasetPreparationError("NO_MODEL_ALLOWED_FEATURES")
        return decisions

    def _validate_semantics(self, frame: pd.DataFrame, confirmation: ConfirmedDatasetPreparation, decisions: dict[str, ConfirmedColumnDecision]) -> None:
        target_name, identifier_name = confirmation.target_column, confirmation.identifier_column
        if target_name == identifier_name:
            raise DatasetPreparationError("TARGET_IDENTIFIER_CONFLICT")
        if target_name not in frame.columns or identifier_name not in frame.columns:
            raise DatasetPreparationError("INVALID_TARGET")
        positive = confirmation.positive_class
        if isinstance(positive, bool):
            pass
        elif isinstance(positive, int):
            pass
        elif isinstance(positive, float) and math.isfinite(positive):
            pass
        elif isinstance(positive, str):
            pass
        else:
            raise DatasetPreparationError("UNSUPPORTED_POSITIVE_CLASS_VALUE")
        target = frame[target_name]
        if target.isna().any() or target.nunique(dropna=True) != 2:
            raise DatasetPreparationError("INVALID_TARGET")
        if not target.eq(positive).any():
            raise DatasetPreparationError("POSITIVE_CLASS_MISSING")
        if int(target.value_counts(dropna=True).min()) < 2:
            raise DatasetPreparationError("INVALID_TARGET")

    @staticmethod
    def _validate_predictors(frame: pd.DataFrame, decisions: dict[str, ConfirmedColumnDecision]) -> None:
        for name, decision in decisions.items():
            if decision.status is not ConfirmedColumnStatus.MODEL_ALLOWED:
                continue
            series = frame[name]
            if pd.api.types.is_complex_dtype(series) or not (pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)):
                raise DatasetPreparationError("UNSUPPORTED_PREDICTOR_REPRESENTATION")
            try:
                values = series.to_numpy(dtype=np.float32)
            except (TypeError, ValueError, OverflowError) as error:
                raise DatasetPreparationError("UNSUPPORTED_PREDICTOR_REPRESENTATION") from error
            if not np.isfinite(values).all():
                raise DatasetPreparationError("NON_FINITE_PREDICTOR")

    def _registry(self, snapshot: TabularSnapshot, report: DatasetInspectionReport, decisions: dict[str, ConfirmedColumnDecision], confirmation_hash_value: str) -> FeatureRegistry:
        by_position = {column.column_position: column for column in report.columns}
        group_ids = {
            ConfirmedColumnStatus.MODEL_ALLOWED: "usage_model_allowed",
            ConfirmedColumnStatus.DIAGNOSTIC_ONLY: "usage_diagnostic_only",
            ConfirmedColumnStatus.IDENTIFIER: "usage_identifier",
            ConfirmedColumnStatus.TARGET: "usage_target",
            ConfirmedColumnStatus.BLOCKED: "usage_blocked",
        }
        group_metadata = {
            ConfirmedColumnStatus.MODEL_ALLOWED: ("Разрешённые признаки", "Признаки, явно подтверждённые для использования моделью."),
            ConfirmedColumnStatus.DIAGNOSTIC_ONLY: ("Диагностические признаки", "Признаки, доступные для анализа, но не выбранные для рабочего набора модели."),
            ConfirmedColumnStatus.IDENTIFIER: ("Идентификатор", "Подтверждённая колонка идентификатора."),
            ConfirmedColumnStatus.TARGET: ("Целевая переменная", "Подтверждённая целевая колонка."),
            ConfirmedColumnStatus.BLOCKED: ("Исключённые признаки", "Признаки, явно исключённые из использования."),
        }
        feature_ids_by_status: dict[ConfirmedColumnStatus, list[str]] = {status: [] for status in group_ids}
        features: list[FeatureSpec] = []
        for position, name in enumerate(snapshot.physical_headers):
            decision = decisions[name]
            column = by_position.get(position)
            if column is None or column.column_name != name:
                raise DatasetPreparationError("REPORT_IDENTITY_MISMATCH")
            feature_ids_by_status[decision.status].append(name)
            features.append(FeatureSpec(
                name, name, name, f"Физическая колонка исходного датасета. Подтверждённый технический статус: {decision.status.value}.",
                group_ids[decision.status], column.physical_dtype, "technical:" + column.inferred_logical_type,
                "dataset_preparation_v1_raw_column", _STATUS_TO_USAGE[decision.status], decision.blocked_reason if decision.status is ConfirmedColumnStatus.BLOCKED else None,
                f"snapshot:{snapshot.fingerprint}/column:{position}", None, position,
            ))
        groups = [FeatureGroup(group_ids[status], *group_metadata[status], index, "dataset_preparation_v1_status_grouping", tuple(ids))
                  for index, (status, ids) in enumerate(feature_ids_by_status.items()) if ids]
        return FeatureRegistry("feature-registry-v1:" + identity_hash({"snapshot_fingerprint": snapshot.fingerprint, "confirmation_hash": confirmation_hash_value}), features, groups)

    def _reload(self, snapshot: TabularSnapshot, confirmation: ConfirmedDatasetPreparation, registry: FeatureRegistry):
        options = snapshot.read_options
        return ReadyDatasetAdapter().load(
            snapshot.source_path, dataset_id="prepared-dataset-v1:" + identity_hash({"snapshot_fingerprint": snapshot.fingerprint}),
            dataset_version="confirmation-v1:" + confirmation_hash(confirmation), dataset_name=confirmation.dataset_name,
            target_column=confirmation.target_column, positive_class=confirmation.positive_class,
            identifier_column=confirmation.identifier_column, feature_registry_id=registry.registry_id,
            feature_registry_hash=registry.registry_hash, final_test_locked=False,
            separator=options.get("separator", ","), encoding=options.get("encoding", "utf-8"), sheet_name=options.get("sheet_name", 0),
        )

    @staticmethod
    def _population(dataset_fingerprint: str, row_count: int) -> EvaluationPopulation:
        positions = tuple(range(row_count))
        fingerprint = identity_hash({"dataset_fingerprint": dataset_fingerprint, "row_positions": positions, "partition_role": "full"})
        return EvaluationPopulation(positions, "full-population-v1:" + fingerprint, fingerprint, "full")

    @staticmethod
    def _delta(proposal: Any, confirmation: ConfirmedDatasetPreparation) -> ProposalConfirmationDelta:
        def candidate(items, name):
            for rank, item in enumerate(items, 1):
                if item.column_name == name:
                    return CandidateConfirmationDelta(name, rank, item.score_points)
            return CandidateConfirmationDelta(name, None, None)
        offered = any(item.target_column == confirmation.target_column and item.value == confirmation.positive_class for item in proposal.positive_class_candidates)
        roles = {item.column_name: item for item in proposal.column_roles}
        decisions = tuple(ColumnDecisionDelta(
            item.column_name,
            roles.get(item.column_name).role.value if item.column_name in roles else None,
            roles.get(item.column_name).predictor_eligibility.value if item.column_name in roles else None,
            item.status.value,
        ) for item in confirmation.column_decisions)
        return ProposalConfirmationDelta(candidate(proposal.target_candidates, confirmation.target_column), candidate(proposal.identifier_candidates, confirmation.identifier_column), offered, decisions)
