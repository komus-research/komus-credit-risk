"""Pure, read-only service for controlled Experiment V1 comparisons."""

from __future__ import annotations

from typing import Any

from komus_risk.hashing import stable_hash

from .contracts import ComparisonResult, ComparisonSubject


_METRIC_NAMES = (
    "gini", "roc_auc", "pr_auc", "precision_at_0_5", "recall_at_0_5", "f1_at_0_5",
)
_CONFUSION_NAMES = ("tp", "tn", "fp", "fn")
_DATASET_INVARIANTS = (
    "dataset_id", "dataset_version", "dataset_fingerprint", "row_count", "column_count",
    "target_column", "positive_class", "identifier_column", "feature_registry_id",
    "feature_registry_hash", "final_test_locked",
)
_CONFIG_INVARIANTS = ("protocol_id", "protocol_version", "evaluation_level", "folds", "seed")


class ExperimentComparisonService:
    """Compares completed evidence only; it neither trains nor imports ML runtime."""

    def compare(self, reference: ComparisonSubject, candidate: ComparisonSubject) -> ComparisonResult:
        self._validate_subject(reference)
        self._validate_subject(candidate)

        feature_change, feature_order_changed = self._feature_change(reference, candidate)
        model_fields = tuple(
            field for field in ("model_id", "model_version", "model_parameters")
            if getattr(reference.config, field) != getattr(candidate.config, field)
        )
        model_change = {"changed_fields": model_fields}
        model_changed = bool(model_fields)
        feature_changed = bool(feature_change["added"] or feature_change["removed"])
        invariant_reasons = self._invariant_differences(reference, candidate)
        actual_dimension = "model" if model_changed and not feature_changed else "feature_set" if feature_changed and not model_changed else None
        model_elements = self._model_changed_elements(reference, candidate)
        feature_elements = self._feature_changed_elements(feature_change)
        actual_elements = (
            model_elements if actual_dimension == "model"
            else feature_elements if actual_dimension == "feature_set"
            else ()
        )
        declaration_check = self._declaration_check(
            reference, candidate, actual_dimension, actual_elements
        )
        provenance = self._provenance(reference, candidate)

        if invariant_reasons:
            return self._result(
                reference, candidate, False, "NOT_COMPARABLE_CONTROLLED_V1", invariant_reasons,
                None, feature_change, model_change, declaration_check, provenance,
            )
        if feature_order_changed:
            return self._result(
                reference, candidate, False, "unsupported_feature_order_change",
                ("unsupported_feature_order_change",), None, feature_change, model_change,
                declaration_check, provenance,
            )
        if model_changed and feature_changed:
            return self._result(
                reference, candidate, False, "UNCONTROLLED_MULTIPLE_CHANGES",
                ("UNCONTROLLED_MULTIPLE_CHANGES",), None, feature_change, model_change,
                declaration_check, provenance,
            )
        if not model_changed and not feature_changed:
            return self._result(
                reference, candidate, False, "NO_CONTROLLED_CHANGE", ("NO_CONTROLLED_CHANGE",),
                None, feature_change, model_change, declaration_check, provenance,
            )
        if not declaration_check["is_consistent"]:
            return self._result(
                reference, candidate, False, declaration_check["reason_code"],
                (declaration_check["reason_code"],), actual_dimension, feature_change, model_change,
                declaration_check, provenance,
            )

        status = "COMPARABLE_MODEL_CHANGE" if actual_dimension == "model" else "COMPARABLE_FEATURE_SET_CHANGE"
        return self._result(
            reference, candidate, True, status, (), actual_dimension, feature_change, model_change,
            declaration_check, provenance,
        )

    @staticmethod
    def _validate_subject(subject: ComparisonSubject) -> None:
        config = subject.config
        result = subject.result
        contract = subject.dataset_contract
        pairs = (
            (result.experiment_config_id, config.experiment_id, "result.experiment_config_id"),
            (result.config_hash, config.config_hash, "result.config_hash"),
            (result.dataset_fingerprint, config.dataset_fingerprint, "result.dataset_fingerprint"),
            (result.feature_set_hash, config.feature_set_hash, "result.feature_set_hash"),
            (result.model_id, config.model_id, "result.model_id"),
            (result.model_version, config.model_version, "result.model_version"),
            (result.evaluation_level, config.evaluation_level, "result.evaluation_level"),
            (contract.dataset_id, config.dataset_id, "dataset_contract.dataset_id"),
            (contract.dataset_fingerprint, config.dataset_fingerprint, "dataset_contract.dataset_fingerprint"),
            (contract.target_column, config.target, "dataset_contract.target_column"),
        )
        for actual, expected, label in pairs:
            if actual != expected:
                raise ValueError(f"Invalid comparison input: {label} не согласован с ExperimentConfig.")

    @staticmethod
    def _feature_change(
        reference: ComparisonSubject, candidate: ComparisonSubject,
    ) -> tuple[dict[str, tuple[str, ...]], bool]:
        reference_ids = reference.config.feature_ids
        candidate_ids = candidate.config.feature_ids
        reference_set = set(reference_ids)
        candidate_set = set(candidate_ids)
        added = tuple(sorted(candidate_set - reference_set))
        removed = tuple(sorted(reference_set - candidate_set))
        unchanged = tuple(sorted(reference_set & candidate_set))
        if reference_set == candidate_set:
            return {"added": added, "removed": removed, "unchanged": unchanged}, reference_ids != candidate_ids
        reference_common = tuple(item for item in reference_ids if item in candidate_set)
        candidate_common = tuple(item for item in candidate_ids if item in reference_set)
        return {"added": added, "removed": removed, "unchanged": unchanged}, reference_common != candidate_common

    @staticmethod
    def _invariant_differences(reference: ComparisonSubject, candidate: ComparisonSubject) -> tuple[str, ...]:
        reasons = [
            f"dataset_contract.{field}"
            for field in _DATASET_INVARIANTS
            if getattr(reference.dataset_contract, field) != getattr(candidate.dataset_contract, field)
        ]
        if reference.population_id != candidate.population_id:
            reasons.append("population_id")
        if reference.population_fingerprint != candidate.population_fingerprint:
            reasons.append("population_fingerprint")
        reasons.extend(
            f"config.{field}"
            for field in _CONFIG_INVARIANTS
            if getattr(reference.config, field) != getattr(candidate.config, field)
        )
        return tuple(reasons)

    @classmethod
    def _model_changed_elements(
        cls, reference: ComparisonSubject, candidate: ComparisonSubject,
    ) -> tuple[str, ...]:
        elements: list[str] = []
        if reference.config.model_id != candidate.config.model_id:
            elements.append("@model_id")
        if reference.config.model_version != candidate.config.model_version:
            elements.append("@model_version")
        elements.extend(
            sorted(cls._structural_diff(reference.config.model_parameters, candidate.config.model_parameters))
        )
        return tuple(elements)

    @classmethod
    def _structural_diff(cls, reference: Any, candidate: Any, path: str = "") -> tuple[str, ...]:
        if isinstance(reference, dict) and isinstance(candidate, dict):
            paths: list[str] = []
            for key in sorted(set(reference) | set(candidate), key=str):
                child_path = cls._join_path(path, str(key))
                if key not in reference or key not in candidate:
                    paths.append(child_path)
                else:
                    paths.extend(cls._structural_diff(reference[key], candidate[key], child_path))
            return tuple(paths)
        if reference != candidate:
            return (path,)
        return ()

    @staticmethod
    def _join_path(parent: str, key: str) -> str:
        escaped = key.replace("~", "~0").replace("/", "~1")
        return f"{parent}/{escaped}" if parent else escaped

    @staticmethod
    def _feature_changed_elements(feature_change: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
        return tuple(f"removed:{feature_id}" for feature_id in feature_change["removed"]) + tuple(
            f"added:{feature_id}" for feature_id in feature_change["added"]
        )

    @staticmethod
    def _declaration_check(
        reference: ComparisonSubject,
        candidate: ComparisonSubject,
        actual_dimension: str | None,
        actual_elements: tuple[str, ...],
    ) -> dict[str, Any]:
        declared_dimension = candidate.config.changed_dimension
        declared_elements = candidate.config.changed_elements
        reference_matches = (
            candidate.config.reference_result_id is None
            or candidate.config.reference_result_id == reference.result.result_id
        )
        dimension_matches = declared_dimension is None or declared_dimension == actual_dimension
        elements_match = not declared_elements or declared_elements == actual_elements
        if not reference_matches:
            reason_code = "REFERENCE_RESULT_MISMATCH"
        elif not dimension_matches or not elements_match:
            reason_code = "DECLARED_CHANGE_MISMATCH"
        else:
            reason_code = None
        return {
            "is_consistent": reason_code is None,
            "reason_code": reason_code,
            "actual_dimension": actual_dimension,
            "actual_elements": actual_elements,
            "declared_dimension": declared_dimension,
            "declared_elements": declared_elements,
            "reference_result_matches": reference_matches,
        }

    def _result(
        self,
        reference: ComparisonSubject,
        candidate: ComparisonSubject,
        is_comparable: bool,
        status: str,
        reason_codes: tuple[str, ...],
        changed_dimension: str | None,
        feature_change: dict[str, tuple[str, ...]],
        model_change: dict[str, tuple[str, ...]],
        declaration_check: dict[str, Any],
        provenance: dict[str, Any],
    ) -> ComparisonResult:
        if is_comparable:
            metric_deltas = self._deltas(reference.result.metrics, candidate.result.metrics, _METRIC_NAMES)
            confusion_deltas = self._deltas(reference.result.confusion, candidate.result.confusion, _CONFUSION_NAMES)
            runtime_delta = self._runtime_delta(reference, candidate)
            fold_deltas = self._fold_deltas(reference, candidate)
        else:
            metric_deltas = {}
            confusion_deltas = {}
            runtime_delta = None
            fold_deltas = ()
        comparison_id = stable_hash(
            {
                "reference_result_id": reference.result.result_id,
                "candidate_result_id": candidate.result.result_id,
                "reference_config_hash": reference.config.config_hash,
                "candidate_config_hash": candidate.config.config_hash,
                "reference_population": reference.population_fingerprint,
                "candidate_population": candidate.population_fingerprint,
                "status": status,
            }
        )
        return ComparisonResult(
            comparison_id, reference.result.result_id, candidate.result.result_id, is_comparable, status,
            reason_codes, changed_dimension, feature_change, model_change, metric_deltas, confusion_deltas,
            runtime_delta, fold_deltas, declaration_check, provenance,
        )

    @staticmethod
    def _deltas(reference: dict[str, Any], candidate: dict[str, Any], names: tuple[str, ...]) -> dict[str, float]:
        try:
            return {name: float(candidate[name]) - float(reference[name]) for name in names}
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Comparable results must contain all required numeric metrics.") from error

    @staticmethod
    def _runtime_delta(reference: ComparisonSubject, candidate: ComparisonSubject) -> float | None:
        if reference.result.runtime_seconds is None or candidate.result.runtime_seconds is None:
            return None
        return candidate.result.runtime_seconds - reference.result.runtime_seconds

    def _fold_deltas(
        self, reference: ComparisonSubject, candidate: ComparisonSubject,
    ) -> tuple[dict[str, float | int | None], ...]:
        reference_folds = reference.result.fold_metrics
        candidate_folds = candidate.result.fold_metrics
        if len(reference_folds) != len(candidate_folds):
            raise ValueError("Comparable results must have the same number of fold records.")
        result: list[dict[str, float | int | None]] = []
        for reference_fold, candidate_fold in zip(reference_folds, candidate_folds, strict=True):
            if reference_fold.get("fold") != candidate_fold.get("fold"):
                raise ValueError("Comparable results must have matching fold identifiers.")
            if reference_fold.get("fold_seed") != candidate_fold.get("fold_seed"):
                raise ValueError("Comparable results must have matching fold seeds.")
            delta = self._deltas(reference_fold, candidate_fold, _METRIC_NAMES)
            reference_runtime = reference_fold.get("runtime_seconds")
            candidate_runtime = candidate_fold.get("runtime_seconds")
            delta["fold"] = candidate_fold["fold"]
            delta["fold_seed"] = candidate_fold["fold_seed"]
            delta["delta_gini"] = delta.pop("gini")
            delta["delta_roc_auc"] = delta.pop("roc_auc")
            delta["delta_pr_auc"] = delta.pop("pr_auc")
            delta["delta_precision_at_0_5"] = delta.pop("precision_at_0_5")
            delta["delta_recall_at_0_5"] = delta.pop("recall_at_0_5")
            delta["delta_f1_at_0_5"] = delta.pop("f1_at_0_5")
            delta["delta_runtime_seconds"] = (
                None if reference_runtime is None or candidate_runtime is None
                else float(candidate_runtime) - float(reference_runtime)
            )
            result.append(delta)
        return tuple(result)

    @staticmethod
    def _provenance(reference: ComparisonSubject, candidate: ComparisonSubject) -> dict[str, Any]:
        return {
            "reference": {
                "result_id": reference.result.result_id,
                "experiment_id": reference.config.experiment_id,
                "config_hash": reference.config.config_hash,
                "code_version": reference.result.code_version,
            },
            "candidate": {
                "result_id": candidate.result.result_id,
                "experiment_id": candidate.config.experiment_id,
                "config_hash": candidate.config.config_hash,
                "code_version": candidate.result.code_version,
            },
        }
