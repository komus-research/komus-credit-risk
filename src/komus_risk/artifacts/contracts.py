"""Typed result of loading an immutable experiment evidence bundle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from komus_risk.contracts import DatasetContract, ExperimentConfig
from komus_risk.experiments import EvaluationPopulation, ExperimentRunOutput
from komus_risk.model_platform import ModelConfigurationRecord, SmokeEvidence
from komus_risk.models.gbdt.native import NativePredictor


@dataclass(frozen=True, slots=True)
class LoadedExperimentArtifact:
    artifact_id: str
    config: ExperimentConfig
    dataset_contract: DatasetContract
    population: EvaluationPopulation
    run_output: ExperimentRunOutput
    manifest: dict[str, Any]
    configuration_record: ModelConfigurationRecord | None = None
    smoke_evidence: SmokeEvidence | None = None

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


@dataclass(frozen=True, slots=True)
class LoadedOOFFoldModel:
    """Trusted, ephemeral evaluation evidence for one persisted V3 fold.

    This is deliberately not a ``LoadedModelVersion``: fold models are only
    evidence for the OOF evaluation population and must never enter the model
    catalogue or the ModelVersion store.
    """

    artifact_id: str
    fold_number: int
    model_binding_id: str
    metadata: dict[str, Any]
    predictor: NativePredictor

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))
