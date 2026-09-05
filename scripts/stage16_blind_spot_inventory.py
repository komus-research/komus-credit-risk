#!/usr/bin/env python3
"""Stage 16 V1: descriptive inventory of the accepted Stage 3 blind spot.

This script is deliberately diagnostic-only.  It loads saved OOF outputs but
does not instantiate, fit, tune, or score a model, and it never selects or
uses the final-test partition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


EXPECTED_BLIND_SPOT_ROWS = 805
FORBIDDEN_PREDICTORS = {"Q_B1_norm", "Q_B2_norm"}
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_or_none(value: float | int | None) -> float | int | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value)


def numeric_summary(values: Any) -> dict[str, float | int | None]:
    import numpy as np

    array = np.asarray(values, dtype=np.float64)
    observed = array[np.isfinite(array)]
    result: dict[str, float | int | None] = {
        "n": int(array.size),
        "non_missing_n": int(observed.size),
        "mean": None,
        "median": None,
        "std": None,
    }
    if observed.size == 0:
        for quantile in QUANTILES:
            result[f"q{int(quantile * 100):02d}"] = None
        return result
    result["mean"] = finite_or_none(float(observed.mean()))
    result["median"] = finite_or_none(float(np.median(observed)))
    result["std"] = finite_or_none(float(observed.std(ddof=1))) if observed.size > 1 else None
    for quantile in QUANTILES:
        result[f"q{int(quantile * 100):02d}"] = finite_or_none(float(np.quantile(observed, quantile)))
    return result


def cohens_d(left: Any, right: Any) -> float | None:
    import numpy as np

    left_values = np.asarray(left, dtype=np.float64)
    right_values = np.asarray(right, dtype=np.float64)
    left_values = left_values[np.isfinite(left_values)]
    right_values = right_values[np.isfinite(right_values)]
    if left_values.size < 2 or right_values.size < 2:
        return None
    pooled_variance = (
        (left_values.size - 1) * left_values.var(ddof=1)
        + (right_values.size - 1) * right_values.var(ddof=1)
    ) / (left_values.size + right_values.size - 2)
    if pooled_variance <= 0 or not math.isfinite(float(pooled_variance)):
        return None
    return finite_or_none(float((left_values.mean() - right_values.mean()) / math.sqrt(pooled_variance)))


def stage3_thresholds(results: dict[str, Any]) -> tuple[float, float]:
    def find_value(node: Any, suffix: str) -> float | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).endswith(suffix):
                    return float(value)
                found = find_value(value, suffix)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find_value(value, suffix)
                if found is not None:
                    return found
        return None

    consensus_rank_lte = find_value(results, "consensus_rank_lte")
    rank_spread_lte = find_value(results, "rank_spread_lte")
    if consensus_rank_lte is None or rank_spread_lte is None:
        raise RuntimeError("Stage 3 diagnostic thresholds are missing from the accepted JSON.")
    return consensus_rank_lte, rank_spread_lte


def accepted_cohort_count(cohorts_path: Path) -> int:
    import pandas as pd

    cohorts = pd.read_csv(cohorts_path)
    label_column, count_column = cohorts.columns[:2]
    blind_rows = cohorts[cohorts[label_column].astype(str).str.lower().str.contains("слеп")]
    if len(blind_rows) != 1:
        raise RuntimeError("Accepted cohort CSV does not contain exactly one blind-spot row.")
    return int(blind_rows.iloc[0][count_column])


def build_inventory(root: Path) -> dict[str, Any]:
    """Build the Stage 16 inventory, stopping before output on any guard failure."""
    import numpy as np
    import pandas as pd

    generated = root / "reports" / "generated"
    results_path = generated / "stage3_error_analysis_results_V1.json"
    cohorts_path = generated / "stage3_error_cohorts_V1.csv"
    oof_path = generated / "stage3_oof_predictions_V1.npz"
    dataset_path = root / "data" / "raw" / "Data_final.xlsb"
    for path in (results_path, cohorts_path, oof_path, dataset_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required Stage 16 input is absent: {path}")

    with results_path.open("r", encoding="utf-8") as source:
        accepted_results = json.load(source)
    expected_dataset_hash = accepted_results["dataset"]["sha256"]
    expected_oof_hash = accepted_results["oof_checkpoint"]["sha256"]
    consensus_rank_lte, rank_spread_lte = stage3_thresholds(accepted_results)
    input_hashes = {
        "stage3_error_analysis_results_V1.json": sha256_file(results_path),
        "stage3_error_cohorts_V1.csv": sha256_file(cohorts_path),
        "stage3_oof_predictions_V1.npz": sha256_file(oof_path),
        "Data_final.xlsb": sha256_file(dataset_path),
    }
    if input_hashes["stage3_oof_predictions_V1.npz"] != expected_oof_hash:
        raise RuntimeError("Stage 3 OOF artifact SHA-256 differs from accepted evidence.")
    if input_hashes["Data_final.xlsb"] != expected_dataset_hash:
        raise RuntimeError("Dataset SHA-256 differs from accepted Stage 3 evidence.")

    with np.load(oof_path, allow_pickle=False) as checkpoint:
        required_arrays = {
            "working_indices", "target", "oof_catboost", "oof_xgboost", "oof_lightgbm",
            "consensus_rank", "rank_spread",
        }
        missing_arrays = required_arrays.difference(checkpoint.files)
        if missing_arrays:
            raise RuntimeError(f"Stage 3 OOF arrays are missing: {sorted(missing_arrays)}")
        working_indices = np.asarray(checkpoint["working_indices"], dtype=np.int64)
        target = np.asarray(checkpoint["target"], dtype=np.int8)
        consensus_rank = np.asarray(checkpoint["consensus_rank"], dtype=np.float64)
        rank_spread = np.asarray(checkpoint["rank_spread"], dtype=np.float64)
        scores = {
            "CatBoost": np.asarray(checkpoint["oof_catboost"], dtype=np.float64),
            "XGBoost": np.asarray(checkpoint["oof_xgboost"], dtype=np.float64),
            "LightGBM": np.asarray(checkpoint["oof_lightgbm"], dtype=np.float64),
        }
    array_lengths = {len(working_indices), len(target), len(consensus_rank), len(rank_spread), *(len(score) for score in scores.values())}
    if len(array_lengths) != 1:
        raise RuntimeError("Stage 3 OOF arrays do not have one common row count.")
    if not np.isin(target, [0, 1]).all() or not np.isfinite(consensus_rank).all() or not np.isfinite(rank_spread).all():
        raise RuntimeError("Stage 3 target or rank arrays violate the accepted descriptive contract.")
    if not all(np.isfinite(score).all() for score in scores.values()):
        raise RuntimeError("Stage 3 OOF score arrays contain non-finite values.")

    blind_spot = (target == 1) & (consensus_rank <= consensus_rank_lte) & (rank_spread <= rank_spread_lte)
    cohort_count = accepted_cohort_count(cohorts_path)
    if int(blind_spot.sum()) != EXPECTED_BLIND_SPOT_ROWS or cohort_count != EXPECTED_BLIND_SPOT_ROWS:
        raise RuntimeError(
            "STOP: blind-spot count mismatch; expected 805, "
            f"reconstructed {int(blind_spot.sum())}, cohort CSV {cohort_count}."
        )
    if not bool(np.all(target[blind_spot] == 1)):
        raise RuntimeError("STOP: reconstructed blind spot contains a non-default row.")

    frame = pd.read_excel(dataset_path, engine="pyxlsb", sheet_name="Data_final").reset_index(drop=True)
    required_columns = {"INN", "DefMark", *FORBIDDEN_PREDICTORS}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise RuntimeError(f"Dataset columns required by the locked contract are absent: {sorted(missing_columns)}")
    features = [column for column in frame.columns if column not in {"INN", "DefMark", *FORBIDDEN_PREDICTORS}]
    if len(features) != 47 or FORBIDDEN_PREDICTORS.intersection(features):
        raise RuntimeError("STOP: accepted 47-feature contract was not reproduced.")
    if working_indices.min() < 0 or working_indices.max() >= len(frame):
        raise RuntimeError("Stage 3 working indices are outside the dataset.")
    working = frame.iloc[working_indices][["DefMark", *features]].copy()
    del frame
    dataset_target = pd.to_numeric(working["DefMark"], errors="raise").to_numpy(dtype=np.int8)
    if not np.array_equal(target, dataset_target):
        raise RuntimeError("Stage 3 target is not aligned to dataset rows selected by working_indices.")
    feature_frame = working[features].apply(pd.to_numeric, errors="raise")
    finite_or_missing = np.isfinite(feature_frame.to_numpy(dtype=np.float64)) | feature_frame.isna().to_numpy()
    if not finite_or_missing.all():
        raise RuntimeError("Feature matrix contains non-finite values outside missingness.")

    other_defaults = (target == 1) & ~blind_spot
    non_defaults = target == 0
    groups = {
        "A_blind_spot_defaults": blind_spot,
        "B_other_defaults": other_defaults,
        "C_non_defaults_context_only": non_defaults,
    }
    if sum(int(mask.sum()) for mask in groups.values()) != len(target):
        raise RuntimeError("Comparison groups are not a partition of the accepted working rows.")

    feature_profile: dict[str, Any] = {}
    missingness: dict[str, Any] = {}
    for feature in features:
        values_by_group = {
            group_name: feature_frame.loc[mask, feature].to_numpy(dtype=np.float64)
            for group_name, mask in groups.items()
        }
        feature_profile[feature] = {
            "groups": {group_name: numeric_summary(values) for group_name, values in values_by_group.items()},
            "cohens_d": {
                "A_vs_B": cohens_d(values_by_group["A_blind_spot_defaults"], values_by_group["B_other_defaults"]),
                "A_vs_C": cohens_d(values_by_group["A_blind_spot_defaults"], values_by_group["C_non_defaults_context_only"]),
            },
        }
        rates = {group_name: float(np.isnan(values).mean()) for group_name, values in values_by_group.items()}
        missingness[feature] = {
            "groups": {
                group_name: {"missing_count": int(np.isnan(values).sum()), "missing_rate": rate}
                for (group_name, values), rate in zip(values_by_group.items(), rates.values())
            },
            "rate_difference": {
                "A_minus_B": rates["A_blind_spot_defaults"] - rates["B_other_defaults"],
                "A_minus_C": rates["A_blind_spot_defaults"] - rates["C_non_defaults_context_only"],
            },
        }

    score_profile = {
        model_name: {group_name: numeric_summary(score[mask]) for group_name, mask in groups.items()}
        for model_name, score in scores.items()
    }
    rank_profile = {
        "consensus_rank": {group_name: numeric_summary(consensus_rank[mask]) for group_name, mask in groups.items()},
        "rank_spread": {group_name: numeric_summary(rank_spread[mask]) for group_name, mask in groups.items()},
        "blind_spot_at_or_below_consensus_rank_threshold": {
            "count": int((consensus_rank[blind_spot] <= consensus_rank_lte).sum()),
            "rate": float((consensus_rank[blind_spot] <= consensus_rank_lte).mean()),
            "threshold": consensus_rank_lte,
        },
    }

    return {
        "stage": "Stage 16 V1 — Blind Spot Information Gap Diagnostics",
        "status": "DESCRIPTIVE_INVENTORY_COMPLETE",
        "final_test_used": False,
        "model_training_or_tuning_performed": False,
        "quality_metrics_calculated": False,
        "sources": {
            "accepted_stage3_results": str(results_path.relative_to(root)).replace("\\", "/"),
            "accepted_stage3_cohorts": str(cohorts_path.relative_to(root)).replace("\\", "/"),
            "accepted_stage3_oof": str(oof_path.relative_to(root)).replace("\\", "/"),
            "dataset": str(dataset_path.relative_to(root)).replace("\\", "/"),
        },
        "input_sha256": input_hashes,
        "blind_spot": {
            "expected_rows": EXPECTED_BLIND_SPOT_ROWS,
            "reconstructed_rows": int(blind_spot.sum()),
            "accepted_cohort_csv_rows": cohort_count,
            "all_rows_are_defaults": True,
            "rule": {
                "target_equals": 1,
                "consensus_rank_lte": consensus_rank_lte,
                "rank_spread_lte": rank_spread_lte,
            },
        },
        "comparison_groups": {
            group_name: {"rows": int(mask.sum()), "definition": definition}
            for group_name, mask, definition in (
                ("A_blind_spot_defaults", blind_spot, "accepted Stage 3 blind-spot defaults"),
                ("B_other_defaults", other_defaults, "all other working rows with DefMark = 1"),
                ("C_non_defaults_context_only", non_defaults, "working rows with DefMark = 0; descriptive context only"),
            )
        },
        "analysis_parameters": {
            "feature_count": len(features),
            "features": features,
            "forbidden_predictors_excluded": sorted(FORBIDDEN_PREDICTORS),
            "quantiles": list(QUANTILES),
            "effect_size": "Cohen's d with pooled sample standard deviation; descriptive only",
            "clustering": "not performed",
        },
        "feature_profile": feature_profile,
        "missingness": missingness,
        "oof_score_profile": {
            "source": "saved Stage 3 OOF score arrays only",
            "model_scores": score_profile,
            "ranking_context": rank_profile,
        },
        "limitations": [
            "Descriptive group differences do not establish causality.",
            "No final-test rows were selected or analysed.",
            "No model training, tuning, or predictive-quality metric calculation was performed.",
        ],
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "reports" / "generated" / "stage16_blind_spot_inventory_V1.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(inventory, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    print(f"Stage 16 descriptive inventory written: {args.output}")
    print(f"Blind-spot rows: {inventory['blind_spot']['reconstructed_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
