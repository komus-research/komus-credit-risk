"""Read-only access to accepted Stage 2 SHAP research evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


_ROOT = Path(__file__).resolve().parents[1]
_MODEL_NAMES = {"catboost": "CatBoost", "xgboost": "XGBoost", "lightgbm": "LightGBM"}


def load_stage2_evidence() -> tuple[dict, pd.DataFrame, pd.DataFrame, dict]:
    """Load the published evidence without fitting or running SHAP again."""
    generated = _ROOT / "reports" / "generated"
    summary_path = _ROOT / "reports" / "summary" / "stage2_explainability_summary_V1.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    by_model = pd.read_csv(generated / "stage2_explainability_by_model_V1.csv")
    consensus = pd.read_csv(generated / "stage2_explainability_consensus_V1.csv")
    details = json.loads((generated / "stage2_explainability_results_V1.json").read_text(encoding="utf-8"))
    return summary, by_model, consensus, details


def stage2_matches_current_run(artifact, context, summary: dict, by_model: pd.DataFrame) -> bool:
    """Require exact dataset, model, feature set and CV settings for comparison."""
    if artifact is None or context is None:
        return False
    config = artifact.config
    model_name = _MODEL_NAMES.get(config.model_id)
    if model_name is None:
        return False
    expected_features = set(by_model.loc[by_model["Модель"] == model_name, "Признак"])
    return bool(
        expected_features
        and set(config.feature_ids) == expected_features
        and len(config.feature_ids) == len(expected_features)
        and config.seed == summary["seed"]
        and config.folds == 3
        and config.protocol_id == "stratified_kfold_oof"
        and config.protocol_version == "1"
        and config.evaluation_level == "oof"
        and config.model_version == "accepted_stage1_v2"
        and context.loaded_dataset.source_file_sha256 == summary["dataset_sha256"]
    )


def model_display_name(model_id: str) -> str | None:
    return _MODEL_NAMES.get(model_id)
