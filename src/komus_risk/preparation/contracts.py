"""Proposal-only contracts for Dataset Onboarding V1."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

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
