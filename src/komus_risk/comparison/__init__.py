"""Read-only controlled comparison of completed experiments."""

from .contracts import ComparisonResult, ComparisonSubject
from .service import ExperimentComparisonService

__all__ = ["ComparisonResult", "ComparisonSubject", "ExperimentComparisonService"]
