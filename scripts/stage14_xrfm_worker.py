"""Isolated Stage 14 xRFM worker; never imported by the parent notebook."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path


def write_result(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def tree_stats(model) -> dict:
    leaves = []
    def visit(node, depth):
        if node["type"] == "leaf":
            leaves.append((depth, len(node.get("train_indices", []))))
        else:
            visit(node["left"], depth + 1); visit(node["right"], depth + 1)
    for tree in model.trees:
        visit(tree, 0)
    rows = sorted(row for _, row in leaves)
    return {"effective_tree_depth": max((depth for depth, _ in leaves), default=0), "leaf_count": len(leaves),
            "leaf_train_rows_min": rows[0], "leaf_train_rows_median": rows[len(rows)//2], "leaf_train_rows_max": rows[-1]}


class ConfigMismatch(RuntimeError):
    def __init__(self, field, expected, observed):
        self.field, self.expected, self.observed = field, expected, observed
        super().__init__(f"XRFM_CONFIG_MISMATCH: {field}")


def validate_model(model, config) -> None:
    import torch
    if torch.version.cuda is not None or torch.cuda.is_available():
        raise ConfigMismatch("torch.version.cuda", None, torch.version.cuda)
    expected = config["xrfm_kwargs"]
    mapping = {"n_trees": "n_trees", "n_tree_iters": "n_tree_iters", "max_leaf_size": "_base_max_leaf_size",
               "split_method": "split_method", "classification_mode": "classification_mode", "tuning_metric": "tuning_metric",
               "n_threads": "n_threads", "number_of_splits": "number_of_splits", "categorical_info": "categorical_info",
               "fixed_vector": "fixed_vector", "callback": "callback", "time_limit_s": "time_limit_s", "verbose": "verbose",
               "refill_size": "min_val_size", "split_temperature": "split_temperature",
               "use_temperature_tuning": "use_temperature_tuning", "overlap_fraction": "overlap_fraction",
               "keep_weight_frac_in_predict": "keep_weight_frac_in_predict", "max_leaf_count_in_ensemble": "max_leaf_count_in_ensemble"}
    if str(model.device) != "cpu": raise ConfigMismatch("device", "cpu", str(model.device))
    for field, attribute in mapping.items():
        if getattr(model, attribute) != expected[field]: raise ConfigMismatch(field, expected[field], getattr(model, attribute))
    for section in ("model", "fit"):
        for field, value in config["rfm_params"][section].items():
            if model.rfm_params[section].get(field) != value: raise ConfigMismatch(f"rfm_params.{section}.{field}", value, model.rfm_params[section].get(field))
    if model.rfm_params["fit"].get("iters") != 3 or "iterations" in model.rfm_params["fit"]:
        raise ConfigMismatch("rfm_params.fit.iters", 3, model.rfm_params["fit"].get("iters"))


def run_job(job_path: Path, result_path: Path) -> None:
    import numpy as np
    import torch
    from sklearn.model_selection import StratifiedShuffleSplit
    from sklearn.preprocessing import StandardScaler
    from xrfm import xRFM
    with np.load(job_path, allow_pickle=False) as job:
        X_train = job["X_train"]; y_train = job["y_train"]
        X_query = job["X_query"]; config = json.loads(str(job["config"].item()))
    mode = config.get("run_mode")
    if mode not in {"smoke", "feasibility", "full_oof"}: raise ValueError(f"invalid worker run_mode: {mode!r}")
    if config["xrfm_kwargs"].get("random_state") is not None: raise ConfigMismatch("random_state", None, config["xrfm_kwargs"].get("random_state"))
    seed = int(config["seed"])
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.set_num_threads(8)
    torch.set_num_interop_threads(1)
    train_rel, inner_val_rel = next(StratifiedShuffleSplit(n_splits=1, test_size=.20, random_state=seed).split(X_train, y_train))
    started = time.monotonic(); scaler = StandardScaler(with_mean=True, with_std=True)
    X_fit = np.ascontiguousarray(scaler.fit_transform(X_train[train_rel]), dtype=np.float32)
    X_val = np.ascontiguousarray(scaler.transform(X_train[inner_val_rel]), dtype=np.float32)
    Xq = np.ascontiguousarray(scaler.transform(X_query), dtype=np.float32)
    preprocessing_seconds = time.monotonic() - started
    model = xRFM(rfm_params=config["rfm_params"], **config["xrfm_kwargs"])
    validate_model(model, config)
    fit_started = time.monotonic(); model.fit(X_fit, y_train[train_rel], X_val, y_train[inner_val_rel])
    fit_seconds = time.monotonic() - fit_started
    passes = []; predict_seconds = []
    for _ in range(1 if mode == "full_oof" else 2):
        prediction_started = time.monotonic()
        chunks = [np.asarray(model.predict_proba(Xq[i:i+4096]), dtype=np.float64) for i in range(0, len(Xq), 4096)]
        passes.append(np.vstack(chunks))
        predict_seconds.append(time.monotonic() - prediction_started)
    arrays = {"first": passes[0]}
    if len(passes) == 2: arrays["second"] = passes[1]
    np.savez_compressed(result_path.with_suffix(".npz"), **arrays)
    write_result(result_path, {"status": "PASS", "preprocessing_seconds": preprocessing_seconds,
                               "fit_seconds": fit_seconds, "predict_seconds": predict_seconds, "prediction_passes": len(passes), "inner_fit_rows": len(train_rel),
                               "inner_validation_rows": len(inner_val_rel), "tree": tree_stats(model)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path); parser.add_argument("--result", type=Path)
    parser.add_argument("--synthetic", choices=("sleep", "memory", "error", "full_oof")); parser.add_argument("--seconds", type=float, default=0.0)
    args = parser.parse_args()
    try:
        if args.synthetic == "sleep":
            time.sleep(args.seconds); write_result(args.result, {"status": "PASS", "synthetic": "sleep"})
        elif args.synthetic == "full_oof":
            write_result(args.result, {"status": "PASS", "synthetic": "full_oof", "prediction_passes": 1, "repeatability": None})
        elif args.synthetic == "memory":
            raise MemoryError("synthetic watchdog memory path")
        elif args.synthetic == "error":
            raise ValueError("synthetic ordinary error")
        else:
            run_job(args.job, args.result)
    except MemoryError as exc:
        write_result(args.result, {"status": "MEMORY_ERROR", "error": repr(exc), "traceback": traceback.format_exc()})
    except ConfigMismatch as exc:
        write_result(args.result, {"status": "XRFM_CONFIG_MISMATCH", "field": exc.field, "expected": exc.expected, "observed": exc.observed})
    except Exception as exc:
        write_result(args.result, {"status": "ERROR", "error": repr(exc), "traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
