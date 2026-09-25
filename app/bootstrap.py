"""Composition root for the Streamlit prototype.

This module owns the frozen historical dataset definition and runtime wiring.  The
presentation layer receives only a fully prepared context and application-facing
services; it never constructs backend contracts itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
import os
from pathlib import Path
from typing import Any

import numpy as np

from komus_risk.application import (
    ExperimentApplicationService,
    FinalModelTrainingService,
    IntegrationWorkflowService,
    LocalExplanationService,
    ModelInferenceService,
    RedactedV1OutboundPolicy,
    ResultInterpreterRuntimeConfiguration,
    ResultInterpreterService,
)
from komus_risk.integrations.openai_result_interpreter import OpenAIResultInterpreterClient
from komus_risk.artifacts import ExperimentArtifactStore, ModelVersionStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.contracts import FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import DatasetInspector, LoadedDataset, ReadyDatasetAdapter, TabularReader, TabularSnapshot
from komus_risk.experiments import EvaluationPopulation
from komus_risk.preparation import (
    ConfirmedColumnDecision,
    ConfirmedColumnStatus,
    ConfirmedDatasetPreparation,
    DatasetPreparationAnalyzer,
    DatasetPreparationError,
    DatasetPreparationManifest,
    KomusDatasetPreparationService,
    PopulationPolicyV1,
)
from komus_risk.preparation.context import PreparedDatasetContext
from komus_risk.preparation.materializer import inspection_report_hash, proposal_hash
from komus_risk.preparation.predictor_compatibility import predictor_compatibility_error
from komus_risk.models import (
    CATBOOST_MODEL_SPEC,
    GBDT_MEAN_MODEL_SPEC,
    LIGHTGBM_MODEL_SPEC,
    XGBOOST_MODEL_SPEC,
    CatBoostFactory,
    GBDTMeanFactory,
    LightGBMFactory,
    ModelAdapterFactory,
    XGBoostFactory,
)
from komus_risk.planning import ExperimentPlanningService
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
        if self.preparation_status == "context_not_prepared" and self.context is not None:
            raise ValueError("Неподготовленный источник не может иметь dataset context.")
        if self.preparation_status in {"historical_context_prepared", "confirmed_context_prepared"} and self.context is None:
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
    "Q_A1_norm", "Q_A2_norm", "Q_A3_norm", "Q_A4_norm", "Q_A5_norm", "Q_A6_norm", "Q_A7_norm",
    "Q_B3_norm", "Q_B4_norm", "Q_B5_norm", "Q_C1_norm", "Q_D1_norm", "Q_D2_norm", "Q_D3_norm",
    "Q_D4_norm", "Q_D5_norm", "Q_D6_norm", "A1_norm", "A2_norm", "A3_norm", "A4_norm", "A5_norm",
    "A6_norm", "B1_norm", "B2_norm", "B3_norm", "C1_norm", "C2_norm", "C3_norm", "C4_norm",
    "D1_norm", "D2_norm", "D3_norm", "D4_norm", "D5_norm", "E1_norm", "E2_norm", "E3_norm",
    "F1_norm", "F2_norm", "F3_norm", "F4_norm", "G1_norm", "G2_norm", "G3_norm", "G4_norm", "G5_norm",
)
_ACCEPTED_DATASET_SHA256 = "fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930"
_ACCEPTED_FULL_ROW_COUNT = 362_018
_ACCEPTED_WORKING_ROW_COUNT = 289_614
_ACCEPTED_FINAL_TEST_ROW_COUNT = 72_404
_ACCEPTED_STAGE3_EVIDENCE_SHA256 = "faa53a8aed86c2d445699c0fd1df6a5b83711c96d3a300f9a8860112ff4473ac"
_ACCEPTED_WORKING_INDEX_SHA256 = "80430ce6290d0982d3641621ba1ed62f6fb495e8d32f7d23d9fca00091aadb45"
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

    def _resolve(self, path: Path, *, source_kind: str, display_name: str) -> ResolvedDatasetSource:
        local_path = path.expanduser()
        if not local_path.exists():
            raise FileNotFoundError(f"Файл датасета не найден: «{local_path}».")
        if not local_path.is_file():
            raise ValueError(f"Путь к датасету должен указывать на файл: «{local_path}».")
        try:
            physical_format = self._FORMATS[local_path.suffix.lower()]
        except KeyError as error:
            supported = ", ".join(sorted(self._FORMATS))
            raise ValueError(f"Неподдерживаемое расширение «{local_path.suffix}». Поддерживаются: {supported}.") from error
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
        return PreparedDatasetContext(
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

    @staticmethod
    def _validate_source_identity(source_path: Path) -> None:
        if _sha256_file(source_path) != _ACCEPTED_DATASET_SHA256:
            raise ValueError("Файл не соответствует принятой identity Data_final.")

    @staticmethod
    def _validate_loaded_dataset(loaded: LoadedDataset, working_split: AcceptedWorkingSplit) -> None:
        if loaded.source_file_sha256 != _ACCEPTED_DATASET_SHA256:
            raise ValueError("Загруженный Data_final не соответствует принятой identity.")
        if loaded.contract.row_count != _ACCEPTED_FULL_ROW_COUNT:
            raise ValueError("Data_final не соответствует принятому полному числу строк.")
        positions = np.asarray(working_split.row_positions, dtype=np.int64)
        if len(positions) != _ACCEPTED_WORKING_ROW_COUNT or len(positions) + _ACCEPTED_FINAL_TEST_ROW_COUNT != loaded.contract.row_count:
            raise ValueError("Принятый working/final split имеет неверный размер.")
        in_working = np.zeros(loaded.contract.row_count, dtype=bool)
        in_working[positions] = True
        if int((~in_working).sum()) != _ACCEPTED_FINAL_TEST_ROW_COUNT:
            raise ValueError("Working population не должна включать final-test строки.")
        actual_target = loaded.dataframe.iloc[positions]["DefMark"].to_numpy(dtype=np.int8)
        if not np.array_equal(actual_target, working_split.target):
            raise ValueError("Working positions не согласованы с accepted Stage 3 evidence.")

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
                "INN", "INN", "ИНН", "Идентификатор организации.", "protected_columns", "string", "identifier",
                "historical_profile_v1", FeatureUsageStatus.IDENTIFIER, None, None, None, len(allowed),
            ),
            FeatureSpec(
                "DefMark", "DefMark", "Признак дефолта", "Целевая переменная.", "protected_columns", "int", "target",
                "historical_profile_v1", FeatureUsageStatus.TARGET, None, None, None, len(allowed) + 1,
            ),
            FeatureSpec(
                "Q_B1_norm", "Q_B1_norm", "Q_B1_norm", "Закрытый reference-сигнал.", "restricted_signals", "float", "numeric",
                "historical_profile_v1", FeatureUsageStatus.BLOCKED, "Сигнал запрещён для рабочей модели.", None, None, len(allowed) + 2,
            ),
            FeatureSpec(
                "Q_B2_norm", "Q_B2_norm", "Q_B2_norm", "Закрытый reference-сигнал.", "restricted_signals", "float", "numeric",
                "historical_profile_v1", FeatureUsageStatus.BLOCKED, "Сигнал запрещён для рабочей модели.", None, None, len(allowed) + 3,
            ),
        )
        return FeatureRegistry(
            "historical-data-final-v1",
            (*allowed, *protected),
            (
                FeatureGroup("accepted_predictors", "Разрешённые показатели", "Признаки рабочего исторического профиля.", 0, "accepted_pipeline_v1", _ACCEPTED_FEATURE_IDS),
                FeatureGroup("protected_columns", "Служебные столбцы", "Идентификатор и целевая переменная доступны только для чтения.", 1, "accepted_pipeline_v1", ("INN", "DefMark")),
                FeatureGroup("restricted_signals", "Закрытые сигналы", "Сигналы не разрешены для рабочей модели.", 2, "accepted_pipeline_v1", ("Q_B1_norm", "Q_B2_norm")),
            ),
        )


def prepare_resolved_source(
    source: ResolvedDatasetSource,
    *,
    historical_provider: HistoricalDatasetProvider | None = None,
    progress_listener: Callable[[str], None] | None = None,
) -> DatasetSourcePreparation:
    """Check a source, preserving historical semantics or creating only a proposal."""
    if _sha256_file(source.local_runtime_path) != _ACCEPTED_DATASET_SHA256:
        # Resolution normally guarantees this.  Keeping the unprepared result for
        # a vanished source preserves the resolver's user-facing error boundary.
        if not source.local_runtime_path.is_file():
            return DatasetSourcePreparation(source, "context_not_prepared", None)
        _notify_data_progress(progress_listener, "reading_source")
        snapshot = TabularReader().read(source.local_runtime_path)
        _notify_data_progress(progress_listener, "inspecting_dataset")
        report = DatasetInspector().inspect(snapshot)
        _notify_data_progress(progress_listener, "analyzing_preparation")
        proposal = DatasetPreparationAnalyzer().analyze(report)
        return DatasetSourcePreparation(
            source, "context_not_prepared", None,
            snapshot=snapshot, inspection_report=report, proposal=proposal,
        )
    provider = historical_provider or HistoricalDatasetProvider()
    return DatasetSourcePreparation(
        source,
        "historical_context_prepared",
        provider.prepare(source, progress_listener=progress_listener),
    )


def default_preparation_draft(preparation: DatasetSourcePreparation) -> dict[str, Any]:
    """Return proposal-backed UI defaults; this is not a confirmation."""
    if preparation.snapshot is None or preparation.proposal is None:
        raise ValueError("No source analysis is available for preparation.")
    target = next((item.column_name for item in preparation.proposal.target_candidates), "")
    identifier = next((item.column_name for item in preparation.proposal.identifier_candidates), "")
    statuses = {
        name: (
            ConfirmedColumnStatus.MODEL_ALLOWED.value
            if predictor_compatibility_error(preparation.snapshot.dataframe[name]) is None
            else ConfirmedColumnStatus.DIAGNOSTIC_ONLY.value
        )
        for name in preparation.snapshot.physical_headers
    }
    draft = {
        "snapshot_fingerprint": preparation.snapshot.fingerprint,
        "dataset_name": preparation.source.file_name,
        "target_column": target,
        "positive_class": None,
        "identifier_column": identifier,
        "column_statuses": statuses,
        "blocked_reasons": {},
        "population_policy": PopulationPolicyV1.FULL_OOF_NO_PROTECTED_FINAL_TEST.value,
        "population_policy_acknowledged": False,
    }
    if preparation.confirmation is not None:
        confirmation = preparation.confirmation
        draft.update(
            dataset_name=confirmation.dataset_name,
            target_column=confirmation.target_column,
            positive_class=confirmation.positive_class,
            identifier_column=confirmation.identifier_column,
            column_statuses={item.column_name: item.status.value for item in confirmation.column_decisions},
            blocked_reasons={
                item.column_name: item.blocked_reason
                for item in confirmation.column_decisions if item.blocked_reason is not None
            },
        )
    return draft


def confirm_dataset_preparation(
    preparation: DatasetSourcePreparation,
    draft: Mapping[str, Any],
    *,
    progress_listener: Callable[[str], None] | None = None,
) -> DatasetSourcePreparation:
    """Materialize an immutable backend confirmation from the explicit UI draft."""
    snapshot, report, proposal = preparation.snapshot, preparation.inspection_report, preparation.proposal
    if snapshot is None or report is None or proposal is None:
        raise ValueError("No source analysis is available for confirmation.")
    if not draft.get("population_policy_acknowledged", False):
        raise DatasetPreparationError("POPULATION_POLICY_NOT_ACKNOWLEDGED")
    _notify_data_progress(progress_listener, "validating_confirmation")
    target = str(draft.get("target_column") or "")
    identifier = str(draft.get("identifier_column") or "")
    if not target or not identifier:
        raise DatasetPreparationError("INCOMPLETE_CONFIRMATION")
    if draft.get("positive_class") is None:
        raise DatasetPreparationError("POSITIVE_CLASS_MISSING")
    statuses = dict(draft.get("column_statuses") or {})
    reasons = dict(draft.get("blocked_reasons") or {})
    decisions = []
    for name in snapshot.physical_headers:
        status = ConfirmedColumnStatus.TARGET if name == target else (
            ConfirmedColumnStatus.IDENTIFIER if name == identifier else ConfirmedColumnStatus(
                statuses.get(name, ConfirmedColumnStatus.DIAGNOSTIC_ONLY.value)
            )
        )
        decisions.append(ConfirmedColumnDecision(name, status, reasons.get(name) if status is ConfirmedColumnStatus.BLOCKED else None))
    report_digest = inspection_report_hash(report)
    confirmation = ConfirmedDatasetPreparation(
        "1", snapshot.fingerprint, report_digest, proposal_hash(proposal, report_digest),
        proposal.policy_id, proposal.policy_version, proposal.policy_hash,
        str(draft.get("dataset_name") or preparation.source.file_name), target,
        draft.get("positive_class"), identifier, tuple(decisions),
        PopulationPolicyV1(draft.get("population_policy")),
    )
    _notify_data_progress(progress_listener, "materializing_dataset")
    context, manifest = KomusDatasetPreparationService().prepare(snapshot, report, proposal, confirmation)
    _notify_data_progress(progress_listener, "prepared_context_ready")
    return DatasetSourcePreparation(
        preparation.source, "confirmed_context_prepared", context,
        snapshot=snapshot, inspection_report=report, proposal=proposal,
        confirmation=confirmation, manifest=manifest,
    )


def reopen_dataset_preparation(preparation: DatasetSourcePreparation) -> DatasetSourcePreparation:
    """Drop an active arbitrary context before its confirmation is edited."""
    if preparation.preparation_status != "confirmed_context_prepared":
        raise ValueError("Only a confirmed preparation can be edited.")
    return replace(preparation, preparation_status="context_not_prepared", context=None, manifest=None)


def create_runtime(
    artifact_root: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
    result_interpreter_factories: Mapping[str, Callable[[str, str], Any]] | None = None,
) -> PrototypeRuntime:
    """Wire existing model, planning, application, persistence and comparison services."""
    component_factories = (CatBoostFactory(), XGBoostFactory(), LightGBMFactory())
    mean_factory = GBDTMeanFactory({factory.model_id: factory for factory in component_factories})
    factories = {factory.model_id: factory for factory in (*component_factories, mean_factory)}
    registry = ModelRegistry()
    for spec in (CATBOOST_MODEL_SPEC, XGBOOST_MODEL_SPEC, LIGHTGBM_MODEL_SPEC, GBDT_MEAN_MODEL_SPEC):
        registry.register(spec)
    store_root = Path(artifact_root) if artifact_root is not None else _repository_root() / ".streamlit-artifacts"
    code_version = "streamlit-prototype-v1"
    artifact_store = ExperimentArtifactStore(store_root)
    model_version_store = ModelVersionStore(
        store_root / "model_versions",
        code_version=code_version,
        model_specs={spec.model_id: spec for spec in (CATBOOST_MODEL_SPEC, XGBOOST_MODEL_SPEC, LIGHTGBM_MODEL_SPEC, GBDT_MEAN_MODEL_SPEC)},
    )
    final_model_training_service = FinalModelTrainingService(
        experiment_artifact_store=artifact_store,
        model_version_store=model_version_store,
        model_registry=registry,
        model_factories=factories,
        code_version=code_version,
    )
    runtime_configuration, interpreter_client, outbound_policy = _result_interpreter_wiring(
        environment=os.environ if environment is None else environment,
        secrets=secrets,
        factories=result_interpreter_factories,
    )
    integration_workflow_service = IntegrationWorkflowService(
        final_model_training_service=final_model_training_service,
        model_version_store=model_version_store,
        model_inference_service=ModelInferenceService(),
        local_explainers={"catboost": LocalExplanationService()},
        result_interpreter_service=ResultInterpreterService(),
        result_interpreter_client=interpreter_client,
        outbound_interpreter_policy=outbound_policy,
        result_interpreter_runtime=runtime_configuration,
    )
    return PrototypeRuntime(
        ExperimentPlanningService(),
        ExperimentApplicationService(
            model_registry=registry,
            model_factories=factories,
            artifact_store=artifact_store,
            comparison_service=ExperimentComparisonService(),
            code_version=code_version,
        ),
        registry,
        factories,
        SUPPORTED_PROTOCOL,
        integration_workflow_service,
    )


def _result_interpreter_wiring(
    *,
    environment: Mapping[str, str],
    secrets: Mapping[str, Any] | None,
    factories: Mapping[str, Callable[[str, str], Any]] | None,
) -> tuple[ResultInterpreterRuntimeConfiguration, Any | None, RedactedV1OutboundPolicy | None]:
    """Resolve external interpretation exclusively in the composition root."""
    policy = str(environment.get("KOMUS_EXTERNAL_DATA_POLICY", "")).strip()
    if not policy:
        return ResultInterpreterRuntimeConfiguration.disabled(), None, None
    if policy != "REDACTED_V1":
        return ResultInterpreterRuntimeConfiguration(policy_mode="INVALID"), None, None

    provider = str(environment.get("KOMUS_RESULT_INTERPRETER_PROVIDER", "")).strip()
    if not provider:
        return ResultInterpreterRuntimeConfiguration(policy_mode=policy), None, None
    provider_registry = dict(factories or {"openai": _openai_result_interpreter_factory})
    factory = provider_registry.get(provider)
    if factory is None:
        return ResultInterpreterRuntimeConfiguration(
            policy_mode=policy, provider_configured=True,
        ), None, None

    model = str(environment.get("KOMUS_RESULT_INTERPRETER_MODEL", "")).strip()
    if not model:
        return ResultInterpreterRuntimeConfiguration(
            policy_mode=policy, provider_configured=True, provider_registered=True,
        ), None, None
    credential = _runtime_secret("OPENAI_API_KEY", secrets=secrets, environment=environment)
    if not credential:
        return ResultInterpreterRuntimeConfiguration(
            policy_mode=policy, provider_configured=True, provider_registered=True,
            model_configured=True,
        ), None, None
    return (
        ResultInterpreterRuntimeConfiguration(
            policy_mode=policy, provider_configured=True, provider_registered=True,
            model_configured=True, credentials_configured=True,
        ),
        factory(model, credential),
        RedactedV1OutboundPolicy(),
    )


def _runtime_secret(
    name: str,
    *,
    secrets: Mapping[str, Any] | None,
    environment: Mapping[str, str],
) -> str:
    available_secrets = _streamlit_secrets() if secrets is None else secrets
    try:
        value = available_secrets.get(name) if available_secrets is not None else None
    except Exception:
        value = None
    if value is None:
        value = environment.get(name)
    return str(value).strip() if value is not None else ""


def _streamlit_secrets() -> Mapping[str, Any] | None:
    """Best-effort secrets access: a missing secrets file must not prevent launch."""
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        return None


def _openai_result_interpreter_factory(model: str, credential: str) -> OpenAIResultInterpreterClient:
    from openai import OpenAI

    return OpenAIResultInterpreterClient(model=model, client=OpenAI(api_key=credential))


def validate_supported_protocol(values: Mapping[str, Any], protocol: SupportedProtocol = SUPPORTED_PROTOCOL) -> str | None:
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
        raise ValueError("Stage 3 evidence не содержит валидные working row positions.") from error
    if (
        working_indices.ndim != 1
        or len(working_indices) != _ACCEPTED_WORKING_ROW_COUNT
        or len(np.unique(working_indices)) != len(working_indices)
        or _sha256_int64(working_indices) != _ACCEPTED_WORKING_INDEX_SHA256
        or target.shape != working_indices.shape
    ):
        raise ValueError("Working row positions не соответствуют принятой Stage 1 identity.")
    if working_indices.min() < 0 or working_indices.max() >= _ACCEPTED_FULL_ROW_COUNT:
        raise ValueError("Working row positions выходят за границы accepted Data_final.")
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
