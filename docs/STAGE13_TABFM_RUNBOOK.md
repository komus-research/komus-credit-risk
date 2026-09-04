# Stage 13 V1 — воспроизведение TabFM SAFE-RUN

## Что воспроизводится

Воспроизводится только technical SAFE-RUN locked TabFM path. Полный 3-fold OOF не воспроизводится и не запускается автоматически.

## Быстрый старт

Из корня проекта выполните:

```powershell
.\scripts\prepare_stage13_tabfm.ps1
```

Для запуска без интерактивных вопросов:

```powershell
.\scripts\prepare_stage13_tabfm.ps1 -NonInteractive
```

Helper предлагает или принимает runtime directory и HF cache, проверяет Python 3.11 и locked dependencies, регистрирует Jupyter kernel. При необходимости можно явно передать `-RuntimeDir`, `-HfCacheDir` и `-PythonExe`.

После успешной подготовки откройте `notebooks/13_Сравнение_TabFM_с_GBDT_baseline_V1.ipynb`, выберите kernel `KOMUS Stage 13 TabFM (Python 3.11)`, оставьте `RUN_FULL_OOF=False`, затем выполните Restart Kernel → Run All.

Helper не загружает модель, не запускает SAFE-RUN и не выполняет OOF.

## Acceptance SAFE-RUN

Успешный SAFE-RUN подтверждает:

- SHA-256 dataset `Data_final.xlsb`;
- SHA-256 checkpoint;
- locked model load;
- real inference preflight;
- `max_abs_diff <= 1e-5` при single-call vs chunked inference;
- финальное сообщение о прохождении SAFE-RUN.

## Full OOF

Не устанавливайте `RUN_FULL_OOF=True` автоматически. Full OOF не выполнялся на текущем CPU KOMUS из-за compute cost; статус Stage 13 V1 — `STOPPED_BY_COMPUTE_COST`.

SAFE-RUN не является proxy качества. Он не даёт TabFM OOF Gini, PR-AUC, Recall или других OOF metrics и не доказывает, что TabFM хуже или лучше `GBDT_mean`. Final test не используется.

## Requirements и provenance

- Python `3.11`;
- locked requirements: `requirements-tabfm-v1.txt`;
- TabFM: Google Research, release `1.0.1`, commit `d8678b6895f1428a468d4cc299c1ff4cf704e726`;
- checkpoint: `google/tabfm-1.0.0-pytorch`, revision `77cb9cc1b4fd3a9c77fbb9552c218200bb4dab83`;
- checkpoint SHA-256: `928cb350becdc77cdb7a9e8c36deda88917bfd14a3091894a2dc516db58a2085`;
- checkpoint size: около `6.11 GiB`;
- validated device/dtype: CPU / `bfloat16`.

Observed operational evidence: исходная commit capacity около 32 GiB привела к native model-load failure; locked load прошёл на машине с примерно 15.3 GiB RAM и 40 GiB pagefile (total commit около 55.3 GiB). Это наблюдение проверенной Windows-среды, а не универсальное требование pagefile ровно 40 GiB.

## Boundaries

Не меняйте dataset, split, features, seeds, TabFM parameters, checkpoint, requirements, helper behavior, Python cells notebook или final-test policy. Не создавайте `reports/generated/stage13_tabfm_oof_V1.npz` либо `reports/generated/stage13_tabfm_results_V1.json`, пока реальный full OOF не выполнен и не принят отдельно.
