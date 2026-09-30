"""Framework-neutral Quality V1A plan and technical preflight use case."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from komus_risk.model_platform import SmokeStatus
from komus_risk.planning import ExperimentPlanningService
from komus_risk.preparation import PreparedDatasetContextAuthority

from .contracts import RunExperimentRequest
from .native_session import (NativeSessionStore, QualityPlanStatus, QualityPreflightStatus)
from .service import ExperimentApplicationService, to_planning_request_metadata


@dataclass(frozen=True, slots=True)
class QualityProtocol:
    protocol_id: str
    protocol_version: str
    evaluation_level: str
    minimum_folds: int
    default_folds: int
    default_seed: int


class NativeQualityService:
    def __init__(self, *, session_store: NativeSessionStore, planning_service: ExperimentPlanningService, application_service: ExperimentApplicationService, prepared_context_authority: PreparedDatasetContextAuthority, supported_protocol: Any) -> None:
        self._sessions = session_store
        self._planning = planning_service
        self._application = application_service
        self._authority = prepared_context_authority
        self.protocol = QualityProtocol(**{name: getattr(supported_protocol, name) for name in QualityProtocol.__dataclass_fields__})

    def state(self, session_id: str) -> dict[str, Any]:
        values = self._sessions.quality_state(session_id, default_seed=self.protocol.default_seed, default_folds=self.protocol.default_folds)
        context_id, features, model_id, mode, overrides, seed, folds, plan, preflight, identity, failure, operation_token = values
        context = self._authority.resolve(context_id)
        model = next((item for item in self._planning.list_models() if item.model_id == model_id), None)
        return {
            "summary": {"dataset_name": context.loaded_dataset.contract.dataset_name, "population_size": len(context.population.row_positions), "selected_feature_count": len(features), "selected_model_id": model_id, "selected_model_display_name_ru": model.display_name_ru if model else model_id, "configuration_mode": mode},
            "supported_protocol": asdict(self.protocol),
            "settings": {"folds": folds, "seed": seed},
            "plan": {"status": plan.value, "safe_validation_state": "Готов к технической проверке." if plan is QualityPlanStatus.VALID else ("Конфигурация требует корректировки." if plan is QualityPlanStatus.INVALID else "Проверка ещё не выполнена.")},
            "preflight": {"status": preflight.value, "identity": identity, "failure_code": failure, "message": self._safe_message(plan, preflight)},
            "can_start_training": bool(
                plan is QualityPlanStatus.VALID
                and preflight is QualityPreflightStatus.PASS
                and identity
                and operation_token
            ),
        }

    def update_settings(self, session_id: str, *, seed: int, folds: int) -> dict[str, Any]:
        if folds < self.protocol.minimum_folds:
            raise ValueError("INVALID_FOLDS")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("INVALID_SEED")
        self._sessions.set_quality_settings(session_id, seed=seed, folds=folds)
        return self.state(session_id)

    def preflight(self, session_id: str) -> dict[str, Any]:
        operation_token, captured = self._sessions.begin_quality_preflight(
            session_id,
            default_seed=self.protocol.default_seed,
            default_folds=self.protocol.default_folds,
        )
        context_id, features, model_id, mode, overrides, seed, folds = captured
        request = RunExperimentRequest(features, model_id, self.protocol.protocol_id, self.protocol.protocol_version, seed, folds, self.protocol.evaluation_level, None, None, (), mode, overrides)
        plan_status = QualityPlanStatus.IDLE
        try:
            context = self._authority.resolve(context_id)
            plan = self._planning.build_plan(to_planning_request_metadata(request), loaded_dataset=context.loaded_dataset, feature_registry=context.feature_registry, population=context.population)
            if not plan.is_valid:
                self._sessions.set_quality_preflight(session_id, operation_token=operation_token, plan_status=QualityPlanStatus.INVALID, preflight_status=QualityPreflightStatus.FAIL, failure_code="PLAN_INVALID")
                return self._current_state(session_id)
            plan_status = QualityPlanStatus.VALID
            evidence = self._application.run_configuration_smoke(loaded_dataset=context.loaded_dataset, feature_registry=context.feature_registry, population=context.population, request=request, prepared_context_id=context_id)
            status = QualityPreflightStatus.PASS if evidence.status is SmokeStatus.PASS else QualityPreflightStatus.FAIL
            self._sessions.set_quality_preflight(session_id, operation_token=operation_token, plan_status=QualityPlanStatus.VALID, preflight_status=status, identity=evidence.smoke_identity, failure_code=evidence.failure_code)
        except Exception:
            self._sessions.set_quality_preflight(session_id, operation_token=operation_token, plan_status=plan_status, preflight_status=QualityPreflightStatus.FAIL, failure_code="PREFLIGHT_UNAVAILABLE")
        return self._current_state(session_id)

    def _current_state(self, session_id: str) -> dict[str, Any]:
        """A superseded worker can only observe the current state, never publish its result."""
        try:
            return self.state(session_id)
        except Exception:
            return {
                "plan": {"status": QualityPlanStatus.IDLE.value, "safe_validation_state": "Проверка ещё не выполнена."},
                "preflight": {"status": QualityPreflightStatus.IDLE.value, "identity": None, "failure_code": None, "message": "Сначала подтвердите актуальные настройки алгоритма."},
                "can_start_training": False,
            }

    @staticmethod
    def _safe_message(plan: QualityPlanStatus, preflight: QualityPreflightStatus) -> str | None:
        if plan is QualityPlanStatus.INVALID:
            return "Конфигурация не готова к запуску. Вернитесь к настройкам алгоритма."
        if preflight is QualityPreflightStatus.FAIL:
            return "Предварительная проверка не завершилась. Проверьте конфигурацию и повторите попытку."
        if preflight is QualityPreflightStatus.RUNNING:
            return "Выполняем предварительную проверку…"
        return None
