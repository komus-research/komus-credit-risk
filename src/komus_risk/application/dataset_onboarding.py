"""Framework-neutral dataset inspection, confirmation and materialization adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Callable
from typing import Any, Iterable, Literal

import numpy as np

from komus_risk.data import DatasetInspector, TabularReader, TabularSnapshot
from komus_risk.preparation import DatasetPreparationAnalyzer, ProposalWarning
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


@dataclass(frozen=True, slots=True)
class PreparationWarningView:
    """Public warning meaning and resolution for the current editable draft."""

    code: str
    severity: Literal["WARNING", "INFO"]
    scope: Literal["COLUMN", "DATASET"]
    column_name: str | None
    detected_reasons: tuple[str, ...]
    detected_requires_confirmation: bool
    resolution_state: Literal["ACTION_REQUIRED", "RESOLVED", "INFO"]
    resolution_code: str
    subject_ru: str
    title_ru: str
    detail_ru: str
    check_ru: str | None
    resolution_note_ru: str | None
    action: Literal[
        "REVIEW_COLUMN",
        "REVIEW_TARGET",
        "REVIEW_IDENTIFIER",
        "REVIEW_DATASET",
    ] | None


_TARGET_WARNING_CODES = frozenset({
    "no_target_candidate",
    "multiple_target_candidates",
    "target_candidate_has_missing_values",
})
_IDENTIFIER_WARNING_CODES = frozenset({
    "no_identifier_candidate",
    "multiple_identifier_candidates",
})


def project_preparation_warnings(
    warnings: Iterable[ProposalWarning], draft: PreparationDraft,
) -> tuple[PreparationWarningView, ...]:
    """Resolve immutable detector warnings against the supplied live draft."""
    return tuple(_project_preparation_warning(warning, draft) for warning in warnings)


@dataclass(frozen=True, slots=True)
class PreparationWarningCounts:
    action_required: int
    resolved: int
    info: int


def preparation_warning_counts(warnings: Iterable[PreparationWarningView]) -> PreparationWarningCounts:
    counts = {"ACTION_REQUIRED": 0, "RESOLVED": 0, "INFO": 0}
    for warning in warnings:
        counts[warning.resolution_state] += 1
    return PreparationWarningCounts(counts["ACTION_REQUIRED"], counts["RESOLVED"], counts["INFO"])


_ROLE_WARNING_CODES = frozenset({"near_unique_column", "high_cardinality_non_numeric"})
_STRUCTURAL_WARNING_CODES = frozenset({
    "all_missing_column", "constant_column", "missing_values_present", "high_missingness",
    "almost_empty_column", "mixed_value_types", "unknown_logical_type", "datetime_semantics_unconfirmed",
})
_PROXY_WARNING_CODES = frozenset({"potential_target_proxy", "potential_deterministic_target_proxy"})


def _effective_role(column: str | None, draft: PreparationDraft) -> str | None:
    if column is None:
        return None
    if column == draft.target_column:
        return "TARGET"
    if column == draft.identifier_column:
        return "IDENTIFIER"
    return draft.column_statuses.get(column)


def _warning_resolution(warning: ProposalWarning, draft: PreparationDraft) -> tuple[str, str]:
    code, column = warning.code, warning.column_name
    role = _effective_role(column, draft)
    blocked_valid = role == "BLOCKED" and bool(draft.blocked_reasons.get(column or "", "").strip())
    if code in {"no_target_candidate", "multiple_target_candidates"}:
        return (("ACTION_REQUIRED", "TARGET_NOT_SELECTED") if draft.target_column is None else ("RESOLVED", "TARGET_SELECTED"))
    if code in {"no_identifier_candidate", "multiple_identifier_candidates"}:
        return (("ACTION_REQUIRED", "IDENTIFIER_NOT_SELECTED") if draft.identifier_column is None else ("RESOLVED", "IDENTIFIER_SELECTED"))
    if code == "target_candidate_has_missing_values":
        same_target = column is not None and column == draft.target_column
        return (("ACTION_REQUIRED", "CURRENT_TARGET_HAS_MISSING_VALUES") if same_target else ("RESOLVED", "WARNING_ABOUT_OTHER_TARGET"))
    if code in _ROLE_WARNING_CODES:
        if role in {"IDENTIFIER", "DIAGNOSTIC_ONLY"} or blocked_valid:
            return "RESOLVED", f"COLUMN_ROLE_{role if not blocked_valid else 'BLOCKED'}"
        if role in {"TARGET", "MODEL_ALLOWED"}:
            return "ACTION_REQUIRED", f"COLUMN_ROLE_{role}"
        return "ACTION_REQUIRED", "COLUMN_ROLE_REQUIRES_REVIEW"
    if code in _STRUCTURAL_WARNING_CODES:
        if role == "DIAGNOSTIC_ONLY":
            return "INFO", "DIAGNOSTIC_ONLY"
        if blocked_valid:
            return "RESOLVED", "VALID_BLOCKED"
        return "ACTION_REQUIRED", "COLUMN_ROLE_REQUIRES_REVIEW"
    if code == "insufficient_evidence":
        return "ACTION_REQUIRED", "INSUFFICIENT_EVIDENCE"
    if code in _PROXY_WARNING_CODES:
        related_target = warning.evidence.get("related_target_candidate")
        if draft.target_column is None:
            return "INFO", "TARGET_NOT_SELECTED"
        if related_target != draft.target_column:
            return "RESOLVED", "PROXY_FOR_OTHER_TARGET"
        if role == "MODEL_ALLOWED":
            return "ACTION_REQUIRED", "CURRENT_TARGET_PROXY_MODEL_ALLOWED"
        if role in {"IDENTIFIER", "DIAGNOSTIC_ONLY"} or blocked_valid:
            return "RESOLVED", f"CURRENT_TARGET_PROXY_ROLE_{role if not blocked_valid else 'BLOCKED'}"
        return "ACTION_REQUIRED", "CURRENT_TARGET_PROXY_ROLE_REQUIRES_REVIEW"
    if warning.severity.value == "INFO":
        return "INFO", "UNCLASSIFIED_INFORMATION"
    return "ACTION_REQUIRED", "UNCLASSIFIED_WARNING"


_WARNING_TEXT: dict[str, tuple[str, str, str | None]] = {
    "no_target_candidate": ("Целевая колонка не выбрана", "Автоматически определить целевую колонку не удалось.", "Выберите колонку с целевым событием."),
    "multiple_target_candidates": ("Найдено несколько вариантов цели", "Среди колонок есть несколько возможных целевых переменных.", "Проверьте выбранную целевую колонку."),
    "no_identifier_candidate": ("Идентификатор не выбран", "Автоматически определить колонку идентификатора не удалось.", "Выберите идентификатор или подтвердите подходящую колонку."),
    "multiple_identifier_candidates": ("Найдено несколько вариантов идентификатора", "Есть несколько колонок, которые могут быть идентификаторами.", "Проверьте выбранный идентификатор."),
    "target_candidate_has_missing_values": ("В целевой колонке есть пропуски", "Обнаруженные пропуски относятся к кандидату на целевую колонку.", "Проверьте пропуски в выбранной целевой колонке."),
    "near_unique_column": ("Почти уникальные значения", "В колонке почти каждое значение встречается один раз.", "Проверьте назначение этой колонки."),
    "high_cardinality_non_numeric": ("Высокая кардинальность", "Нечисловая колонка содержит много различных значений.", "Проверьте назначение этой колонки."),
    "all_missing_column": ("Колонка полностью пустая", "В колонке обнаружены только пропущенные значения.", "Проверьте, нужна ли эта колонка."),
    "constant_column": ("Постоянное значение", "Колонка содержит одно непустое значение.", "Проверьте, нужна ли эта колонка."),
    "missing_values_present": ("В колонке есть пропуски", "В колонке обнаружены пропущенные значения.", "Проверьте пропуски в этой колонке."),
    "high_missingness": ("Много пропусков", "В колонке обнаружена высокая доля пропущенных значений.", "Проверьте пропуски в этой колонке."),
    "almost_empty_column": ("Колонка почти пустая", "В колонке найдено мало непустых значений.", "Проверьте, нужна ли эта колонка."),
    "mixed_value_types": ("Смешанные типы значений", "В колонке обнаружены значения разных типов.", "Проверьте содержимое этой колонки."),
    "unknown_logical_type": ("Тип колонки не определён", "Не удалось определить логический тип значений колонки.", "Проверьте содержимое этой колонки."),
    "datetime_semantics_unconfirmed": ("Семантика даты не подтверждена", "Колонка содержит значения даты или времени.", "Проверьте смысл и доступность этих значений."),
    "insufficient_evidence": ("Недостаточно данных для анализа", "В файле недостаточно непустых значений для формирования предложений.", "Проверьте данные и выбранный файл."),
    "potential_target_proxy": ("Возможная утечка цели", "Колонка почти полностью соответствует текущей целевой переменной. Это может означать, что модель получает информацию, которая появилась после целевого события или была рассчитана на его основе.", "Проверьте, было ли значение этой колонки известно на момент принятия решения."),
    "potential_deterministic_target_proxy": ("Возможная утечка цели", "Колонка почти полностью соответствует текущей целевой переменной. Это может означать, что модель получает информацию, которая появилась после целевого события или была рассчитана на его основе.", "Проверьте, было ли значение этой колонки известно на момент принятия решения."),
}


def _project_preparation_warning(warning: ProposalWarning, draft: PreparationDraft) -> PreparationWarningView:
    if warning.code in _TARGET_WARNING_CODES:
        action = "REVIEW_TARGET"
    elif warning.code in _IDENTIFIER_WARNING_CODES:
        action = "REVIEW_IDENTIFIER"
    elif warning.code == "insufficient_evidence":
        action = "REVIEW_DATASET"
    elif warning.column_name is not None:
        action = "REVIEW_COLUMN"
    else:
        action = None
    resolution_state, resolution_code = _warning_resolution(warning, draft)
    title, detail, check = _WARNING_TEXT.get(
        warning.code,
        ("Замечание по данным", "Для этого замечания требуется проверить данные набора.", None),
    )
    if warning.column_name is not None:
        subject = warning.column_name
    elif warning.code in _TARGET_WARNING_CODES:
        subject = "Целевая колонка"
    elif warning.code in _IDENTIFIER_WARNING_CODES:
        subject = "Идентификатор"
    else:
        subject = "Набор данных"
    resolution_note = _warning_resolution_note(warning, draft, resolution_code)
    return PreparationWarningView(
        code=warning.code,
        severity=warning.severity.value,
        scope="COLUMN" if warning.column_name is not None else "DATASET",
        column_name=warning.column_name,
        detected_reasons=tuple(warning.reasons_ru),
        detected_requires_confirmation=warning.requires_confirmation,
        resolution_state=resolution_state,
        resolution_code=resolution_code,
        subject_ru=subject,
        title_ru=title,
        detail_ru=detail,
        check_ru=check,
        resolution_note_ru=resolution_note,
        action=action,
    )


def _warning_resolution_note(warning: ProposalWarning, draft: PreparationDraft, resolution_code: str) -> str | None:
    if resolution_code == "TARGET_SELECTED":
        selected = draft.target_column or ""
        if warning.code == "no_target_candidate":
            return f"Целевая колонка выбрана вручную: {selected}."
        return f"Выбрана целевая колонка {selected}."
    if resolution_code == "IDENTIFIER_SELECTED":
        return f"Выбран идентификатор {draft.identifier_column}."
    if resolution_code == "WARNING_ABOUT_OTHER_TARGET":
        return "Выбрана другая целевая колонка."
    if resolution_code == "PROXY_FOR_OTHER_TARGET":
        return "Предупреждение относится к другой кандидатной цели."
    if resolution_code == "DIAGNOSTIC_ONLY" or resolution_code.startswith(("COLUMN_ROLE_DIAGNOSTIC_ONLY", "CURRENT_TARGET_PROXY_ROLE_DIAGNOSTIC_ONLY")):
        return "Колонка не используется как признак модели."
    if resolution_code in {"VALID_BLOCKED", "COLUMN_ROLE_BLOCKED"} or resolution_code.endswith("_BLOCKED"):
        return "Колонка исключена из признаков модели."
    if resolution_code == "COLUMN_ROLE_IDENTIFIER":
        return "Выбрана в качестве идентификатора."
    return None


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
