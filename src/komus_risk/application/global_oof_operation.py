"""Persisted, deduplicated lifecycle for trusted global OOF derivations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from komus_risk.hashing import canonical_json, stable_hash

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .oof_explanation import GlobalOOFExplanation

_SCHEMA = "global_oof_derived_v1"
_STAGE_LABELS = {
    "VALIDATING": "Проверка",
    "PROCESSING_FOLD": "Обработка части",
    "AGGREGATING": "Агрегация",
    "PERSISTING": "Сохранение",
    "READY": "Готово",
    "FAILED": "Ошибка",
}
_TRUSTED_OPERATION_ERROR_CODES = frozenset({
    "FOLD_MODEL_UNAVAILABLE",
    "GLOBAL_OOF_EXPLANATION_FAILED",
    "GLOBAL_OOF_EXPLANATION_INCOMPATIBLE",
    "GLOBAL_OOF_EXPLANATION_UNSUPPORTED",
    "OOF_PREDICTION_MISMATCH",
    "PROVENANCE_MISMATCH",
})


@dataclass(frozen=True, slots=True)
class GlobalOOFOperationSnapshot:
    artifact_id: str
    derivation_key: str
    status: str
    stage: str
    stage_label: str
    current_fold: int | None
    total_folds: int
    processed_rows: int
    total_rows: int
    started_at: str | None
    updated_at: str
    elapsed_seconds: float
    safe_error_code: str | None = None
    message: str | None = None


class GlobalOOFOperationFailed(ValueError):
    """Stable operation failure whose code survives the worker boundary."""

    def __init__(self, code: str) -> None:
        if code not in _TRUSTED_OPERATION_ERROR_CODES:
            raise ValueError("Operation failure code is not a trusted stable code.")
        self.code = code
        super().__init__(code)


class GlobalOOFDerivedStore:
    """Content-addressed derived-result files, separate from immutable artifacts."""

    def __init__(self, artifact_root: str | Path) -> None:
        self.root = Path(artifact_root) / "derived" / "global-oof-v1"

    def load(self, derivation_key: str, expected: dict[str, Any]) -> GlobalOOFExplanation | None:
        directory = self.root / derivation_key
        if not directory.exists():
            return None
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            payload = (directory / "result.json").read_bytes()
            result_data = json.loads(payload.decode("utf-8"))
            if (directory.name != derivation_key or manifest.get("schema") != _SCHEMA
                    or manifest.get("derivation_key") != derivation_key
                    or manifest.get("identity") != expected
                    or manifest.get("result_hash") != stable_hash(result_data)):
                raise ValueError("derived result identity or hash is invalid")
            result = _result_from_dict(result_data)
            _validate_result(result, expected)
            return result
        except Exception as error:
            raise ValueError("GLOBAL_OOF_DERIVED_EVIDENCE_INVALID") from error

    def publish(self, derivation_key: str, expected: dict[str, Any], result: GlobalOOFExplanation) -> GlobalOOFExplanation:
        _validate_result(result, expected)
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / derivation_key
        if target.exists():
            loaded = self.load(derivation_key, expected)
            if loaded is None:
                raise ValueError("GLOBAL_OOF_DERIVED_EVIDENCE_INVALID")
            return loaded
        temporary = self.root / f".tmp-{derivation_key}-{uuid4().hex}"
        temporary.mkdir()
        try:
            data = _result_to_dict(result)
            result_bytes = canonical_json(data).encode("utf-8")
            manifest = {"schema": _SCHEMA, "derivation_key": derivation_key,
                        "identity": expected, "result_hash": stable_hash(data)}
            (temporary / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
            (temporary / "result.json").write_bytes(result_bytes)
            # Verify the exact bytes and schema before making the directory visible.
            check = json.loads((temporary / "result.json").read_text(encoding="utf-8"))
            if stable_hash(check) != manifest["result_hash"]:
                raise ValueError("derived result integrity check failed")
            try:
                os.rename(temporary, target)
            except FileExistsError:
                shutil.rmtree(temporary, ignore_errors=True)
            loaded = self.load(derivation_key, expected)
            if loaded is None:
                raise ValueError("derived result publication failed")
            return loaded
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise


@dataclass(slots=True)
class _Attempt:
    token: str
    snapshot: GlobalOOFOperationSnapshot
    result: GlobalOOFExplanation | None = None
    event: threading.Event | None = None
    monotonic_started: float = 0.0
    identity: dict[str, Any] | None = None


class GlobalOOFOperationService:
    """Process-local thread-safe operation registry with ownership-safe retry."""

    def __init__(self, derived_store: GlobalOOFDerivedStore) -> None:
        self.derived_store = derived_store
        self._lock = threading.RLock()
        self._attempts: dict[str, _Attempt] = {}
        self._not_started_snapshots: dict[str, GlobalOOFOperationSnapshot] = {}
        self._not_started_resolved: set[str] = set()

    def get_or_run(self, *, artifact_id: str, derivation_key: str,
                   identity: dict[str, Any], total_rows: int, total_folds: int,
                   compute: Callable[[str, Callable[[int, int], None]], GlobalOOFExplanation]) -> GlobalOOFExplanation:
        self.start(artifact_id=artifact_id, derivation_key=derivation_key, identity=identity,
                   total_rows=total_rows, total_folds=total_folds, compute=compute)
        return self.wait_result(derivation_key)

    def start(self, *, artifact_id: str, derivation_key: str, identity: dict[str, Any],
              total_rows: int, total_folds: int,
              compute: Callable[[str, Callable[[int, int], None]], GlobalOOFExplanation]) -> GlobalOOFOperationSnapshot:
        """Start one background attempt, or return its existing process-local state."""
        worker = None
        with self._lock:
            active = self._attempts.get(derivation_key)
            if active is not None:
                return active.snapshot
            self._not_started_snapshots.pop(derivation_key, None)
            self._not_started_resolved.discard(derivation_key)
            persisted = self.derived_store.load(derivation_key, identity)
            attempt = self._new_attempt(artifact_id, derivation_key, total_rows, total_folds)
            attempt.identity = identity
            if persisted is not None:
                attempt.result = persisted
                attempt.snapshot = _snapshot(attempt.snapshot, status="READY", stage="READY", stage_label=_STAGE_LABELS["READY"],
                    processed_rows=total_rows, monotonic_started=attempt.monotonic_started)
                self._attempts[derivation_key] = attempt
                attempt.event.set()
                return attempt.snapshot
            self._attempts[derivation_key] = attempt
            worker = threading.Thread(target=self._execute, args=(attempt, compute), daemon=True,
                                      name=f"global-oof-{derivation_key[:10]}")
            worker.start()
            return attempt.snapshot

    def wait_result(self, derivation_key: str, timeout: float | None = None) -> GlobalOOFExplanation:
        with self._lock:
            attempt = self._attempts.get(derivation_key)
        if attempt is None or attempt.event is None:
            raise ValueError("GLOBAL_OOF_OPERATION_NOT_STARTED")
        if not attempt.event.wait(timeout):
            raise TimeoutError("GLOBAL_OOF_OPERATION_RUNNING")
        if attempt.snapshot.status == "FAILED":
            raise GlobalOOFOperationFailed(attempt.snapshot.safe_error_code or "GLOBAL_OOF_EXPLANATION_FAILED")
        if attempt.snapshot.status != "READY" or attempt.identity is None:
            raise ValueError("GLOBAL_OOF_EXPLANATION_FAILED")
        persisted = self.derived_store.load(derivation_key, attempt.identity)
        if persisted is None:
            raise ValueError("GLOBAL_OOF_DERIVED_EVIDENCE_INVALID")
        attempt.result = persisted
        return persisted

    def _execute(self, attempt, compute):
        key = attempt.snapshot.derivation_key
        try:
            with self._lock:
                if self._attempts.get(key) is attempt:
                    attempt.snapshot = _snapshot(attempt.snapshot, stage="PROCESSING_FOLD", stage_label=_STAGE_LABELS["PROCESSING_FOLD"],
                                                 monotonic_started=attempt.monotonic_started)
            result = compute(attempt.token, lambda fold, rows: self._progress(key, attempt.token, fold, rows))
            self._progress_stage(key, attempt.token, "AGGREGATING")
            self._progress_stage(key, attempt.token, "PERSISTING")
            persisted = self.derived_store.publish(key, attempt.identity, result)
            with self._lock:
                if self._attempts.get(key) is attempt:
                    attempt.result = persisted
                    attempt.snapshot = _snapshot(attempt.snapshot, status="READY", stage="READY", stage_label=_STAGE_LABELS["READY"],
                        processed_rows=attempt.snapshot.total_rows, monotonic_started=attempt.monotonic_started)
                attempt.event.set()
        except Exception as error:
            with self._lock:
                if self._attempts.get(key) is attempt:
                    code = (error.code if isinstance(error, GlobalOOFOperationFailed)
                            else "GLOBAL_OOF_EXPLANATION_FAILED")
                    attempt.snapshot = _snapshot(attempt.snapshot, status="FAILED", stage="FAILED", stage_label=_STAGE_LABELS["FAILED"],
                        current_fold=None, safe_error_code=code,
                        monotonic_started=attempt.monotonic_started)
                attempt.event.set()

    def retry(self, derivation_key: str) -> None:
        with self._lock:
            attempt = self._attempts.get(derivation_key)
            if attempt and attempt.snapshot.status == "RUNNING":
                raise ValueError("GLOBAL_OOF_OPERATION_RUNNING")
            self._attempts.pop(derivation_key, None)
            self._not_started_snapshots.pop(derivation_key, None)
            self._not_started_resolved.discard(derivation_key)

    def status(self, derivation_key: str, *, artifact_id: str | None = None,
               identity: dict[str, Any] | None = None, total_rows: int = 0,
               total_folds: int = 0) -> GlobalOOFOperationSnapshot:
        with self._lock:
            attempt = self._attempts.get(derivation_key)
            if attempt:
                if attempt.snapshot.status == "RUNNING":
                    return _snapshot(attempt.snapshot, monotonic_started=attempt.monotonic_started,
                                     refresh_updated_at=False)
                return attempt.snapshot

            not_started = self._not_started_snapshots.get(derivation_key)
            if not_started is not None:
                needs_resolution = identity is not None and derivation_key not in self._not_started_resolved
                if needs_resolution:
                    persisted = self.derived_store.load(derivation_key, identity)
                    self._not_started_resolved.add(derivation_key)
                    if persisted is not None:
                        attempt = self._new_attempt(artifact_id or not_started.artifact_id,
                                                    derivation_key, total_rows, total_folds)
                        attempt.identity = identity
                        attempt.result = persisted
                        attempt.snapshot = _snapshot(attempt.snapshot, status="READY", stage="READY",
                            stage_label=_STAGE_LABELS["READY"], processed_rows=total_rows,
                            monotonic_started=attempt.monotonic_started)
                        self._attempts[derivation_key] = attempt
                        self._not_started_snapshots.pop(derivation_key, None)
                        attempt.event.set()
                        return attempt.snapshot
                if not_started.artifact_id or artifact_id is None:
                    return not_started
                enriched = GlobalOOFOperationSnapshot(
                    artifact_id, derivation_key, "NOT_STARTED", "VALIDATING",
                    "\u041d\u0435 \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u043e", None,
                    total_folds, 0, total_rows, None, not_started.updated_at, 0.0,
                )
                self._not_started_snapshots[derivation_key] = enriched
                return enriched

            if artifact_id is not None and identity is not None:
                persisted = self.derived_store.load(derivation_key, identity)
                if persisted is not None:
                    attempt = self._new_attempt(artifact_id, derivation_key, total_rows, total_folds)
                    attempt.identity = identity
                    attempt.result = persisted
                    attempt.snapshot = _snapshot(attempt.snapshot, status="READY", stage="READY",
                        stage_label=_STAGE_LABELS["READY"], processed_rows=total_rows,
                        monotonic_started=attempt.monotonic_started)
                    self._attempts[derivation_key] = attempt
                    attempt.event.set()
                    return attempt.snapshot
                self._not_started_resolved.add(derivation_key)

            now = _now()
            snapshot = GlobalOOFOperationSnapshot(
                artifact_id or "", derivation_key, "NOT_STARTED", "VALIDATING",
                "\u041d\u0435 \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u043e", None,
                total_folds, 0, total_rows, None, now, 0.0,
            )
            self._not_started_snapshots[derivation_key] = snapshot
            return snapshot

    def _new_attempt(self, artifact_id, key, total_rows, total_folds):
        now = _now()
        snapshot = GlobalOOFOperationSnapshot(artifact_id, key, "RUNNING", "VALIDATING", _STAGE_LABELS["VALIDATING"], None,
            total_folds, 0, total_rows, now, now, 0.0)
        attempt = _Attempt(uuid4().hex, snapshot, event=threading.Event(), monotonic_started=time.monotonic())
        return attempt

    def _progress(self, key, token, fold, rows):
        with self._lock:
            attempt = self._attempts.get(key)
            if attempt is None or attempt.token != token or attempt.snapshot.status != "RUNNING":
                return
            if rows < attempt.snapshot.processed_rows or rows > attempt.snapshot.total_rows:
                raise ValueError("GLOBAL_OOF_PROGRESS_INVALID")
            attempt.snapshot = _snapshot(attempt.snapshot, stage="PROCESSING_FOLD", stage_label=_STAGE_LABELS["PROCESSING_FOLD"], current_fold=fold, processed_rows=rows, monotonic_started=attempt.monotonic_started)

    def _progress_stage(self, key, token, stage):
        with self._lock:
            attempt = self._attempts.get(key)
            if attempt and attempt.token == token and attempt.snapshot.status == "RUNNING":
                attempt.snapshot = _snapshot(attempt.snapshot, stage=stage,
                    stage_label=_STAGE_LABELS[stage], current_fold=None,
                    monotonic_started=attempt.monotonic_started)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot(old, *, refresh_updated_at: bool = True, **changes):
    started = changes.pop("monotonic_started", None)
    elapsed = max(0.0, time.monotonic() - started) if started is not None else old.elapsed_seconds
    data = asdict(old)
    data.update(changes)
    data["updated_at"] = _now() if refresh_updated_at else old.updated_at
    data["elapsed_seconds"] = elapsed
    return GlobalOOFOperationSnapshot(**data)


def _result_to_dict(result):
    data = asdict(result)
    data["fold_model_binding_ids"] = list(result.fold_model_binding_ids)
    data["features"] = [asdict(feature) for feature in result.features]
    return data


def _result_from_dict(data):
    from .oof_explanation import GlobalOOFExplanation, GlobalOOFFeatureImportance
    return GlobalOOFExplanation(
        artifact_id=data["artifact_id"], model_id=data["model_id"], model_version=data["model_version"],
        row_count=data["row_count"], feature_count=data["feature_count"], output_space=data["output_space"],
        provider_id=data["provider_id"], provider_version=data["provider_version"],
        explanation_method_id=data["explanation_method_id"], explanation_method_version=data["explanation_method_version"],
        background_policy_id=data["background_policy_id"], feature_binding_hash=data["feature_binding_hash"],
        fold_model_binding_ids=tuple(data["fold_model_binding_ids"]),
        features=tuple(GlobalOOFFeatureImportance(**feature) for feature in data["features"]),
        evidence_hash=data["evidence_hash"],
    )


def _validate_result(result, identity):
    if (result.artifact_id != identity["artifact_id"] or result.row_count != identity["row_count"] or result.row_count <= 0
            or result.feature_count != len(result.features) or result.feature_count != identity["feature_count"]
            or tuple(item.feature_id for item in result.features) != tuple(
                sorted(identity["feature_ids"], key=lambda feature_id: (
                    next(-item.mean_abs_shap for item in result.features if item.feature_id == feature_id),
                    identity["feature_ids"].index(feature_id),
                ))
            )
            or tuple(item.column_name for item in result.features) != tuple(
                identity["feature_columns"][identity["feature_ids"].index(item.feature_id)]
                for item in result.features
            )
            or tuple(result.fold_model_binding_ids) != tuple(identity["fold_model_binding_ids"])
            or result.provider_id != identity["provider_id"] or result.provider_version != identity["provider_version"]
            or result.explanation_method_id != identity["explanation_method_id"]
            or result.explanation_method_version != identity["explanation_method_version"]
            or result.output_space != identity["output_space"]
            or result.background_policy_id != identity["background_policy_id"]
            or result.feature_binding_hash != identity["feature_binding_hash"]
            or len({item.feature_id for item in result.features}) != len(result.features)
            or len({item.column_name for item in result.features}) != len(result.features)
            or [item.rank for item in result.features] != list(range(1, result.feature_count + 1))
            or any(not math.isfinite(item.mean_abs_shap) or item.mean_abs_shap < 0 for item in result.features)):
        raise ValueError("GLOBAL_OOF_DERIVED_EVIDENCE_INVALID")
    payload = {"artifact_id": result.artifact_id, "model_id": result.model_id, "model_version": result.model_version,
        "row_count": result.row_count, "feature_count": result.feature_count, "output_space": result.output_space,
        "provider_id": result.provider_id, "provider_version": result.provider_version,
        "explanation_method_id": result.explanation_method_id, "explanation_method_version": result.explanation_method_version,
        "background_policy_id": result.background_policy_id, "feature_binding_hash": result.feature_binding_hash,
        "fold_model_binding_ids": list(result.fold_model_binding_ids),
        "fold_background_hashes": identity["fold_background_hashes"],
        "aggregation_method_id": identity["aggregation_method_id"],
        "aggregation_method_version": identity["aggregation_method_version"],
        "numerical_validation_profile_id": identity["numerical_validation_profile_id"],
        "numerical_validation_profile_version": identity["numerical_validation_profile_version"],
        "features": [(item.feature_id, item.column_name, item.mean_abs_shap, item.rank) for item in result.features]}
    if stable_hash(payload) != result.evidence_hash:
        raise ValueError("GLOBAL_OOF_DERIVED_EVIDENCE_INVALID")
