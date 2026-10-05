"""Read-only Result V2 access to validated V3 OOF experiment evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from komus_risk.artifacts import ExperimentArtifactStore, LoadedExperimentArtifact
from komus_risk.hashing import stable_hash


_V3_SCHEMA_VERSION = "3"
_OUTCOMES = frozenset({"TP", "TN", "FP", "FN"})
_TARGETS = frozenset({"ANY", "POSITIVE", "NEGATIVE"})
_SORTS = frozenset(
    {"SCORE_DESC", "SCORE_ASC", "DISTANCE_TO_THRESHOLD_ASC"}
)
_MAX_LIMIT = 1_000


class OOFResultError(ValueError):
    """Stable fail-closed error returned by the Result V2 application boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OOFResultSummary:
    artifact_id: str
    result_id: str
    model_id: str
    model_version: str
    object_count: int
    feature_count: int
    folds: int
    evaluation_level: str
    runtime_seconds: float | None
    gini: float
    roc_auc: float
    pr_auc: float
    fold_metrics: tuple[Mapping[str, object], ...]
    limitations: tuple[str, ...]
    capture: "OOFResultCapture"


@dataclass(frozen=True, slots=True)
class OOFResultCapturePoint:
    """One compact, trusted point of the cumulative OOF capture curve."""

    object_share: float
    event_share: float


@dataclass(frozen=True, slots=True)
class OOFResultCapture:
    """Read-only cumulative capture facts derived from validated OOF evidence."""

    total_positive_events: int
    points: tuple[OOFResultCapturePoint, ...]
    marker: OOFResultCapturePoint | None


@dataclass(frozen=True, slots=True)
class OOFThresholdMetrics:
    artifact_id: str
    threshold: float
    tp: int
    tn: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    above_threshold_count: int
    above_threshold_share: float


@dataclass(frozen=True, slots=True)
class OOFObjectListItem:
    object_id: str
    identifier_display: str
    y_true: int
    score: float
    predicted_positive: bool
    outcome: str


@dataclass(frozen=True, slots=True)
class OOFObjectList:
    artifact_id: str
    threshold: float
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    returned_count: int
    items: tuple[OOFObjectListItem, ...]


@dataclass(frozen=True, slots=True)
class OOFObjectDetail:
    artifact_id: str
    object_id: str
    identifier_display: str
    y_true: int
    score: float
    threshold: float
    predicted_positive: bool
    outcome: str
    fold_number: int


@dataclass(frozen=True, slots=True)
class _OOFContext:
    artifact: LoadedExperimentArtifact
    y_true: np.ndarray
    scores: np.ndarray
    folds: np.ndarray
    row_positions: np.ndarray
    identifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedOOFObject:
    """Internal shared Object Detail identity resolution for Result V2 consumers."""

    context: _OOFContext
    index: int
    object_id: str


class OOFResultService:
    """Serves immutable V3 OOF facts without accessing a runner or final test data."""

    def __init__(self, artifact_store: ExperimentArtifactStore) -> None:
        self.artifact_store = artifact_store

    def summary(self, artifact_id: str) -> OOFResultSummary:
        context = self._context(artifact_id)
        result = context.artifact.run_output.result
        metrics = result.metrics
        return OOFResultSummary(
            artifact_id=context.artifact.artifact_id,
            result_id=result.result_id,
            model_id=result.model_id,
            model_version=result.model_version,
            object_count=len(context.scores),
            feature_count=len(context.artifact.config.feature_ids),
            folds=context.artifact.config.folds,
            evaluation_level=result.evaluation_level,
            runtime_seconds=result.runtime_seconds,
            gini=self._metric(metrics, "gini"),
            roc_auc=self._metric(metrics, "roc_auc"),
            pr_auc=self._metric(metrics, "pr_auc"),
            fold_metrics=tuple(
                MappingProxyType(dict(item)) for item in result.fold_metrics
            ),
            limitations=tuple(result.limitations),
            capture=self._capture(context),
        )

    def threshold(self, artifact_id: str, threshold: float) -> OOFThresholdMetrics:
        context = self._context(artifact_id)
        value = self._threshold(threshold)
        return self._threshold_metrics(context, value)

    def threshold_sweep(self, artifact_id: str) -> tuple[OOFThresholdMetrics, ...]:
        """Return exact 0.01 threshold steps from immutable OOF evidence."""
        context = self._context(artifact_id)
        return tuple(
            self._threshold_metrics(context, index / 100)
            for index in range(101)
        )

    def objects(
        self,
        artifact_id: str,
        threshold: float,
        offset: int,
        limit: int,
        search: str | None = None,
        target: str | None = None,
        outcomes: Sequence[str] | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        sort: str = "SCORE_DESC",
    ) -> OOFObjectList:
        context = self._context(artifact_id)
        value = self._threshold(threshold)
        self._paging(offset, limit)
        target_value = self._target(target)
        outcomes_value = self._outcomes(outcomes)
        min_value, max_value = self._score_bounds(min_score, max_score)
        if not isinstance(sort, str) or sort not in _SORTS:
            raise OOFResultError("INVALID_QUERY")

        predicted = context.scores >= value
        outcome = self._outcomes_for(context.y_true, predicted)
        mask = np.ones(len(context.scores), dtype=bool)
        if search is not None:
            if not isinstance(search, str):
                raise OOFResultError("INVALID_QUERY")
            needle = search.strip().casefold()
            if needle:
                mask &= np.fromiter(
                    (needle in identifier.casefold() for identifier in context.identifiers),
                    dtype=bool,
                    count=len(context.identifiers),
                )
        if target_value == "POSITIVE":
            mask &= context.y_true == 1
        elif target_value == "NEGATIVE":
            mask &= context.y_true == 0
        if outcomes_value is not None:
            mask &= np.isin(outcome, tuple(outcomes_value))
        if min_value is not None:
            mask &= context.scores >= min_value
        if max_value is not None:
            mask &= context.scores <= max_value

        selected = np.flatnonzero(mask)
        ordered = self._sort_indices(context, selected, value, sort)
        page = ordered[offset : offset + limit]
        items = tuple(
            self._list_item(context, index, value, predicted, outcome) for index in page
        )
        return OOFObjectList(
            artifact_id=context.artifact.artifact_id,
            threshold=value,
            total_count=len(context.scores),
            filtered_count=len(ordered),
            offset=offset,
            limit=limit,
            returned_count=len(items),
            items=items,
        )

    def object_detail(
        self, artifact_id: str, object_id: str, threshold: float
    ) -> OOFObjectDetail:
        context = self._context(artifact_id)
        value = self._threshold(threshold)
        resolved = _resolve_oof_object(context, object_id)
        index = resolved.index
        predicted = bool(context.scores[index] >= value)
        return OOFObjectDetail(
            artifact_id=context.artifact.artifact_id,
            object_id=object_id,
            identifier_display=context.identifiers[index],
            y_true=int(context.y_true[index]),
            score=float(context.scores[index]),
            threshold=value,
            predicted_positive=predicted,
            outcome=self._outcome(int(context.y_true[index]), predicted),
            fold_number=int(context.folds[index]),
        )

    def _context(self, artifact_id: str) -> _OOFContext:
        try:
            artifact = self.artifact_store.load(artifact_id)
        except (OSError, ValueError) as error:
            message = str(error)
            code = (
                "RESULT_NOT_FOUND"
                if "directory is missing" in message or "Invalid experiment artifact identifier" in message
                else "RESULT_INTEGRITY_ERROR"
            )
            raise OOFResultError(code) from error
        return self._validated_context(artifact)

    def _validated_context(self, artifact: LoadedExperimentArtifact) -> _OOFContext:
        if artifact.manifest.get("artifact_schema_version") != _V3_SCHEMA_VERSION:
            raise OOFResultError("OOF_RESULT_EVIDENCE_INCOMPLETE")
        evidence = artifact.run_output.oof_evidence
        if evidence is None:
            raise OOFResultError("OOF_RESULT_EVIDENCE_INCOMPLETE")
        try:
            y_true = np.asarray(evidence.y_true)
            scores = np.asarray(artifact.run_output.oof_positive_proba)
            folds = np.asarray(artifact.run_output.fold_assignments)
            row_positions = np.asarray(artifact.run_output.row_positions)
            identifiers = tuple(evidence.identifier_display)
            n_rows = len(scores)
            complete = (
                y_true.ndim == scores.ndim == folds.ndim == row_positions.ndim == 1
                and len(y_true) == len(folds) == len(row_positions) == len(identifiers) == n_rows
                and n_rows > 0
                and np.issubdtype(y_true.dtype, np.integer)
                and np.issubdtype(scores.dtype, np.number)
                and np.issubdtype(folds.dtype, np.integer)
                and np.issubdtype(row_positions.dtype, np.integer)
                and np.isin(y_true, (0, 1)).all()
                and np.isfinite(scores).all()
                and ((scores >= 0) & (scores <= 1)).all()
                and (folds >= 1).all()
                and len(set(int(item) for item in row_positions)) == n_rows
                and all(isinstance(item, str) for item in identifiers)
                and artifact.config.dataset_fingerprint == artifact.run_output.result.dataset_fingerprint
            )
        except (TypeError, ValueError):
            complete = False
        if not complete:
            raise OOFResultError("OOF_RESULT_EVIDENCE_INCOMPLETE")
        context = _OOFContext(
            artifact=artifact,
            y_true=np.ascontiguousarray(y_true, dtype=np.int64),
            scores=np.ascontiguousarray(scores, dtype=np.float64),
            folds=np.ascontiguousarray(folds, dtype=np.int64),
            row_positions=np.ascontiguousarray(row_positions, dtype=np.int64),
            identifiers=identifiers,
        )
        self._verify_canonical_threshold(context)
        return context

    def _verify_canonical_threshold(self, context: _OOFContext) -> None:
        result = context.artifact.run_output.result
        derived = self._threshold_metrics(context, 0.5)
        expected = result.confusion
        try:
            matches = (
                float(expected["threshold"]) == 0.5
                and derived.tp == int(expected["tp"])
                and derived.tn == int(expected["tn"])
                and derived.fp == int(expected["fp"])
                and derived.fn == int(expected["fn"])
                and np.isclose(
                    derived.precision,
                    self._metric(result.metrics, "precision_at_0_5"),
                    rtol=1e-12,
                    atol=1e-12,
                )
                and np.isclose(
                    derived.recall,
                    self._metric(result.metrics, "recall_at_0_5"),
                    rtol=1e-12,
                    atol=1e-12,
                )
                and np.isclose(
                    derived.f1,
                    self._metric(result.metrics, "f1_at_0_5"),
                    rtol=1e-12,
                    atol=1e-12,
                )
            )
        except (KeyError, TypeError, ValueError, OOFResultError):
            matches = False
        if not matches:
            raise OOFResultError("RESULT_INTEGRITY_ERROR")

    @staticmethod
    def _metric(metrics: Mapping[str, object], name: str) -> float:
        try:
            raw = metrics[name]
        except KeyError as error:
            raise OOFResultError("RESULT_INTEGRITY_ERROR") from error
        if isinstance(raw, bool) or not isinstance(raw, Real):
            raise OOFResultError("RESULT_INTEGRITY_ERROR")
        value = float(raw)
        if not isfinite(value):
            raise OOFResultError("RESULT_INTEGRITY_ERROR")
        return value

    @staticmethod
    def _threshold(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise OOFResultError("INVALID_THRESHOLD")
        threshold = float(value)
        if not isfinite(threshold) or not 0 <= threshold <= 1:
            raise OOFResultError("INVALID_THRESHOLD")
        return threshold

    @staticmethod
    def _paging(offset: int, limit: int) -> None:
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_LIMIT
        ):
            raise OOFResultError("INVALID_QUERY")

    @staticmethod
    def _target(value: str | None) -> str:
        target = "ANY" if value is None else value
        if not isinstance(target, str) or target not in _TARGETS:
            raise OOFResultError("INVALID_QUERY")
        return target

    @staticmethod
    def _outcomes(value: Sequence[str] | None) -> frozenset[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            raise OOFResultError("INVALID_QUERY")
        try:
            selected = frozenset(value)
        except TypeError as error:
            raise OOFResultError("INVALID_QUERY") from error
        if not selected.issubset(_OUTCOMES):
            raise OOFResultError("INVALID_QUERY")
        return selected

    def _score_bounds(
        self, min_score: float | None, max_score: float | None
    ) -> tuple[float | None, float | None]:
        minimum = self._score_bound(min_score)
        maximum = self._score_bound(max_score)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise OOFResultError("INVALID_QUERY")
        return minimum, maximum

    @staticmethod
    def _score_bound(value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, Real):
            raise OOFResultError("INVALID_QUERY")
        number = float(value)
        if not isfinite(number) or not 0 <= number <= 1:
            raise OOFResultError("INVALID_QUERY")
        return number

    def _threshold_metrics(self, context: _OOFContext, threshold: float) -> OOFThresholdMetrics:
        predicted = context.scores >= threshold
        positive = context.y_true == 1
        tp = int(np.count_nonzero(predicted & positive))
        tn = int(np.count_nonzero(~predicted & ~positive))
        fp = int(np.count_nonzero(predicted & ~positive))
        fn = int(np.count_nonzero(~predicted & positive))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        above = int(np.count_nonzero(predicted))
        return OOFThresholdMetrics(
            artifact_id=context.artifact.artifact_id,
            threshold=threshold,
            tp=tp,
            tn=tn,
            fp=fp,
            fn=fn,
            precision=precision,
            recall=recall,
            f1=f1,
            above_threshold_count=above,
            above_threshold_share=above / len(context.scores),
        )

    @staticmethod
    def _capture(context: _OOFContext) -> OOFResultCapture:
        """Build a bounded cumulative-capture payload from immutable OOF facts.

        Scores are ordered exactly as Result object lists: descending score and,
        for ties, ascending original row position.  The API intentionally returns
        101 percentage checkpoints instead of exposing row-level OOF evidence.
        """

        total_positive_events = int(np.count_nonzero(context.y_true == 1))
        if total_positive_events == 0:
            return OOFResultCapture(
                total_positive_events=0,
                points=(),
                marker=None,
            )

        ordered = np.lexsort((context.row_positions, -context.scores))
        cumulative_positive = np.cumsum(context.y_true[ordered], dtype=np.int64)
        row_count = len(ordered)

        def point_at(requested_share: float) -> OOFResultCapturePoint:
            if requested_share == 0:
                return OOFResultCapturePoint(object_share=0.0, event_share=0.0)
            selected_count = min(
                row_count,
                int(np.ceil(row_count * requested_share)),
            )
            actual_object_share = selected_count / row_count
            event_share = float(cumulative_positive[selected_count - 1]) / total_positive_events
            return OOFResultCapturePoint(
                object_share=actual_object_share,
                event_share=event_share,
            )

        points = tuple(point_at(percentage / 100) for percentage in range(101))
        return OOFResultCapture(
            total_positive_events=total_positive_events,
            points=points,
            marker=point_at(0.15),
        )

    @staticmethod
    def _outcomes_for(y_true: np.ndarray, predicted: np.ndarray) -> np.ndarray:
        return np.where(
            y_true == 1,
            np.where(predicted, "TP", "FN"),
            np.where(predicted, "FP", "TN"),
        )

    @staticmethod
    def _outcome(y_true: int, predicted: bool) -> str:
        return "TP" if y_true and predicted else "FN" if y_true else "FP" if predicted else "TN"

    @staticmethod
    def _sort_indices(
        context: _OOFContext, indices: np.ndarray, threshold: float, sort: str
    ) -> np.ndarray:
        rows = context.row_positions[indices]
        scores = context.scores[indices]
        primary = (
            -scores
            if sort == "SCORE_DESC"
            else scores
            if sort == "SCORE_ASC"
            else np.abs(scores - threshold)
        )
        return indices[np.lexsort((rows, primary))]

    def _list_item(
        self,
        context: _OOFContext,
        index: int,
        threshold: float,
        predicted: np.ndarray,
        outcomes: np.ndarray,
    ) -> OOFObjectListItem:
        return OOFObjectListItem(
            object_id=self._object_id(context, index),
            identifier_display=context.identifiers[index],
            y_true=int(context.y_true[index]),
            score=float(context.scores[index]),
            predicted_positive=bool(predicted[index]),
            outcome=str(outcomes[index]),
        )

    @staticmethod
    def _object_id(context: _OOFContext, index: int) -> str:
        return stable_hash(
            {
                "artifact_id": context.artifact.artifact_id,
                "dataset_fingerprint": context.artifact.config.dataset_fingerprint,
                "row_position": int(context.row_positions[index]),
            }
        )


def _resolve_oof_object(context: _OOFContext, object_id: str) -> _ResolvedOOFObject:
    """Resolve the accepted BE2A public object identity exactly once."""
    if not isinstance(object_id, str) or not object_id:
        raise OOFResultError("OBJECT_NOT_FOUND")
    matches = np.fromiter(
        (
            OOFResultService._object_id(context, index) == object_id
            for index in range(len(context.scores))
        ),
        dtype=bool,
        count=len(context.scores),
    )
    positions = np.flatnonzero(matches)
    if len(positions) != 1:
        raise OOFResultError("OBJECT_NOT_FOUND")
    return _ResolvedOOFObject(context, int(positions[0]), object_id)


def _load_oof_object(
    artifact_store: ExperimentArtifactStore, artifact_id: str, object_id: str
) -> _ResolvedOOFObject:
    """Shared private read path preserving public Result V2 identity semantics."""
    service = OOFResultService(artifact_store)
    return _resolve_oof_object(service._context(artifact_id), object_id)


def _load_oof_context(
    artifact_store: ExperimentArtifactStore, artifact_id: str
) -> _OOFContext:
    """Shared private V3 evidence loader for fold-bound OOF consumers."""
    return OOFResultService(artifact_store)._context(artifact_id)
