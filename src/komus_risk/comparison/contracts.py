"""Read-only contracts for controlled comparisons of completed experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from komus_risk.contracts import DatasetContract, ExperimentConfig, ExperimentResult


@dataclass(frozen=True, slots=True)
class ComparisonSubject:
    """All immutable evidence needed to compare one completed experiment."""

    config: ExperimentConfig
    result: ExperimentResult
    dataset_contract: DatasetContract
    population_id: str
    population_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("population_id", "population_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Поле «{name}» должно быть непустой строкой.")

    @classmethod
    def from_run(
        cls,
        *,
        config: ExperimentConfig,
        dataset_contract: DatasetContract,
        run_output: Any,
    ) -> "ComparisonSubject":
        """Builds a subject from an existing run output without running anything."""
        return cls(
            config=config,
            result=run_output.result,
            dataset_contract=dataset_contract,
            population_id=run_output.population_id,
            population_fingerprint=run_output.population_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Factual candidate-minus-reference comparison; never a recommendation."""

    comparison_id: str
    reference_result_id: str
    candidate_result_id: str
    is_comparable: bool
    status: str
    reason_codes: tuple[str, ...]
    changed_dimension: str | None
    feature_change: dict[str, tuple[str, ...]]
    model_change: dict[str, tuple[str, ...]]
    metric_deltas: dict[str, float]
    confusion_deltas: dict[str, float]
    runtime_delta_seconds: float | None
    fold_deltas: tuple[dict[str, float | int | None], ...]
    declaration_check: dict[str, Any]
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.comparison_id, str) or not self.comparison_id:
            raise ValueError("comparison_id должен быть непустой строкой.")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "feature_change", dict(self.feature_change))
        object.__setattr__(self, "model_change", dict(self.model_change))
        object.__setattr__(self, "metric_deltas", dict(self.metric_deltas))
        object.__setattr__(self, "confusion_deltas", dict(self.confusion_deltas))
        object.__setattr__(self, "fold_deltas", tuple(dict(item) for item in self.fold_deltas))
        object.__setattr__(self, "declaration_check", dict(self.declaration_check))
        object.__setattr__(self, "provenance", dict(self.provenance))
