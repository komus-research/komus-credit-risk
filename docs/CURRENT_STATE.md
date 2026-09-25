# KOMUS — CURRENT STATE

Дата фиксации: **2026-09-25**

Этот файл содержит только актуальное подтверждённое состояние проекта.
Он обновляется после принятого исследовательского этапа или существенного изменения требований.

---

## Source of truth и рабочая среда

- Рабочий репозиторий: `komus-research/komus-credit-risk`.
- Активная рабочая ветка определяется фактическим Git state перед изменением; статическая ветка в этом документе не является source of truth.
- Локальная рабочая папка: `D:\Projects\komus-work`.
- Точный `HEAD` и `git status` проверяются непосредственно перед изменением; они не фиксируются в этом документе.

`AIUniverstorage/commus` — репозиторий Института и integration point, но не ежедневный source of truth для research. Фактические файлы текущего репозитория, accepted artifacts и notebooks имеют приоритет над stale docs, чатами и памятью.

---

## 1. Текущая задача

Персональная задача исследования:

1. Довести рабочее решение до варианта **без `Q_B1_norm` и `Q_B2_norm`**.
2. Иметь сильный воспроизводимый baseline на разрешённых признаках.
3. Понять потерю качества, ограничения Recall/Gini и причины тяжёлых ошибок.
4. Проверить, можно ли вернуть недостающий сигнал.
5. Исследовать современные модели/подходы, которых не было в старом решении Комуса.
6. Постепенно подготовить основу backend/interface.
7. Сохранить доказательства, таблицы и графики для итоговой презентации и защиты.

**LLM в этом исследовании не является кредитным предиктором.**
LLM используется только как интерпретатор уже рассчитанных ML-результатов.

---

## 2. Основные данные

Dataset:

`Data_final.xlsb`

SHA-256:

`fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930`

Структура:

* 362 018 строк;
* 51 столбец;
* target: `DefMark`;
* identifier: `INN`;
* 49 исходных модельных признаков;
* 47 разрешённых признаков после исключения `Q_B1_norm` и `Q_B2_norm`;
* доля дефолтов около 9.7%.

Зафиксированный split:

* working sample: **289 614**;
* final test: **72 404**;
* 80/20;
* seed: **42**.

Final test закрыт для выбора моделей, признаков, tuning, balancing, threshold, calibration и research direction.

---

## 3. Q_B1 / Q_B2

`Q_B1_norm` — Индекс финансового риска СПАРК.

`Q_B2_norm` — Индекс должной осмотрительности СПАРК.

По подтверждённым требованиям заказчика:

* они существовали до дефолта и сами по себе не признаны temporal leakage;
* их можно использовать как reference/diagnostic signals;
* **их нельзя использовать как predictors в финальной рабочей модели**.

---

## 4. Подтверждённое временное ограничение

`DefMark` собирался на исторических данных за период **2005–2024**.

В текущем dataset **нет достоверной row-level observation date**, соответствующей моменту оценки конкретной строки.

Следствия:

* random CV/OOF не доказывает temporal stability;
* нельзя приклеивать текущие СПАРК/ФНС snapshots к историческим строкам как исторические признаки;
* historical external enrichment заблокирован без нового временного основания.

Для направления `registration reliability` provenance gate уже считается завершённым:

`BLOCKED_NO_OBSERVATION_DATE`

Не повторять поиск observation date или source probe без нового evidence.

---

## 5. Stage 1 — baseline без Q_B1/Q_B2

Статус: **ЗАВЕРШЁН**

Протокол:

* 47 разрешённых признаков;
* 3-fold StratifiedKFold;
* seed 42;
* final test не использован.

OOF результаты:

* XGBoost: Gini **0.8040**, PR-AUC **0.5993**;
* CatBoost: Gini **0.8038**, PR-AUC **0.6010**;
* LightGBM: Gini **0.8034**, PR-AUC **0.5978**.

Вывод:

подтверждённый baseline проекта без закрытых индексов:

**Gini ≈ 0.804**

Разница между моделями мала относительно вариативности фолдов, поэтому абсолютный победитель не объявлен.

---

## 6. Stage 2 — Explainability

Статус: **ЗАВЕРШЁН**

Ключевые факты:

* три GBDT используют практически одинаковое ядро разрешённых признаков;
* минимальная межмодельная корреляция SHAP ranks: **0.974**;
* permutation ranks: **0.899**;
* historical top-15 overlap: **13/15**.

Вывод:

поведение моделей по важности признаков устойчиво.

SHAP/importance показывают модельные связи, а не причинность.

---

## 7. Stage 3 — анализ ошибок и blind spot

Статус: **ЗАВЕРШЁН**

Ключевые факты:

* дефолтов в working sample: **28 015**;
* глубоко пропущенных дефолтов: **1 278**;
* общая blind spot трёх моделей: **805**;
* это **63.0%** глубоко пропущенных дефолтов;
* сильное model disagreement: **1.9%**.

Вывод:

существенная часть тяжёлых ошибок общая для CatBoost, XGBoost и LightGBM.

Это поддерживает гипотезу информационного ограничения текущих признаков сильнее, чем гипотезу проблемы одного алгоритма.

---

## 8. Stage 4 V2 — диагностика Q_B1/Q_B2

Статус: **ЗАВЕРШЁН И ПРИНЯТ**

Основные результаты:

* standalone Gini Q_B1: **0.8044**;
* standalone Gini Q_B2: **0.6768**;
* Pearson Q_B1/Q_B2: **0.8266**;
* blind spot vs non-default AUC:

  * Q_B1: **0.6973**;
  * Q_B2: **0.7234**;
* rescue @30%:

  * Q_B1: **53.75%**;
  * Q_B2: **59.43%**.

Вывод:

Q_B1 сильнее как общий risk score, но Q_B2 лучше диагностирует именно Stage 3 blind spot.

Stage 4 V1 отклонён из-за некорректного использования percentile thresholds при крупных tie-группах.

---

## 9. Stage 5 V1 — proxy Q_B2

Статус:

`completed_accepted`

Decision:

`material_missing_signal`

Основные результаты:

* OOF Spearman восстановления Q_B2: **0.5421**;
* OOF MAE: **0.7058**;
* Spearman внутри blind spot: **0.0242**;
* oracle Q_B2 blind AUC: **0.7234**;
* proxy blind AUC: **0.3981**;
* AUC gap: **0.3253**;
* rescue @30%:

  * oracle: **59.43%**;
  * proxy: **10.43%**;
  * gap: **49.00 п.п.**

Вывод:

47 разрешённых признаков частично воспроизводят общий сигнал Q_B2, но не воспроизводят существенную часть его сигнала, полезную внутри общей blind spot.

Это поддерживает наличие **material information gap**.

Это НЕ доказывает:

* причинность Q_B2;
* гарантированный прирост от внешних данных;
* temporal stability;
* что конкретный внешний источник решит проблему.

---

## 11. Business constraints

Recall около **69%** — подтверждённый бизнес-ориентир, а не цель, которую нужно максимизировать любой ценой.

Threshold и баланс FN/FP являются отдельной business policy.

Заказчик связывает пользу проекта со снижением ПДЗ примерно:

**15% → 10%**

Но подтверждённой формальной связи:

`ML errors / threshold → ПДЗ`

пока нет.

Поэтому нельзя придумывать `C_FN`, `C_FP` или бизнес-cost function без отдельного подтверждения.

---

## 12. Stage 1–12: завершённая и принятая model-research chain

Stage 12 V1 — Research Synthesis Stage 1–11 — имеет статус `completed_accepted`.
Он закрепляет принятую цепочку Stage 1–12 на текущих 47 разрешённых признаках без
`Q_B1_norm` / `Q_B2_norm`; проект в целом при этом не завершён.

| Stage | Проверка | Принятый факт / решение |
| --- | --- | --- |
| 6 V4 | TabM standalone | OOF Gini **0.781310**; inferior относительно GBDT control. |
| 7 V1 | TabM stacking | GBDT_mean Gini **0.806399**, hybrid **0.804260**; `no_material_benefit`. |
| 8 V1 | FT-Transformer | OOF Gini **0.801528**, Δ к GBDT_mean **-0.004871**; `no_material_benefit`. |
| 9 V1 | rank complementarity | При capacity 30% FT rescue **9/805**, GBDT_mean **0/805**; результат ниже material threshold. |
| 10 V1 | oracle/residual reserve | Максимум **15/805**, Δ **+1.863 п.п.**; effective union capacity **37.446%**; `limited_residual_model_reserve`. |
| 11 V1 | RealMLP | Gini **0.793325** против **0.806399** у GBDT_mean, Δ **-0.013074**; проигрыш **3/3** folds; `inferior`. |

Все числа — из accepted artifacts в `reports/summary/` и `reports/generated/`; final test в Stages 6–11 не использовался.

### Решение

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`

Model-only поиск на текущих 47 признаках остановлен: после проверок TabM standalone/stacking, FT-Transformer, rank complementarity, oracle/residual reserve и RealMLP дальнейший architecture search имеет низкий ожидаемый information gain. Evidence сильнее поддерживает limitation информации/признаков, чем недостаточность проверенных architectures.

Это не означает, что проект завершён, что доказан математический потолок Gini или что никакая модель никогда не сможет быть лучше. Random CV также не доказывает temporal stability.

---

## 13. Stage 12 V1 — принятый Research Synthesis

Принятый synthesis объединяет evidence Stages 1–11: baseline без закрытых индексов,
общую blind spot **805**, Stage 5 `material_missing_signal` и результаты TabM,
stacking, FT-Transformer, rank complementarity, oracle/residual reserve и RealMLP.
Ни одна из этих architecture-проверок на неизменном feature contract не дала evidence,
что ещё одна architecture сама по себе снимает основное ограничение.

Следствие: ожидаемый information gain ещё одной model architecture на тех же 47
признаках сейчас низкий. Это не является математическим потолком Gini, не доказывает
temporal stability и не исключает будущего улучшения при новом основании.

Evidence хранится в `notebooks/`, `reports/summary/`, `reports/generated/`,
`reports/figures/` и реестре `docs/RESEARCH_RECORD.md`.

---

## 14. Следующий приоритет: открытый data research и условия повторного открытия model research

Data research остаётся открытым. Следующий приоритет: новые валидные признаки,
СПАРК-пилот, динамика и связи, row-level temporal anchor при его появлении, а также
presentation / defence evidence. Эти направления могут снова открыть model research.

Reopen conditions:

1. новый валидный feature source;
2. row-level temporal anchor;
3. сильный независимый противоречащий результат;
4. новый business operating point;
5. новая научная гипотеза, реально меняющая решение.

Не добавлять новый model shortlist ради количества.

---

## 15. Stage 13 V1 — TabFM technical SAFE-RUN

### FACTS

- Dataset: `Data_final.xlsb`, SHA-256 `fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930`.
- Working sample: **289 614** строк; 47 разрешённых признаков; `Q_B1_norm` и `Q_B2_norm` не являются predictors; final test не использовался.
- Comparator: `GBDT_mean`, OOF Gini **0.8063993952**.
- Locked TabFM provenance: Google Research TabFM release `1.0.1`, source commit `d8678b6895f1428a468d4cc299c1ff4cf704e726`, checkpoint `google/tabfm-1.0.0-pytorch` revision `77cb9cc1b4fd3a9c77fbb9552c218200bb4dab83`, checkpoint SHA-256 `928cb350becdc77cdb7a9e8c36deda88917bfd14a3091894a2dc516db58a2085`.
- SAFE-RUN прошёл: runtime/dataset guards, exact checkpoint SHA, locked model load, real inference preflight и single-call/chunked equivalence. `max_abs_diff = 0` при tolerance `<= 1e-5`.
- `RUN_FULL_OOF=False`; полный 3-fold OOF не запускался.

### INTERPRETATION

Зафиксированный TabFM path технически воспроизводим. Проверка не дала ответа на вопрос качества относительно `GBDT_mean`, так как полного OOF нет.

### LIMITATIONS

Наблюдаемая CPU inference throughput делает full OOF на текущей среде многодневной, потенциально многонедельной операцией. Точный runtime не установлен: часть wall elapsed была загрязнена sleep/idle. Это не является evidence, что TabFM хуже или лучше GBDT, и не даёт TabFM OOF metrics.

### DECISION

Статус Stage 13 V1: `STOPPED_BY_COMPUTE_COST`. Полный OOF на текущей CPU-среде не запускать; `RUN_FULL_OOF=False` сохранить. Воспроизводимый setup helper существует: `scripts/prepare_stage13_tabfm.ps1`.

### Stage 14 V1 — xRFM CPU-only controlled reopen

TabPFN-3 Stage 14 candidate закрыт до запуска: `TABPFN3_STAGE14_REJECTED_BY_CPU_CONSTRAINT`. Его честный locked large-context contract требовал GPU/H100; CPU-only является основным research path KOMUS, а subsampling или уменьшение context изменили бы hypothesis. GPU fallback запрещён. TabPFN-3 не запускался, OOF не выполнялся, quality остаётся `UNKNOWN` — это не `inferior` и не `no_material_benefit`; final test не использовался. `notebooks/14_Сравнение_TabPFN3_с_GBDT_baseline_V1.ipynb` и `requirements-tabpfn3-v1.txt` остаются tracked historical rejected pre-run artifacts и не являются активной implementation; их не запускать.

Stage 14 V1 **был разрешён** как один narrow controlled reopen: `xRFM CPU_ONLY_RESEARCH_EXPERIMENT`, с lock `xrfm==0.4.5`, `device='cpu'`, 8 threads, `split_method='linear'`, `n_trees=1`, `max_leaf_size=8192` и leaf RFM iterations=3. Это historical pre-run plan; последующий hardware closeout зафиксирован ниже и данный lock больше не является current active state.

### Stage 14 V1 — xRFM hardware closeout

Статус: `STOPPED_BY_COMPUTE_COST / HARDWARE_CONSTRAINT`; quality: `UNKNOWN`. Environment setup прошёл, pre-run implementation принят, однако hardware guard остановил первый разрешённый Smoke до model.fit: AMD Ryzen 5 5500U имеет 6 физических cores и 15.34 GiB RAM при contract 8 cores / 32 GiB; требование 16 GiB available RAM перед feasibility на этой машине физически невыполнимо. Training, predict_proba, smoke quality, feasibility и OOF отсутствуют; final test не использован. Это ничего не утверждает о predictive quality xRFM. Frozen lock не ослабляется; active default восстановлен: `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`. Следующее направление — data / feature / blind-spot research.

Создан Model Research Coverage & Exclusion Register V1 и действует `FEASIBILITY_BEFORE_EXPERIMENT_LOCK`. Новый Stage 15 не открыт; предполагаемый следующий вопрос — blind-spot / information-gap diagnostics.

---

## Current model-research status

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`

Подбор новых моделей на текущем наборе из 47 разрешённых признаков остановлен.
Проверенные семейства моделей показали сходные ограничения, а общая зона ошибок
не объясняется одной конкретной моделью.

Stage 16 — blind spot diagnostics — завершён.

Анализ общей группы ошибок показал:

- существует группа из 805 клиентов, не обнаруженных тремя базовыми моделями;
- группа имеет наблюдаемый профиль, отличный от остальных дефолтов;
- различия связаны с комбинацией характеристик бизнеса, финансовых показателей,
  исполнительной активности и организационных факторов;
- проблема не объясняется пропусками данных;
- для KMeans при k=2–6 silhouette не показал сильного разделения на отдельные типы.

Вывод:

результаты Stage 16 указывают на возможное ограничение текущего информационного пространства
для части сложных клиентов, но не доказывают недостаточность 47 признаков.

Следующий приоритет — исследование дополнительных источников информации и
потенциальных новых факторов, а не дальнейший поиск моделей на неизменном
feature contract.

Это не является математическим доказательством потолка качества и не отменяет
возможную пользу модели при появлении новой проверяемой гипотезы, новых данных
или нового временного основания.

---

## 17. Stage 17 V1 — карта информационного разрыва

Статус:

`CURRENT_DATASET_TEMPORAL_ENRICHMENT_BLOCKED`

### FACTS

- Рабочий feature contract остаётся неизменным: 47 разрешённых признаков.
- `Q_B1_norm` и `Q_B2_norm` не используются как predictors.
- Подтверждённый бизнес-смысл имеется для 17 из 47 признаков.
- Бизнес-смысл ещё 30 признаков по имеющимся материалам не подтверждён.
- Среди 17 расшифрованных predictors не подтверждено прямое соответствие бизнес-факторам дефолта `D_1–D_8`.
- Для `D_8` присутствует только связанный сигнал `Q_B3_norm` — количество активных исполнительных производств; это не прямой эквивалент `D_8`.
- Рассмотрены 10 потенциальных дополнительных информационных источников; все 10 требуют исторической временной привязки.
- Надёжная row-level `observation_date` / `decision_date` в текущем датасете отсутствует.
- Заказчик подтвердил, что такой временной якорь для текущего датасета восстановлен не будет.
- Точная временная схема формирования `DefMark` относительно каждой строки также восстановлена не будет.
- Новые модели не обучались.
- Final test не использовался.

### INTERPRETATION

Stage 17 выявил обоснованные гипотезы дополнительной информации, но их predictive value нельзя корректно проверить на текущем историческом датасете без временной структуры.

Это не доказывает недостаточность текущих 47 признаков и не доказывает, что blind spot вызван отсутствующей информацией.

### DECISION

Историческое внешнее enrichment текущего `Data_final.xlsb` закрыто по методологическим причинам.

Современные snapshots Spark, ФНС, судебных систем, ЕГРЮЛ и других источников нельзя присоединять к историческим строкам только по `INN` и трактовать как исторические predictors.

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` сохраняется.

Текущий датасет остаётся воспроизводимым baseline для завершённого model/blind-spot research.

Следующий новый data-research объект должен иметь корректную row-level временную структуру.

Evidence:

- `notebooks/17_Карта_информационного_разрыва_V1.ipynb`
- `reports/generated/stage17_information_gap_map_V1.json`

---

## 18. Stage 18 V1 — FP/FN и operating modes

Статус:

`FP_FN_OPERATING_MAP_COMPLETE`

Reviewer verdict: `ACCEPT`.

### FACTS

Исследование выполнено только на сохранённом working-sample OOF:

- working rows: **289 614**;
- defaults: **28 015**;
- final test не использовался;
- новые модели не обучались;
- новые признаки не создавались;
- `Q_B1_norm` / `Q_B2_norm` не predictors;
- threshold и размеры review zone не оптимизировались по результатам.

Заранее были зафиксированы operating modes с risk capacity 10%, 15%, 20%, 25% и 30%.

Ключевые результаты:

- 10% capacity → Recall **57.42%**, Precision **55.54%**, FN **11 929**, FP **12 876**;
- 15% → Recall **69.94%**, Precision **45.10%**, FN **8 421**, FP **23 848**;
- 20% → Recall **78.04%**, Precision **37.75%**, FN **6 151**, FP **36 059**;
- 25% → Recall **83.76%**, Precision **32.41%**, FN **4 550**, FP **48 939**;
- 30% → Recall **87.47%**, Precision **28.21%**, FN **3 509**, FP **62 378**.

Режим `Moderate` с capacity 15% используется только как reference,
поскольку оказался близок к бизнес-ориентиру Recall около 69%.
Он не признан оптимальным threshold.

### Common blind spot

При operating modes 10–30% захвачено **0 из 805** common blind-spot defaults.

Первый blind case появляется примерно при **50.11%** risk capacity.
Для захвата 50% группы требуется около **63.51%** risk capacity.

Это не является доказательством невозможности обнаружения этой группы другими механизмами:
blind spot изначально определён через низкий model rank.

### Model disagreement

Принятое правило Stage 3 `rank_spread >= 0.25`
не показало полезной концентрации FN:

- review candidates: **1 762**;
- FN routed: **32**;
- доля всех FN: **0.38%**;
- default enrichment: **0.53x**.

Вывод относится только к этому конкретному правилу disagreement.

### Threshold review zone

Зона вокруг Moderate boundary показала высокую концентрацию ошибок:

- 2% review load → **8.95%** всех ошибок, error rate **49.88%**;
- 5% → **21.56%** всех ошибок, error rate **48.05%**;
- 10% → **41.04%** всех ошибок, error rate **45.72%**.

Общий error rate Moderate составляет **11.14%**.

### INTERPRETATION

Stage 18 разделяет три разные задачи:

1. threshold управляет общим компромиссом Recall / Precision / FN / FP;
2. область около threshold является evidence-supported кандидатом на дополнительную проверку;
3. common blind spot требует отдельного механизма и не решается практически одним снижением threshold.

### DECISION

Threshold рассматривается как business operating parameter.

Размер review zone нельзя выбирать без стоимости FP/FN и допустимой операционной нагрузки.

Протокол проверки нового признака принят в Stage 19. Его практическое применение
возможно только для нового временно корректного источника данных; на текущем
historical `Data_final.xlsb` новый feature experiment не запускается.

Evidence:

- `notebooks/18_FP_FN_и_operating_modes_baseline_V1.ipynb`
- `reports/generated/stage18_fp_fn_operating_modes_V1.json`

---

## 19. Stage 19 V1 — Протокол проверки нового признака

Статус:

`NEW_FEATURE_PROTOCOL_READY`

Вердикт Reviewer: `ACCEPT`.

Stage 19 — повторно используемый исследовательский протокол, а не ML-эксперимент. Новый реальный
признак не создавался, модель не обучалась, final test не использовался, а
hyperparameter tuning и оптимизация threshold не выполнялись.

Протокол устанавливает следующую последовательность: источник → происхождение
признака → временная корректность → допуск → одно контролируемое изменение →
одинаковая working CV/OOF-проверка → качество и ошибки → решение.

До ML обязательны проверка происхождения и временной допустимости. Современный snapshot
без исторической row-level временной привязки не допускается. Недопуск к
эксперименту не означает, что предиктор плохой: его предиктивная ценность остаётся
`UNKNOWN`.

В одном будущем эксперименте разрешено ровно одно новое изменение признака. Сравнение
проводится при неизменном контракте baseline и одинаковой рабочей CV/OOF-проверке;
final test не используется для выбора признака. Без заранее заданного критерия
нельзя задним числом принять признак.

Обязательный анализ включает общее качество, ложноположительные и
ложноотрицательные ошибки, стабильность по folds, сложные случаи и зону
дополнительной проверки. **805** сложных дефолтов остаются diagnostic group, а
не optimization target.

Все 4 контрольных сценария протокола прошли.

Доказательства:

- `notebooks/19_Протокол_проверки_нового_признака_V1.ipynb`
- `reports/generated/stage19_new_feature_protocol_V1.json`

---

## 20. Stage 20 V1 — ролевой интерпретатор результата GPT

### D-060 — Stage 20 V1 принят: ролевой интерпретатор результата GPT

Статус: `ROLE_BASED_RESULT_INTERPRETER_PROTOTYPE_READY`.

Reviewer final verdict: `ACCEPT`.

`accepted=true`.

Stage 20 V1 — ролевой интерпретатор результата GPT — ACCEPTED.

### Research question

Можно ли при неизменном заранее рассчитанном ML-результате менять только форму и акценты объяснения для четырёх бизнес-ролей, сохраняя факты и не превращая LLM в кредитную модель или decision-maker.

### Evidence

- 2 frozen synthetic cards × 4 roles = 8 independent OpenAI Responses API calls;
- model `gpt-5.6-luna`;
- openai SDK `3.8.0`;
- reasoning effort `none`;
- `store=false`;
- `tools=[]`;
- реальные клиентские данные не использовались;
- automated validation 8/8 PASS;
- manual review 8/8 PASS;
- Reviewer final verdict ACCEPT;
- `accepted=true`;
- final status `ROLE_BASED_RESULT_INTERPRETER_PROTOTYPE_READY`.

### Artifacts

- `notebooks/20_Ролевой_интерпретатор_результата_GPT_V1.ipynb`
- `reports/generated/stage20_role_interpreter_V1.json`

### Conclusion

LLM подтверждён только как Result Interpreter заранее рассчитанного ML-результата.

Ролевая адаптация объяснений показана для:

- менеджера по продажам;
- кредитного контролёра;
- юриста;
- информационной безопасности.

### Limits

Stage 20 не доказывает:

- улучшение Gini/Recall/PR-AUC;
- улучшение кредитного решения;
- юридическую достаточность;
- production/security readiness;
- пользу для реальных пользователей;
- детерминированность prose;
- способность GPT самостоятельно строить объяснение без подготовленных фактов.

`store=false` не трактуется как Zero Data Retention или гарантия отсутствия хранения.

### Next

Stage 20 закрыт. Новые API-вызовы не нужны. Следующий приоритет — итоговый research synthesis / evidence package / презентация для защиты.

---

## PRODUCT / APPLICATION STATE

Этот раздел фиксирует принятое product/application состояние и не является новым research Stage.

### Архитектурная цепочка

`READY DATASET → DATASET CONTRACT → FEATURE REGISTRY → MODEL REGISTRY → EXPERIMENT CONFIG → EXPERIMENT RUNNER → EXPERIMENT RESULT → FRONTEND`

Также приняты:

- Ready Dataset Adapter;
- GBDT adapters;
- GBDT_mean;
- Comparison;
- Artifact Persistence;
- Application Service;
- Planning Service;
- Streamlit Prototype V1.

Архитектурный invariant: ML-core не знает о Streamlit/SPARK. Frontend не знает о конкретных моделях и конкретном списке 47 признаков.

### Integration V1 — принятая backend-цепочка

Принята следующая модульная цепочка:

`ExperimentArtifact → explicit final fit → immutable ModelVersion → targetless inference → PredictionBatch → selected-row LocalExplanationEvidence → ResultInterpreterRequest → ResultInterpreterClient → ResultInterpreterResponse`.

Принятые этапы:

- **Stage I / Fitted Model Lifecycle — ACCEPT.** `ExperimentArtifact` не является `ModelVersion`; сохранённая модель создаётся отдельным explicit final-fit действием и связывается с dataset/feature/config/code identity.
- **Stage II-A / Generic Model Inference V1 — ACCEPT.** Новый targetless tabular source проверяется по сохранённому model contract; required features приводятся к точному порядку модели; identifier берётся из `DatasetContract`, а не из hardcoded `INN`; duplicate identifiers допустимы и различаются через row identity/source position; canonical output — probability.
- **Stage II-B / Local SHAP V1 — ACCEPT.** Local explanation строится для той же сохранённой модели и тех же validated feature values. В V1 local SHAP поддержан только для CatBoost как capability; другие модели могут выполнять inference, а local explanation для них должен явно возвращать unsupported. Для CatBoost проверяется additivity в `raw_margin`.
- **Stage III-A / Result Interpreter Core V1 — ACCEPT.** Interpreter model-independent, получает только структурированный `LocalExplanationEvidence`, не пересчитывает probability/SHAP, не принимает кредитное решение и защищает semantic request через deterministic hash integrity.
- **Stage III-B / OpenAI Result Interpreter Adapter V1 — ACCEPT.** OpenAI реализован как сменный provider adapter к `ResultInterpreterClient`; model name задаётся конфигурацией, не hardcoded; Responses API вызывается с `store=False`. Это не трактуется как Zero Data Retention.

Внешний LLM provider не является обязательным для prediction/SHAP path. Ошибка или отсутствие LLM не должны делать prediction и LocalExplanationEvidence недоступными.

Для реальных клиентских identifiers/feature values использование внешнего LLM API требует отдельного подтверждения допустимого data-sharing/redaction policy. Наличие `store=False` само по себе такого разрешения не создаёт.

### Streamlit Prototype V1

Пользовательский flow:

`Данные → Признаки → Модель → Эксперимент → Результат`

Canonical launch:

```powershell
uv run python -m streamlit run app/streamlit_app.py
```

UX/runtime remediation имеет Reviewer verdict: `ACCEPT`.

Принятые свойства:

- подготовка данных показывает реальные стадии выполнения;
- experiment run показывает реальные стадии: run, folds, aggregation, persistence;
- fake percentages и ETA отсутствуют;
- progress listener observational;
- callback overhead не входит в `ExperimentResult.runtime_seconds`;
- `completed` отправляется только после успешного persistence;
- comparison скрыт по умолчанию;
- last successful artifact можно использовать как same-session reference;
- protocol technical metadata вынесены на второй уровень;
- result сгруппирован человеческими разделами;
- fold metrics представлены таблицей, raw metadata — в technical details.

### Scientific/product invariants

- Dataset / split / folds / seed semantics не изменены;
- model profiles не изменены;
- metrics contracts не изменены;
- `Q_B1_norm` / `Q_B2_norm` не predictors;
- final test не используется;
- ArtifactStore / ComparisonService semantics не изменены.

### Future / not implemented

- SPARK Dataset Builder;
- user model onboarding;
- semantic taxonomy для всех features;
- threshold optimization/calibration;
- production auth/DB/deployment;
- отдельный production frontend.

---

## Dataset Preparation V1 — CLOSED / ACCEPTED

Принята универсальная backend-граница подготовки табличного датасета:

`file → inspection → proposal → human confirmation → materialization → PreparedDatasetContext`.

Главный инвариант:

`FACT ≠ PROPOSAL ≠ CONFIRMED`.

Proposal не становится runtime semantics автоматически. Специалист явно подтверждает target, positive class, identifier и использование колонок.

Run-ready contract требует ровно один `TARGET`, ровно один `IDENTIFIER` и минимум один `MODEL_ALLOWED`. Для generic arbitrary dataset V1 действует `FULL_OOF_NO_PROTECTED_FINAL_TEST`: вся подтверждённая популяция получает `partition_role="full"`, `final_test_locked=False`; automatic holdout/final/temporal split не создаётся.

Physical headers проверяются до pandas normalization; snapshot/report/proposal/confirmation связаны deterministic identities. `positive_class` нормализуется в Python bool/int/finite float/str, а final semantic/predictor validation выполняется на фактически загруженном dataframe.

`DatasetPreparationManifest` остаётся deterministic provenance artifact; source fingerprint/SHA и связанные provenance identities используются для fail-closed проверки stale source.

Generic preparation не содержит name-based blacklist признаков.

Historical `Data_final` сохраняется только как frozen compatibility profile для воспроизводимости принятого исследования. Его target, identifier, feature statuses и split не являются правилами универсального продукта.

Stale source и provenance mismatch работают fail-closed.

## Dataset Preparation UI V1 — TECHNICAL ACCEPT

Техническая интеграция preparation flow со Streamlit реализована и получила итоговый Reviewer `ACCEPT`.

Подтверждено:

- generic-first rendering через `PreparedDatasetContext`;
- explicit human confirmation;
- explicit positive class;
- explicit acknowledgement evaluation population;
- successful materialization сразу переводит dataset в ready state;
- stale/provenance fail-closed;
- same-source reconfirmation;
- lifecycle формы изолирован через `context_revision + snapshot fingerprint`;
- downstream после UX V1: `Признаки → Алгоритм → Проверка качества → Результат` общий для любого `PreparedDatasetContext`.

Execution evidence Codex: 69 targeted tests PASS, `compileall app` PASS, `git diff --check` PASS.

### Universal Pipeline UX V1 — ACCEPTED

После ручного E2E принят пользовательский слой универсального конвейера.

Верхнеуровневый flow теперь:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`.

Подтверждено:

- generic flow не содержит специальных правил по именам `Q_B1_norm`, `Q_B2_norm`, `INN`, `DefMark`;
- historical `Data_final` остаётся отдельным frozen compatibility profile и не задаёт правила для новых датасетов;
- экран подтверждения данных явно отделён от обучения;
- количество `MODEL_ALLOWED` объясняется как число признаков, доступных к выбору далее, а не как уже выбранный feature set;
- редкие dataset-level overrides спрятаны в «Дополнительные ограничения колонок»;
- экран признаков явно фиксирует invariant: выбранные при обучении признаки затем требуются сохранённой ModelVersion на новых данных;
- пользовательский термин «Алгоритм» заменяет внутренний `Predictor`, а recipe/version остаются в технических деталях;
- этап обучения называется «Обучение и проверка качества» и показывает реальные progress events по fold/metrics/persistence;
- Result объясняет OOF-метрики как проверку на строках, не использованных соответствующей моделью для обучения;
- порог `0.5` обозначен только как техническая точка сравнения, не как business decision;
- перед final fit явно сказано, что метрики повторно не считаются: качество уже измерено OOF;
- inference UI объясняет, что target не нужен, а сохранённая модель ожидает тот же feature set; дополнительные колонки допустимы.

Reviewer verdict: **ACCEPT Universal Pipeline UX V1**.

## Integration V1 / Stage III-C1 — LOCAL MODEL USE FLOW — ACCEPTED

Reviewer принял локальный пользовательский flow:

`Результат → explicit save ModelVersion → targetless file → PredictionBatch → select row → LocalExplanationEvidence`.

Реализовано:

- верхнеуровневый Streamlit flow после UX V1: `Данные → Признаки → Алгоритм → Проверка качества → Результат`;
- на экране `Результат` добавлен блок **«Применить модель к новым данным»**;
- frontend работает через application-facing `IntegrationWorkflowService`;
- ModelVersion создаётся только явным действием пользователя;
- targetless inference использует `TabularReader → TabularSnapshot → ModelInferenceService`;
- identifier и feature schema берутся из сохранённого ModelVersion contract, без hardcode `INN` / `DefMark`;
- duplicate identifiers допустимы, строка выбирается по `row_id`;
- local explanation подключается capability/registry-механизмом;
- CatBoost Local SHAP работает через существующий `LocalExplanationService`;
- модель без зарегистрированного explainer сохраняет рабочий prediction path и получает `UNSUPPORTED` для local explanation;
- смена inference source немедленно инвалидирует только stale snapshot/batch/row/evidence и сохраняет active ModelVersion;
- failure downstream не удаляет успешный upstream state.

Reviewer verdict: **ACCEPT Stage III-C1**.

Локальная verification evidence после corrective fix:

- focused session/UI: 31 tests PASS;
- full suite: 225 tests PASS;
- `compileall src app` PASS;
- `git diff --check` PASS.

Принятый commit в рабочей ветке: `ec9f397e7ea30ba509283e095acc74b0a4c4352a`.

### Manual Stage III-C1 E2E — PASS

Ручной Streamlit-прогон завершён успешно:

`проверка качества → save ModelVersion → targetless inference → select row → Local SHAP`.

Фактически проверено:

- CatBoost ModelVersion сохраняется и применяется к новому targetless файлу;
- duplicate identifier values не схлопываются и различаются по `row_id`;
- для двух строк с одинаковым identifier получены разные probability и разные Local SHAP;
- смена source A → B убирает stale batch/row/evidence до нового успешного inference;
- несовместимый новый файл fail-closed и не уничтожает active ModelVersion;
- probability остаётся probability, без автоматического threshold/business decision;
- UTF-8 CSV with BOM выявил реальный `header_identity_mismatch`; corrective fix принят Reviewer и зафиксирован commit `c009f3bd8bd94c23e13cf3ebf0db1be5c4c4c6e0`.

После UX-прохода full suite: **229 tests PASS**, `compileall src app` PASS, `git diff --check` PASS.

Принятый UX commit: `492b6dc6`.

**CURRENT PRODUCT PRIORITY — Stage III-C2**

Следующий defense-critical шаг:

`LocalExplanationEvidence → external-data policy/redaction → ResultInterpreter → provider adapter → понятное объяснение`.

Dataset History / Persistence V1, дополнительный UX-polish и расширение local explainers остаются отдельными workstreams и не должны размывать Stage III-C2.
