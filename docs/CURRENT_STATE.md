# KOMUS — CURRENT STATE

Дата фиксации: **2026-08-26**

Этот файл содержит только актуальное подтверждённое состояние проекта.
Он обновляется после принятого исследовательского этапа или существенного изменения требований.

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

## 10. Stage 6 V4 — TabM

Статус: **ЗАВЕРШЁН И ПРИНЯТ**

### FACTS

* Выполнены **3/3** outer folds; runtime: **31 332.65 сек** (≈ **8 ч 42 мин**).
* Полный OOF TabM: Gini **0.781310**, ROC-AUC **0.890655**, PR-AUC **0.567993**, Precision **0.737602**, Recall **0.280850**, F1 **0.406804**.
* Delta TabM vs XGBoost: Gini **-0.022680**, ROC-AUC **-0.011340**, PR-AUC **-0.031280**, Precision **+0.025347**, Recall **-0.087596**, F1 **-0.078857**.
* Final test не использован.

### INTERPRETATION

TabM уступила XGBoost baseline по Gini, ROC-AUC, PR-AUC, Recall и F1 на всех трёх folds; Precision выше. Stage 6 закрыт: оснований заменять GBDT baseline на TabM в текущем 47-feature protocol нет.

### LIMITATIONS

Random CV не доказывает temporal stability. Три фолда не являются statistical significance claim. Порог 0.5 диагностический. Final test не использован.

### NEXT STEP

Перейти к следующему отдельному исследовательскому вопросу по controlled experiment; новый TabM run не выполнять.

---

## Stage 7 V1 — TabM поверх GBDT

Статус: **ЗАВЕРШЁН И ПРИНЯТ**

### FACTS

* B* = **GBDT_mean**; его OOF Gini: **0.806399**.
* Hybrid TabM OOF: Gini **0.804260**, ROC-AUC **0.902130**, PR-AUC **0.605662**, Precision **0.719060**, Recall **0.375585**, F1 **0.493435**.
* Delta vs B*: Gini **-0.002139**, ROC-AUC **-0.001070**, PR-AUC **+0.001805**, Precision **-0.005566**, Recall **+0.011422**, F1 **+0.008710**.
* Gini hybrid ниже B* на всех трёх outer folds.
* Decision: **no_material_benefit**.
* Runtime: **20 700.83 сек** (≈ **5 ч 45 мин**).
* Final test не использован.

### INTERPRETATION

Stacking значительно улучшил TabM относительно standalone Stage 6, но TabM meta-model не дал материального преимущества относительно простого GBDT_mean. Оснований продолжать направление TabM в текущем locked design нет.

### LIMITATIONS

* Random CV не доказывает temporal stability.
* Три folds не являются statistical significance claim.
* Stacking не доказывает business benefit.
* Порог 0.5 диагностический.
* Final test не использован.

### NEXT STEP

Направление TabM закрыто. Следующий отдельный controlled experiment — FT-Transformer на тех же 47 разрешённых признаках.

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

## 12. Что больше не нужно повторять

Без нового evidence не повторять:

* сравнение тех же CatBoost/XGBoost/LightGBM как baseline;
* бесконечный tuning этих моделей;
* Stage 2 explainability;
* Stage 3 blind-spot analysis;
* Stage 4 диагностику Q_B1/Q_B2;
* Stage 5 proxy Q_B2;
* standalone TabM;
* Stage 7 TabM stacking;
* поиск row-level observation date;
* historical enrichment текущими СПАРК/ФНС snapshots.

---

## 13. Следующая исследовательская задача

Основная диагностическая цепочка Stage 1–7 завершена.

Следующий исследовательский шаг должен отвечать персональной задаче:

> проверить **FT-Transformer** на тех же 47 разрешённых признаках и сопоставимом evaluation protocol.

Stage 6 V4 и Stage 7 V1 закрыты: standalone TabM и TabM stacking не дали оснований заменить GBDT control. FT-Transformer выполнять только как отдельный controlled experiment.

Порядок:

1. Architect выбирает один следующий research question.
2. Technical Coordinator проверяет предложение.
3. Codex получает только узкое implementation task.
4. Reviewer проверяет результат.
5. После acceptance сохраняются evidence и следующий вывод.

Не исследовать несколько новых подходов одновременно.

---

## 14. Git / artifacts

Рабочая ветка:

`research/stage6-tabm-v1`

Точный HEAD и Git status всегда проверяются fresh через `git` непосредственно перед изменениями; они намеренно не фиксируются в этом документе.

Evidence Stage 1–7 хранится в:

* `notebooks/`;
* `reports/summary/`;
* `reports/generated/`;
* `reports/figures/`;
* `docs/RESEARCH_RECORD.md`;
* `docs/DECISIONS.md`.

Итоговую презентацию собирать из проверенных artifacts, а не по памяти старых чатов.

---

## 15. Текущий приоритет

Времени мало.

Порядок работы:

**закончить core research → сохранить evidence → собрать презентацию → подготовиться к защите → только затем необязательный engineering polish.**

Не тратить время на организационные и косметические изменения, если они не помогают закончить исследование или защитить результат.
