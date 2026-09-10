"""Зафиксированные CPU GBDT adapters Stage 1 V2."""

from .catboost import CATBOOST_MODEL_SPEC, CATBOOST_PROFILE, CatBoostAdapter, CatBoostFactory
from .lightgbm import LIGHTGBM_MODEL_SPEC, LIGHTGBM_PROFILE, LightGBMAdapter, LightGBMFactory
from .mean import GBDT_MEAN_MODEL_SPEC, GBDT_MEAN_PROFILE, GBDTMeanAdapter, GBDTMeanFactory
from .xgboost import XGBOOST_MODEL_SPEC, XGBOOST_PROFILE, XGBoostAdapter, XGBoostFactory

GBDT_MODEL_SPECS = (CATBOOST_MODEL_SPEC, XGBOOST_MODEL_SPEC, LIGHTGBM_MODEL_SPEC, GBDT_MEAN_MODEL_SPEC)

__all__ = [
    "CATBOOST_MODEL_SPEC", "CATBOOST_PROFILE", "CatBoostAdapter", "CatBoostFactory",
    "GBDT_MEAN_MODEL_SPEC", "GBDT_MEAN_PROFILE", "GBDTMeanAdapter", "GBDTMeanFactory",
    "GBDT_MODEL_SPECS", "LIGHTGBM_MODEL_SPEC", "LIGHTGBM_PROFILE", "LightGBMAdapter",
    "LightGBMFactory", "XGBOOST_MODEL_SPEC", "XGBOOST_PROFILE", "XGBoostAdapter", "XGBoostFactory",
]
