"""Composition root for the Streamlit prototype.

This module owns the frozen historical dataset definition and runtime wiring.  The
presentation layer receives only a fully prepared context and application-facing
services; it never constructs backend contracts itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np

from komus_risk.application import (
    ExperimentApplicationService,
    FinalModelTrainingService,
    IntegrationWorkflowService,
    LocalExplanationService,
    ModelInferenceService,
    ResultInterpreterService,
    NativeDatasetOnboardingService,
)
from komus_risk.application.dataset_onboarding import (
    build_confirmed_dataset_preparation,
    proposal_backed_initial_draft,
)
from komus_risk.artifacts import ExperimentArtifactStore, ModelVersionStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.contracts import FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset, ReadyDatasetAdapter, TabularSnapshot
from komus_risk.experiments import EvaluationPopulation
from app.result_interpreter_runtime import compose_result_interpreter_runtime
from app.experiment_runtime import compose_experiment_models
from komus_risk.model_platform import builtin_model_presentation_registry
from komus_risk.models import (
    ModelAdapterFactory,
)
from komus_risk.planning import ExperimentPlanningService
from komus_risk.preparation import (
    ConfirmedDatasetPreparation,
    DatasetPreparationManifest,
    KomusDatasetPreparationService,
    PreparedDatasetContextAuthority,
)
from komus_risk.preparation.context import PreparedDatasetContext
from komus_risk.registries import FeatureRegistry, ModelRegistry


@dataclass(frozen=True, slots=True)
class ResolvedDatasetSource:
    """A local physical source, deliberately without scientific dataset semantics."""

    source_kind: str
    display_name: str
    local_runtime_path: Path
    file_name: str
    physical_format: str
    file_size: int


@dataclass(frozen=True, slots=True)
class DatasetSourcePreparation:
    """Result of resolving a source and, when identity permits, preparing it."""

    source: ResolvedDatasetSource
    preparation_status: str
    context: PreparedDatasetContext | None
    snapshot: TabularSnapshot | None = None
    inspection_report: Any | None = None
    proposal: Any | None = None
    confirmation: ConfirmedDatasetPreparation | None = None
    manifest: DatasetPreparationManifest | None = None

    def __post_init__(self) -> None:
        if (
            self.preparation_status == "context_not_prepared"
            and self.context is not None
        ):
            raise ValueError(
                "Неподготовленный источник не может иметь dataset context."
            )
        if (
            self.preparation_status
            in {"historical_context_prepared", "confirmed_context_prepared"}
            and self.context is None
        ):
            raise ValueError("Подготовленный источник должен иметь dataset context.")

    @property
    def is_prepared(self) -> bool:
        return self.context is not None


@dataclass(frozen=True, slots=True)
class PrototypeRuntime:
    planning_service: ExperimentPlanningService
    application_service: ExperimentApplicationService
    model_registry: ModelRegistry
    model_factories: Mapping[str, ModelAdapterFactory]
    supported_protocol: "SupportedProtocol"
    integration_workflow_service: IntegrationWorkflowService
    prepared_context_authority: PreparedDatasetContextAuthority


@dataclass(frozen=True, slots=True)
class SupportedProtocol:
    protocol_id: str
    protocol_version: str
    evaluation_level: str
    minimum_folds: int
    default_folds: int
    default_seed: int


@dataclass(frozen=True, slots=True)
class AcceptedWorkingSplit:
    row_positions: tuple[int, ...]
    target: np.ndarray


_ACCEPTED_FEATURE_IDS = (
    "Q_A1_norm",
    "Q_A2_norm",
    "Q_A3_norm",
    "Q_A4_norm",
    "Q_A5_norm",
    "Q_A6_norm",
    "Q_A7_norm",
    "Q_B3_norm",
    "Q_B4_norm",
    "Q_B5_norm",
    "Q_C1_norm",
    "Q_D1_norm",
    "Q_D2_norm",
    "Q_D3_norm",
    "Q_D4_norm",
    "Q_D5_norm",
    "Q_D6_norm",
    "A1_norm",
    "A2_norm",
    "A3_norm",
    "A4_norm",
    "A5_norm",
    "A6_norm",
    "B1_norm",
    "B2_norm",
    "B3_norm",
    "C1_norm",
    "C2_norm",
    "C3_norm",
    "C4_norm",
    "D1_norm",
    "D2_norm",
    "D3_norm",
    "D4_norm",
    "D5_norm",
    "E1_norm",
    "E2_norm",
    "E3_norm",
    "F1_norm",
    "F2_norm",
    "F3_norm",
    "F4_norm",
    "G1_norm",
    "G2_norm",
    "G3_norm",
    "G4_norm",
    "G5_norm",
)
_ACCEPTED_DATASET_SHA256 = (
    "fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930"
)
_ACCEPTED_FULL_ROW_COUNT = 362_018
_ACCEPTED_WORKING_ROW_COUNT = 289_614
_ACCEPTED_FINAL_TEST_ROW_COUNT = 72_404
_ACCEPTED_STAGE3_EVIDENCE_SHA256 = (
    "faa53a8aed86c2d445699c0fd1df6a5b83711c96d3a300f9a8860112ff4473ac"
)
_ACCEPTED_WORKING_INDEX_SHA256 = (
    "80430ce6290d0982d3641621ba1ed62f6fb495e8d32f7d23d9fca00091aadb45"
)
_STAGE3_EVIDENCE_PATH = Path("reports/generated/stage3_oof_predictions_V1.npz")

SUPPORTED_PROTOCOL = SupportedProtocol(
    protocol_id="stratified_kfold_oof",
    protocol_version="1",
    evaluation_level="oof",
    minimum_folds=2,
    default_folds=3,
    default_seed=42,
)


class LocalDatasetSourceResolver:
    """Resolve local physical files without inferring any dataset semantics."""

    _FORMATS = {".csv": "csv", ".xlsx": "xlsx", ".xlsb": "xlsb", ".parquet": "parquet"}

    def __init__(self, repository_data_final_path: Path | None = None) -> None:
        self._repository_data_final_path = (
            repository_data_final_path
            or _repository_root() / "data" / "raw" / "Data_final.xlsb"
        )

    def resolve_repository_data_final(self) -> ResolvedDatasetSource:
        return self._resolve(
            self._repository_data_final_path,
            source_kind="repository_local",
            display_name="Принятый исторический Data_final",
        )

    def resolve_explicit_local_path(self, path: str | Path) -> ResolvedDatasetSource:
        raw_path = str(path).strip()
        if not raw_path:
            raise ValueError("Укажите путь к локальному файлу.")
        return self._resolve(
            Path(raw_path),
            source_kind="explicit_local",
            display_name=f"Локальный файл: {Path(raw_path).name}",
        )

    def _resolve(
        self, path: Path, *, source_kind: str, display_name: str
    ) -> ResolvedDatasetSource:
        local_path = path.expanduser()
        if not local_path.exists():
            raise FileNotFoundError(f"Файл датасета не найден: «{local_path}».")
        if not local_path.is_file():
            raise ValueError(
                f"Путь к датасету должен указывать на файл: «{local_path}»."
            )
        try:
            physical_format = self._FORMATS[local_path.suffix.lower()]
        except KeyError as error:
            supported = ", ".join(sorted(self._FORMATS))
            raise ValueError(
                f"Неподдерживаемое расширение «{local_path.suffix}». Поддерживаются: {supported}."
            ) from error
        resolved_path = local_path.resolve()
        return ResolvedDatasetSource(
            source_kind=source_kind,
            display_name=display_name,
            local_runtime_path=resolved_path,
            file_name=resolved_path.name,
            physical_format=physical_format,
            file_size=resolved_path.stat().st_size,
        )


class HistoricalDatasetProvider:
    """Prepare only the accepted historical Pipeline V1 profile."""

    context_id = "historical_data_final_v1"
    display_name = "Исторический Data_final — рабочая популяция"

    def __init__(
        self, context_authority: PreparedDatasetContextAuthority | None = None
    ) -> None:
        self._context_authority = context_authority

    def prepare(
        self,
        source: ResolvedDatasetSource,
        progress_listener: Callable[[str], None] | None = None,
    ) -> PreparedDatasetContext:
        registry = self._feature_registry()
        source_path = source.local_runtime_path
        _notify_data_progress(progress_listener, "checking_file_identity")
        self._validate_source_identity(source_path)
        _notify_data_progress(progress_listener, "checking_working_split")
        working_split = _load_accepted_working_split()
        _notify_data_progress(progress_listener, "loading_dataset")
        loaded = ReadyDatasetAdapter().load(
            source_path,
            dataset_id="komus-historical-data-final",
            dataset_version="accepted-v1",
            dataset_name="Data_final",
            target_column="DefMark",
            positive_class=1,
            identifier_column="INN",
            feature_registry_id=registry.registry_id,
            feature_registry_hash=registry.registry_hash,
            final_test_locked=True,
            sheet_name="Data_final",
        )
        _notify_data_progress(progress_listener, "validating_target_split")
        self._validate_loaded_dataset(loaded, working_split)
        _notify_data_progress(progress_listener, "preparing_context")
        context = PreparedDatasetContext(
            self.context_id,
            self.display_name,
            loaded,
            registry,
            EvaluationPopulation(
                working_split.row_positions,
                "accepted-stage1-working-v1",
                _ACCEPTED_WORKING_INDEX_SHA256,
                "working",
            ),
        )
        if self._context_authority is not None:
            return self._context_authority.register(context)
        return context

    @staticmethod
    def _validate_source_identity(source_path: Path) -> None:
        if _sha256_file(source_path) != _ACCEPTED_DATASET_SHA256:
            raise ValueError("Файл не соответствует принятой identity Data_final.")

    @staticmethod
    def _validate_loaded_dataset(
        loaded: LoadedDataset, working_split: AcceptedWorkingSplit
    ) -> None:
        if loaded.source_file_sha256 != _ACCEPTED_DATASET_SHA256:
            raise ValueError(
                "Загруженный Data_final не соответствует принятой identity."
            )
        if loaded.contract.row_count != _ACCEPTED_FULL_ROW_COUNT:
            raise ValueError(
                "Data_final не соответствует принятому полному числу строк."
            )
        positions = np.asarray(working_split.row_positions, dtype=np.int64)
        if (
            len(positions) != _ACCEPTED_WORKING_ROW_COUNT
            or len(positions) + _ACCEPTED_FINAL_TEST_ROW_COUNT
            != loaded.contract.row_count
        ):
            raise ValueError("Принятый working/final split имеет неверный размер.")
        in_working = np.zeros(loaded.contract.row_count, dtype=bool)
        in_working[positions] = True
        if int((~in_working).sum()) != _ACCEPTED_FINAL_TEST_ROW_COUNT:
            raise ValueError("Working population не должна включать final-test строки.")
        actual_target = loaded.dataframe.iloc[positions]["DefMark"].to_numpy(
            dtype=np.int8
        )
        if not np.array_equal(actual_target, working_split.target):
            raise ValueError(
                "Working positions не согласованы с accepted Stage 3 evidence."
            )

    @staticmethod
    def _feature_registry() -> FeatureRegistry:
        allowed = tuple(
            FeatureSpec(
                feature_id,
                feature_id,
                feature_id,
                "Разрешённый показатель исторического профиля.",
                "accepted_predictors",
                "float",
                "numeric",
                "historical_profile_v1",
                FeatureUsageStatus.MODEL_ALLOWED,
                None,
                "accepted_pipeline_v1",
                None,
                position,
            )
            for position, feature_id in enumerate(_ACCEPTED_FEATURE_IDS)
        )
        protected = (
            FeatureSpec(
                "INN",
                "INN",
                "ИНН",
                "Идентификатор организации.",
                "protected_columns",
                "string",
                "identifier",
                "historical_profile_v1",
                FeatureUsageStatus.IDENTIFIER,
                None,
                None,
                None,
                len(allowed),
            ),
            FeatureSpec(
                "DefMark",
                "DefMark",
                "Признак дефолта",
                "Целевая переменная.",
                "protected_columns",
                "int",
                "target",
                "historical_profile_v1",
                FeatureUsageStatus.TARGET,
                None,
                None,
                None,
                len(allowed) + 1,
            ),
            FeatureSpec(
                "Q_B1_norm",
                "Q_B1_norm",
                "Q_B1_norm",
                "Закрытый reference-сигнал.",
                "restricted_signals",
                "float",
                "numeric",
                "historical_profile_v1",
                FeatureUsageStatus.BLOCKED,
                "Сигнал запрещён для рабочей модели.",
                None,
                None,
                len(allowed) + 2,
            ),
            FeatureSpec(
                "Q_B2_norm",
                "Q_B2_norm",
                "Q_B2_norm",
                "Закрытый reference-сигнал.",
                "restricted_signals",
                "float",
                "numeric",
                "historical_profile_v1",
                FeatureUsageStatus.BLOCKED,
                "Сигнал запрещён для рабочей модели.",
                None,
                None,
                len(allowed) + 3,
            ),
        )
        return FeatureRegistry(
            "historical-data-final-v1",
            (*allowed, *protected),
            (
                FeatureGroup(
                    "accepted_predictors",
                    "Разрешённые показатели",
                    "Признаки рабочего исторического профиля.",
                    0,
                    "accepted_pipeline_v1",
                    _ACCEPTED_FEATURE_IDS,
                ),
                FeatureGroup(
                    "protected_columns",
                    "Служебные столбцы",
                    "Идентификатор и целевая переменная доступны только для чтения.",
                    1,
                    "accepted_pipeline_v1",
                    ("INN", "DefMark"),
                ),
                FeatureGroup(
                    "restricted_signals",
                    "Закрытые сигналы",
                    "Сигналы не разрешены для рабочей модели.",
                    2,
                    "accepted_pipeline_v1",
                    ("Q_B1_norm", "Q_B2_norm"),
                ),
            ),
        )


def prepare_resolved_source(
    source: ResolvedDatasetSource,
    *,
    historical_provider: HistoricalDatasetProvider | None = None,
    context_authority: PreparedDatasetContextAuthority | None = None,
    progress_listener: Callable[[str], None] | None = None,
) -> DatasetSourcePreparation:
    """Check a source, preserving historical semantics or creating only a proposal."""
    if _sha256_file(source.local_runtime_path) != _ACCEPTED_DATASET_SHA256:
        # Resolution normally guarantees this.  Keeping the unprepared result for
        # a vanished source preserves the resolver's user-facing error boundary.
        if not source.local_runtime_path.is_file():
            return DatasetSourcePreparation(source, "context_not_prepared", None)
        inspected = NativeDatasetOnboardingService().inspect(
            source.local_runtime_path,
            display_name=source.file_name,
            size=source.file_size,
            progress_listener=progress_listener,
        )
        return DatasetSourcePreparation(
            source,
            "context_not_prepared",
            None,
            snapshot=inspected.snapshot,
            inspection_report=inspected.report,
            proposal=inspected.proposal,
        )
    provider = historical_provider or HistoricalDatasetProvider(context_authority)
    context = provider.prepare(source, progress_listener=progress_listener)
    if context_authority is not None:
        context = context_authority.register(context)
    return DatasetSourcePreparation(
        source,
        "historical_context_prepared",
        context,
    )


def default_preparation_draft(preparation: DatasetSourcePreparation) -> dict[str, Any]:
    """Return proposal-backed UI defaults; this is not a confirmation."""
    if preparation.snapshot is None or preparation.proposal is None:
        raise ValueError("No source analysis is available for preparation.")
    initial = proposal_backed_initial_draft(
        preparation.snapshot, preparation.proposal
    )
    draft = {
        "snapshot_fingerprint": preparation.snapshot.fingerprint,
        "dataset_name": preparation.source.file_name,
        "target_column": initial.target_column or "",
        "positive_class": initial.positive_class,
        "identifier_column": initial.identifier_column or "",
        "column_statuses": dict(initial.column_statuses),
        "blocked_reasons": {},
        "population_policy": initial.population_policy,
        "population_policy_acknowledged": initial.population_policy_acknowledged,
    }
    if preparation.confirmation is not None:
        confirmation = preparation.confirmation
        draft.update(
            dataset_name=confirmation.dataset_name,
            target_column=confirmation.target_column,
            positive_class=confirmation.positive_class,
            identifier_column=confirmation.identifier_column,
            column_statuses={
                item.column_name: item.status.value
                for item in confirmation.column_decisions
            },
            blocked_reasons={
                item.column_name: item.blocked_reason
                for item in confirmation.column_decisions
                if item.blocked_reason is not None
            },
        )
    return draft


def confirm_dataset_preparation(
    preparation: DatasetSourcePreparation,
    draft: Mapping[str, Any],
    *,
    progress_listener: Callable[[str], None] | None = None,
    context_authority: PreparedDatasetContextAuthority | None = None,
) -> DatasetSourcePreparation:
    """Materialize an immutable backend confirmation from the explicit UI draft."""
    snapshot, report, proposal = (
        preparation.snapshot,
        preparation.inspection_report,
        preparation.proposal,
    )
    if snapshot is None or report is None or proposal is None:
        raise ValueError("No source analysis is available for confirmation.")
    _notify_data_progress(progress_listener, "validating_confirmation")
    confirmation = build_confirmed_dataset_preparation(
        snapshot, report, proposal,
        dataset_name=str(draft.get("dataset_name") or preparation.source.file_name),
        target_column=str(draft.get("target_column") or "") or None,
        positive_class=draft.get("positive_class"),
        identifier_column=str(draft.get("identifier_column") or "") or None,
        column_statuses=dict(draft.get("column_statuses") or {}),
        blocked_reasons=dict(draft.get("blocked_reasons") or {}),
        population_policy=str(draft.get("population_policy") or ""),
        population_policy_acknowledged=bool(draft.get("population_policy_acknowledged", False)),
    )
    _notify_data_progress(progress_listener, "materializing_dataset")
    context, manifest = KomusDatasetPreparationService(
        context_authority=context_authority
    ).prepare(snapshot, report, proposal, confirmation)
    _notify_data_progress(progress_listener, "prepared_context_ready")
    return DatasetSourcePreparation(
        preparation.source,
        "confirmed_context_prepared",
        context,
        snapshot=snapshot,
        inspection_report=report,
        proposal=proposal,
        confirmation=confirmation,
        manifest=manifest,
    )


def reopen_dataset_preparation(
    preparation: DatasetSourcePreparation,
) -> DatasetSourcePreparation:
    """Drop an active arbitrary context before its confirmation is edited."""
    if preparation.preparation_status != "confirmed_context_prepared":
        raise ValueError("Only a confirmed preparation can be edited.")
    return replace(
        preparation,
        preparation_status="context_not_prepared",
        context=None,
        manifest=None,
    )


def create_runtime(
    artifact_root: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
    result_interpreter_factories: Mapping[str, Callable[[str, str], Any]] | None = None,
) -> PrototypeRuntime:
    """Wire existing model, planning, application, persistence and comparison services."""
    model_runtime = compose_experiment_models()
    plugin_registry = model_runtime.plugin_registry
    plugins = plugin_registry.list()
    factories = model_runtime.model_factories
    registry = model_runtime.model_registry
    persistence_provider_registry = plugin_registry.persistence_providers
    if persistence_provider_registry is None:  # pragma: no cover - builtin invariant
        raise RuntimeError("Builtin model plugins require persistence providers.")
    context_authority = PreparedDatasetContextAuthority()
    store_root = (
        Path(artifact_root)
        if artifact_root is not None
        else _repository_root() / ".streamlit-artifacts"
    )
    code_version = "streamlit-prototype-v1"
    artifact_store = ExperimentArtifactStore(store_root)
    model_version_store = ModelVersionStore(
        store_root / "model_versions",
        code_version=code_version,
        model_specs={plugin.spec.model_id: plugin.spec for plugin in plugins},
        model_plugin_registry=plugin_registry,
        persistence_provider_registry=persistence_provider_registry,
    )
    final_model_training_service = FinalModelTrainingService(
        experiment_artifact_store=artifact_store,
        model_version_store=model_version_store,
        model_registry=registry,
        model_factories=factories,
        code_version=code_version,
        model_plugin_registry=plugin_registry,
    )
    interpreter_runtime = compose_result_interpreter_runtime(
        environment=environment,
        secrets=secrets if secrets is not None else _streamlit_secrets(),
        factories=result_interpreter_factories,
    )
    integration_workflow_service = IntegrationWorkflowService(
        final_model_training_service=final_model_training_service,
        model_version_store=model_version_store,
        model_inference_service=ModelInferenceService(),
        local_explainers={plugin.spec.model_id: LocalExplanationService() for plugin in plugins if plugin.local_explanation_provider is not None},
        result_interpreter_service=ResultInterpreterService(interpreter_runtime.prompt_loader),
        result_interpreter_client=interpreter_runtime.client,
        outbound_interpreter_policy=interpreter_runtime.outbound_policy,
        result_interpreter_runtime=interpreter_runtime.configuration,
    )
    return PrototypeRuntime(
        ExperimentPlanningService(
            model_plugin_registry=plugin_registry,
            model_presentation_registry=builtin_model_presentation_registry(
                plugin_registry
            ),
        ),
        ExperimentApplicationService(
            model_registry=registry,
            model_factories=factories,
            artifact_store=artifact_store,
            comparison_service=ExperimentComparisonService(),
            code_version=code_version,
            model_plugin_registry=plugin_registry,
            prepared_context_authority=context_authority,
        ),
        registry,
        factories,
        SUPPORTED_PROTOCOL,
        integration_workflow_service,
        context_authority,
    )


def _streamlit_secrets() -> Mapping[str, Any] | None:
    """Resolve Streamlit's optional secret source at the app boundary."""
    try:
        import streamlit as st

        return st.secrets
    except Exception:
        return None


def validate_supported_protocol(
    values: Mapping[str, Any], protocol: SupportedProtocol = SUPPORTED_PROTOCOL
) -> str | None:
    """Return a user-facing validation message for the one supported Pipeline V1 protocol."""
    if (
        values.get("protocol_id") != protocol.protocol_id
        or values.get("protocol_version") != protocol.protocol_version
        or values.get("evaluation_level") != protocol.evaluation_level
    ):
        return "В Prototype V1 доступен только указанный протокол OOF-оценки."
    if values.get("folds", 0) < protocol.minimum_folds:
        return f"Количество фолдов должно быть не меньше {protocol.minimum_folds}."
    return None


def _load_accepted_working_split() -> AcceptedWorkingSplit:
    evidence_path = _repository_root() / _STAGE3_EVIDENCE_PATH
    if not evidence_path.is_file():
        raise ValueError("Не найден accepted Stage 3 evidence с working row positions.")
    if _sha256_file(evidence_path) != _ACCEPTED_STAGE3_EVIDENCE_SHA256:
        raise ValueError("Stage 3 evidence не соответствует принятой identity.")
    try:
        with np.load(evidence_path, allow_pickle=False) as evidence:
            working_indices = np.asarray(evidence["working_indices"], dtype=np.int64)
            target = np.asarray(evidence["target"], dtype=np.int8)
    except (KeyError, OSError, ValueError) as error:
        raise ValueError(
            "Stage 3 evidence не содержит валидные working row positions."
        ) from error
    if (
        working_indices.ndim != 1
        or len(working_indices) != _ACCEPTED_WORKING_ROW_COUNT
        or len(np.unique(working_indices)) != len(working_indices)
        or _sha256_int64(working_indices) != _ACCEPTED_WORKING_INDEX_SHA256
        or target.shape != working_indices.shape
    ):
        raise ValueError(
            "Working row positions не соответствуют принятой Stage 1 identity."
        )
    if working_indices.min() < 0 or working_indices.max() >= _ACCEPTED_FULL_ROW_COUNT:
        raise ValueError(
            "Working row positions выходят за границы accepted Data_final."
        )
    return AcceptedWorkingSplit(tuple(working_indices.tolist()), target)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_int64(values: np.ndarray) -> str:
    return sha256(np.asarray(values, dtype=np.int64).tobytes()).hexdigest()


def _notify_data_progress(listener: Callable[[str], None] | None, stage: str) -> None:
    if listener is None:
        return
    try:
        listener(stage)
    except Exception:
        return


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]
