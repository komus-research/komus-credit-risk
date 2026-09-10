"""Реестры переиспользуемых компонентов pipeline."""

from .feature_registry import FeatureRegistry
from .model_registry import ModelRegistry, ModelSpec

__all__ = ["FeatureRegistry", "ModelRegistry", "ModelSpec"]
