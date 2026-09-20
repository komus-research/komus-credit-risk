"""Загрузка готовых табличных датасетов."""

from .ready_dataset import LoadedDataset, ReadyDatasetAdapter
from .tabular import TabularReadError, TabularReader, TabularSnapshot
from .inspection import DatasetInspector, DatasetInspectionReport

__all__ = ["LoadedDataset", "ReadyDatasetAdapter", "TabularReadError", "TabularReader", "TabularSnapshot", "DatasetInspector", "DatasetInspectionReport"]
