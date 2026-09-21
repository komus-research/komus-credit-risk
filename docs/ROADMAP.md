# Дорожная карта

## Статус

Этапы выполняются отдельными контролируемыми блоками. Наличие пункта в roadmap не означает, что его нужно реализовывать заранее.

Перед крупным изменением проверяются branch/HEAD/status, данные и affected artifacts. Исследовательский Stage закрывается только после review результата и сохранения evidence package по правилам `docs/RESEARCH_RECORD.md`.

Дата актуализации: **2026-09-04**.

---

## 0. Фундамент репозитория — ЗАВЕРШЁН

Создан и проверен рабочий контур:

- рабочий GitHub repository `komus-research/komus-credit-risk` на ветке `main`;
- локальная рабочая папка `D:\Projects\komus-work`;
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

`AIUniverstorage/commus` является repository Института / integration point, но не ежедневным research source of truth.

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

## 6. Stage 6–11: model-only research на текущих 47 признаках — ЗАВЕРШЁН

| Stage | Направление | Результат |
| --- | --- | --- |
| 6 V4 | TabM standalone | OOF Gini **0.781310**; inferior. |
| 7 V1 | TabM stacking | GBDT_mean **0.806399**, hybrid **0.804260**; `no_material_benefit`. |
| 8 V1 | FT-Transformer | Gini **0.801528**, Δ **-0.004871**; `no_material_benefit`. |
| 9 V1 | rank complementarity | FT rescue **9/805**, GBDT_mean **0/805** при 30%; ниже material threshold. |
| 10 V1 | oracle/residual reserve | **15/805**, Δ **+1.863 п.п.**, effective union capacity **37.446%**; `limited_residual_model_reserve`. |
| 11 V1 | RealMLP | Gini **0.793325** против **0.806399**, Δ **-0.013074**, проигрыш **3/3** folds; `inferior`. |

Final test не использовался. Числа берутся из accepted artifacts `reports/summary/` и `reports/generated/`.

Решение: `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`. Новый architecture search на неизменных 47 признаках не планируется: ожидаемый information gain низок. Это не является утверждением о завершении проекта, доказанном потолке Gini или невозможности более сильной модели при новых основаниях.

---

## 7. Research Synthesis Stage 1–11 (Stage 12 V1) — ЗАВЕРШЁН И ПРИНЯТ

Статус: `completed_accepted`.

Stage 12 V1 зафиксировал единый presentation-ready evidence package: итоговую
таблицу Stage 1–11, verified evidence/figures, FACT / INTERPRETATION / LIMITATION,
closed/blocked questions, reopen conditions и материалы для presentation / defence.
Он подтверждает `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`: на неизменных
47 признаках ожидаемый information gain ещё одной model architecture низок.

Это не означает, что проект завершён, что доказан математический потолок Gini или
что temporal stability подтверждена.

---

## 8. Data research — ОТКРЫТ И ЯВЛЯЕТСЯ СЛЕДУЮЩИМ ПРИОРИТЕТОМ

Следующий приоритет: новые валидные признаки, СПАРК-пилот, связи, динамика,
row-level temporal anchor при его появлении и presentation / defence evidence.
Новый feature block формулируется только как проверяемая гипотеза с provenance и
temporal admissibility; final test остаётся закрытым.

Model research может быть открыт повторно при новом валидном feature source, row-level temporal anchor, сильном независимом противоречащем результате, новом business operating point или новой научной гипотезе, реально меняющей решение. Новый model shortlist ради количества не добавляется.

---

## 9. Business Policy / delivery — ПОСЛЕ SYNTHESIS И ПРИ НАЛИЧИИ ОСНОВАНИЯ

Business policy, reusable ML-core, backend/frontend и LLM Result Interpreter развиваются только по подтверждённой потребности. LLM остаётся post-processing interpreter и не принимает кредитное решение.

---

## 10. Stage 13 V1 — TabFM — ЗАКРЫТ OPERATIONALLY

Статус: `STOPPED_BY_COMPUTE_COST`.

Locked TabFM SAFE-RUN технически принят: dataset/checkpoint guards, model load, real inference preflight и single-call/chunked equivalence прошли. Полный 3-fold OOF не запускался (`RUN_FULL_OOF=False`), поэтому quality question относительно `GBDT_mean` остаётся неразрешённым; final test не использовался и TabFM OOF metrics отсутствуют.

На текущем CPU full OOF не запускать: observed compute cost непропорционален information gain. Это не вывод о том, что TabFM хуже или лучше GBDT.

Evidence: `docs/STAGE13_TABFM_RUNBOOK.md` и `reports/summary/stage13_tabfm_summary_V1.json`.

---

## 11. TabPFN-3 Stage 14 candidate — REJECTED BEFORE RUN

Статус: `TABPFN3_STAGE14_REJECTED_BY_CPU_CONSTRAINT`.

Locked large-context TabPFN-3 contract требовал GPU/H100. Основной KOMUS research path CPU-only; GPU fallback запрещён, а subsampling или context reduction изменили бы проверяемую hypothesis. TabPFN-3 не запускался, OOF не выполнялся, quality `UNKNOWN`; это не `inferior` и не `no_material_benefit`, final test не использовался.

`notebooks/14_Сравнение_TabPFN3_с_GBDT_baseline_V1.ipynb` и `requirements-tabpfn3-v1.txt` остаются tracked historical rejected pre-run artifacts. Это не active Stage 14 implementation; запускать их не следует.

## 12. Stage 14 V1 — xRFM historical pre-run plan — superseded

Architect status `XRFM_V1_LOCKED` / `READY_FOR_TECHNICAL_COORDINATOR` относится только к historical pre-run plan; он superseded последующим hardware closeout.

Это был один narrow controlled reopen, не model-zoo: планировалась проверка material reserve тех же 47 разрешённых features через iterative kernel / metric feature learning + supervised recursive localization. Он больше не является active roadmap state.

Key implementation lock:

- `xrfm==0.4.5`; CPU only, `device='cpu'`, 8 threads;
- `split_method='linear'`, `n_trees=1`, `max_leaf_size=8192`, leaf RFM iterations=3;
- no HPO; smoke → full Fold-1 feasibility → compute gate;
- full OOF — только после отдельного manual review;
- ceiling: 12 CPU wall-clock hours; `STOPPED_BY_COMPUTE_COST` не является quality verdict.

Сохраняются `Data_final.xlsb` и его SHA, 289614 working rows, `DefMark`, исключение `INN`, exact accepted 47 features, запрет `Q_B1_norm`/`Q_B2_norm` как predictors, same 3 folds seed 42, saved `GBDT_mean` Gini 0.8063993952 и закрытый final test. GPU-only experiment не становится следующим основным Stage без отдельного нового решения пользователя.

При xRFM `no_material_benefit`/`inferior` default direction — data / feature / blind-spot research, не новая модель. Data research, presentation и defence остаются параллельными открытыми направлениями.

## 13. Stage 14 V1 — xRFM — CLOSED: HARDWARE_CONSTRAINT

Environment PASS и pre-run implementation ACCEPT, но guard остановил первый Smoke до model.fit: 6 physical cores / 15.34 GiB RAM не выполняют contract 8 cores / 32 GiB, а 16 GiB available RAM перед feasibility на этой машине невозможно. Статус `STOPPED_BY_COMPUTE_COST / HARDWARE_CONSTRAINT`, quality `UNKNOWN`; training, predict_proba, feasibility, OOF и final test отсутствуют. Новый model candidate автоматически не назначается.

Следующий содержательный research direction: точнее охарактеризовать common blind spot текущих 47 features и тип недостающей информации — профиль 805 common blind-spot defaults, отличие от корректно поднятых defaults, устойчивые feature-space regions, missingness/pattern diagnostics и future valid feature-source hypotheses. Новый predictor в этом closeout не проектируется.

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

---

## Stage 16 — Blind Spot Information Gap Diagnostics

**Цель:** понять, чем отличаются клиенты, которых не смогли определить текущие
модели.

Stage 16 использует сохранённые OOF и error artifacts для анализа общей зоны
из **805** ошибок. В рамках этапа не выполняются новое обучение, создание новых
признаков или изменение принятого протокола.

---

## 17. Stage 17 — Information Gap Map — ЗАВЕРШЁН

Статус:

`CURRENT_DATASET_TEMPORAL_ENRICHMENT_BLOCKED`

Stage 17 закрыл следующий вопрос после blind-spot diagnostics:

можно ли честно проверить дополнительные источники информации на текущем историческом датасете?

Ответ: нет.

Причина не в отсутствии идей новых факторов, а в отсутствии восстанавливаемого row-level временного якоря.

По подтверждению заказчика:

- `observation_date` / `decision_date` для текущих исторических строк восстановлена не будет;
- точная temporal-схема формирования `DefMark` относительно каждой строки также восстановлена не будет.

Следовательно:

- SPARK/FNS/current external snapshots не присоединяются к текущим историческим строкам как predictors;
- historical enrichment `Data_final.xlsb` закрыт;
- новый model-only search на неизменных 47 признаках не открывается;
- текущий dataset сохраняется как baseline/evidence dataset.

### Следующий приоритет

Не новый feature experiment на `Data_final.xlsb`.

Следующий отдельный research question должен относиться к новому временно корректному dataset / data design, где существуют:

- row-level observation / decision date;
- определённый prediction horizon;
- historical feature availability;
- temporal target definition.

До появления такого объекта data research текущего historical dataset считается закрытым по temporal-enrichment направлению.

Presentation / defence evidence остаётся параллельным приоритетом.

---

## 18. Stage 18 — FP/FN и operating modes — ЗАВЕРШЁН

Статус: `FP_FN_OPERATING_MAP_COMPLETE`.

Reviewer: `ACCEPT`.

Stage 18 закрыл практический вопрос управления ошибками текущего baseline:

- threshold задаёт общий FP/FN trade-off;
- Moderate 15% даёт Recall 69.94%, но не является оптимальным threshold;
- снижение threshold не решает common blind spot 805;
- принятое disagreement-rule не даёт полезной FN review zone;
- область около operating threshold концентрирует ошибки и является кандидатом на дополнительную проверку.

Stage 19 завершил формализацию воспроизводимого конвейера проверки нового признака.

LLM остаётся отдельным Result Interpreter и не является credit predictor.

---

## 19. Этап 19 — Протокол проверки нового признака — ЗАВЕРШЁН

Статус: `NEW_FEATURE_PROTOCOL_READY`.

Вердикт Reviewer: `ACCEPT`.

Повторно используемая последовательность:

`источник → происхождение → временная корректность → допуск → одно контролируемое изменение → одинаковая проверка → качество и ошибки → решение`.

До ML обязательны проверка происхождения и временной допустимости. В одном будущем
эксперименте разрешено ровно одно новое изменение признака; final test не используется
для выбора признака. Решение о принятии требует заранее определённого критерия.

## 20. Stage 20 V1 — ролевой интерпретатор результата GPT — ЗАВЕРШЁН И ПРИНЯТ

Статус: `ROLE_BASED_RESULT_INTERPRETER_PROTOTYPE_READY`.

Reviewer: `ACCEPT`.

Evidence:

- 2 synthetic cards × 4 roles = 8 OpenAI Responses API calls;
- automated validation 8/8 PASS;
- manual review 8/8 PASS;
- реальные клиентские данные не использовались;
- GPT используется только как Result Interpreter заранее рассчитанного ML-результата;
- notebook: `notebooks/20_Ролевой_интерпретатор_результата_GPT_V1.ipynb`;
- artifact: `reports/generated/stage20_role_interpreter_V1.json`.

---

## 21. Final research closeout — следующий шаг

Основная исследовательская цепочка на текущем historical dataset завершена.

Новые model/data experiments на текущем `Data_final.xlsb` не открываются без нового основания.

Следующий этап:

- итоговый research synthesis;
- evidence package;
- презентация / защита;
- обсуждение с заказчиком нового временно корректного data design.

Новый research может быть открыт только при появлении нового валидного основания:

- temporally valid dataset / feature source;
- row-level temporal anchor;
- нового business question;
- иной новой гипотезы, реально меняющей исследовательское решение.

Это не означает доказанный математический потолок модели.

## Dataset Preparation V1 — завершено

Backend Dataset Preparation V1 принят: произвольный источник проходит factual inspection, proposal, explicit human confirmation и deterministic materialization в PreparedDatasetContext. Historical Data_final baseline при этом остаётся frozen.

Следующий product/application этап: **Dataset Preparation UI / Confirmation Flow**. Он подключит уже принятый backend flow к Streamlit; новый ML research stage этим не открывается.
