#!/usr/bin/env python3
"""Minimal pre-lock CPU feasibility probe for the official TabICLv2 contract.

This is intentionally not an ML experiment: it calculates no quality metric,
does not create OOF predictions, and never materialises or uses the final test.
Run it only from an isolated environment created from
requirements-tabiclv2-probe-v1.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import multiprocessing as mp
import platform
import queue
import sys
import time
from pathlib import Path
from typing import Any


# ============================================================
# ОПЕРАТОР: ВЫБЕРИТЕ РЕЖИМ ЗАПУСКА ТОЛЬКО ЗДЕСЬ
# ============================================================
RUN_MODE = "DRY_RUN"
ALLOWED_RUN_MODES = ("DRY_RUN", "SETUP_CHECK", "FULL_FEASIBILITY_PROBE")

# Direct pins in requirements-tabiclv2-probe-v1.txt were read from the local
# CPU project runtime (.venv-tabfm-v1), without installing or changing any
# package during this implementation task.
PINNED_PACKAGE_VERSIONS = {
    "tabicl": "2.2.0",
    "pandas": "2.2.3",
    "pyxlsb": "1.0.10",
    "numpy": "2.2.0",
    "scikit-learn": "1.6.0",
    "psutil": "7.2.2",
}
RUNTIME_PACKAGE_MODULES = {
    "tabicl": "tabicl",
    "torch": "torch",
    "numpy": "numpy",
    "scikit-learn": "sklearn",
    "psutil": "psutil",
    "pandas": "pandas",
    "pyxlsb": "pyxlsb",
}


EXPECTED_DATASET_SHA256 = "fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930"
EXPECTED_WORKING_INDEX_SHA256 = "80430ce6290d0982d3641621ba1ed62f6fb495e8d32f7d23d9fca00091aadb45"
CHECKPOINT_VERSION = "tabicl-classifier-v2-20260212.ckpt"
EXPECTED_TABICL_VERSION = "2.2.0"
WORKING_ROWS = 289_614
FEATURE_COUNT = 47
OUTER_FOLD_NUMBER = 1
QUERY_BLOCK_SIZE = 32
MIN_AVAILABLE_RAM_BYTES = 8 * 1024**3
ABORT_AVAILABLE_RAM_BYTES = 2 * 1024**3
ABORT_PROCESS_TREE_RSS_BYTES = 10 * 1024**3
ABORT_WALL_SECONDS = 30 * 60
SAFETY_FACTOR = 2.0
MAX_CONSERVATIVE_PROJECTION_SECONDS = 24 * 60 * 60


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_int64(values: Any) -> str:
    """Hash the Stage 3 working-index identity exactly as the saved notebook did."""
    import numpy as np

    return hashlib.sha256(np.asarray(values, dtype=np.int64).tobytes()).hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def gib(value: int | float | None) -> float | None:
    return None if value is None else round(float(value) / 1024**3, 3)


def hardware_snapshot(psutil_module: Any) -> dict[str, Any]:
    memory = psutil_module.virtual_memory()
    return {
        "cpu": platform.processor() or platform.uname().processor or "unknown",
        "physical_cores": psutil_module.cpu_count(logical=False),
        "logical_cores": psutil_module.cpu_count(logical=True),
        "ram_total_bytes": int(memory.total),
        "ram_total_gib": gib(memory.total),
        "ram_available_bytes": int(memory.available),
        "ram_available_gib": gib(memory.available),
    }


def base_result() -> dict[str, Any]:
    return {
        "probe_name": "MERITS_MINIMAL_PRE_LOCK_FEASIBILITY_PROBE",
        "quality": "UNKNOWN",
        "final_test_used": False,
        "checkpoint": {"name": CHECKPOINT_VERSION, "sha256": None},
        "dataset": {
            "filename": "Data_final.xlsb",
            "expected_sha256": EXPECTED_DATASET_SHA256,
            "actual_sha256": None,
            "working_rows": None,
            "feature_count": None,
            "forbidden_predictors": ["Q_B1_norm", "Q_B2_norm"],
        },
        "fold": {
            "working_split_identity": "saved Stage 3 working_indices from stage3_oof_predictions_V1.npz",
            "working_index_sha256": None,
            "outer_cv": {
                "type": "StratifiedKFold",
                "n_splits": 3,
                "shuffle": True,
                "random_state": 42,
            },
            "fold_number": OUTER_FOLD_NUMBER,
            "train_rows": None,
            "query_fold_rows": None,
        },
        "model_configuration": {
            "n_estimators": 8,
            "device": "cpu",
            "checkpoint_version": CHECKPOINT_VERSION,
            "random_state": 42,
            "offload_mode": "auto",
            "n_jobs": 6,
            "verbose": True,
            "kv_cache": True,
            "use_fa3": False,
        },
        "expected_context_rows": None,
        "effective_context_rows": None,
        "query_rows": None,
        "timings_seconds": {
            "model_checkpoint_load": None,
            "fit_full_context_kv_preparation": None,
            "fit_total_including_load": None,
            "predict_proba_query_block": None,
            "total_wall": None,
        },
        "memory": {
            "peak_process_tree_rss_bytes": 0,
            "peak_process_tree_rss_gib": 0.0,
            "minimum_system_available_ram_bytes": None,
            "minimum_system_available_ram_gib": None,
        },
        "projection_seconds": {
            "per_query_row": None,
            "single_fold": None,
            "full_3fold_raw": None,
            "safety_factor": SAFETY_FACTOR,
            "full_3fold_conservative": None,
        },
        "abort_reason": None,
        "software": {
            "python": platform.python_version(),
            "tabicl": package_version("tabicl"),
            "torch": package_version("torch"),
            "numpy": package_version("numpy"),
            "scikit_learn": package_version("scikit-learn"),
            "psutil": package_version("psutil"),
            "pandas": package_version("pandas"),
            "pyxlsb": package_version("pyxlsb"),
        },
        "hardware": None,
    }


def emit_phase(events: Any, step: int, label: str) -> None:
    events.put({"kind": "phase", "step": step, "label": label})


def setup_blocked(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["status"] = "PROBE_SETUP_BLOCKED"
    result["abort_reason"] = reason
    return result


def likely_setup_problem(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    markers = (
        "download", "huggingface", "hf_hub", "connection", "network", "http",
        "ssl", "certificate", "proxy", "offline", "checkpoint", "not cached",
        "no module named", "cannot import", "package not found",
    )
    return any(marker in text for marker in markers)


def worker(repo_root_text: str, events: Any, results: Any) -> None:
    """Load data and run all heavy TabICL operations in a killable child process."""
    result = base_result()
    try:
        emit_phase(events, 2, "Проверка dataset/split identity")
        import numpy as np
        import pandas as pd
        import torch
        from sklearn.model_selection import StratifiedKFold
        from tabicl import TabICLClassifier

        dependency_mismatches = [
            f"{name}={package_version(name)}"
            for name, expected in PINNED_PACKAGE_VERSIONS.items()
            if package_version(name) != expected
        ]
        if dependency_mismatches:
            results.put(setup_blocked(
                result,
                "DEPENDENCY_CONTRACT_MISMATCH: " + ", ".join(dependency_mismatches),
            ))
            return

        root = Path(repo_root_text)
        dataset_path = root / "data" / "raw" / "Data_final.xlsb"
        stage3_path = root / "reports" / "generated" / "stage3_oof_predictions_V1.npz"

        if not dataset_path.is_file():
            results.put(setup_blocked(result, "DATASET_NOT_FOUND"))
            return
        if not stage3_path.is_file():
            results.put(setup_blocked(result, "STAGE3_WORKING_INDEX_EVIDENCE_NOT_FOUND"))
            return

        dataset_hash = sha256_file(dataset_path)
        result["dataset"]["actual_sha256"] = dataset_hash
        if dataset_hash.lower() != EXPECTED_DATASET_SHA256:
            results.put(setup_blocked(result, "DATASET_SHA256_MISMATCH"))
            return

        # Access only working_indices; the saved OOF target/predictions are not read.
        with np.load(stage3_path, allow_pickle=False) as stage3_evidence:
            if "working_indices" not in stage3_evidence.files:
                results.put(setup_blocked(result, "STAGE3_WORKING_INDEX_EVIDENCE_INVALID"))
                return
            working_indices = np.asarray(stage3_evidence["working_indices"], dtype=np.int64)
        working_index_hash = sha256_int64(working_indices)
        result["fold"]["working_index_sha256"] = working_index_hash
        if len(working_indices) != WORKING_ROWS or working_index_hash != EXPECTED_WORKING_INDEX_SHA256:
            results.put(setup_blocked(result, "STAGE3_WORKING_INDEX_IDENTITY_MISMATCH"))
            return

        emit_phase(events, 3, "Подготовка полного outer-train context")
        frame = pd.read_excel(dataset_path, engine="pyxlsb", sheet_name="Data_final").reset_index(drop=True)
        required = {"INN", "DefMark", "Q_B1_norm", "Q_B2_norm"}
        missing = required.difference(frame.columns)
        if missing:
            results.put(setup_blocked(result, "DATASET_REQUIRED_COLUMNS_MISSING"))
            return
        all_features = [column for column in frame.columns if column not in {"INN", "DefMark"}]
        features = [column for column in all_features if column not in {"Q_B1_norm", "Q_B2_norm"}]
        if len(all_features) != 49 or len(features) != FEATURE_COUNT:
            results.put(setup_blocked(result, "FEATURE_CONTRACT_MISMATCH"))
            return
        if {"Q_B1_norm", "Q_B2_norm"}.intersection(features):
            results.put(setup_blocked(result, "FORBIDDEN_PREDICTOR_IN_FEATURES"))
            return

        # This directly reconstructs the accepted working sample. No final-test
        # frame/target is materialised. Validation y is used only by splitter.
        x_work = frame.loc[working_indices, features].apply(pd.to_numeric, errors="raise").astype("float32").reset_index(drop=True)
        y_work = pd.to_numeric(frame.loc[working_indices, "DefMark"], errors="raise").astype("int8").reset_index(drop=True)
        del frame
        if int(x_work.isna().sum().sum()) != 0:
            results.put(setup_blocked(result, "FEATURE_CONTRACT_CONTAINS_MISSING_VALUES"))
            return

        splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
        train_indices, query_fold_indices = next(splitter.split(x_work, y_work))
        x_train = x_work.iloc[train_indices].reset_index(drop=True)
        y_train = y_work.iloc[train_indices].reset_index(drop=True)
        # Do not read validation target: the probe only passes X query to predict_proba.
        x_query = x_work.iloc[query_fold_indices[:QUERY_BLOCK_SIZE]].reset_index(drop=True)
        del x_work, y_work

        expected_context_rows = len(x_train)
        result["dataset"]["working_rows"] = int(expected_context_rows + len(query_fold_indices))
        result["dataset"]["feature_count"] = int(x_train.shape[1])
        result["fold"]["train_rows"] = int(expected_context_rows)
        result["fold"]["query_fold_rows"] = int(len(query_fold_indices))
        result["expected_context_rows"] = int(expected_context_rows)
        result["query_rows"] = int(len(x_query))
        if expected_context_rows + len(query_fold_indices) != WORKING_ROWS or x_train.shape[1] != FEATURE_COUNT or len(x_query) != QUERY_BLOCK_SIZE:
            results.put(setup_blocked(result, "FOLD_OR_QUERY_CONTRACT_MISMATCH"))
            return
        events.put({
            "kind": "contract",
            "working_rows": WORKING_ROWS,
            "train_rows": expected_context_rows,
            "query_fold_rows": len(query_fold_indices),
            "feature_count": x_train.shape[1],
            "dataset_sha256": dataset_hash,
            "working_split_sha256": working_index_hash,
            "fold_number": OUTER_FOLD_NUMBER,
        })

        emit_phase(events, 4, "Загрузка TabICLv2 checkpoint")
        load_seconds: list[float] = []

        class TimedTabICLClassifier(TabICLClassifier):
            def _load_model(self) -> None:  # Uses the official implementation; no library patching.
                started = time.perf_counter()
                super()._load_model()
                load_seconds.append(time.perf_counter() - started)
                emit_phase(events, 5, "Full-context fit/KV preparation")

        classifier = TimedTabICLClassifier(
            n_estimators=8,
            device="cpu",
            checkpoint_version=CHECKPOINT_VERSION,
            random_state=42,
            offload_mode="auto",
            n_jobs=6,
            verbose=True,
            kv_cache=True,
            use_fa3=False,
        )
        fit_started = time.perf_counter()
        classifier.fit(x_train, y_train)
        fit_total = time.perf_counter() - fit_started
        result["timings_seconds"]["model_checkpoint_load"] = load_seconds[0] if load_seconds else None
        result["timings_seconds"]["fit_total_including_load"] = fit_total
        result["timings_seconds"]["fit_full_context_kv_preparation"] = max(
            0.0, fit_total - (load_seconds[0] if load_seconds else 0.0)
        )

        resolved_device = str(getattr(classifier, "device_", "unknown"))
        actual_estimators = sum(
            len(shuffles) for shuffles in getattr(classifier.ensemble_generator_, "class_shuffles_", {}).values()
        )
        result["model_configuration"]["resolved_device"] = resolved_device
        result["model_configuration"]["effective_n_estimators"] = actual_estimators
        result["model_configuration"]["effective_feature_count"] = int(getattr(classifier, "n_features_in_", -1))
        if resolved_device != "cpu" or actual_estimators != 8 or int(getattr(classifier, "n_features_in_", -1)) != FEATURE_COUNT:
            result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
            result["abort_reason"] = "OFFICIAL_CONFIGURATION_NOT_EFFECTIVE"
            results.put(result)
            return

        # n_samples_in_ is the estimator's public fitted attribute. KV cache train
        # shapes independently verify that every cached ensemble view retained all rows.
        estimator_rows = int(getattr(classifier, "n_samples_in_", -1))
        caches = getattr(classifier, "model_kv_cache_", None)
        cache_rows = sorted({int(cache.train_shape[1]) for cache in caches.values()}) if caches else []
        result["effective_context_rows"] = estimator_rows
        result["context_verification"] = {
            "estimator_n_samples_in": estimator_rows,
            "kv_cache_train_rows_by_normalization": cache_rows,
        }
        if estimator_rows != expected_context_rows or cache_rows != [expected_context_rows]:
            result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
            result["abort_reason"] = "IMPLICIT_CONTEXT_REDUCTION"
            results.put(result)
            return

        model_path = Path(str(getattr(classifier, "model_path_", "")))
        if model_path.is_file():
            result["checkpoint"]["sha256"] = sha256_file(model_path)

        emit_phase(events, 6, "Predict query block + feasibility projection")
        query_started = time.perf_counter()
        probabilities = classifier.predict_proba(x_query)
        query_seconds = time.perf_counter() - query_started
        result["timings_seconds"]["predict_proba_query_block"] = query_seconds
        observed_shape = list(getattr(probabilities, "shape", ()))
        shape_pass = observed_shape == [QUERY_BLOCK_SIZE, 2]
        finite_pass = False
        range_pass = False
        row_sum_pass = False
        row_sum_max_abs_error: float | None = None
        try:
            finite_pass = bool(np.isfinite(probabilities).all())
            if finite_pass:
                range_pass = bool(((probabilities >= 0.0) & (probabilities <= 1.0)).all())
                if shape_pass:
                    row_sum_error = np.abs(probabilities.sum(axis=1) - 1.0)
                    row_sum_max_abs_error = float(np.max(row_sum_error))
                    row_sum_pass = bool(np.allclose(
                        probabilities.sum(axis=1), 1.0, rtol=0.0, atol=1e-6,
                    ))
        except (TypeError, ValueError):
            pass
        prediction_contract_pass = shape_pass and finite_pass and range_pass and row_sum_pass
        result["prediction_contract"] = {
            "observed_shape": observed_shape,
            "shape_pass": shape_pass,
            "finite_pass": finite_pass,
            "range_pass": range_pass,
            "row_sum_pass": row_sum_pass,
            "row_sum_max_abs_error": row_sum_max_abs_error,
            "reason": None if prediction_contract_pass else "QUERY_PREDICTION_CONTRACT_MISMATCH",
        }
        if not prediction_contract_pass:
            result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
            result["abort_reason"] = "QUERY_PREDICTION_CONTRACT_MISMATCH"
            results.put(result)
            return

        per_query_row = query_seconds / QUERY_BLOCK_SIZE
        single_fold = result["timings_seconds"]["fit_full_context_kv_preparation"] + per_query_row * len(query_fold_indices)
        raw_projection = 3 * single_fold
        conservative_projection = SAFETY_FACTOR * raw_projection
        result["projection_seconds"] = {
            "per_query_row": per_query_row,
            "single_fold": single_fold,
            "full_3fold_raw": raw_projection,
            "safety_factor": SAFETY_FACTOR,
            "full_3fold_conservative": conservative_projection,
        }
        result["status"] = "FEASIBILITY_PASS" if conservative_projection <= MAX_CONSERVATIVE_PROJECTION_SECONDS else "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
        if result["status"] != "FEASIBILITY_PASS":
            result["abort_reason"] = "CONSERVATIVE_OOF_PROJECTION_OVER_24_HOURS"
        results.put(result)
    except BaseException as error:
        if likely_setup_problem(error):
            results.put(setup_blocked(result, f"SETUP_OR_CHECKPOINT_ERROR: {type(error).__name__}"))
        else:
            result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
            result["abort_reason"] = f"MODEL_OPERATION_ERROR: {type(error).__name__}"
            results.put(result)


def process_tree_rss(psutil_module: Any, pid: int) -> int:
    try:
        root = psutil_module.Process(pid)
        processes = [root, *root.children(recursive=True)]
        return sum(process.memory_info().rss for process in processes if process.is_running())
    except (psutil_module.Error, OSError):
        return 0


def terminate_process_tree(psutil_module: Any, pid: int) -> None:
    try:
        root = psutil_module.Process(pid)
        descendants = root.children(recursive=True)
        for process in reversed(descendants):
            if process.is_running():
                process.terminate()
        psutil_module.wait_procs(descendants, timeout=10)
        for process in descendants:
            if process.is_running():
                process.kill()
        if root.is_running():
            root.terminate()
        try:
            root.wait(timeout=10)
        except psutil_module.TimeoutExpired:
            root.kill()
    except (psutil_module.Error, OSError):
        return


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=ALLOWED_RUN_MODES, help="Optional override for the single operator-panel RUN_MODE.")
    default_output = Path(__file__).resolve().parents[1] / "reports" / "generated" / "tabiclv2_feasibility_probe_V1.json"
    parser.add_argument("--output", type=Path, default=default_output, help="Result JSON path only for FULL_FEASIBILITY_PROBE.")
    return parser.parse_args()


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def validate_fixed_config(selected_mode: str = RUN_MODE) -> list[str]:
    errors: list[str] = []
    if selected_mode not in ALLOWED_RUN_MODES:
        errors.append(f"mode must be one of {ALLOWED_RUN_MODES}")
    if CHECKPOINT_VERSION != "tabicl-classifier-v2-20260212.ckpt":
        errors.append("checkpoint contract changed")
    if EXPECTED_TABICL_VERSION != PINNED_PACKAGE_VERSIONS["tabicl"]:
        errors.append("tabicl package contract changed")
    if QUERY_BLOCK_SIZE != 32 or FEATURE_COUNT != 47 or WORKING_ROWS != 289_614:
        errors.append("dataset/query contract changed")
    if ABORT_WALL_SECONDS != 30 * 60 or SAFETY_FACTOR != 2.0:
        errors.append("guard/projection contract changed")
    return errors


def print_start_screen(mode: str, cli_override: bool) -> None:
    plans = {
        "DRY_RUN": [
            "[1/2] Проверка фиксированной конфигурации",
            "[2/2] Показ плана без доступа к dataset/model/checkpoint",
        ],
        "SETUP_CHECK": [
            "[1/3] Проверка Python, packages и hardware",
            "[2/3] Проверка наличия dataset path без чтения полного dataset",
            "[3/3] Итог readiness без model/checkpoint/fit/predict",
        ],
        "FULL_FEASIBILITY_PROBE": [
            "[1/6] Проверка окружения и hardware",
            "[2/6] Проверка dataset/split identity",
            "[3/6] Подготовка полного outer-train context",
            "[4/6] Загрузка TabICLv2 checkpoint",
            "[5/6] Full-context fit/KV preparation",
            "[6/6] Predict query block + feasibility projection",
        ],
    }
    print("=" * 60)
    print("TabICLv2 — pre-lock feasibility probe")
    print(f"Режим: {mode}")
    if cli_override:
        print("Источник режима: CLI override --mode (операторская панель переопределена для этого запуска)")
    else:
        print("Источник режима: operator panel RUN_MODE")
    print("=" * 60)
    print("Что будет сделано:")
    for line in plans.get(mode, []):
        print(line)
    print("Запрещено в этом запуске:")
    print("- quality metrics")
    print("- final test")
    print("- OOF")
    print("- tuning")
    print("- уменьшение context")
    print()


def run_dry_run(selected_mode: str) -> int:
    errors = validate_fixed_config(selected_mode)
    if errors:
        print("=" * 60)
        print("ИТОГ DRY_RUN: CONFIGURATION_INVALID")
        for error in errors:
            print(f"- {error}")
        print("Dataset, checkpoint и модель не открывались.")
        print("=" * 60)
        return 2
    print("[1/2] Конфигурация: PASS")
    print("[2/2] Dataset, checkpoint и TabICL model не открывались.")
    print("=" * 60)
    print("ИТОГ DRY_RUN: PASS")
    print("Dataset, checkpoint и модель не открывались.")
    print("Для реального probe выберите FULL_FEASIBILITY_PROBE только в operator panel.")
    print("=" * 60)
    return 0


def inspect_runtime_dependencies() -> tuple[list[tuple[str, str, str, str]], list[str]]:
    rows: list[tuple[str, str, str, str]] = []
    errors: list[str] = []
    for package_name, module_name in RUNTIME_PACKAGE_MODULES.items():
        expected = PINNED_PACKAGE_VERSIONS.get(package_name)
        required = expected if expected is not None else "установлен"
        found = package_version(package_name)
        if found is None:
            rows.append((package_name, required, "—", "ОТСУТСТВУЕТ"))
            errors.append(f"{package_name}: package is not installed")
            continue
        try:
            importlib.import_module(module_name)
        except Exception as error:
            rows.append((package_name, required, found, "IMPORT_ERROR"))
            errors.append(f"{package_name}: import failed ({type(error).__name__})")
            continue
        if expected is not None and found != expected:
            rows.append((package_name, required, found, "VERSION_MISMATCH"))
            errors.append(f"{package_name}: expected {expected}, found {found}")
            continue
        rows.append((package_name, required, found, "PASS"))
    return rows, errors


def print_dependency_table(rows: list[tuple[str, str, str, str]]) -> None:
    print("Пакет | Требуется | Найдено | Статус")
    print("--- | --- | --- | ---")
    for package_name, required, found, status in rows:
        print(f"{package_name} | {required} | {found} | {status}")


def run_setup_check(selected_mode: str) -> int:
    errors = validate_fixed_config(selected_mode)
    print("[1/3] Python/packages/hardware")
    dependency_rows, dependency_errors = inspect_runtime_dependencies()
    print_dependency_table(dependency_rows)
    errors.extend(dependency_errors)
    try:
        import psutil
    except ImportError:
        # The table above carries the package/import reason; this keeps the
        # hardware branch safe without replacing it with a model operation.
        psutil = None
    if psutil is not None:
        snapshot = hardware_snapshot(psutil)
        print(
            f"CPU cores physical/logical: {snapshot['physical_cores']}/{snapshot['logical_cores']}; "
            f"RAM available: {snapshot['ram_available_gib']:.2f} GiB"
        )
        if not snapshot["physical_cores"] or snapshot["physical_cores"] < 6:
            errors.append("physical cores below 6")
        if snapshot["ram_available_bytes"] < MIN_AVAILABLE_RAM_BYTES:
            errors.append("available RAM below 8 GiB")
    print("[2/3] Dataset path only")
    dataset_path = Path(__file__).resolve().parents[1] / "data" / "raw" / "Data_final.xlsb"
    if dataset_path.is_file():
        print("Dataset path: found (full dataset was not read)")
    else:
        errors.append("dataset path not found")
        print("Dataset path: not found")
    print("[3/3] Model/checkpoint/fit/predict: not executed")
    if errors:
        print("=" * 60)
        print("ИТОГ: PROBE_SETUP_BLOCKED")
        print("Причина: " + "; ".join(errors))
        print("Это НЕ model feasibility FAIL.")
        print("Quality: UNKNOWN")
        print("=" * 60)
        return 2
    print("=" * 60)
    print("ИТОГ SETUP_CHECK: PASS")
    print("Это не feasibility result; checkpoint и модель не создавались.")
    print("Quality: UNKNOWN")
    print("=" * 60)
    return 0


def print_heartbeat(step: int, label: str, elapsed: float, rss: int, available: int) -> None:
    print(f"[Этап {step}/6] {label}")
    print(f"Прошло: {format_duration(elapsed)}")
    print(f"Выполнено этапов: {max(0, step - 1)}/6")
    print("Текущий этап: выполняется")
    print(f"До hard timeout текущего probe: {format_duration(ABORT_WALL_SECONDS - elapsed)}")
    print(f"Process-tree RSS: {gib(rss):.2f} GiB / лимит 10 GiB")
    print(f"Свободно RAM в системе: {gib(available):.2f} GiB / stop <2 GiB")
    print(flush=True)


def print_runtime_evidence(result: dict[str, Any]) -> None:
    timings = result.get("timings_seconds", {})
    projection = result.get("projection_seconds", {})
    query_seconds = timings.get("predict_proba_query_block")
    setup_seconds = timings.get("fit_full_context_kv_preparation")
    if query_seconds is None or setup_seconds is None or projection.get("full_3fold_raw") is None:
        return
    throughput = QUERY_BLOCK_SIZE / query_seconds if query_seconds > 0 else None
    runtime_pass = projection["full_3fold_conservative"] <= MAX_CONSERVATIVE_PROJECTION_SECONDS
    print("Фактические timing/projection evidence:")
    print(f"T_setup: {format_duration(setup_seconds)}")
    print(f"T_query_32: {format_duration(query_seconds)}")
    print(f"Query throughput: {throughput:.4f} rows/s")
    print(f"Raw 3-fold projection: {format_duration(projection['full_3fold_raw'])}")
    print(f"Safety factor: {projection['safety_factor']:.1f}")
    print(f"Conservative 3-fold projection: {format_duration(projection['full_3fold_conservative'])}")
    print("Runtime criterion (<= 24h): " + ("PASS" if runtime_pass else "FAIL"))


def print_final_screen(result: dict[str, Any]) -> None:
    status = result["status"]
    reason = result.get("abort_reason") or "not applicable"
    print("=" * 60)
    if status == "FEASIBILITY_PASS":
        print("ИТОГ FEASIBILITY PROBE: PASS")
        print("Quality: UNKNOWN")
        print("Полный OOF НЕ запускался.")
        print("Следующий шаг: отдельный Architect Experiment Lock.")
    elif status == "PROBE_SETUP_BLOCKED":
        print("ИТОГ: PROBE_SETUP_BLOCKED")
        print(f"Причина: {reason}")
        print("Это НЕ model feasibility FAIL.")
        print("Quality: UNKNOWN")
    else:
        print("ИТОГ FEASIBILITY PROBE: FAIL")
        print(f"Причина: {reason}")
        print("Quality: UNKNOWN")
        print("Полный OOF НЕ запускался.")
        print("Следующий шаг: model reopen закрыт → blind-spot research.")
    print("=" * 60)


def run_full_feasibility_probe(selected_mode: str, output_path: Path) -> int:
    result = base_result()
    started = time.monotonic()
    configuration_errors = validate_fixed_config(selected_mode)
    if configuration_errors:
        setup_blocked(result, "CONFIGURATION_INVALID: " + "; ".join(configuration_errors))
        result["timings_seconds"]["total_wall"] = time.monotonic() - started
        write_result(output_path, result)
        print_final_screen(result)
        return 2
    try:
        import psutil
    except ImportError:
        setup_blocked(result, "PSUTIL_NOT_AVAILABLE")
        result["timings_seconds"]["total_wall"] = time.monotonic() - started
        write_result(output_path, result)
        print_final_screen(result)
        return 2

    result["hardware"] = hardware_snapshot(psutil)
    initial_hardware = result["hardware"]
    minimum_available = result["hardware"]["ram_available_bytes"]
    peak_rss = 0
    if not result["hardware"]["physical_cores"] or result["hardware"]["physical_cores"] < 6:
        result["status"] = "STOP_PRECONDITION_PHYSICAL_CORES"
        result["abort_reason"] = "PHYSICAL_CORES_BELOW_6"
    elif minimum_available < MIN_AVAILABLE_RAM_BYTES:
        result["status"] = "STOP_PRECONDITION_AVAILABLE_RAM"
        result["abort_reason"] = "AVAILABLE_RAM_BELOW_8_GIB"
    else:
        print("[Этап 1/6] Проверка окружения и hardware: PASS")
        context = mp.get_context("spawn")
        events = context.Queue()
        results = context.Queue(maxsize=1)
        repo_root = Path(__file__).resolve().parents[1]
        process = context.Process(target=worker, args=(str(repo_root), events, results), daemon=False)
        process.start()
        phase_step = 2
        phase_label = "Проверка dataset/split identity"
        last_heartbeat = 0.0
        guard_reason: str | None = None
        while process.is_alive():
            now = time.monotonic()
            while True:
                try:
                    event = events.get_nowait()
                except queue.Empty:
                    break
                if event.get("kind") == "phase":
                    phase_step = int(event["step"])
                    phase_label = str(event["label"])
                elif event.get("kind") == "contract":
                    print(
                        "Контракт: "
                        f"working={event['working_rows']}; train={event['train_rows']}; "
                        f"query-fold={event['query_fold_rows']}; features={event['feature_count']}; "
                        f"dataset SHA-256={event['dataset_sha256']}; "
                        f"working split SHA-256={event['working_split_sha256']}; "
                        f"fold={event['fold_number']}",
                        flush=True,
                    )
            available = int(psutil.virtual_memory().available)
            rss = process_tree_rss(psutil, process.pid)
            minimum_available = min(minimum_available, available)
            peak_rss = max(peak_rss, rss)
            elapsed = now - started
            if available < ABORT_AVAILABLE_RAM_BYTES:
                guard_reason = "SYSTEM_AVAILABLE_RAM_BELOW_2_GIB"
            elif rss > ABORT_PROCESS_TREE_RSS_BYTES:
                guard_reason = "WORKER_PROCESS_TREE_RSS_OVER_10_GIB"
            elif elapsed > ABORT_WALL_SECONDS:
                guard_reason = "WALL_CLOCK_OVER_30_MINUTES"
            if guard_reason:
                terminate_process_tree(psutil, process.pid)
                break
            if now - last_heartbeat >= 30.0:
                print_heartbeat(phase_step, phase_label, elapsed, rss, available)
                last_heartbeat = now
            time.sleep(1.0)
        process.join(timeout=15)
        available = int(psutil.virtual_memory().available)
        minimum_available = min(minimum_available, available)
        peak_rss = max(peak_rss, process_tree_rss(psutil, process.pid))
        if guard_reason:
            result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
            result["abort_reason"] = guard_reason
        else:
            try:
                result = results.get(timeout=5)
            except queue.Empty:
                result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
                result["abort_reason"] = "WORKER_EXITED_WITHOUT_RESULT"

    # The worker owns package inspection; the parent owns the machine snapshot
    # and guard measurements, so retain the latter when taking the worker result.
    result["hardware"] = initial_hardware

    total_wall = time.monotonic() - started
    result["timings_seconds"]["total_wall"] = total_wall
    result["memory"]["peak_process_tree_rss_bytes"] = peak_rss
    result["memory"]["peak_process_tree_rss_gib"] = gib(peak_rss)
    result["memory"]["minimum_system_available_ram_bytes"] = minimum_available
    result["memory"]["minimum_system_available_ram_gib"] = gib(minimum_available)
    if result["status"] == "FEASIBILITY_PASS" and total_wall > ABORT_WALL_SECONDS:
        result["status"] = "TABICLV2_REJECTED_BY_FEASIBILITY_GATE"
        result["abort_reason"] = "WALL_CLOCK_OVER_30_MINUTES"
    write_result(output_path, result)
    print_runtime_evidence(result)
    print_final_screen(result)
    return 0 if result["status"] == "FEASIBILITY_PASS" else 2


def main() -> int:
    args = parse_args()
    mode = args.mode or RUN_MODE
    cli_override = args.mode is not None
    print_start_screen(mode, cli_override)
    if mode not in ALLOWED_RUN_MODES:
        print("Invalid mode. Select one of: " + ", ".join(ALLOWED_RUN_MODES))
        return 2
    if mode == "DRY_RUN":
        return run_dry_run(mode)
    if mode == "SETUP_CHECK":
        return run_setup_check(mode)
    return run_full_feasibility_probe(mode, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
