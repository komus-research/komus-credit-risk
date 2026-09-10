"""Typed result of loading an immutable experiment evidence bundle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from komus_risk.contracts import DatasetContract, ExperimentConfig
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput


@dataclass(frozen=True, slots=True)
class LoadedExperimentArtifact:
    artifact_id: str
    config: ExperimentConfig
    dataset_contract: DatasetContract
    population: EvaluationPopulation
    run_output: ExperimentRunOutput
    manifest: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", dict(self.manifest))

    def to_comparison_subject(self):
        """Builds comparison evidence only; no runner or model is invoked."""
        from komus_risk.comparison import ComparisonSubject

        return ComparisonSubject.from_run(
            config=self.config,
            dataset_contract=self.dataset_contract,
            run_output=self.run_output,
        )
