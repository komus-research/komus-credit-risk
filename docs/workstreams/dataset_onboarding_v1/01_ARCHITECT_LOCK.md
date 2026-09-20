# ARCHITECT LOCK — Dataset Source / Input V1

## PROPOSAL

Следующий минимальный product-stage — **Dataset Source V1**.

Зафиксировать новую границу:

```text
DATASET SOURCE
    ↓
SOURCE RESOLUTION
    ↓
DATASET VALIDATION / PREPARATION PROFILE
    ↓
DATASET CONTRACT + EVALUATION POPULATION
    ↓
PREPARED DATASET CONTEXT
    ↓
FEATURES / MODEL / EXPERIMENT
```

Ключевое решение:

> **Источник данных сообщает, откуда взять данные. Он не решает, можно ли на этих данных проводить ML-эксперимент.**

В V1 поддержать только локальные источники:

* преднастроенный локальный `Data_final`;
* явно выбранный пользователем локальный файл.

При этом **единственным run-ready preparation profile пока остаётся accepted historical profile**. Произвольный новый файл можно выбрать и проверить как источник, но нельзя автоматически превратить в `PreparedDatasetContext`.

Это правильный следующий этап: текущий `HistoricalDatasetProvider` действительно объединяет сразу выбор источника, historical identity, FeatureRegistry, Stage 3 split и создание `PreparedDatasetContext`.

---

## WHY NOW

Сейчас product flow уже работает end-to-end. Следующее реальное ограничение находится не в моделях или UI признаков, а здесь:

```text
"откуда взялись данные?"
        смешано с
"что эти данные означают для эксперимента?"
```

Пока эти понятия объединены, любое расширение на новый dataset создаёт опасное искушение:

```text
новый файл
→ применить historical profile
→ использовать historical working_indices
→ experiment формально работает
```

Это как раз тот случай, который необходимо архитектурно сделать невозможным.

При этом создавать сейчас универсальный Dataset Profile Registry, arbitrary feature onboarding или split builder рано.

---

## WHAT CHANGES FOR USER

На экране **«Данные»** пользователь сначала выбирает **источник**:

```text
Источник данных

● Принятый исторический Data_final
○ Локальный файл
```

Для локального файла пользователь указывает путь **на машине, где запущено приложение**, затем нажимает:

**«Проверить источник»**.

После проверки UI показывает один из двух принципиально разных результатов.

Для exact historical Data_final:

```text
Источник: локальный файл
Dataset: Data_final
Статус: Принятый исторический dataset
Validation: пройдена

Рабочая популяция:
289 614 строк

Protected final test:
72 404 строки
```

Для другого файла:

```text
Источник: локальный файл
Статус источника: доступен

Dataset:
новый пользовательский dataset

ML-контекст:
не подготовлен

Для запуска эксперимента требуется
явная подготовка Dataset Contract,
Feature Registry и Evaluation Population.
```

Кнопка перехода к **«Признаки»** во втором случае disabled.

---

## WHAT DOES NOT CHANGE

Без отдельного решения не меняются:

* accepted `Data_final`;
* SHA/identity validation;
* Stage 3 working population;
* final-test isolation;
* `Q_B1_norm / Q_B2_norm`;
* `FeatureRegistry` semantics;
* модельные profiles;
* `ExperimentConfig`;
* `ExperimentResult`;
* `ArtifactStore`;
* comparison semantics;
* Runner;
* текущий CV/OOF protocol.

Также Dataset Source V1 **не делает новый dataset автоматически обучаемым**.

---

## NEXT ACTION

После этого Lock Technical Coordinator может подготовить одну implementation task:

> **отделить local source resolution от historical dataset preparation, сохранив historical pipeline byte-for-byte/semantically неизменным.**

Следующий product-stage после его ACCEPT — уже отдельный вопрос:

**New Dataset Preparation / Feature Onboarding V1.**

---

# 1. CURRENT DATA FLOW

Текущее фактическое состояние примерно такое:

```text
Streamlit
   ↓
context_id + optional_uploaded_file
   ↓
HistoricalDatasetProvider
   ├─ выбирает default path / temporary uploaded file
   ├─ проверяет accepted SHA
   ├─ создаёт historical FeatureRegistry
   ├─ восстанавливает Stage 3 working split
   ├─ вызывает ReadyDatasetAdapter
   └─ создаёт EvaluationPopulation
   ↓
PreparedDatasetContext
```

То есть `HistoricalDatasetProvider` сейчас является одновременно:

* source resolver;
* dataset profile;
* identity validator;
* feature registry factory;
* population factory;
* context builder.

Для одного historical dataset это было рационально.

Для следующего product-stage ответственности нужно разделить.

---

# 2. PROBLEM

Основная проблема — **scientific identity сейчас слишком близка к file selection**.

Файл сам по себе не сообщает:

* какой у него target;
* какой positive class;
* что является identifier;
* какие признаки разрешены;
* какие diagnostic/blocked;
* есть ли protected final test;
* какие строки относятся к working population;
* откуда произошёл split;
* можно ли сравнивать его с historical experiment.

Текущий `DatasetContract` уже хранит многие из этих semantic attributes — target, positive class, identifier, FeatureRegistry binding, validation status и final-test lock.

А `EvaluationPopulation` отдельно фиксирует конкретные строки, population identity и роль `working/full`.

Следовательно источник файла не должен сам придумывать эти значения.

---

# 3. ARCHITECTURAL DECISION

Канонически разделить **Source** и **Prepared Dataset Context**.

```text
┌─────────────────────┐
│   DATASET SOURCE    │
│ где находятся байты │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ SOURCE RESOLUTION   │
│ доступен ли файл    │
│ формат / размер     │
└──────────┬──────────┘
           ↓
┌────────────────────────────┐
│ DATASET PREPARATION PROFILE│
│ что этот dataset означает  │
└──────────┬─────────────────┘
           ↓
 DatasetContract
 FeatureRegistry
 EvaluationPopulation
           ↓
 PreparedDatasetContext
```

### Dataset Source не знает

* target;
* predictors;
* feature statuses;
* split;
* final-test policy;
* model;
* CV;
* Stage 3;
* Q_B policy.

### Dataset preparation profile не выбирает

* файл через browser;
* GUI;
* Streamlit uploader;
* local dialog.

Он получает уже разрешённый источник.

---

# 4. DATASET SOURCE CONTRACT

V1 нужен **один минимальный source contract**, без универсального registry framework.

Концептуально источник имеет:

```text
source_kind
display_name
runtime locator
```

После resolution:

```text
ResolvedDatasetSource

source_kind
display_name
materialized local path
file name
format
file size
```

`local path` является **runtime locator**, а не scientific identity и не должен входить в experiment identity.

Например:

```text
D:\Projects\komus\data\Data_final.xlsb
```

и:

```text
E:\backup\Data_final.xlsb
```

могут представлять один и тот же dataset, если accepted content identity совпадает.

## Источники V1

Только:

### A. Preconfigured local source

```text
data/raw/Data_final.xlsb
```

относительно repository root.

### B. Explicit local file source

Путь явно задаёт пользователь.

Оба downstream дают один и тот же тип:

```text
ResolvedDatasetSource
```

Никакого поиска по диску.

Никакого определения профиля по:

* имени файла;
* directory;
* sheet name;
* набору похожих колонок.

---

# 5. DATASET VALIDATION / POPULATION RULES

Это главный methodological lock.

## Historical profile разрешён только при exact identity

Accepted historical `EvaluationPopulation` разрешается применять **только если доказано**, что источник — именно accepted `Data_final`.

Минимальная историческая цепочка остаётся:

```text
exact accepted file identity
+ expected dataset shape/schema
+ accepted Stage 3 evidence identity
+ exact working positions identity
+ target alignment
        ↓
historical PreparedDatasetContext
```

Путь к файлу значения не имеет.

### Критическое правило

> **Schema compatibility недостаточна для применения historical split.**

Например:

```text
тот же DefMark
те же 51 колонка
те же названия признаков
те же 362 018 строк
```

но другой content SHA:

```text
≠ historical Data_final
```

Следовательно:

```text
NO historical working_indices
NO accepted historical population
NO silent fallback to full population
```

---

## Новый пользовательский dataset

Для нового dataset Dataset Source V1 заканчивается на:

```text
source resolved
+
source accessible
+
supported physical format
```

После этого:

```text
PREPARED CONTEXT = NOT AVAILABLE
```

Это не ошибка.

Это нормальное product-состояние:

> «Источник данных выбран, но dataset ещё не подготовлен для эксперимента».

---

## Что потребуется новому dataset позднее

Это **не входит в Dataset Source V1**, но boundary должен быть зафиксирован.

Чтобы новый dataset стал run-ready, следующий stage обязан явно определить минимум:

* `dataset_id/version/name`;
* target;
* positive class;
* identifier;
* explicit FeatureRegistry;
* allowed predictors;
* protected/diagnostic/blocked features;
* population definition;
* split/final-test policy;
* population identity/fingerprint;
* validation result.

То есть:

```text
FILE ≠ DATASET CONTRACT
DATASET CONTRACT ≠ EVALUATION POPULATION
```

и:

```text
LoadedDataset alone ≠ PreparedDatasetContext
```

---

# 6. UX FLOW

## Шаг 1 — выбор источника

```text
Данные

Источник:
● Принятый исторический Data_final
○ Другой локальный файл
```

### Historical

Пользователь может использовать default repository source без ввода пути.

### Local file

Пользователь указывает путь на машине, где выполняется Streamlit.

Например:

```text
D:\Data\client_dataset_2026.parquet
```

UI явно сообщает:

> Путь относится к машине, на которой запущено приложение.

---

## Шаг 2 — source validation

Показывать:

* источник;
* имя файла;
* формат;
* размер;
* доступность.

Не показывать на основном уровне:

* SHA;
* registry hash;
* population fingerprint.

Они могут быть в **«Технические детали»**.

---

## Шаг 3 — preparation status

### Accepted historical

```text
✓ Dataset подтверждён
✓ Historical profile применён
✓ Working population подтверждена
✓ Final test защищён
```

Можно идти к признакам.

### Arbitrary dataset

```text
✓ Файл доступен
○ Dataset context не подготовлен

Этот источник ещё нельзя использовать
для ML-эксперимента.
```

Признаки/model/run disabled.

---

## Browser upload decision

### 1. `file_uploader`

Не выбираем как canonical V1.

Причины:

* данные идут browser → Python process;
* большие файлы бессмысленно копируются через browser;
* есть отдельный Streamlit upload limit;
* появляются временные файлы и лишняя memory/I/O semantics;
* этот механизм плохо соответствует локальному research/product prototype с большими datasets.

### 2. Local path

**Выбираем для V1.**

Плюсы:

* нет browser upload;
* нет ≈200 MB product bottleneck;
* pandas/adapter читает файл напрямую;
* хорошо соответствует текущему локальному deployment;
* источник отделяется от dataset semantics.

### 3. Future provider/source

Архитектура должна позволить позже:

```text
LocalFileSource ───┐
                   │
SparkSource ───────┼→ Resolved / Materialized Source
                   │
OtherSource ───────┘
```

Но сейчас реализуется только Local File.

### Вердикт по uploader

> **`file_uploader` больше не является основным working-dataset path. Dataset Source V1 использует прямой local-file source.**

Не нужно ради этого строить собственный OS file dialog. Для Prototype V1 достаточно явного пути.

---

# 7. SCOPE

## IN

Dataset Source V1:

* source vs context separation;
* explicit local-file source;
* existing default historical path как preconfigured local source;
* source validation;
* historical profile получает resolved source;
* exact historical identity gate;
* новый файл может быть recognized as source;
* новый файл без preparation context не проходит дальше;
* понятный UX status.

## Boundary с Feature Onboarding

Dataset Source V1 отвечает только на вопрос:

> **«Откуда взять dataset?»**

Future Dataset Preparation / Feature Onboarding отвечает:

> **«Что в этом dataset является target, identifier и разрешёнными predictors, и какую population разрешено оценивать?»**

Это две разные задачи.

Не смешивать их в одном Stage.

---

# 8. INVARIANTS

1. Exact accepted `Data_final` остаётся тем же baseline.

2. Accepted Stage 3 working population используется **только** с exact historical dataset identity.

3. Изменение пути файла не меняет scientific identity.

4. Изменение содержимого файла запрещает historical split.

5. Arbitrary file никогда не получает historical `EvaluationPopulation` по schema similarity.

6. Dataset Source не создаёт FeatureRegistry.

7. Dataset Source не создаёт EvaluationPopulation.

8. Dataset Source не определяет target/identifier.

9. Dataset Source не решает final-test policy.

10. UI не определяет scientific validity.

11. `PreparedDatasetContext` остаётся atomic run-ready bundle:

```text
LoadedDataset
+ FeatureRegistry
+ EvaluationPopulation
```

12. `Q_B1_norm / Q_B2_norm` historical policy не меняется.

13. ML-core не знает Streamlit, browser upload, GUI или SPARK.

14. `ExperimentConfig`, Runner, ArtifactStore и Comparison не меняются ради Dataset Source V1.

---

# 9. NON-GOALS

Не включать:

* arbitrary dataset onboarding;
* создание FeatureRegistry из колонок;
* автоматический выбор predictors;
* schema inference → MODEL_ALLOWED;
* split builder;
* automatic full-population fallback;
* train/test split UI;
* final-test configuration UI;
* SPARK;
* browser/cloud storage;
* DB;
* auth;
* Docker;
* background jobs;
* production deployment;
* arbitrary feature engineering;
* model onboarding;
* новые research experiments;
* изменение historical protocol.

---

# 10. ACCEPTANCE CRITERIA

Dataset Source V1 принимается, если:

1. Default historical `Data_final` продолжает создавать тот же run-ready historical context.

2. Accepted local copy `Data_final` из другого filesystem path также проходит historical identity checks.

3. UI и preparation layer не определяют historical dataset по filename.

4. Файл с именем `Data_final.xlsb`, но изменённым содержимым, **не получает historical context**.

5. Schema-compatible, но другой dataset **не получает Stage 3 indices**.

6. Explicit local path может быть выбран без browser upload.

7. Большой local dataset не обязан проходить через Streamlit upload memory.

8. Arbitrary local file может быть успешно resolved как source, но получает статус:

```text
context_not_prepared
```

и не допускается к Feature/Model/Run.

9. Dataset Source не создаёт FeatureRegistry или EvaluationPopulation.

10. Historical profile остаётся единственным run-ready profile V1.

11. Existing historical Streamlit end-to-end flow не меняет scientific result.

12. Final test остаётся недоступным для feature/model selection.

13. Ошибка source-level ясно отличается от отсутствия preparation profile:

```text
Файл не найден
```

не равно:

```text
Файл найден, но dataset context ещё не подготовлен
```

14. UI не содержит hidden hardcoded feature/model behavior.

15. Future source типа SPARK можно добавить до preparation boundary без изменения ML-core.

---

# 11. RISKS

### Risk 1 — пользователь ожидает, что любой файл сразу можно обучать

UX должен явно разделять:

**«Файл выбран»** и **«Dataset готов к эксперименту»**.

---

### Risk 2 — local path в будущем не работает в remote deployment

Это осознанное ограничение V1.

В локальном Prototype:

```text
browser
и
Streamlit process
```

фактически относятся к пользовательской рабочей машине.

Для server/cloud позже потребуется отдельный source provider. Сейчас его не строим.

---

### Risk 3 — случайное переиспользование historical population

Это BLOCKER-класс риска.

Защита:

> historical population разрешена только после exact historical identity gate.

---

### Risk 4 — Dataset Source abstraction начинает превращаться в Dataset Platform

Не допускать.

V1 — только:

```text
source selection
+
source resolution
+
handoff to preparation
```

Без source catalog DB, plugins framework, storage manager и т.п.

---

### Risk 5 — два набора validation logic

Source layer проверяет только physical/source validity.

Dataset preparation владеет semantic/scientific validation.

Не дублировать проверки `DatasetContract` в UI.

---

# 12. MINIMAL DEVELOPER HANDOFF OUTLINE

Это **не Codex task**, а граница будущего handoff.

Coordinator должен будет сформулировать одну узкую задачу:

**Goal**

Отделить local dataset source resolution от historical dataset preparation.

**Required behavior**

* default repository Data_final → local source → historical preparation → прежний `PreparedDatasetContext`;
* explicit local path → local source;
* exact Data_final copy → historical context;
* другой dataset → source resolved, context unavailable;
* historical split никогда не применяется к другому dataset;
* browser upload не является canonical working-dataset path.

**Do not touch**

* Runner;
* model adapters/profiles;
* ExperimentConfig/Result;
* comparison;
* persistence;
* research protocol;
* Stage 3 evidence;
* FeatureRegistry semantics.

**Verification focus**

* accepted historical regression;
* wrong-identity dataset cannot receive historical population;
* arbitrary local source stops safely before ML.

---

## ARCHITECT DECISION

Граница:

```text
DATASET SOURCE
    ↓
DATASET PREPARATION
    ↓
PREPARED DATASET CONTEXT
```

**принята.**

Самое важное правило этого Stage:

> **Источник отвечает только за получение конкретных данных. Право использовать target, features, working population и final-test policy возникает только после явной dataset preparation/validation. Ни filename, ни schema similarity, ни пользовательский выбор файла не дают права применять historical research protocol.**

## READY_FOR_TECHNICAL_COORDINATOR
