# Реестр исследовательских этапов и доказательств

## Назначение

Этот документ фиксирует единое правило хранения результатов исследования так, чтобы любой завершённый этап можно было:

- воспроизвести;
- проверить без опоры на память или старый чат;
- восстановить как последовательный исследовательский рассказ;
- без повторного «археологического» разбора использовать при подготовке итогового отчёта и презентации для защиты.

Документ не заменяет `PROJECT_CONTEXT.md`, `ROADMAP.md`, `ARCHITECTURE.md`, `PRODUCT_SPEC.md`, `BUSINESS_RULES.md` или `DECISIONS.md`. Он отвечает только за **research evidence / presentation-ready record**.

Дата актуализации: **2026-09-04**.

Рабочий source of truth: `komus-research/komus-credit-risk`, ветка `main`, локальная папка `D:\Projects\komus-work`. `AIUniverstorage/commus` — integration point Института, не ежедневный research source of truth. При конфликте фактические notebooks и accepted artifacts `reports/summary/` / `reports/generated/` выше stale documentation.

---

## 1. Обязательный пакет каждого значимого Stage

Завершённый исследовательский Stage должен иметь:

1. **Notebook** с последовательностью:
   - Markdown: исследовательский вопрос;
   - Code: контролируемый эксперимент;
   - Markdown: анализ результата;
   - итог: FACTS / INTERPRETATION / LIMITATIONS / NEXT STEP.
2. **Небольшой machine-readable summary** в `reports/summary/`.
3. **Идентичность данных и протокола**: dataset SHA-256, feature set, split/folds, seed и уровень оценки.
4. **Ключевые метрики/диагностические числа**, на которых основан вывод.
5. **Явное решение**, что доказал эксперимент и какой следующий вопрос из него следует.
6. **Ограничения**: что результат не доказывает.
7. **Machine-readable evidence** в `reports/generated/`, если оно нужно для повторной проверки, построения графиков или следующего Stage: таблицы, агрегаты, checkpoints, OOF/diagnostic arrays и metadata. Для каждого такого файла должна быть понятна связь со Stage/версией.
8. **Графики/таблицы, важные для защиты**, в `reports/figures/`. Ключевой график не должен существовать только как картинка внутри notebook, если он поддерживает итоговый вывод и может понадобиться отдельно в презентации.
9. При наличии тяжёлых моделей или иных файлов, которые сознательно не хранятся в Git, — их имя/тип и SHA-256 либо другой проверяемый идентификатор.

Если хотя бы один из пунктов, необходимый для вывода, отсутствует, Stage не считается полностью подготовленным для итоговой защиты.

---

## 2. Контракт `reports/summary/`

Summary — компактный источник проверяемых чисел, а не замена notebook.

Минимальные поля, когда применимо:

- `experiment`;
- `version`;
- `status`;
- `question`;
- `dataset_sha256`;
- `final_test_used`;
- размер working/final выборок;
- feature set / исключённые или добавленные признаки;
- split/CV/seed;
- основные метрики или диагностические показатели;
- `facts`;
- `interpretation`;
- `limitations`;
- `decision`.

Summary не должен превращаться в копию notebook или содержать случайные временные данные.

### Ретроспективно созданные summary

Если Stage был выполнен до введения этого правила, summary можно восстановить только из сохранённых notebook outputs и проверенной документации.

Такой файл обязан явно иметь статус/поле, показывающее, что summary создан **после эксперимента без повторного вычислительного запуска**. Нельзя выдавать восстановленный summary за оригинальный run artifact.

---

## 3. Контракт `reports/generated/`

`reports/generated/` больше не считается автоматически локальной мусорной папкой. Это слой проверяемых вычислительных артефактов.

Туда допускается сохранять и коммитить:

- агрегированные JSON/CSV;
- таблицы importances/diagnostics;
- OOF/diagnostic checkpoints в `.npz`, если они нужны для повторного анализа;
- experiment metadata;
- промежуточные результаты, повторное получение которых дорого или которые являются входом следующего контролируемого Stage.

Правила:

1. имя файла содержит Stage/версию, когда это применимо;
2. артефакт должен быть воспроизводимым и иметь понятное происхождение;
3. временные файлы, caches и логи туда не складываются;
4. если один файл становится чрезмерно большим, решение о его хранении принимается отдельно, а не через blanket-ignore всего каталога;
5. если позже появляются действительно чувствительные данные, для них вводится отдельное явное ограничение **до commit/push**.

Текущий проект ведётся как учебное исследование; blanket-исключение `reports/generated/` из Git отменено.

---

## 4. Контракт `reports/figures/`

`reports/figures/` — источник графиков и визуальных таблиц, пригодных для отчёта и презентации.

Для нового значимого Stage:

- ключевые графики сохраняются отдельными файлами по возможности прямо во время выполнения notebook;
- предпочтительный формат для обычных графиков — PNG с достаточным разрешением для слайда; при полезности допускается SVG/PDF;
- имя должно быть понятным, например `stage5_qb2_proxy_reconstruction_V1.png`;
- подписи, легенда и оси оформляются по-русски, кроме стандартных технических названий;
- график должен быть связан с конкретным Stage/версией и выводом;
- декоративные или дублирующие картинки не коммитятся только ради количества.

Сохранённые outputs внутри `.ipynb` остаются частью research narrative, но отдельный figure-файл удобнее для презентации и повторного использования.

---

## 5. Presentation-ready правило

Для будущей презентации каждый Stage должен отвечать на пять вопросов:

1. **Что мы хотели узнать?**
2. **Как поставили контролируемый эксперимент?**
3. **Что фактически получили?**
4. **Что это означает и чего не доказывает?**
5. **Почему следующий Stage логично следует именно отсюда?**

Итоговая презентация строится из проверенных summaries, актуальной документации, tracked generated artifacts и выбранных графиков/таблиц. Stale notebook output, старый чат или память не являются источником истины.

При подготовке презентации график или таблица используется только вместе с контекстом:

- к какому Stage и версии относится;
- на каком evaluation level получен результат;
- какие данные/feature set использованы;
- какой вывод график действительно поддерживает.

`reports/presentation/` можно использовать как финальный curated-набор материалов для защиты, но он не заменяет `reports/figures/` и `reports/summary/`.

---

## 6. Политика веток для research evidence

- `main` — рабочая и интеграционная ветка текущего репозитория.
- Для review может существовать вспомогательная ветка, но она не заменяет `main` как source of truth после integration.
- Перед любым изменением проверяются фактические branch/HEAD/status.

---

## 7. Реестр текущей исследовательской цепочки

### Stage 1 — baseline без `Q_B1_norm` и `Q_B2_norm`

- Notebook: `notebooks/01_Новый_baseline_без_Q_B1_Q_B2_V2.ipynb`
- Принятая версия: **V2**
- Результат: воспроизводимый OOF baseline **Gini ≈ 0.804**; различия CatBoost/XGBoost/LightGBM малы относительно межфолдового разброса.
- Summary: `reports/summary/stage1_baseline_summary_V2.json`
- Summary создан ретроспективно 2026-08-20 из сохранённых outputs.

### Stage 2 — explainability разрешённых признаков

- Notebook: `notebooks/02_Explainability_допустимых_признаков_V1.ipynb`
- Версия: **V1**
- Результат: три GBDT показывают устойчивое общее ядро признаков; minimum rank correlation SHAP **0.974**, permutation importance **0.899**; пересечение consensus top-15 с historical top-15 — **13/15**.
- Summary: `reports/summary/stage2_explainability_summary_V1.json`
- Summary создан ретроспективно 2026-08-20 из сохранённых outputs.

### Stage 3 — анализ ошибок и общей слепой зоны

- Notebook: `notebooks/03_Анализ_ошибок_и_потерянного_сигнала_V1.ipynb`
- Версия: **V1**
- Результат: 1 278 глубоко пропущенных дефолтов; **805** объектов образуют общую слепую зону, то есть **63.0%** глубоко пропущенных; сильное межмодельное расхождение среди них только **1.9%**.
- OOF checkpoint SHA-256: `faa53a8aed86c2d445699c0fd1df6a5b83711c96d3a300f9a8860112ff4473ac`
- Summary: `reports/summary/stage3_error_analysis_summary_V1.json`
- Summary создан ретроспективно 2026-08-20 из сохранённых outputs.

### Stage 4 — диагностика закрытых сигналов `Q_B1/Q_B2`

- Notebook: `notebooks/04_Диагностика_потерянного_сигнала_Q_B1_Q_B2_V2.ipynb`
- Принятая для продолжения версия: **V2**
- Формальный статус: `completed_accepted`.
- Summary: `reports/summary/stage4_closed_signal_summary_V2.json`
- Ключевой результат: `Q_B1_norm` сильнее как общий standalone predictor, а `Q_B2_norm` лучше видит именно Stage 3 blind spot при fixed-capacity диагностике.
- Final test не использован.

### Stage 5 — аудит proxy-сигнала `Q_B2`

- Notebook: `notebooks/05_Аудит_proxy-сигнала_Q_B2_разрешёнными_признаками_V1.ipynb`
- Версия: **V1**
- Summary: `reports/summary/stage5_qb2_proxy_audit_summary_V1.json`
- Формальный статус: `completed_accepted`.
- Решение: `decision_class = material_missing_signal`.
- Ключевой факт: общий `Q_B2` частично восстанавливается из 47 разрешённых признаков (OOF Spearman ≈ **0.542**), но внутри blind spot proxy практически теряет связь (Spearman ≈ **0.024**) и сильно уступает oracle `Q_B2`. Это поддерживает наличие material information gap.

---

### Stage 6 V4 — TabM standalone

- Notebook: `notebooks/06_Сравнение_TabM_с_GBDT_baseline_V4.ipynb`.
- Summary: `reports/summary/stage6_tabm_summary_V4.json`; generated result: `reports/generated/stage6_tabm_results_V4.json`.
- Факт: OOF Gini **0.781310**; Delta Gini относительно XGBoost **-0.022680**.
- Решение: TabM standalone inferior для locked 47-feature protocol; final test не использован.

### Stage 7 V1 — TabM stacking

- Notebook: `notebooks/07_TabM_поверх_GBDT_stacking_V1.ipynb`.
- Summary: `reports/summary/stage7_tabm_stacking_summary_V1.json`; OOF: `reports/generated/stage7_tabm_stacking_oof_V1.npz`.
- Факт: B* = GBDT_mean с OOF Gini **0.806399**; hybrid TabM Gini **0.804260** и ниже B* на 3/3 outer folds.
- Решение: `no_material_benefit`; final test не использован.

### Stage 8 V1 — FT-Transformer

- Notebook: `notebooks/08_Сравнение_FT_Transformer_с_GBDT_baseline_V1.ipynb`.
- Summary: `reports/summary/stage8_ft_transformer_summary_V1.json`; OOF: `reports/generated/stage8_ft_transformer_oof_V1.npz`.
- Факт: OOF Gini **0.801528**, Δ к GBDT_mean **-0.004871**.
- Решение: `no_material_benefit`; final test не использован.

### Stage 9 V1 — rank complementarity

- Summary: `reports/summary/stage9_rank_capacity_summary_V1.json`; result: `reports/generated/stage9_rank_capacity_results_V1.json`.
- Факт: при capacity 30% FT-Transformer rescue **9/805**, GBDT_mean **0/805**; Δ rescue **+1.118 п.п.**.
- Решение: `no_material_rank_complementarity`: результат ниже material threshold; final test не использован.

### Stage 10 V1 — oracle/residual model reserve

- Summary: `reports/summary/stage10_residual_model_reserve_summary_V1.json`; result: `reports/generated/stage10_residual_model_reserve_results_V1.json`.
- Факт: при nominal capacity 30% oracle-any rescue **15/805**, Δ **+1.863 п.п.**; actual union имеет effective capacity **37.446%**.
- Решение: `limited_residual_model_reserve`. Это upper-bound diagnostic, а не production system с общей fixed capacity; final test не использован.

### Stage 11 V1 — RealMLP

- Notebook: `notebooks/11_Сравнение_RealMLP_с_GBDT_baseline_V1.ipynb`.
- Summary: `reports/summary/stage11_realmlp_summary_V1.json`; results: `reports/generated/stage11_realmlp_results_V1.json` и `reports/generated/stage11_realmlp_oof_V1.npz`.
- Факт: RealMLP OOF Gini **0.793325**, GBDT_mean **0.806399**, Δ **-0.013074**; fold deltas отрицательны на **3/3** folds.
- Решение: `inferior`; final test не использован.

### Stage 12 V1 — Research Synthesis Stage 1–11

- Status: `completed_accepted`.
- Notebook: `notebooks/12_Research_Synthesis_Stage_1_11_V1.ipynb`.
- Summary: `reports/summary/stage12_research_synthesis_summary_V1.json`; evidence:
  `reports/generated/stage12_research_synthesis_evidence_V1.json`.
- Факт: synthesis закрепил цепочку Stage 1–12 на текущих 47 разрешённых признаках
  без `Q_B1_norm` / `Q_B2_norm`: strong baseline, common blind spot **805**,
  Stage 5 `material_missing_signal` и отсутствие evidence material solution от TabM,
  stacking, FT-Transformer, rank complementarity, oracle/residual reserve и RealMLP.
- Решение: `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`. Ещё одна model
  architecture на том же feature contract имеет низкий ожидаемый information gain.
  Это не доказывает математический потолок Gini, temporal stability, завершение
  проекта или невозможность будущего улучшения.
- Next priority: data research — валидные новые признаки, СПАРК-пилот, динамика,
  связи, row-level temporal anchor при его появлении — и presentation / defence evidence.
  Reopen conditions сохранены: новый валидный feature source; row-level temporal
  anchor; сильный независимый противоречащий результат; новый business operating
  point; новая научная гипотеза, реально меняющая решение.

### Сводное решение после Stage 12

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`: model-only поиск на неизменных 47 признаках остановлен, поскольку дальнейший architecture search имеет низкий ожидаемый information gain. Evidence сильнее поддерживает information/feature limitation, чем недостаток проверенных architectures. Это не доказывает математический потолок Gini, невозможность будущего улучшения или temporal stability.

Следующий record относится к data research или presentation / defence evidence. Model
research открывается повторно только при новом валидном feature source, row-level
temporal anchor, сильном независимом противоречащем результате, новом business
operating point или новой научной гипотезе, реально меняющей решение.

---

## 8. Правило закрытия Stage с этого момента

После выполнения нового Stage порядок такой:

1. проверить полный notebook и outputs;
2. сверить ключевые числа с сохранённым summary;
3. проверить, что final test не использован вне разрешённого gate;
4. проверить tracked generated artifacts, необходимые для повторного анализа;
5. проверить, что ключевые presentation-worthy графики сохранены отдельно в `reports/figures/` либо явно зафиксировано, почему отдельный файл не нужен;
6. сформулировать FACTS / INTERPRETATION / LIMITATIONS / NEXT STEP;
7. сохранить/обновить summary в `reports/summary/`;
8. обновить только те проектные документы, чья ответственность реально изменилась;
9. проверить Git diff и commit;
10. только после этого считать Stage закрытым и переходить к следующему исследовательскому вопросу.

Не нужно дублировать одинаковый текст во всех документах. Каждый факт хранится в своём source-of-truth, а этот реестр связывает Stage с доказательствами для будущего отчёта и презентации.

---

## 9. Stage 13 V1 — TabFM SAFE-RUN, operational closeout

- Status: `STOPPED_BY_COMPUTE_COST`.
- Notebook: `notebooks/13_Сравнение_TabFM_с_GBDT_baseline_V1.ipynb`.
- Locked requirements: `requirements-tabfm-v1.txt`.
- Setup helper: `scripts/prepare_stage13_tabfm.ps1`.
- Operator runbook: `docs/STAGE13_TABFM_RUNBOOK.md`.
- Machine-readable retrospective summary: `reports/summary/stage13_tabfm_summary_V1.json`.

### Result

Technical SAFE-RUN PASS: runtime/dataset guards, exact checkpoint SHA, locked model load, real inference preflight и single-call/chunked equivalence passed; `max_abs_diff = 0` при tolerance `<= 1e-5`. `RUN_FULL_OOF=False`; full 3-fold OOF отсутствует, quality comparison с `GBDT_mean` не разрешён, final test не использовался.

На текущей CPU-среде observed inference cost делает full OOF operationally disproportionate; точный runtime не установлен из-за sleep/idle в части wall elapsed. Это не verdict качества TabFM.

### Evidence boundary

Stage 13 OOF/result artifacts отсутствуют, потому что full OOF не выполнялся. В частности, не созданы `reports/generated/stage13_tabfm_oof_V1.npz` и `reports/generated/stage13_tabfm_results_V1.json`; никакие TabFM OOF metrics не заявляются.

### Next research status

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` остаётся действующим против обычного model-zoo search. TabPFN-3 Stage 14 candidate закрыт как `TABPFN3_STAGE14_REJECTED_BY_CPU_CONSTRAINT`: locked large-context path требовал GPU/H100, а основной research path CPU-only; уменьшение context/subsampling меняет hypothesis, GPU fallback запрещён. TabPFN-3 не запускался, OOF не выполнялся, quality `UNKNOWN` (не `inferior` и не `no_material_benefit`), final test не использовался. Его tracked notebook и requirements сохранены исключительно как historical rejected pre-run artifacts; запускать их не следует.

Единственный narrow controlled reopen — Stage 14 V1: `xRFM CPU_ONLY_RESEARCH_EXPERIMENT`, Architect status `XRFM_V1_LOCKED` / `READY_FOR_TECHNICAL_COORDINATOR`. Hypothesis: iterative kernel / metric feature learning + supervised recursive localization. Lock включает `xrfm==0.4.5`, CPU `device='cpu'`, 8 threads, `split_method='linear'`, `n_trees=1`, `max_leaf_size=8192`, три leaf RFM iterations, отсутствие HPO, smoke → full Fold-1 feasibility → compute gate, manual review до full OOF и 12-hour CPU ceiling. `STOPPED_BY_COMPUTE_COST` не является quality verdict. Final test остаётся закрытым; при `no_material_benefit`/`inferior` default return — data / feature / blind-spot research, не новая модель.

### Stage 14 V1 — xRFM hardware closeout

#### FACTS

Environment setup PASS и pre-run implementation ACCEPT. Первый разрешённый Smoke остановлен в hardware guard до model.fit: AMD Ryzen 5 5500U имеет 6 physical cores / 12 logical processors, 15.34 GiB physical RAM и 4.14 GiB available RAM; contract требует 8 cores, 32 GiB RAM и 16 GiB available перед feasibility. Training, predict_proba, smoke quality, feasibility и OOF не выполнялись; final test unused; quality `UNKNOWN`.

#### INTERPRETATION

Frozen full xRFM V1 нельзя честно исполнить на текущей машине без изменения experiment contract.

#### LIMITATIONS

Hardware stop ничего не говорит о predictive quality xRFM и не доказывает mathematical ceiling.

#### NEXT STEP

Восстановлен `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`; следующий content path — data / feature / blind-spot research.
