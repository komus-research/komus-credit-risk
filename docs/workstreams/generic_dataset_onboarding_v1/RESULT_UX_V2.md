# Result UX V2 — UX / VISUAL LOCK

Status: **UX / VISUAL LOCK — ACCEPTED / BACKEND ARCHITECTURE LOCKED**

Primary visual references:
- `docs/design/screens/result/02_result_model_overview_v2.png`
- `docs/design/screens/result/03_threshold_explorer_v1.png`
- `docs/design/screens/result/04_result_objects_v2.png`
- `docs/design/screens/result/05_result_object_detail_v1.png`
- `docs/design/screens/result/06_result_object_detail_llm_v1.png`
- `docs/design/screens/result/07_result_global_oof_shap_v1.png`
- `docs/design/screens/result/08_result_object_detail_explanation_loading_v1.png`
- `docs/design/screens/result/09_result_object_detail_explanation_error_v1.png`
- `docs/design/screens/result/10_result_object_detail_explanation_detailed_v1.png`
- `docs/design/screens/result/11_result_object_detail_llm_loading_v1.png`
- `docs/design/screens/result/12_result_object_detail_llm_error_v1.png`

Эти PNG фиксируют композицию, визуальную иерархию и пользовательский поток Result V2.
Фактические данные, доступность действий, persistence, provenance и API semantics определяются только принятыми backend/research contracts.

## 1. Result V2 flow

Canonical flow шага Result:

```text
Результат модели
→ Исследование порога
→ Объекты оценки
→ Объект оценки
→ Local Explanation автоматически
→ LLM-интерпретация по явному действию пользователя, если runtime capability доступна
```

Одиннадцать текущих Result PNG имеют принятый visual lock.
Для Object Detail зафиксированы состояния Local Explanation LOADING, Local Explanation READY, Local Explanation ERROR, detailed Local Explanation, Result Interpreter LOADING, Result Interpreter READY и Result Interpreter ERROR. Global OOF feature influence зафиксирован отдельным экраном `07_result_global_oof_shap_v1.png`.
`10_result_object_detail_explanation_detailed_v1.png` — это режим `Подробно` того же Object Detail, а не новый top-level экран. Technical explanation method/output space/provider в runtime всегда берутся из backend provenance, даже если PNG содержит демонстрационный текст.

Result работает на persisted accepted experiment evidence.
Final test не используется для threshold research, object filtering, selection/tuning или OOF explainability.
## 2. Экран «Результат модели»

Visual lock: `02_result_model_overview_v2.png`.

Экран является обзором завершённого эксперимента и показывает только реальные persisted/runtime факты:
- алгоритм;
- количество объектов;
- количество признаков;
- способ проверки / OOF;
- фактическое время обучения, если оно сохранено;
- Gini, ROC-AUC, PR-AUC;
- стабильность по folds;
- capture/coverage view;
- диагностический threshold и связанные Recall/Precision/errors;
- глобальную explainability только при наличии корректного backend evidence;
- переходы в Threshold Explorer и Objects.

PNG содержит демонстрационные числа и названия признаков. Их запрещено hardcode-ить.

Карточка «Качество модели» не является бизнес-решением.
График стабильности показывает fold-level evidence и не доказывает temporal stability.
Capture/coverage view не определяет автоматически оптимальный threshold.

Блок feature influence:
- описывает поведение модели, а не причинное влияние;
- не должен называться доказательством причинности;
- должен использовать backend-supported explainability semantics.

## 3. Экран «Исследование порога»

Visual lock: `03_threshold_explorer_v1.png`.

Implementation status: **R2-UI2 — ACCEPTED / CLOSED**, source commit `8050a9c5761963555a1181bede2150305979cfee`.

Threshold Explorer работает только с сохранёнными OOF scores текущего accepted run.
Изменение threshold:
- НЕ переобучает модель;
- НЕ меняет prediction score;
- меняет derived class labels и threshold-dependent metrics.
При выбранном threshold показываются:
- Recall;
- Precision;
- F1;
- количество / доля объектов выше порога;
- FN и FP;
- зависимость Recall/Precision от threshold;
- пояснение, что Gini / ROC-AUC / PR-AUC от threshold не зависят.

Semantic accents:
- основной interaction / neutral positive analytics — AXION cyan/teal;
- FN / пропущенное целевое событие — restrained pink/red;
- FP / ложное срабатывание — amber;
- secondary neutral states — slate / muted blue-gray.

Выбранный стиль: **AXION + semantic accents**.
Не возвращаться к A/B/C вариантам без нового решения владельца.

Threshold Explorer не выбирает «лучший» или business-optimal threshold автоматически.
Сохранение сценария возможно только через backend contract, если такой contract принят.

В принятом R2-UI2 runtime один `result_v2_threshold` сохраняется в session state: Overview показывает компактную сводку для текущего значения без editable slider, а отдельный Threshold Explorer является единственной точкой изменения threshold. Все threshold-dependent значения приходят только из `OOFResultService.threshold()`; Gini / ROC-AUC / PR-AUC — из `summary()`.

Visual reference содержит threshold-dependence curves, но public sweep DTO сейчас отсутствует. Поэтому R2-UI2 честно откладывает Recall/Precision curves: UI не читает OOF arrays, не реконструирует их локально и не выполняет скрытый grid вызовов `threshold()` только ради совпадения с PNG.

## 4. Экран «Объекты оценки»

Visual lock: `04_result_objects_v2.png`.

Implementation status: **R2-UI3 — ACCEPTED / CLOSED**, source commit `dbe580091e40510022a79ffdf2c67da17016ab70`.

Назначение:
аналитик исследует отдельные OOF-объекты, ошибки модели и переход к detail screen.

Основные элементы:
- контекст модели / OOF / числа объектов / целевых событий / текущего threshold / ошибок;
- поиск;
- quick filters;
- дополнительные фильтры;
- сортировка;
- таблица объектов;
- переход по строке к будущему detail screen.
Canonical table fields:
- объект / идентификатор;
- score модели;
- целевое событие;
- положение относительно текущего threshold;
- TP / TN / FP / FN;
- Fold;
- действие перехода к detail.

### 4.1. Целевое событие — marker semantics

Форма marker кодирует только фактический target:
- `●` filled = **Да**;
- `○` hollow = **Нет**.

Цвет marker кодирует classification outcome:
- TP = `●` cyan/teal «Да»;
- FN = `●` restrained pink/red «Да»;
- TN = `○` muted slate/blue-gray «Нет»;
- FP = `○` amber «Нет».

Это единая матрица. Других комбинаций быть не должно.
Tooltip у «Целевое событие» объясняет эту матрицу.

### 4.2. Положение относительно threshold

Отдельная колонка показывает:
- `↑ Выше порога`;
- `↓ Ниже порога`.

Это не success/error semantics и не бизнес-решение.
Цвет threshold position не должен подменять TP/TN/FP/FN.
### 4.3. Fold

Fold остаётся read-only provenance для аналитика на Object Detail. В текущем R2-UI3 list DTO Fold отсутствует, поэтому Objects runtime его не реконструирует и не делает дополнительный per-row lookup только ради совпадения с PNG.

Когда Fold показывается на Object Detail, tooltip должен объяснять:
- Fold — номер части cross-validation, на которой получена OOF-оценка объекта;
- модель для этой оценки обучалась на других folds и не использовала этот объект при обучении;
- Fold нужен для происхождения OOF prediction и связи с моделью, которая его сформировала.

Количество folds на Result не редактируется.
Его настройка относится к upstream Quality configuration.

### 4.4. Scroll / large table UX

Классическая постоянная пагинация не является основным UX.

Принято:
- фиксированная рабочая высота table viewport;
- вертикальная прокрутка колесом / scrollbar;
- sticky table header;
- визуально одна длинная выборка;
- compact position indicator вида `12 481–12 530 из 362 018`;
- быстрый drag scrollbar допустим.

Implementation expectation:
frontend может использовать virtualized/windowed rendering;
backend должен отдавать данные порциями и не требовать загрузки сотен тысяч rows в browser.

Public list contract, server-side filtering/sorting и random-access semantics зафиксированы в `RESULT_V2_ARCHITECTURE_LOCK.md`. Developer не изобретает их из PNG.
### 4.5. Filters and sorting

Принятые пользовательские смыслы:
- «Ошибки модели»;
- «Высокая оценка модели»;
- «Пограничные»;
- «Пропущенные события»;
- «Ложные срабатывания»;
- «Все объекты»;
- target Да/Нет;
- TP/TN/FP/FN;
- score range;
- sorting.

#### Обязательный control «Диапазон оценки модели»

На экране «Объекты оценки» обязательно присутствует явный control **«Диапазон оценки модели»**.

Canonical UX:
- dual-handle slider по диапазону `[0,00; 1,00]`;
- рядом отображаются точные текущие `min_score` и `max_score`;
- обе границы включительные;
- изменение диапазона фильтрует текущий OOF object list через public backend query contract;
- control не меняет score, threshold или модель;
- default state — полный диапазон `0,00–1,00`;
- никаких скрытых cutoffs или автоматической подмены диапазона quick-view пресетами.

Backend semantics уже зафиксирована как `min_score` / `max_score` в `RESULT_V2_ARCHITECTURE_LOCK.md`.
Если текущий visual reference не показывает этот control, это считается известным visual omission: при следующем обновлении макета control нужно вернуть, а не удалять capability из реализации.

Точная backend-supported семантика quick views задана public contract. В принятом R2-UI3 это взаимоисключающие frontend presets: `Ошибки модели → {FP,FN}`, `Пропущенные события → {FN}`, `Ложные срабатывания → {FP}`, `Пограничные → DISTANCE_TO_THRESHOLD_ASC`, `Высокая оценка модели → SCORE_DESC`, `Все объекты → снять quick-view preset`. `Пограничные` и `Высокая оценка модели` очищают quick-view outcomes; это не hidden filtering. Никаких `score >= 0.8`, `threshold ± band` или иных незафиксированных cutoffs нет.

R2-UI3 использует server-side chunks по 50 строк с Previous/Next и compact range indicator. Это допустимая Streamlit V1 реализация принятого offset/limit contract; full Result в UI не загружается. Active Object Detail transition реализован и принят в R2-UI4A. Выбранная строка current server-side chunk переводит exact `object_id` в `OBJECT_DETAIL`; detail повторно читает scientific facts через public `object_detail()` contract. Local Explanation остаётся следующим R2-UI4B.

## 5. Professional analyst principle

AXION — профессиональный инструмент для аналитика.

Правило:
**скрыть сложность ≠ удалить возможность**.

Часто используемые и безопасные controls находятся в основном flow.
Редкие, технические и чувствительные controls могут быть помещены в «Дополнительные» /
«Расширенные настройки», но только если backend реально поддерживает их изменение.

Read-only facts не превращаются в editable controls.
UI не обходит research/protocol invariants ради «гибкости».

## 6. OOF provenance / explainability boundary

Для конкретного OOF object нельзя показывать Local Explanation от другой модели,
если prediction был сформирован fold-specific model.

Canonical invariant:
```text
object → OOF prediction → fold identity → model/artifact identity → explanation identity
```

Artifact/provenance contract зафиксирован в `RESULT_V2_ARCHITECTURE_LOCK.md`.
Universal provider/explanation contract зафиксирован в `UNIVERSAL_MODEL_EXPLAINABILITY_V1.md`.

R2-UI4A foundation уже реализует basic Object Detail: exact object выбирается по opaque `object_id`, подтверждается через `OOFResultService.object_detail()` и показывает DTO facts вместе с Fold provenance. Local Explanation в этом stage намеренно не вызывается.

R2-UI4B — **ACCEPTED / CLOSED**, source commit `06f13a11`. Basic OOF facts остаются доступными сразу; Local Explanation запускается автоматически отдельным вызовом `OOFExplanationService.local()` и использует accepted READY / LOADING / ERROR / DETAILED semantics. Explanation failure не подменяет evidence final/refit моделью и не ломает Object Detail.

R2-UI4C — **ACCEPTED / CLOSED**, source commit `6c8cdd71`. После READY Local Explanation пользователь явно выбирает одну trusted role и запускает `Сформировать объяснение`; до этого provider call не выполняется. Capability берётся из application workflow, OOF path не передаёт `loaded_model_version`, retry переиспользует prepared request, regenerate готовит новый request. LLM failure локален и не меняет OOF/SHAP evidence; backend response text отображается без UI-реконструкции.

R2-UI5 — **ACCEPTED / CLOSED**, source commit `7aef2893`. `GLOBAL_OOF` использует только `OOFExplanationService.global_oof(artifact_id)`, кешируется по artifact, не зависит от threshold и отображает trusted rank + exact `mean_abs_shap` без нормализации и directional semantics. Error/retry локальны, LLM не вызывается.

**Result V2 core UX implementation закрыта** по accepted visual locks и public scientific contracts.

Final/refit model fallback запрещён.

External LLM не запускается автоматически: после READY Local Explanation пользователь явно запускает «Сформировать объяснение», если external-data policy и provider capability это разрешают.
## 7. Source-of-truth priority

Для Result V2:
1. accepted research/backend contracts;
2. accepted Result UX semantics из этого документа;
3. соответствующий PNG visual lock;
4. общий AXION Design System / Brandbook.

Если PNG конфликтует с backend truth:
- не hardcode-ить demo data;
- не подделывать capability;
- сохранить композицию насколько возможно;
- STOP и поднять точное расхождение.

## 8. Что уже зафиксировано и что ещё открыто

Backend architecture Result V2 зафиксирована в `RESULT_V2_ARCHITECTURE_LOCK.md`: ExperimentArtifact V3, fold-model provenance, Local/Global OOF SHAP semantics, threshold read contract и Object List random-access contract.

Object Detail имеет два принятых visual lock:
- `05_result_object_detail_v1.png` — Local Explanation READY, LLM ещё не вызван;
- `06_result_object_detail_llm_v1.png` — та же страница после успешной LLM-интерпретации.

Они фиксируют:
- summary конкретного OOF-объекта;
- deterministic FN/TP/TN/FP explanation;
- Local Explanation success-state в режиме «Кратко»;
- направление вкладов: pink увеличивает model score, cyan уменьшает;
- обязательный агрегат «Остальные признаки»;
- понятную «Начальную оценку модели» как SHAP reference point с info-tooltip;
- LLM entry с выбором роли и явным действием пользователя;
- LLM READY state: «Краткий вывод / Что увеличило оценку / Что уменьшило оценку / Что важно учитывать»;
- действие «Сформировать заново» после успешной интерпретации;
- collapsed «Данные объекта» и «Технические сведения».

LLM-текст обязан опираться только на validated Local Explanation evidence текущего объекта: он не добавляет отсутствующие в SHAP признаки, факты или причинные утверждения.

Пока не имеют отдельного visual lock только дополнительные expanded states:
- expanded «Данные объекта»;
- отдельный expanded technical-detail state, если он реально понадобится при реализации.

Local Explanation LOADING/ERROR, режим `Подробно`, Result Interpreter LOADING/READY/ERROR уже имеют accepted visual lock.

Product semantics detail зафиксированы:
- basic OOF result показывается сразу;
- Local Explanation запускается автоматически;
- loading не блокирует основной экран;
- validated explanation появляется на том же detail;
- explanation failure fail-closed и не подменяется final/refit model;
- LLM запускается только явным действием пользователя;
- UX не ветвится по CatBoost / XGBoost / LightGBM / GBDT Mean.

Открытым остаётся persistence пользовательских threshold scenarios, если для неё позже появится отдельная продуктовая потребность.

## 9. Acceptance для реализации visual layer

Developer должен:
1. использовать актуальные принятые visual lock PNG из списка в начале документа;
2. не хардкодить демонстрационные значения;
3. сохранить semantic colors и marker matrix;
4. не смешивать target fact, threshold position и classification outcome;
5. сохранить Fold provenance;
6. реализовать scrollable/virtualizable object table только через принятый public contract;
7. не обращаться из UI к runner/registry/filesystem internals;
8. не использовать final test для Result exploration;
9. не изобретать SHAP provenance или threshold semantics;
10. при отсутствии backend capability показывать честный unavailable/disabled state и STOP для design gap.
