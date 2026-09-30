# Result UX V2 — UX / VISUAL LOCK

Status: **UX / VISUAL LOCK — ACCEPTED / BACKEND ARCHITECTURE LOCKED**

Primary visual references:
- `docs/design/screens/result/02_result_model_overview_v2.png`
- `docs/design/screens/result/03_threshold_explorer_v1.png`
- `docs/design/screens/result/04_result_objects_v1.png`

Эти PNG фиксируют композицию, визуальную иерархию и пользовательский поток Result V2.
Фактические данные, доступность действий, persistence, provenance и API semantics определяются только принятыми backend/research contracts.

## 1. Result V2 flow

Canonical flow шага Result:

```text
Результат модели
→ Исследование порога
→ Объекты оценки
→ Объект оценки
→ Local SHAP
→ LLM-интерпретация, если поддерживается
```

Первые три экрана имеют принятый visual lock.
Detail screen объекта, Local SHAP и LLM presentation пока не считаются visual lock.

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

## 4. Экран «Объекты оценки»

Visual lock: `04_result_objects_v1.png`.

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

Fold остаётся видимым read-only provenance для аналитика.

Tooltip должен объяснять:
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

Точная backend-supported семантика «пограничные», «высокая оценка модели» и иных derived filters
должна быть задана public contract. UI не придумывает скрытые формулы.

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

Для конкретного OOF object нельзя показывать Local SHAP от другой модели,
если prediction был сформирован fold-specific model.

Canonical invariant:
```text
object → OOF prediction → fold identity → model/artifact identity → explanation identity
```

Точный artifact/public contract определяется Architect.
До принятия такого решения Developer не делает shortcut через final/refit model.
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

Пока не считаются visual/product lock:
- detail screen конкретного объекта;
- presentation Local SHAP на detail screen;
- LLM presentation на detail screen;
- persistence пользовательских threshold scenarios, если для неё позже появится отдельная продуктовая потребность.

## 9. Acceptance для реализации visual layer

Developer должен:
1. использовать три текущих visual lock PNG;
2. не хардкодить демонстрационные значения;
3. сохранить semantic colors и marker matrix;
4. не смешивать target fact, threshold position и classification outcome;
5. сохранить Fold provenance;
6. реализовать scrollable/virtualizable object table только через принятый public contract;
7. не обращаться из UI к runner/registry/filesystem internals;
8. не использовать final test для Result exploration;
9. не изобретать SHAP provenance или threshold semantics;
10. при отсутствии backend capability показывать честный unavailable/disabled state и STOP для design gap.
