"""Deterministic, machine-readable Dataset Preparation V1 manifest."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any
from .contracts import ConfirmedDatasetPreparation


@dataclass(frozen=True, slots=True)
class ProposalConfirmationDelta:
    confirmed_target: dict[str, Any]
    confirmed_identifier: dict[str, Any]
    positive_class_offered: bool
    column_decisions: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DatasetPreparationManifest:
    manifest_version: str
    materializer_version: str
    snapshot_fingerprint: str
    inspection_report_hash: str
    proposal_hash: str
    confirmed_preparation: ConfirmedDatasetPreparation
    confirmation_hash: str
    proposal_confirmation_delta: ProposalConfirmationDelta
    dataset_id: str
    dataset_version: str
    dataset_fingerprint: str
    feature_registry_id: str
    feature_registry_hash: str
    population_id: str
    population_fingerprint: str
    context_id: str
    materialization_identity: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["confirmed_preparation"]["population_policy"] = self.confirmed_preparation.population_policy.value
        for item in value["confirmed_preparation"]["column_decisions"]:
            item["status"] = str(item["status"])
        return value


def write_manifest(manifest: DatasetPreparationManifest, path: str | Path) -> None:
    Path(path).write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
