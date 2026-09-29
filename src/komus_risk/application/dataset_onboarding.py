"""Framework-neutral dataset inspection, confirmation and materialization adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Callable
from typing import Any

import numpy as np

from komus_risk.data import DatasetInspector, TabularReader, TabularSnapshot
from komus_risk.preparation import DatasetPreparationAnalyzer
from komus_risk.preparation import (
    ConfirmedColumnDecision,
    ConfirmedColumnStatus,
    ConfirmedDatasetPreparation,
    DatasetPreparationError,
    KomusDatasetPreparationService,
    PopulationPolicyV1,
    PreparedDatasetContextAuthority,
)
from komus_risk.preparation.materializer import inspection_report_hash, proposal_hash
from komus_risk.preparation.predictor_compatibility import predictor_compatibility_error

DRAFT_FIELD_UNSET = object()


class DatasetDraftError(ValueError):
    """A stable, safe error caused by an editable native draft."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class InspectedDataset:
    """Facts and proposal for one controlled, local source."""

    local_path: Path
    display_name: str
    source_format: str
    size: int
    snapshot: TabularSnapshot
    report: Any
    proposal: Any


@dataclass(frozen=True, slots=True)
class PreparationDraft:
    """A user-editable proposal-derived draft, not a confirmation."""

    target_column: str | None
    positive_class: Any | None
    identifier_column: str | None
    column_statuses: dict[str, str]
    blocked_reasons: dict[str, str]
    population_policy: str
    population_policy_acknowledged: bool


@dataclass(frozen=True, slots=True)
class ProposalBackedInitialDraft:
    """One proposal-derived initial draft shared by all presentation adapters.

    Positive class deliberately remains empty.  Selecting it is a human draft
    decision in the accepted preparation flow, so N2a must not silently turn a
    proposal candidate into an auto-confirmed-looking value.
    """

    target_column: str | None
    positive_class: Any | None
    identifier_column: str | None
    column_statuses: dict[str, str]
    population_policy: str
    population_policy_acknowledged: bool


class NativeDatasetOnboardingService:
    """Reuse physical reading, inspection and proposal services for N2a."""

    def inspect(
        self,
        path: Path,
        *,
        display_name: str,
        size: int,
        progress_listener: Callable[[str], None] | None = None,
    ) -> InspectedDataset:
        if progress_listener is not None:
            progress_listener("reading_source")
        snapshot = TabularReader().read(path)
        if progress_listener is not None:
            progress_listener("inspecting_dataset")
        report = DatasetInspector().inspect(snapshot)
        if progress_listener is not None:
            progress_listener("analyzing_preparation")
        proposal = DatasetPreparationAnalyzer().analyze(report)
        return InspectedDataset(
            local_path=path,
            display_name=display_name,
            source_format=snapshot.source_format,
            size=size,
            snapshot=snapshot,
            report=report,
            proposal=proposal,
        )

    def default_draft(self, dataset: InspectedDataset) -> PreparationDraft:
        initial = proposal_backed_initial_draft(dataset.snapshot, dataset.proposal)
        return PreparationDraft(
            initial.target_column,
            initial.positive_class,
            initial.identifier_column,
            dict(initial.column_statuses),
            {},
            initial.population_policy,
            initial.population_policy_acknowledged,
        )

    def update_draft(
        self,
        dataset: InspectedDataset,
        current: PreparationDraft,
        *,
        target_column: Any = DRAFT_FIELD_UNSET,
        positive_class: Any = DRAFT_FIELD_UNSET,
        identifier_column: Any = DRAFT_FIELD_UNSET,
    ) -> PreparationDraft:
        headers = set(dataset.snapshot.physical_headers)
        target = current.target_column if target_column is DRAFT_FIELD_UNSET else target_column
        identifier = (
            current.identifier_column
            if identifier_column is DRAFT_FIELD_UNSET
            else identifier_column
        )
        if target is not None and target not in headers:
            raise DatasetDraftError("UNKNOWN_TARGET_COLUMN")
        if identifier is not None and identifier not in headers:
            raise DatasetDraftError("UNKNOWN_IDENTIFIER_COLUMN")
        if target and identifier and target == identifier:
            raise DatasetDraftError("TARGET_IDENTIFIER_CONFLICT")

        # A positive class belongs to a particular target.  Changing that target
        # always drops the old value unless the client explicitly supplies a new
        # value for the new target in the same request.
        target_changed = target != current.target_column
        positive = None if target_changed else current.positive_class
        if positive_class is not DRAFT_FIELD_UNSET:
            positive = positive_class
        choices = self.positive_class_choices(dataset, target)
        if positive is not None and not any(_same_value(positive, choice) for choice in choices):
            raise DatasetDraftError("INVALID_POSITIVE_CLASS")
        return replace(current, target_column=target, positive_class=positive, identifier_column=identifier)

    @staticmethod
    def acknowledge_population_policy(
        current: PreparationDraft, acknowledged: bool
    ) -> PreparationDraft:
        return replace(current, population_policy_acknowledged=acknowledged)

    @staticmethod
    def build_confirmation(
        dataset: InspectedDataset, draft: PreparationDraft
    ) -> ConfirmedDatasetPreparation:
        """Turn an explicitly acknowledged native draft into the shared contract."""
        return build_confirmed_dataset_preparation(
            dataset.snapshot, dataset.report, dataset.proposal,
            dataset_name=dataset.display_name,
            target_column=draft.target_column,
            positive_class=draft.positive_class,
            identifier_column=draft.identifier_column,
            column_statuses=draft.column_statuses,
            blocked_reasons=draft.blocked_reasons,
            population_policy=draft.population_policy,
            population_policy_acknowledged=draft.population_policy_acknowledged,
        )

    def materialize_confirmation(
        self,
        dataset: InspectedDataset,
        draft: PreparationDraft,
        *,
        context_authority: PreparedDatasetContextAuthority,
    ) -> tuple[Any, Any, ConfirmedDatasetPreparation]:
        """Use the canonical materializer; a proposal never becomes runtime truth."""
        confirmation = self.build_confirmation(dataset, draft)
        context, manifest = KomusDatasetPreparationService(
            context_authority=context_authority
        ).prepare(dataset.snapshot, dataset.report, dataset.proposal, confirmation)
        return context, manifest, confirmation

    @staticmethod
    def positive_class_choices(dataset: InspectedDataset, target: str | None) -> tuple[Any, ...]:
        if not target:
            return ()
        column = next((item for item in dataset.report.columns if item.column_name == target), None)
        if column is None:
            return ()
        return tuple(_json_value(item.value) for item in (column.value_counts or ()))

    @staticmethod
    def permission_counts(dataset: InspectedDataset, draft: PreparationDraft) -> dict[str, int]:
        counts = {key: 0 for key in ("MODEL_ALLOWED", "DIAGNOSTIC_ONLY", "BLOCKED", "TARGET", "IDENTIFIER")}
        for name in dataset.snapshot.physical_headers:
            if name == draft.target_column:
                counts["TARGET"] += 1
            elif name == draft.identifier_column:
                counts["IDENTIFIER"] += 1
            elif predictor_compatibility_error(dataset.snapshot.dataframe[name]) is None:
                counts["MODEL_ALLOWED"] += 1
            else:
                counts["DIAGNOSTIC_ONLY"] += 1
        return counts


def proposal_backed_initial_draft(
    snapshot: TabularSnapshot, proposal: Any
) -> ProposalBackedInitialDraft:
    """Build the only reusable initial preparation draft from facts and proposal."""
    target = next((item.column_name for item in proposal.target_candidates), None)
    identifier = next((item.column_name for item in proposal.identifier_candidates), None)
    if target == identifier:
        identifier = None
    statuses = {
        name: (
            "MODEL_ALLOWED"
            if predictor_compatibility_error(snapshot.dataframe[name]) is None
            else "DIAGNOSTIC_ONLY"
        )
        for name in snapshot.physical_headers
    }
    return ProposalBackedInitialDraft(
        target_column=target,
        positive_class=None,
        identifier_column=identifier,
        column_statuses=statuses,
        population_policy="FULL_OOF_NO_PROTECTED_FINAL_TEST",
        population_policy_acknowledged=False,
    )


def build_confirmed_dataset_preparation(
    snapshot: TabularSnapshot,
    report: Any,
    proposal: Any,
    *,
    dataset_name: str,
    target_column: str | None,
    positive_class: Any | None,
    identifier_column: str | None,
    column_statuses: dict[str, str],
    blocked_reasons: dict[str, str],
    population_policy: str,
    population_policy_acknowledged: bool,
) -> ConfirmedDatasetPreparation:
    """The one framework-neutral draft-to-confirmation semantic boundary."""
    if not population_policy_acknowledged:
        raise DatasetPreparationError("POPULATION_POLICY_NOT_ACKNOWLEDGED")
    if not target_column or not identifier_column:
        raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
    if positive_class is None:
        raise DatasetPreparationError("POSITIVE_CLASS_MISSING")
    decisions = []
    for name in snapshot.physical_headers:
        status = (
            ConfirmedColumnStatus.TARGET if name == target_column
            else ConfirmedColumnStatus.IDENTIFIER if name == identifier_column
            else ConfirmedColumnStatus(column_statuses.get(
                name, ConfirmedColumnStatus.DIAGNOSTIC_ONLY.value
            ))
        )
        decisions.append(ConfirmedColumnDecision(
            name, status,
            blocked_reasons.get(name) if status is ConfirmedColumnStatus.BLOCKED else None,
        ))
    report_digest = inspection_report_hash(report)
    return ConfirmedDatasetPreparation(
        "1", snapshot.fingerprint, report_digest, proposal_hash(proposal, report_digest),
        proposal.policy_id, proposal.policy_version, proposal.policy_hash, dataset_name,
        target_column, positive_class, identifier_column, tuple(decisions),
        PopulationPolicyV1(population_policy),
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _same_value(left: Any, right: Any) -> bool:
    return _json_value(left) == _json_value(right)
