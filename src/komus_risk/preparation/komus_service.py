"""Public KOMUS preparation facade."""
from __future__ import annotations
from typing import Any
from komus_risk.data import TabularSnapshot
from komus_risk.data.inspection import DatasetInspectionReport
from .contracts import ConfirmedDatasetPreparation
from .materializer import DatasetPreparationMaterializer


class KomusDatasetPreparationService:
    def __init__(self, materializer: DatasetPreparationMaterializer | None = None) -> None:
        self._materializer = materializer or DatasetPreparationMaterializer()

    def prepare(self, snapshot: TabularSnapshot, inspection_report: DatasetInspectionReport, proposal: Any, confirmation: ConfirmedDatasetPreparation):
        return self._materializer.materialize(snapshot, inspection_report, proposal, confirmation)
