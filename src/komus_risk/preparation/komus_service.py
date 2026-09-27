"""Public KOMUS preparation facade."""

from __future__ import annotations

from typing import Any

from komus_risk.data import TabularSnapshot
from komus_risk.data.inspection import DatasetInspectionReport

from .authority import PreparedDatasetContextAuthority
from .contracts import ConfirmedDatasetPreparation
from .materializer import DatasetPreparationMaterializer


class KomusDatasetPreparationService:
    def __init__(
        self,
        materializer: DatasetPreparationMaterializer | None = None,
        context_authority: PreparedDatasetContextAuthority | None = None,
    ) -> None:
        self._materializer = materializer or DatasetPreparationMaterializer()
        self._context_authority = context_authority

    def prepare(
        self,
        snapshot: TabularSnapshot,
        inspection_report: DatasetInspectionReport,
        proposal: Any,
        confirmation: ConfirmedDatasetPreparation,
    ):
        context, manifest = self._materializer.materialize(
            snapshot, inspection_report, proposal, confirmation
        )
        if self._context_authority is not None:
            context = self._context_authority.register(context)
        return context, manifest
