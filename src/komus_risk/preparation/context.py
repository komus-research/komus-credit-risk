"""Runtime context created by Dataset Preparation V1."""
from __future__ import annotations
from dataclasses import dataclass
from komus_risk.data import LoadedDataset
from komus_risk.experiments import EvaluationPopulation
from komus_risk.registries import FeatureRegistry


@dataclass(frozen=True, slots=True)
class PreparedDatasetContext:
    context_id: str
    display_name: str
    loaded_dataset: LoadedDataset
    feature_registry: FeatureRegistry
    population: EvaluationPopulation
