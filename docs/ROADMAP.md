# Дорожная карта

## Статус

Этапы выполняются отдельными контролируемыми блоками. Наличие пункта в roadmap не означает, что его нужно реализовывать заранее.

Перед крупным изменением проверяются branch/HEAD/status, данные и affected artifacts. Исследовательский Stage закрывается только после review результата и сохранения evidence package по правилам `docs/RESEARCH_RECORD.md`.

Дата актуализации: **2026-08-20**.

---

## 0. Фундамент репозитория — ЗАВЕРШЁН

Создан и проверен рабочий контур:

- private GitHub repository `alekseeva943-cloud/komus-credit-risk`;
- VS Code + Git + GitHub;
- Python 3.12.2 + `uv` + `.venv` + Jupyter;
- historical notebook №06 сохранён как frozen baseline;
- `Data_final.xlsb` хранится локально вне Git и идентифицируется SHA-256;
- Git не хранит raw/customer data, secrets и тяжёлые временные artifacts;
- Python 3.10 сохранён как будущий delivery compatibility gate;
- Docker отложен до стабилизации ML-core/runtime.

### Критерий завершения

Проект можно открыть локально, однозначно определить environment/repository state и воспроизвести исследовательский путь без зависимости от Colab как source of truth.

Критерий выполнен.

---

## 1. Новый baseline без `Q_B1_norm` и `Q_B2_norm` — ЗАВЕРШЁН

### Вопрос

Какой честный уровень качества дают CatBoost, XGBoost и LightGBM после полного исключения двух закрытых индексов при одинаковом evaluation protocol?

### Протокол

Не менялись:

- dataset identity;
- 47 разрешённых признаков;
- working/final split 80/20;
- 3-fold StratifiedKFold;
- seed 42;
- preprocessing/evaluation level.

Не использовались:

- Optuna;
- class weights;
- calibration;
- threshold optimization;
- final test для model selection.

### Фактический результат Stage 1 V2

- XGBoost: Gini **0.8040**, PR-AUC **0.5993**;
- CatBoost: Gini **0.8038**, PR-AUC **0.6010**;
- LightGBM: Gini **0.8034**, PR-AUC **0.5978**.

Различия меньше межфолдового разброса; абсолютный победитель не объявляется.

Принятый baseline: **Gini ≈ 0.804**.

### Evidence

- notebook: `notebooks/01_Новый_baseline_без_Q_B1_Q_B2_V2.ipynb`;
- summary: `reports/summary/stage1_baseline_summary_V2.json`.

Summary backfilled 2026-08-20 из сохранённых outputs без rerun.

---

## 2. Explainability допустимых признаков — ЗАВЕРШЁН

### Вопрос

Какие из 47 разрешённых признаков стабильно формируют прогноз и насколько эта картина согласуется между CatBoost, XGBoost и LightGBM?

### Фактический результат Stage 2 V1

Consensus top-10:

`Q_D6_norm, Q_A5_norm, Q_B3_norm, Q_C1_norm, G1_norm, Q_D4_norm, D5_norm, A4_norm, C4_norm, Q_A4_norm`

- minimum intermodel SHAP rank correlation: **0.974**;
- minimum intermodel permutation rank correlation: **0.899**;
- historical top-15 overlap: **13/15**.

### Вывод

Три GBDT опираются на почти одно и то же ядро признаков. Это повышает уверенность в устойчивости модельной интерпретации, но не доказывает причинность и не означает, что закрытый сигнал полностью восстановлен.

### Evidence

- notebook: `notebooks/02_Explainability_допустимых_признаков_V1.ipynb`;
- summary: `reports/summary/stage2_explainability_summary_V1.json`.

Summary backfilled 2026-08-20 из сохранённых outputs без rerun.

---

## 3. Анализ ошибок и общей слепой зоны — ЗАВЕРШЁН

### Вопрос

Есть ли у трёх baseline-моделей общая группа тяжёлых OOF-ошибок, указывающая на информационный gap, а не на проблему одного алгоритма?

### Фактический результат Stage 3 V1

- working defaults: **28 015**;
- глубоко пропущенные дефолты: **1 278** (**4.6%** дефолтов);
- общая blind spot: **805** объектов;
- blind spot = **63.0%** глубоко пропущенных дефолтов;
- сильное межмодельное расхождение среди глубоко пропущенных: **1.9%**;
- capture дефолтов consensus ranking: top-10% **57.2%**, top-20% **77.8%**, top-30% **87.4%**.

### Вывод

Большая доля общей blind spot и малое межмодельное расхождение сильнее поддерживают гипотезу о недостающем информационном слое, чем гипотезу «нужен другой GBDT».

### Evidence

- notebook: `notebooks/03_Анализ_ошибок_и_потерянного_сигнала_V1.ipynb`;
- summary: `reports/summary/stage3_error_analysis_summary_V1.json`;
- OOF checkpoint SHA-256: `faa53a8aed86c2d445699c0fd1df6a5b83711c96d3a300f9a8860112ff4473ac`.

Summary backfilled 2026-08-20 из сохранённых outputs без rerun.

---

## 4. Диагностика закрытых `Q_B1_norm` / `Q_B2_norm` — ЗАВЕРШЁН И ПРИНЯТ (V2)

### Вопрос

Какой из двух закрытых reference-индексов лучше объясняет общую blind spot при контролируемой ёмкости risk-zone?

### Фактический результат Stage 4 V2

- standalone Gini `Q_B1_norm`: **0.8044**;
- standalone Gini `Q_B2_norm`: **0.6768**;
- Pearson `Q_B1/Q_B2`: **0.8266**;
- blind spot vs non-default ROC-AUC: `Q_B1` **0.6973**, `Q_B2` **0.7234**;
- fixed-capacity rescue при 30%: `Q_B1` **53.75%**, `Q_B2` **59.43%**.

### Вывод

`Q_B1_norm` сильнее как общий standalone risk predictor, но `Q_B2_norm` лучше видит именно Stage 3 blind spot. Поэтому следующий вопрос — можно ли воспроизвести именно `Q_B2` прозрачными разрешёнными признаками.

### Evidence

- notebook: `notebooks/04_Диагностика_потерянного_сигнала_Q_B1_Q_B2_V2.ipynb`;
- summary: `reports/summary/stage4_closed_signal_summary_V2.json`.

Final test не использован.

---

## 5. Аудит proxy-сигнала `Q_B2` разрешёнными признаками — ЗАВЕРШЁН И ПРИНЯТ (V1)

### Вопрос

Какую часть диагностического сигнала `Q_B2_norm` можно восстановить только из 47 разрешённых признаков и остаётся ли material information gap именно в blind spot?

### Контролируемый эксперимент

Не меняются:

- dataset;
- working/final partition;
- 47 разрешённых признаков;
- Stage 3 OOF checkpoint;
- blind spot definition;
- final test остаётся закрытым.

`Q_B2_norm` используется только как diagnostic target/reference, не production feature.

Один фиксированный CatBoost surrogate обучается OOF восстанавливать порядковый risk-level `Q_B2`.

### Сохранённые результаты Stage 5 V1

- OOF Spearman reconstruction: **0.5421**;
- Spearman внутри blind spot: **0.0242**;
- oracle `Q_B2` blind AUC: **0.7234**;
- proxy blind AUC: **0.3981**;
- AUC gap: **0.3253**;
- rescue at 30% capacity: oracle **59.43%**, proxy **10.43%**.

### Решение

Stage 5 V1 имеет статус `completed_accepted`; `decision_class = material_missing_signal`.

Текущие 47 разрешённых признаков частично воспроизводят общий `Q_B2` signal, но не воспроизводят существенную часть сигнала, полезную именно для Stage 3 blind spot. Это поддерживает наличие material information gap. Причинность, гарантированный рост Gini от внешних данных и выбор конкретного источника не утверждаются.

### Evidence

- notebook: `notebooks/05_Аудит_proxy-сигнала_Q_B2_разрешёнными_признаками_V1.ipynb`;
- summary: `reports/summary/stage5_qb2_proxy_audit_summary_V1.json`.

---

## 6. Новый внешний feature block для blind spot — БУДУЩЕЕ НАПРАВЛЕНИЕ; STAGE 6 НЕ НАЧАТ

### Предварительный исследовательский вопрос

Какой **один** новый прозрачный внешний feature block способен добавить информацию, которой нет в текущих 47 признаках, и улучшить ранжирование/coverage общей blind spot без использования закрытых `Q_B1/Q_B2`?

### Приоритет направления

На основании Stage 5 текущий приоритет — внешние сигналы должной осмотрительности / негативных событий, которые доступны до даты оценки и имеют проверяемый provenance.

Конкретный блок ещё не выбран; его выбор и проектирование отдельного Stage 6 не выполнены.

### Правило

Одна связанная группа новых признаков → один controlled experiment → сравнение с baseline/OOF blind-spot diagnostics при неизменном split/CV/seed.

Final test остаётся закрытым.

---

## 7. Современные CPU-подходы — ПЛАНИРУЕТСЯ

После проработки информационного gap исследуется минимум один содержательно иной CPU-подход относительно GBDT.

Перед реализацией проводится актуальный research по первичным источникам и фиксируется:

- гипотеза;
- отличие от GBDT;
- CPU feasibility;
- explainability;
- контролируемый evaluation protocol.

Не создаётся длинный leaderboard ради количества моделей.

---

## 8. Stability и controlled tuning — ПЛАНИРУЕТСЯ

Только после определения сильного feature/model candidate:

- seed stability;
- bootstrap;
- ограниченный parameter search/Optuna;
- calibration;
- class weights только под отдельную гипотезу.

Tuning не используется как бесконечный способ добывать тысячные без исследовательского смысла.

---

## 9. Business Policy Engine — ПЛАНИРУЕТСЯ

Модель выдаёт probability, а business policy применяется отдельно:

- manual threshold;
- `C_FN/C_FP` или ratio;
- manual review capacity;
- review minutes per company;
- FP/FN/Recall/Precision/cost/human-hours scenarios.

Цель ПДЗ `15% → 10%` не превращается в выдуманную cost function без подтверждения заказчика.

---

## 10. `ExperimentRunner` и reusable ML-core — ПЛАНИРУЕТСЯ ПО МЕРЕ ПОЯВЛЕНИЯ СТАБИЛЬНОЙ ПОВТОРЯЕМОЙ ЛОГИКИ

Постепенно выносятся:

- dataset validation/hash;
- feature registry;
- model registry;
- CV/OOF;
- metrics;
- runtime;
- artifact contract;
- explainability;
- experiment signature.

Notebook остаётся research narrative.

---

## 11. Backend / frontend / LLM Result Interpreter — ПОСЛЕ СТАБИЛИЗАЦИИ EXPERIMENT CORE

Направление:

`notebooks → reusable ML/data logic → ExperimentRunner → backend → frontend`

LLM остаётся post-processing interpreter и не принимает кредитное решение.

---

## 12. Итоговый отчёт и презентация — СОБИРАЮТСЯ ИЗ RESEARCH EVIDENCE

Подготовка защиты не должна требовать заново восстанавливать историю экспериментов.

Источник:

- `docs/RESEARCH_RECORD.md`;
- `reports/summary/`;
- актуальные domain docs;
- выбранные проверенные графики/таблицы из notebooks.

Ближе к защите создаётся отдельный небольшой каталог финальных иллюстраций, а не коммитится весь `reports/generated/`.

---

## Универсальный критерий закрытия следующего Stage

Stage считается закрытым, когда:

1. research question сформулирован заранее;
2. controlled experiment выполнен;
3. result проверен;
4. final test gate не нарушен;
5. есть FACTS / INTERPRETATION / LIMITATIONS / NEXT STEP;
6. notebook и summary согласованы;
7. сохранены необходимые hashes/metadata;
8. обновлены только реально затронутые project docs;
9. Git diff проверен;
10. только после этого начинается следующий research question.
