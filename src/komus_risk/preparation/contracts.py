"""Proposal-only contracts for Dataset Onboarding V1."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import StrEnum
import math
from typing import Any

import numpy as np


class DatasetPreparationError(ValueError):
    """Fail-closed Dataset Preparation V1 error with a stable code."""
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ConfirmedColumnStatus(StrEnum):
    TARGET = "TARGET"
    IDENTIFIER = "IDENTIFIER"
    MODEL_ALLOWED = "MODEL_ALLOWED"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    BLOCKED = "BLOCKED"


class PopulationPolicyV1(StrEnum):
    FULL_OOF_NO_PROTECTED_FINAL_TEST = "FULL_OOF_NO_PROTECTED_FINAL_TEST"


@dataclass(frozen=True, slots=True)
class ConfirmedColumnDecision:
    column_name: str
    status: ConfirmedColumnStatus
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ConfirmedColumnStatus(self.status))
        if not isinstance(self.column_name, str) or not self.column_name:
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        if self.status is ConfirmedColumnStatus.BLOCKED:
            if not isinstance(self.blocked_reason, str) or not self.blocked_reason.strip():
                raise DatasetPreparationError("BLOCKED_REASON_MISSING")
        elif self.blocked_reason is not None:
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")


@dataclass(frozen=True, slots=True)
class ConfirmedDatasetPreparation:
    spec_version: str
    snapshot_fingerprint: str
    inspection_report_hash: str
    proposal_hash: str
    proposal_policy_id: str
    proposal_policy_version: str
    proposal_policy_hash: str
    dataset_name: str
    target_column: str
    positive_class: Any
    identifier_column: str
    column_decisions: tuple[ConfirmedColumnDecision, ...]
    population_policy: PopulationPolicyV1

    def __post_init__(self) -> None:
        object.__setattr__(self, "column_decisions", tuple(self.column_decisions))
        object.__setattr__(self, "population_policy", PopulationPolicyV1(self.population_policy))
        positive_class = self.positive_class
        if isinstance(positive_class, np.generic):
            positive_class = positive_class.item()
        if isinstance(positive_class, bool):
            positive_class = bool(positive_class)
        elif isinstance(positive_class, int):
            positive_class = int(positive_class)
        elif isinstance(positive_class, float) and math.isfinite(positive_class):
            positive_class = float(positive_class)
        elif isinstance(positive_class, str):
            positive_class = str(positive_class)
        else:
            raise DatasetPreparationError("UNSUPPORTED_POSITIVE_CLASS_VALUE")
        object.__setattr__(self, "positive_class", positive_class)
        if self.spec_version != "1" or not self.column_decisions:
            raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
        for name in ("snapshot_fingerprint", "inspection_report_hash", "proposal_hash", "proposal_policy_id", "proposal_policy_version", "proposal_policy_hash", "dataset_name", "target_column", "identifier_column"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")

class ConfidenceLevel(StrEnum): HIGH="HIGH"; MEDIUM="MEDIUM"; LOW="LOW"; UNDETERMINED="UNDETERMINED"
class ProposedColumnRole(StrEnum): EXCLUDE_CANDIDATE="EXCLUDE_CANDIDATE"; REVIEW_REQUIRED="REVIEW_REQUIRED"; TARGET_CANDIDATE="TARGET_CANDIDATE"; IDENTIFIER_CANDIDATE="IDENTIFIER_CANDIDATE"; FEATURE_CANDIDATE="FEATURE_CANDIDATE"; UNKNOWN="UNKNOWN"
class PredictorEligibility(StrEnum): ELIGIBLE_CANDIDATE="ELIGIBLE_CANDIDATE"; REVIEW_REQUIRED="REVIEW_REQUIRED"; NOT_RECOMMENDED_CANDIDATE="NOT_RECOMMENDED_CANDIDATE"; UNKNOWN="UNKNOWN"
class WarningSeverity(StrEnum): WARNING="WARNING"; INFO="INFO"
@dataclass(frozen=True, slots=True)
class ProposalItem:
    column_name: str; column_position: int; proposal_type: str; score_points: int | None; confidence_level: ConfidenceLevel
    reason_codes: tuple[str, ...]; reasons_ru: tuple[str, ...]; evidence: dict[str, Any]; requires_confirmation: bool = True
@dataclass(frozen=True, slots=True)
class PositiveClassCandidate:
    target_column: str; value: Any; score_points: None; confidence_level: ConfidenceLevel; requires_confirmation: bool = True
@dataclass(frozen=True, slots=True)
class ColumnRoleProposal:
    column_name: str; column_position: int; role: ProposedColumnRole; predictor_eligibility: PredictorEligibility; reason_codes: tuple[str, ...]; requires_confirmation: bool = True
@dataclass(frozen=True, slots=True)
class ProposedTechnicalGroup:
    group_kind: str; group_key: str; column_names: tuple[str, ...]; score_points: int | None; confidence_level: ConfidenceLevel; requires_confirmation: bool = True
@dataclass(frozen=True, slots=True)
class ProposalWarning:
    code: str; severity: WarningSeverity; column_name: str | None; column_position: int | None; reasons_ru: tuple[str, ...]; evidence: dict[str, Any]; requires_confirmation: bool = True
@dataclass(frozen=True, slots=True)
class DatasetPreparationProposal:
    snapshot_fingerprint: str; inspection_policy_version: str; policy_id: str; policy_version: str; policy_hash: str
    analysis_status: str; target_candidates: tuple[ProposalItem, ...]; positive_class_candidates: tuple[PositiveClassCandidate, ...]
    identifier_candidates: tuple[ProposalItem, ...]; column_roles: tuple[ColumnRoleProposal, ...]; technical_groups: tuple[ProposedTechnicalGroup, ...]; warnings: tuple[ProposalWarning, ...]
    def to_dict(self) -> dict[str, Any]: return asdict(self)
