# Контекст проекта

## Статус документа

Актуальная точка входа в проект. Обновляется после завершения значимого исследовательского этапа, изменения требований заказчика или смены source of truth.

Дата фиксации: **2026-09-04**.

---

## 1. Проект

**Заказчик:** ООО «Комус».

**Задача:** исследовать современные DS/ML/AI-подходы для прогнозирования дефолта коммерческих организаций РФ на горизонте 1 года и постепенно превратить проверенную исследовательскую логику в воспроизводимый инструмент сравнения моделей, признаков и бизнес-сценариев.

Главный принцип проекта: не максимизировать одну метрику любой ценой, а строить защищаемую цепочку доказательств:

`исследовательский вопрос → контролируемый эксперимент → факты → интерпретация → ограничения → следующий вопрос`.

---

## 2. Source of truth и рабочая среда

Основная среда:

- VS Code;
- Git + GitHub;
- `uv`;
- Python **3.12.2**;
- локальная `.venv`;
- Jupyter в VS Code.

Рабочий репозиторий:

`komus-research/komus-credit-risk`

Рабочая ветка:

`main`

Локальная рабочая папка:

`D:\Projects\komus-work`

`AIUniverstorage/commus` — репозиторий Института / integration point, а не ежедневный research source of truth. Перед локальным изменением проверяются фактические branch/HEAD/status. При расхождении текущий repo, notebooks и accepted artifacts имеют приоритет над stale docs, старыми чатами и памятью.

Colab остаётся дополнительной средой, но не source of truth текущего кода.

Python 3.10 из исходного ТЗ не отменён: он остаётся отдельным **delivery compatibility gate** перед поставкой. Docker также откладывается до стабилизации ML-core/runtime contracts.

---

## 3. Данные

Основной исторический dataset:

`Data_final.xlsb`

SHA-256:

`fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930`

Зафиксированная структура:

- строк: **362 018**;
- столбцов: **51**;
- identifier: `INN`;
- target: `DefMark`;
- исходных модельных признаков: **49**;
- доля дефолтов: около **9.7%**.

Текущий working/final split:

- working sample: **289 614** строк;
- final test: **72 404** строки;
- split: **80/20**;
- seed: **42**.

В dataset нет достоверной row-level даты наблюдения, поэтому random split/CV/OOF не доказывают temporal stability.

Final test не используется для выбора модели, признаков, параметров, balancing, threshold, calibration или feature engineering.

---

## 4. Historical baseline

Frozen notebook:

`notebooks/baseline/06_Сравнение_моделей_на_датасете_заказчика_v5_3_3_AI_анализ_одна_кнопка.ipynb`

SHA-256:

`cd51d78c82f386b61d1380529b710e4c0d9eaf1c148b58523b2f2741dc0a1523`

Historical результаты:

- CatBoost: Gini ≈ **0.9236**;
- XGBoost: Gini ≈ **0.9232**;
- LightGBM: Gini ≈ **0.9228**;
- после Optuna XGBoost ≈ **0.9244**.

Историческая абляция:

- все 49 признаков: Gini ≈ **0.9244**;
- без `Q_B1_norm`: ≈ **0.9183**;
- без `Q_B2_norm`: ≈ **0.9172**;
- без обоих: ≈ **0.8070**.

`0.8070` — диагностическая абляция старой схемы, а не новый baseline.

---

## 5. Ограничение `Q_B1_norm` / `Q_B2_norm`

`Q_B1_norm` — ИФР СПАРК.

`Q_B2_norm` — ИДО СПАРК.

По подтверждённым требованиям заказчика оба индекса:

- были доступны до дефолта и поэтому сами по себе не объявляются temporal leakage;
- могут использоваться как reference/diagnostic signal;
- **запрещены в финальной рабочей модели**, поскольку это внешние закрытые индексы.

Цель текущей исследовательской цепочки — понять, какую часть их сигнала можно объяснить/воспроизвести прозрачными доступными факторами и где остаётся информационный gap.

---

## 6. Текущая исследовательская цепочка

Подробный реестр доказательств каждого Stage хранится в:

`docs/RESEARCH_RECORD.md`

Компактные результаты — в:

`reports/summary/`

### Stage 1 — новый baseline без `Q_B1_norm/Q_B2_norm` — ЗАВЕРШЁН

Notebook:

`notebooks/01_Новый_baseline_без_Q_B1_Q_B2_V2.ipynb`

Протокол:

- 47 разрешённых признаков;
- 3-fold `StratifiedKFold`;
- seed 42;
- без Optuna, class weights, calibration и threshold optimization;
- early stopping только на внутренней validation-части train-фолда с последующим refit;
- final test закрыт.

OOF:

- XGBoost: Gini **0.8040**, PR-AUC **0.5993**;
- CatBoost: Gini **0.8038**, PR-AUC **0.6010**;
- LightGBM: Gini **0.8034**, PR-AUC **0.5978**.

Вывод: подтверждённый baseline без закрытых индексов — **Gini ≈ 0.804**. Абсолютный победитель среди трёх GBDT не объявляется.

Summary:

`reports/summary/stage1_baseline_summary_V2.json`

Файл summary восстановлен ретроспективно 2026-08-20 из сохранённых notebook outputs без повторного запуска вычислений.

### Stage 2 — Explainability разрешённых признаков — ЗАВЕРШЁН

Notebook:

`notebooks/02_Explainability_допустимых_признаков_V1.ipynb`

Ключевые факты:

- final test не использован;
- global SHAP и permutation importance рассчитаны на внешних validation-подвыборках;
- consensus top-10: `Q_D6_norm`, `Q_A5_norm`, `Q_B3_norm`, `Q_C1_norm`, `G1_norm`, `Q_D4_norm`, `D5_norm`, `A4_norm`, `C4_norm`, `Q_A4_norm`;
- минимальная межмодельная корреляция рангов SHAP: **0.974**;
- минимальная межмодельная корреляция permutation importance: **0.899**;
- пересечение consensus top-15 с historical top-15: **13/15**.

Вывод: три GBDT опираются на очень похожее ядро разрешённых факторов. Это модельная устойчивость интерпретации, а не причинность.

Summary:

`reports/summary/stage2_explainability_summary_V1.json`

Summary восстановлен ретроспективно 2026-08-20 из сохранённых outputs.

### Stage 3 — анализ ошибок и общей слепой зоны — ЗАВЕРШЁН

Notebook:

`notebooks/03_Анализ_ошибок_и_потерянного_сигнала_V1.ipynb`

Ключевые факты:

- всего дефолтов в working sample: **28 015**;
- глубоко пропущенных дефолтов: **1 278** (**4.6%** дефолтов);
- общая слепая зона: **805** объектов;
- это **63.0%** глубоко пропущенных дефолтов;
- сильное межмодельное расхождение среди глубоко пропущенных: только **1.9%**;
- захват дефолтов consensus ranking: top-10% = **57.2%**, top-20% = **77.8%**, top-30% = **87.4%**.

Stage 3 OOF checkpoint SHA-256:

`faa53a8aed86c2d445699c0fd1df6a5b83711c96d3a300f9a8860112ff4473ac`

Вывод: значительная часть тяжёлых ошибок общая для всех трёх GBDT, что сильнее указывает на информационный gap, чем на проблему одного алгоритма.

Summary:

`reports/summary/stage3_error_analysis_summary_V1.json`

Summary восстановлен ретроспективно 2026-08-20 из сохранённых outputs.

### Stage 4 V2 — диагностика закрытых `Q_B1/Q_B2` — ЗАВЕРШЁН И ПРИНЯТ

Notebook:

`notebooks/04_Диагностика_потерянного_сигнала_Q_B1_Q_B2_V2.ipynb`

Summary:

`reports/summary/stage4_closed_signal_summary_V2.json`

Ключевые факты:

- standalone Gini `Q_B1_norm`: **0.8044**;
- standalone Gini `Q_B2_norm`: **0.6768**;
- `Q_B1/Q_B2` Pearson ≈ **0.8266**;
- `Q_B2_norm` лучше видит именно Stage 3 blind spot, несмотря на более слабую standalone-ранжировку;
- ROC-AUC blind spot vs non-default: `Q_B1` ≈ **0.6973**, `Q_B2` ≈ **0.7234**;
- при fixed capacity 30% expected rescue: `Q_B1` ≈ **53.75%**, `Q_B2` ≈ **59.43%**;
- final test не использован.

Интерпретация: `Q_B1` сильнее как общий risk score, а `Q_B2` интереснее как diagnostic target для общей слепой зоны. Именно поэтому Stage 5 исследует proxy `Q_B2`.

### Stage 5 V1 — аудит proxy-сигнала `Q_B2` — ЗАВЕРШЁН И ПРИНЯТ

Notebook:

`notebooks/05_Аудит_proxy-сигнала_Q_B2_разрешёнными_признаками_V1.ipynb`

Summary:

`reports/summary/stage5_qb2_proxy_audit_summary_V1.json`

Формальный статус summary:

`completed_accepted`

Подтверждённые факты:

- working rows: **289 614**;
- blind spot: **805**;
- OOF Spearman восстановления `Q_B2`: ≈ **0.5421**;
- Spearman внутри blind spot: ≈ **0.0242**;
- oracle `Q_B2` blind-spot AUC: ≈ **0.7234**;
- proxy blind-spot AUC: ≈ **0.3981**;
- gap AUC: ≈ **0.3253**;
- rescue при capacity 30%: oracle `Q_B2` ≈ **59.43%**, proxy ≈ **10.43%**.

Решение: Stage 5 V1 принят с `decision_class = material_missing_signal`. Текущие 47 признаков частично отражают общий сигнал `Q_B2`, но не воспроизводят существенную часть сигнала, полезную именно для общей Stage 3 blind spot. Это поддерживает наличие material information gap; причинность и гарантированный эффект внешних данных не утверждаются.

---

## 7. Stage 6–11: модельная проверка на текущих 47 признаках

Все Stages использовали locked 47-feature protocol; final test не использовался.

- Stage 6 V4: TabM standalone, OOF Gini **0.781310** — inferior.
- Stage 7 V1: TabM stacking, GBDT_mean **0.806399**, hybrid **0.804260** — `no_material_benefit`.
- Stage 8 V1: FT-Transformer, OOF Gini **0.801528**, Δ **-0.004871** к GBDT_mean — `no_material_benefit`.
- Stage 9 V1: rank complementarity при capacity 30% — FT rescue **9/805**, GBDT_mean **0/805**; прирост ниже material threshold.
- Stage 10 V1: oracle/residual reserve — **15/805**, Δ **+1.863 п.п.**, effective union capacity **37.446%** — `limited_residual_model_reserve`.
- Stage 11 V1: RealMLP, OOF Gini **0.793325** против **0.806399** у GBDT_mean, Δ **-0.013074**; отрицательная разница на **3/3** folds — `inferior`.

Решение: `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`. Architecture search без нового информационного основания на текущих 47 признаках остановлен: его ожидаемый information gain низок. Evidence сильнее поддерживает information/feature limitation, чем дефицит проверенных architectures. Это не доказывает математический потолок Gini, невозможность лучшей модели в будущем или temporal stability.

---

## 8. Stage 12 V1 — принятый Research Synthesis Stage 1–11

Stage 12 V1 имеет статус `completed_accepted`. Он завершает текущую model-research
chain Stages 1–12 на 47 разрешённых признаках без `Q_B1_norm` / `Q_B2_norm`.

Synthesis подтверждает сильный baseline без закрытых индексов, common blind spot
**805** и вывод Stage 5 `material_missing_signal`. TabM, stacking, FT-Transformer,
rank complementarity, oracle/residual reserve и RealMLP не дали evidence, что ещё
одна architecture на неизменном feature contract решает основное ограничение.

Статус: `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`. Ожидаемый information
gain ещё одной architecture на тех же 47 признаках низок. Это не означает завершения
проекта, доказанного математического Gini ceiling, temporal stability или невозможности
будущего улучшения.

Следующий приоритет: data research — новые валидные признаки, СПАРК-пилот, динамика,
связи и row-level temporal anchor при его появлении — плюс presentation / defence
evidence. Reopen conditions остаются: новый валидный feature source; row-level
temporal anchor; сильный независимый противоречащий результат; новый business
operating point; новая научная гипотеза, реально меняющая решение.

---

## 9. Research evidence и будущая презентация

С 2026-08-20 введён отдельный контракт:

`docs/RESEARCH_RECORD.md`

Для каждого значимого Stage сохраняются:

- notebook;
- небольшой `reports/summary/*.json`;
- data/split/feature identity;
- ключевые числа;
- FACTS / INTERPRETATION / LIMITATIONS / NEXT STEP;
- ссылка на локальные тяжёлые артефакты и их hash при необходимости.

Это обязательный материал для будущего итогового отчёта и презентации. Итоговая защита должна собираться из проверенных артефактов, а не из памяти, старых чатов или stale outputs.

---

## 10. CPU, explainability и business policy

CPU — first-class критерий.

Ориентиры заказчика:

- обучение модели: не более **8 часов**;
- prediction одной компании: не более **2 минут**.

Explainability также обязательна. SHAP/permutation importance объясняют поведение модели, а не причинное влияние на дефолт.

Модель выдаёт вероятность. Threshold, `C_FN/C_FP` и manual-review capacity являются отдельной business policy и не должны подмешиваться в training без отдельной гипотезы.

Заказчик связывает бизнес-ценность со снижением ПДЗ примерно **15% → 10%**, но подтверждённой формулы `ML metrics/errors → ПДЗ` пока нет, поэтому cost function не додумывается.

---

## 11. Роль LLM

Текущее решение: LLM не является кредитным predictor.

LLM используется как post-processing Result Interpreter для уже рассчитанных ML facts. В принятом Integration V1 selected-row path источником является structured `LocalExplanationEvidence`: готовая probability, SHAP facts, row/identifier provenance и optional trusted feature descriptions.

LLM:

- не пересчитывает probability;
- не пересчитывает SHAP;
- не выбирает threshold;
- не принимает решение «одобрить/отказать»;
- не трактует SHAP как причинность;
- не придумывает business meaning feature без trusted description.

Result Interpreter model-independent; provider подключается через `ResultInterpreterClient`. OpenAI является одной сменной реализацией, а не частью ML-core. Текущий OpenAI adapter использует configurable model и `store=False`; это не Zero Data Retention.

Ошибка или отсутствие LLM provider не должны делать prediction и Local SHAP недоступными.

### Product/Application Integration V1 — current accepted backend state

Принята цепочка:

`ExperimentArtifact → explicit final fit → ModelVersion → targetless inference → PredictionBatch → selected-row LocalExplanationEvidence → ResultInterpreterRequest → ResultInterpreterClient → ResultInterpreterResponse`.

Accepted:

- Stage I — Fitted Model Lifecycle;
- Stage II-A — Generic Model Inference V1;
- Stage II-B — CatBoost Local SHAP V1 как capability;
- Stage III-A — model-independent Result Interpreter Core V1;
- Stage III-B — modular OpenAI adapter с `store=False`.

Architect Lock для Stage III-C принят.

**Stage III-C1 / LOCAL MODEL USE FLOW — ACCEPTED.**

Реализован и принят Reviewer flow:

`Result → explicit save ModelVersion → targetless file → PredictionBatch → select row → LocalExplanationEvidence`.

Подтверждено:

- новый верхнеуровневый экран не создавался; после Universal Pipeline UX V1 flow: `Данные → Признаки → Алгоритм → Проверка качества → Результат`;
- локальное применение модели находится на экране `Результат`;
- frontend работает через `IntegrationWorkflowService` и capability contract;
- ModelVersion создаётся explicit action;
- inference schema динамически берётся из сохранённого ModelVersion;
- local explainer подключён registry/capability-механизмом;
- CatBoost Local SHAP работает через accepted backend;
- unsupported explainer не блокирует prediction;
- stale inference source invalidation закрыта: новый source очищает старый batch/row/evidence, но сохраняет active ModelVersion.

Принятый Stage III-C1 commit: `ec9f397e7ea30ba509283e095acc74b0a4c4352a`.

**Manual III-C1 E2E — PASS.**

Ручной пользовательский прогон подтвердил:

- final fit/save CatBoost ModelVersion;
- targetless inference;
- duplicate identifiers через отдельный `row_id`;
- selected-row Local SHAP;
- source A → B invalidation;
- fail-closed несовместимого файла без потери active ModelVersion.

Во время E2E найден и закрыт UTF-8 BOM defect физического header reader: commit `c009f3bd8bd94c23e13cf3ebf0db1be5c4c4c6e0`.

**Universal Pipeline UX V1 — ACCEPTED.**

Generic UI не содержит special-case правил для `Q_B1_norm`, `Q_B2_norm`, `INN`, `DefMark`; historical semantics остаются только внутри frozen compatibility profile. Пользовательский flow и терминология приведены к:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`.

Принятый UX commit: `492b6dc6`.
Текущая local verification evidence: 52 focused UX tests PASS, 229 full tests PASS, `compileall src app` PASS, `git diff --check` PASS.

**Следующий шаг — Stage III-C2.**

`LocalExplanationEvidence → external-data policy/redaction → ResultInterpreter → provider adapter → explanation`.

Для III-C2 default external policy — `DISABLED`; defense-ready режим — `REDACTED_V1`, без передачи identifier value, raw feature values и row identity.

---

## 12. Текущие открытые вопросы

1. Утверждённое отношение/стоимость FN и FP.
2. Допустимые локальные LLM и отдельное разрешение/data-sharing/redaction policy для передачи реальных client identifiers/feature values во внешний LLM API.
3. В сообщении заказчика упоминаются «7 внешних признаков 100% дефолта», но подтверждено только 6 внешних факторов; седьмой не додумывать.
4. Temporal validation для текущего `Data_final` невозможна без дополнительной исторической структуры.
5. Формальная связь ошибок/threshold-сценариев с целью ПДЗ `15% → 10%`.
6. Какие валидные новые источники информации и признаки доступны для data research (включая СПАРК-пилот, связи и динамику).

---

## 13. Reopen conditions для model research

Model research может быть открыт повторно только при одном из условий:

1. новый валидный feature source;
2. row-level temporal anchor;
3. сильный независимый противоречащий результат;
4. новый business operating point;
5. новая научная гипотеза, реально меняющая решение.

Новый model shortlist ради количества не создаётся.

---

## 14. Приоритет источников

При расхождении:

1. текущая явная инструкция пользователя;
2. свежие подтверждённые требования заказчика;
3. актуальное ТЗ;
4. текущий GitHub-репозиторий и фактические файлы;
5. проверенные experiment artifacts / summaries;
6. архитектурные документы;
7. предыдущие чаты и summaries только как контекст.

Historical baseline не переписывается задним числом. Новый вывод оформляется новым Stage/версией и новым артефактом.

---

## 15. Current model-research state after Stage 13 V1

Stages 1–12 остаются accepted. Stage 13 TabFM V1 технически подтвердил locked SAFE-RUN: dataset/checkpoint guards, model load, real inference preflight и эквивалентность single-call/chunked inference (`max_abs_diff = 0`, tolerance `<= 1e-5`). Полный OOF не выполнялся, final test не использовался, а TabFM OOF metrics отсутствуют.

Статус: `STOPPED_BY_COMPUTE_COST`. На текущем CPU full OOF операционно непропорционален ожидаемому information gain; это не quality verdict TabFM. Воспроизводимая подготовка доступна через `scripts/prepare_stage13_tabfm.ps1`; helper не загружает модель и не запускает SAFE-RUN или OOF.

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` сохраняется для обычного architecture/model-zoo search. TabPFN-3 Stage 14 candidate имеет статус `TABPFN3_STAGE14_REJECTED_BY_CPU_CONSTRAINT`: его locked large-context experiment требовал GPU/H100, что несовместимо с primary CPU-only research path; subsampling/context reduction меняет hypothesis, а GPU fallback запрещён. TabPFN-3 не запускался, OOF не выполнялся, quality `UNKNOWN` (не `inferior` и не `no_material_benefit`), final test не использовался. Его tracked notebook и requirements — historical rejected pre-run artifacts, не active implementation и не рекомендуются к запуску.

Stage 14 xRFM V1 **был разрешён** как narrow controlled reopen с frozen CPU-only lock для проверки iterative kernel / metric feature learning + supervised recursive localization на неизменном 47-feature contract. Впоследствии он закрыт D-053 по `HARDWARE_CONSTRAINT`; этот pre-run plan больше не является current active state. Active default снова `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`; reopening возможен только по принятым evidence/hypothesis conditions. Data research, presentation и defence evidence остаются открытыми направлениями.

### Stage 14 xRFM V1 — hardware closeout

Environment PASS и pre-run implementation ACCEPT, но первый разрешённый Smoke остановлен hardware guard до `model.fit()`: фактически 6 physical cores, 15.34 GiB RAM и 4.14 GiB available RAM против contract 8 cores, 32 GiB RAM и 16 GiB available перед feasibility. Статус `STOPPED_BY_COMPUTE_COST / HARDWARE_CONSTRAINT`; training/prediction/OOF отсутствуют, quality `UNKNOWN`, final test unused. Это не mathematical ceiling и не evidence качества xRFM. Ordinary model-only search на 47 признаках снова остановлен; reopening возможен только по принятым evidence/hypothesis conditions.
