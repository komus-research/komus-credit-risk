from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================================
# KOMUS — подготовка пилотного списка ИНН для новой выгрузки СПАРК
#
# Что делает скрипт:
# 1. Проверяет, что используется именно принятый Data_final.xlsb.
# 2. Загружает сохранённый Stage 3 OOF-checkpoint — модели НЕ переобучаются.
# 3. Воспроизводит группы Stage 3.
# 4. Формирует основной диагностический пилот на 10 000 компаний.
# 5. Формирует резерв ещё на 5 000 компаний.
# 6. Создаёт ДВА Excel:
#    - файл для коллеги: только ИНН + порядок/приоритет;
#    - служебный файл: группы, target и диагностика для внутреннего контроля.
#
# Запуск из корня проекта:
#   uv run --with xlsxwriter scripts/prepare_spark_pilot_inns_V1.py
# ============================================================================


EXPECTED_DATASET_SHA256 = (
    "fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930"
)
EXPECTED_OOF_SHA256 = (
    "faa53a8aed86c2d445699c0fd1df6a5b83711c96d3a300f9a8860112ff4473ac"
)
EXPECTED_WORKING_INDEX_SHA256 = (
    "80430ce6290d0982d3641621ba1ed62f6fb495e8d32f7d23d9fca00091aadb45"
)

TARGET = "DefMark"
IDENTIFIER = "INN"
SEED = 42

# Stage 3 — зафиксированные диагностические границы
DEEP_MISS_MAX_RANK = 0.50
WELL_RANKED_MIN_RANK = 0.90
HIGH_RISK_NONDEFAULT_MIN_RANK = 0.95
BLIND_SPOT_MAX_SPREAD = 0.10

# Основной пилот = ровно 10 000
MAIN_COUNTS = {
    "blind_spot": 805,                 # все найденные Stage 3 blind spot
    "well_ranked_default": 2_000,      # положительный контроль
    "high_risk_nondefault": 2_000,     # сложные ложноположительные случаи
    "typical_nondefault": 5_195,       # контрольный фон
}

# Резерв = ещё 5 000.
# Использовать только при технической невозможности выгрузить часть основного
# списка или если понадобится расширить пилот. Пустые/редкие данные НЕ являются
# причиной заменять компанию: отсутствие данных само может быть информативно.
RESERVE_COUNTS = {
    "deep_missed_not_blind": 473,
    "well_ranked_default": 1_000,
    "high_risk_nondefault": 1_000,
    "other_default": 527,
    "typical_nondefault": 2_000,
}

GROUP_RU = {
    "blind_spot": "Общая слепая зона",
    "deep_missed_not_blind": "Глубоко пропущенный дефолт вне общей слепой зоны",
    "well_ranked_default": "Хорошо ранжированный дефолт",
    "high_risk_nondefault": "Высокорисковый недефолт",
    "other_default": "Прочий дефолт",
    "typical_nondefault": "Типичный недефолт",
}


def project_root() -> Path:
    """Возвращает корень модуля credit-scoring независимо от текущей папки запуска."""
    root = Path(__file__).resolve().parents[1]

    if not (root / "pyproject.toml").exists():
        raise FileNotFoundError(
            f"Не найден pyproject.toml в корне модуля credit-scoring: {root}"
        )

    return root


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_indices(values: np.ndarray) -> str:
    arr = np.asarray(values, dtype=np.int64)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def normalize_inn(value: object) -> str:
    """Приводит ИНН к тексту для Excel и защищает от scientific notation."""
    if pd.isna(value):
        raise ValueError("В Data_final найден пустой INN.")

    if isinstance(value, (int, np.integer)):
        text = str(int(value))
    elif isinstance(value, (float, np.floating)):
        if not float(value).is_integer():
            raise ValueError(f"INN имеет нецелое значение: {value!r}")
        text = str(int(value))
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d+\.0", text):
            text = text[:-2]

    text = re.sub(r"\s+", "", text)

    if not text.isdigit():
        raise ValueError(f"INN содержит нецифровые символы: {value!r}")

    # ИНН в РФ имеет 10 или 12 цифр. Если Excel когда-то съел ведущий ноль,
    # длина станет 9 или 11 — восстанавливаем один ведущий ноль.
    if len(text) == 9:
        text = text.zfill(10)
    elif len(text) == 11:
        text = text.zfill(12)

    if len(text) not in (10, 12):
        raise ValueError(
            f"Неожиданная длина INN={text!r}: {len(text)} цифр. "
            "Нужно проверить исходный Data_final."
        )
    return text


def choose(pool: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    if n < 0:
        raise ValueError("n не может быть отрицательным.")
    if len(pool) < n:
        raise RuntimeError(
            f"Недостаточно строк в группе: требуется {n}, доступно {len(pool)}."
        )
    if n == 0:
        return pool.iloc[0:0].copy()
    return pool.sample(n=n, random_state=seed, replace=False).copy()


def add_group_columns(
    frame: pd.DataFrame,
    group_code: str,
    list_name: str,
    priority: int,
    do_not_replace: bool,
) -> pd.DataFrame:
    out = frame.copy()
    out["Группа_code"] = group_code
    out["Группа"] = GROUP_RU[group_code]
    out["Список"] = list_name
    out["Приоритет"] = priority
    out["Не_заменять"] = "ДА" if do_not_replace else "НЕТ"
    return out


def main() -> None:
    try:
        import xlsxwriter  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Для записи .xlsx нужен xlsxwriter.\n"
            "Запусти так:\n"
            "uv run --with xlsxwriter scripts/prepare_spark_pilot_inns_V1.py"
        ) from exc

    root = project_root()
    dataset_path = root / "data" / "raw" / "Data_final.xlsb"
    oof_path = root / "reports" / "generated" / "stage3_oof_predictions_V1.npz"
    output_dir = root / "reports" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    share_path = output_dir / "СПАРК_ИНН_пилот_для_коллеги_V1.xlsx"
    audit_path = output_dir / "СПАРК_ИНН_пилот_служебный_V1.xlsx"

    print("Этап 1/6. Проверяю исходные файлы...")
    if not dataset_path.exists():
        raise FileNotFoundError(f"Не найден dataset: {dataset_path}")
    if not oof_path.exists():
        raise FileNotFoundError(
            f"Не найден Stage 3 OOF checkpoint: {oof_path}\n"
            "Он должен быть сохранён в reports/generated."
        )

    dataset_sha = sha256_file(dataset_path)
    if dataset_sha.lower() != EXPECTED_DATASET_SHA256.lower():
        raise RuntimeError(
            "Data_final.xlsb не совпадает с принятым dataset.\n"
            f"Ожидался: {EXPECTED_DATASET_SHA256}\n"
            f"Получен:  {dataset_sha}"
        )

    oof_sha = sha256_file(oof_path)
    if oof_sha.lower() != EXPECTED_OOF_SHA256.lower():
        raise RuntimeError(
            "Stage 3 OOF checkpoint не совпадает с принятым артефактом.\n"
            f"Ожидался: {EXPECTED_OOF_SHA256}\n"
            f"Получен:  {oof_sha}"
        )

    print("Этап 2/6. Читаю только INN и DefMark из Data_final...")
    data = pd.read_excel(
        dataset_path,
        engine="pyxlsb",
        sheet_name="Data_final",
        usecols=[IDENTIFIER, TARGET],
    ).reset_index(drop=True)

    data[TARGET] = pd.to_numeric(data[TARGET], errors="raise").astype("int8")
    if data[IDENTIFIER].duplicated().any():
        raise RuntimeError("В Data_final обнаружены дубликаты INN.")

    print("Этап 3/6. Загружаю сохранённую Stage 3 диагностику...")
    with np.load(oof_path, allow_pickle=False) as checkpoint:
        required = {
            "working_indices",
            "target",
            "consensus_rank",
            "rank_spread",
        }
        missing = required.difference(checkpoint.files)
        if missing:
            raise KeyError(
                f"В OOF checkpoint отсутствуют ключи: {sorted(missing)}"
            )

        working_indices = np.asarray(checkpoint["working_indices"], dtype=np.int64)
        target = np.asarray(checkpoint["target"], dtype=np.int8)
        consensus_rank = np.asarray(checkpoint["consensus_rank"], dtype=np.float64)
        rank_spread = np.asarray(checkpoint["rank_spread"], dtype=np.float64)

    if hash_indices(working_indices) != EXPECTED_WORKING_INDEX_SHA256:
        raise RuntimeError("Working split не совпадает со Stage 3.")

    if not (
        len(working_indices)
        == len(target)
        == len(consensus_rank)
        == len(rank_spread)
    ):
        raise RuntimeError("Размеры массивов Stage 3 не совпадают.")

    dataset_target = data.iloc[working_indices][TARGET].to_numpy(dtype=np.int8)
    if not np.array_equal(dataset_target, target):
        raise RuntimeError("Target в OOF checkpoint не совпал с Data_final.")

    work = pd.DataFrame(
        {
            "Dataset_row_index": working_indices,
            "Working_position": np.arange(len(working_indices), dtype=np.int64),
            TARGET: target,
            "Consensus_rank": consensus_rank,
            "Rank_spread": rank_spread,
        }
    )
    work["INN"] = [
        normalize_inn(v)
        for v in data.iloc[working_indices][IDENTIFIER].tolist()
    ]

    is_default = work[TARGET].eq(1)
    is_nondefault = ~is_default

    blind = (
        is_default
        & work["Consensus_rank"].le(DEEP_MISS_MAX_RANK)
        & work["Rank_spread"].le(BLIND_SPOT_MAX_SPREAD)
    )
    deep_missed = is_default & work["Consensus_rank"].le(DEEP_MISS_MAX_RANK)
    well_ranked = is_default & work["Consensus_rank"].ge(WELL_RANKED_MIN_RANK)
    high_risk_nondefault = (
        is_nondefault
        & work["Consensus_rank"].ge(HIGH_RISK_NONDEFAULT_MIN_RANK)
    )
    typical_nondefault = (
        is_nondefault
        & work["Consensus_rank"].lt(HIGH_RISK_NONDEFAULT_MIN_RANK)
    )

    print("Этап 4/6. Проверяю воспроизводимость групп Stage 3...")
    actual_counts = {
        "blind_spot": int(blind.sum()),
        "deep_missed": int(deep_missed.sum()),
        "well_ranked_default": int(well_ranked.sum()),
        "high_risk_nondefault": int(high_risk_nondefault.sum()),
    }
    expected_counts = {
        "blind_spot": 805,
        "deep_missed": 1278,
        "well_ranked_default": 16026,
        "high_risk_nondefault": 3911,
    }

    if actual_counts != expected_counts:
        raise RuntimeError(
            "Группы Stage 3 не воспроизвелись.\n"
            f"Ожидалось: {expected_counts}\n"
            f"Получено:  {actual_counts}"
        )

    pools = {
        "blind_spot": work.loc[blind].copy(),
        "deep_missed_not_blind": work.loc[deep_missed & ~blind].copy(),
        "well_ranked_default": work.loc[well_ranked].copy(),
        "high_risk_nondefault": work.loc[high_risk_nondefault].copy(),
        "typical_nondefault": work.loc[typical_nondefault].copy(),
    }
    pools["other_default"] = work.loc[
        is_default
        & ~blind
        & ~well_ranked
        & ~(deep_missed & ~blind)
    ].copy()

    print("Этап 5/6. Формирую основной список 10 000 и резерв 5 000...")

    selected_positions: set[int] = set()
    main_parts: list[pd.DataFrame] = []

    # Все 805 blind spot — без случайной выборки и без замены.
    part = add_group_columns(
        pools["blind_spot"],
        "blind_spot",
        "Основной",
        priority=1,
        do_not_replace=True,
    )
    main_parts.append(part)
    selected_positions.update(part["Working_position"].astype(int).tolist())

    main_specs = [
        ("well_ranked_default", 2_000, 2),
        ("high_risk_nondefault", 2_000, 2),
        ("typical_nondefault", 5_195, 3),
    ]
    for offset, (group_code, n, priority) in enumerate(main_specs, start=1):
        available = pools[group_code].loc[
            ~pools[group_code]["Working_position"].isin(selected_positions)
        ]
        part = choose(available, n, SEED + offset)
        part = add_group_columns(
            part,
            group_code,
            "Основной",
            priority=priority,
            do_not_replace=False,
        )
        main_parts.append(part)
        selected_positions.update(part["Working_position"].astype(int).tolist())

    main_df = pd.concat(main_parts, ignore_index=True)
    if len(main_df) != 10_000:
        raise RuntimeError(f"Основной список должен быть 10 000, получено {len(main_df)}.")

    reserve_parts: list[pd.DataFrame] = []
    reserve_specs = [
        ("deep_missed_not_blind", 473, 4),
        ("well_ranked_default", 1_000, 4),
        ("high_risk_nondefault", 1_000, 4),
        ("other_default", 527, 4),
        ("typical_nondefault", 2_000, 4),
    ]
    for offset, (group_code, n, priority) in enumerate(reserve_specs, start=20):
        available = pools[group_code].loc[
            ~pools[group_code]["Working_position"].isin(selected_positions)
        ]
        part = choose(available, n, SEED + offset)
        part = add_group_columns(
            part,
            group_code,
            "Резерв",
            priority=priority,
            do_not_replace=False,
        )
        reserve_parts.append(part)
        selected_positions.update(part["Working_position"].astype(int).tolist())

    reserve_df = pd.concat(reserve_parts, ignore_index=True)
    if len(reserve_df) != 5_000:
        raise RuntimeError(f"Резерв должен быть 5 000, получено {len(reserve_df)}.")

    # Стабильный порядок: blind spot первыми, затем остальные основные, затем резерв.
    main_df = main_df.sort_values(
        ["Приоритет", "Группа_code", "INN"], kind="stable"
    ).reset_index(drop=True)
    reserve_df = reserve_df.sort_values(
        ["Приоритет", "Группа_code", "INN"], kind="stable"
    ).reset_index(drop=True)

    all_df = pd.concat([main_df, reserve_df], ignore_index=True)
    all_df.insert(0, "Порядок", np.arange(1, len(all_df) + 1, dtype=np.int64))

    if all_df["INN"].duplicated().any():
        dupes = all_df.loc[all_df["INN"].duplicated(keep=False), "INN"].tolist()
        raise RuntimeError(f"В итоговом списке появились дубликаты INN: {dupes[:10]}")

    # Файл ДЛЯ КОЛЛЕГИ — без DefMark и внутренних групп.
    share_df = all_df[
        ["Порядок", "INN", "Список", "Приоритет", "Не_заменять"]
    ].copy()
    share_df["Комментарий"] = np.where(
        share_df["Не_заменять"].eq("ДА"),
        "Обязательный ИНН: вернуть результат даже при пустых/редких данных",
        "Резерв использовать только по порядку при технической необходимости",
    )

    # Служебный файл — полный audit.
    audit_df = all_df[
        [
            "Порядок",
            "INN",
            "Список",
            "Приоритет",
            "Не_заменять",
            "Группа",
            "Группа_code",
            TARGET,
            "Consensus_rank",
            "Rank_spread",
            "Dataset_row_index",
            "Working_position",
        ]
    ].copy()

    summary = (
        audit_df.groupby(["Список", "Группа"], as_index=False)
        .size()
        .rename(columns={"size": "Число компаний"})
    )

    instruction_rows = [
        ["Цель", "Пилотная выгрузка новых исходных данных СПАРК для проверки нового информационного сигнала."],
        ["Основной список", "10 000 ИНН. Обработать в первую очередь."],
        ["Резерв", "5 000 ИНН. Использовать только при технической невозможности выгрузить часть основного списка или для расширения пилота."],
        ["Важно", "Не исключать компанию из-за малого количества данных. Пустота/пропуски сами могут быть диагностическим сигналом."],
        ["Обязательные строки", "Строки с 'Не_заменять = ДА' необходимо попытаться выгрузить в любом случае и вернуть статус, даже если сведений нет."],
        ["Что вернуть", "Желательно сохранить INN, дату/дату среза, все запрошенные исходные поля и явный статус: найден / не найден / данные отсутствуют / ошибка выгрузки."],
        ["Время", "Для модельного эксперимента особенно ценны исторические значения, доступные на дату оценки компании. Текущий snapshot используется только как разведка данных."],
        ["Не использовать", "Этот пилот целенаправленный и НЕ является репрезентативной выборкой для оценки общего Gini/Recall на популяции."],
    ]
    instructions = pd.DataFrame(instruction_rows, columns=["Пункт", "Описание"])

    print("Этап 6/6. Записываю Excel...")

    def write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
        with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
            workbook = writer.book

            fmt_header = workbook.add_format(
                {
                    "bold": True,
                    "font_color": "white",
                    "bg_color": "#1F4E78",
                    "border": 1,
                    "align": "center",
                    "valign": "vcenter",
                    "text_wrap": True,
                }
            )
            fmt_text = workbook.add_format({"num_format": "@", "valign": "top"})
            fmt_wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
            fmt_note = workbook.add_format(
                {
                    "text_wrap": True,
                    "valign": "top",
                    "bg_color": "#FFF2CC",
                }
            )
            fmt_decimal = workbook.add_format({"num_format": "0.0000"})

            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                ws = writer.sheets[sheet_name]

                ws.freeze_panes(1, 0)
                ws.autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))

                for col_idx, col_name in enumerate(df.columns):
                    ws.write(0, col_idx, col_name, fmt_header)

                # Разумные ширины.
                for col_idx, col_name in enumerate(df.columns):
                    sample = df[col_name].astype(str).head(500)
                    width = min(
                        max(len(str(col_name)) + 2, int(sample.str.len().quantile(0.95)) + 2),
                        48,
                    )
                    if col_name == "INN":
                        width = 16
                        ws.set_column(col_idx, col_idx, width, fmt_text)
                    elif col_name in {"Описание", "Комментарий"}:
                        width = 55
                        ws.set_column(col_idx, col_idx, width, fmt_wrap)
                    elif col_name in {"Consensus_rank", "Rank_spread"}:
                        ws.set_column(col_idx, col_idx, 16, fmt_decimal)
                    else:
                        ws.set_column(col_idx, col_idx, max(width, 11))

                if sheet_name == "Инструкция":
                    ws.set_column(0, 0, 22)
                    ws.set_column(1, 1, 85, fmt_wrap)
                    ws.set_row(0, 30)
                    for r in range(1, len(df) + 1):
                        if df.iloc[r - 1, 0] in {"Важно", "Не использовать"}:
                            ws.set_row(r, 45, fmt_note)
                        else:
                            ws.set_row(r, 36, fmt_wrap)

                if sheet_name == "ИНН_для_СПАРК":
                    # Визуально отделяем резерв.
                    reserve_start = int((df["Список"] == "Основной").sum()) + 1
                    if reserve_start <= len(df):
                        ws.set_row(reserve_start, None, workbook.add_format({"top": 2}))
                    ws.conditional_format(
                        1,
                        4,
                        len(df),
                        4,
                        {
                            "type": "text",
                            "criteria": "containing",
                            "value": "ДА",
                            "format": workbook.add_format({"bg_color": "#FCE4D6", "bold": True}),
                        },
                    )

    write_workbook(
        share_path,
        {
            "Инструкция": instructions,
            "ИНН_для_СПАРК": share_df,
        },
    )

    write_workbook(
        audit_path,
        {
            "Сводка": summary,
            "Служебный_список": audit_df,
        },
    )

    # Итоговые проверки.
    if not share_path.exists() or share_path.stat().st_size == 0:
        raise RuntimeError("Файл для коллеги не создан.")
    if not audit_path.exists() or audit_path.stat().st_size == 0:
        raise RuntimeError("Служебный файл не создан.")

    print()
    print("ГОТОВО")
    print("-" * 72)
    print("Основной список:", len(main_df))
    print("Резерв:", len(reserve_df))
    print("Blind spot в основном списке:", int((main_df["Группа_code"] == "blind_spot").sum()))
    print("Файл для коллеги:")
    print(share_path)
    print("Служебный файл:")
    print(audit_path)
    print()
    print("Коллеге отправляй именно файл: СПАРК_ИНН_пилот_для_коллеги_V1.xlsx")


if __name__ == "__main__":
    main()
