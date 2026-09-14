"""Composition root for the Streamlit prototype.

This module owns the frozen historical dataset definition and runtime wiring.  The
presentation layer receives only a fully prepared context and application-facing
services; it never constructs backend contracts itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

import numpy as np

from komus_risk.application import ExperimentApplicationService
from komus_risk.artifacts import ExperimentArtifactStore
from komus_risk.comparison import ExperimentComparisonService
from komus_risk.contracts import FeatureGroup, FeatureSpec, FeatureUsageStatus
from komus_risk.data import LoadedDataset, ReadyDatasetAdapter
from komus_risk.experiments import EvaluationPopulation
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
class PreparedDatasetContext:
    """The complete, runtime-only dataset bundle available to the UI."""

    context_id: str
    display_name: str
    loaded_dataset: LoadedDataset
    feature_registry: FeatureRegistry
    population: EvaluationPopulation


@dataclass(frozen=True, slots=True)
class ContextOption:
    context_id: str
    display_name: str
    upload_capable: bool


class DatasetContextProvider(Protocol):
    context_id: str
    display_name: str
    upload_capable: bool

    def resolve(
        self,
        optional_uploaded_file: Any | None = None,
        progress_listener: Callable[[str], None] | None = None,
    ) -> PreparedDatasetContext: ...


@dataclass(frozen=True, slots=True)
class PrototypeRuntime:
    planning_service: ExperimentPlanningService
    application_service: ExperimentApplicationService
    model_registry: ModelRegistry
    model_factories: Mapping[str, ModelAdapterFactory]
    supported_protocol: "SupportedProtocol"


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


class HistoricalDatasetProvider:
    """One explicit provider for the accepted historical Pipeline V1 profile."""

    context_id = "historical_data_final_v1"
    display_name = "Исторический Data_final — рабочая популяция"
    upload_capable = True

    def __init__(self, source_path: Path | None = None) -> None:
        self._source_path = source_path or Path(__file__).resolve().parents[1] / "data" / "raw" / "Data_final.xlsb"

    def resolve(
        self,
        optional_uploaded_file: Any | None = None,
        progress_listener: Callable[[str], None] | None = None,
    ) -> PreparedDatasetContext:
        registry = self._feature_registry()
        temporary_upload: Path | None = None
        try:
            source_path, temporary_upload = self._source(optional_uploaded_file)
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
        finally:
            if temporary_upload is not None and temporary_upload.exists():
                temporary_upload.unlink()
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

    def _source(self, optional_uploaded_file: Any | None) -> tuple[Path, Path | None]:
        if optional_uploaded_file is None:
            return self._source_path, None
        if isinstance(optional_uploaded_file, (str, Path)):
            return Path(optional_uploaded_file), None
        name = getattr(optional_uploaded_file, "name", "uploaded")
        content = optional_uploaded_file.getvalue()
        with NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as temporary:
            temporary.write(content)
            return Path(temporary.name), Path(temporary.name)

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


_PROVIDERS: Mapping[str, DatasetContextProvider] = {
    HistoricalDatasetProvider.context_id: HistoricalDatasetProvider(),
}


def list_available_contexts(
    providers: Mapping[str, DatasetContextProvider] | None = None,
) -> tuple[ContextOption, ...]:
    """List only explicit, composition-owned dataset contexts."""
    source = _PROVIDERS if providers is None else providers
    return tuple(
        ContextOption(provider.context_id, provider.display_name, provider.upload_capable)
        for provider in source.values()
    )


def resolve_context(
    context_id: str,
    optional_uploaded_file: Any | None = None,
    *,
    providers: Mapping[str, DatasetContextProvider] | None = None,
    progress_listener: Callable[[str], None] | None = None,
) -> PreparedDatasetContext:
    """Resolve a selected provider; there is intentionally no generic upload path."""
    source = _PROVIDERS if providers is None else providers
    try:
        provider = source[context_id]
    except KeyError as error:
        raise ValueError("Неизвестный подготовленный контекст данных.") from error
    if optional_uploaded_file is not None and not provider.upload_capable:
        raise ValueError("Выбранный контекст не поддерживает загрузку файла.")
    if progress_listener is None:
        return provider.resolve(optional_uploaded_file)
    return provider.resolve(optional_uploaded_file, progress_listener=progress_listener)


def create_runtime(artifact_root: str | Path | None = None) -> PrototypeRuntime:
    """Wire existing model, planning, application, persistence and comparison services."""
    component_factories = (CatBoostFactory(), XGBoostFactory(), LightGBMFactory())
    mean_factory = GBDTMeanFactory({factory.model_id: factory for factory in component_factories})
    factories = {factory.model_id: factory for factory in (*component_factories, mean_factory)}
    registry = ModelRegistry()
    for spec in (CATBOOST_MODEL_SPEC, XGBOOST_MODEL_SPEC, LIGHTGBM_MODEL_SPEC, GBDT_MEAN_MODEL_SPEC):
        registry.register(spec)
    store_root = Path(artifact_root) if artifact_root is not None else _repository_root() / ".streamlit-artifacts"
    return PrototypeRuntime(
        ExperimentPlanningService(),
        ExperimentApplicationService(
            model_registry=registry,
            model_factories=factories,
            artifact_store=ExperimentArtifactStore(store_root),
            comparison_service=ExperimentComparisonService(),
            code_version="streamlit-prototype-v1",
        ),
        registry,
        factories,
        SUPPORTED_PROTOCOL,
    )


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
