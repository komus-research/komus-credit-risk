# Backend Design — Dataset Onboarding V1

STATUS: READY_FOR_COORDINATOR
OWNER: Backend Engineer
LAST_UPDATED: 2026-09-19
SUPERSEDES: none

## PURPOSE

Технический вопрос этого документа:

> Как backend должен детерминированно прочитать новый поддерживаемый табличный файл, описать наблюдаемую структуру данных и сформировать безопасные неподтверждённые предложения о возможных ролях колонок, не превращая автоматические эвристики в подтверждённые dataset/feature semantics?

Dataset Onboarding V1 заканчивается на формировании анализа и предложений системы.

Подтверждение пользователем и материализация подтверждённых контрактов находятся за границей V1.

---

## INPUT / ACTUAL STATE

Дизайн опирается на уже принятую архитектурную границу:

```text
файл
→ физический анализ таблицы
→ отчёт о фактах
→ предложения системы
→ позднее подтверждение пользователя
→ DatasetContract / FeatureRegistry / EvaluationPopulation
```

Существующий ML/backend pipeline уже содержит:

* `ReadyDatasetAdapter`;
* `DatasetContract`;
* `FeatureSpec`;
* `FeatureGroup`;
* `FeatureUsageStatus`;
* `FeatureRegistry`;
* `ModelRegistry`;
* Planning/Application services;
* `ExperimentConfig`;
* `ExperimentRunner`;
* `ArtifactStore`;
* Comparison layer.

Существующий `ReadyDatasetAdapter` обслуживает **уже подготовленный dataset**:

* поддерживает CSV, XLSX, XLSB и Parquet;
* читает физический файл;
* проверяет источник;
* проверяет duplicate headers для поддерживаемых табличных форматов;
* рассчитывает identity/fingerprint;
* принимает уже известные `target_column`, `positive_class`, `identifier_column`;
* формирует подтверждённый `DatasetContract`.

Поэтому `ReadyDatasetAdapter` не расширяется до универсального heuristic analyzer.

`FeatureRegistry` является явным подтверждённым runtime-реестром признаков и групп. Автоматические догадки Dataset Onboarding V1 в него не записываются.

В существующем Streamlit prototype также имеется логика разрешения локального источника данных, однако generic backend Dataset Onboarding не должен зависеть от `app/` или импортировать UI/composition logic.

---

## DECISION / DESIGN

Dataset Onboarding V1 реализуется как последовательность независимых backend-компонентов:

```text
TabularReader
    ↓
TabularSnapshot
    ↓
DatasetInspector
    ↓
DatasetInspectionReport
    ↓
DatasetPreparationAnalyzer
    ↓
DatasetPreparationProposal
```

Разделение ответственности обязательно.

### `TabularSnapshot`

Отвечает только за то, **что физически было прочитано из файла**.

Не содержит подтверждённых ML-смыслов.

### `DatasetInspectionReport`

Отвечает только за **наблюдаемые факты и технические выводы о структуре**:

* schema;
* physical dtype;
* inferred logical type;
* missingness;
* cardinality;
* constant / near-unique;
* безопасные примеры;
* технические предупреждения.

Это не FeatureRegistry и не dataset contract.

### `DatasetPreparationProposal`

Содержит только **гипотезы системы**, например:

* возможные target candidates;
* возможные positive-class candidates;
* возможные identifier candidates;
* proposed column roles;
* proposed technical groups;
* potential leakage warnings;
* confidence;
* reasons/evidence;
* analyzer policy identity.

Proposal не является source of truth.

### Критическое разделение

Пример:

```text
FACT:
колонка содержит два непустых значения: 0 и 1

PROPOSAL:
колонка структурно похожа на возможный binary target

CONFIRMED:
отсутствует в V1
```

Аналогично:

```text
FACT:
значения колонки уникальны или почти уникальны

PROPOSAL:
колонка может быть identifier

CONFIRMED:
отсутствует в V1
```

Автоматический анализ не должен утверждать:

* что `1` является положительным классом;
* что unique column является идентификатором;
* что статистически сильная связь доказывает leakage;
* что имя колонки подтверждает её бизнес-смысл;
* что дата является `observation_date`;
* что признак исторически валиден;
* что correlation/importance означает причинность.

Точные правила, пороги, веса, tie-breaking и сортировка Analyzer V1 определяются отдельным документом:

```text
docs/workstreams/dataset_onboarding_v1/04_ANALYZER_POLICY.md
```

Этот Backend Design их не дублирует.

---

## CONTRACTS

### `TabularSnapshot`

Назначение: immutable/runtime-представление физически прочитанного табличного источника.

Должен содержать как минимум:

* источник;
* физический формат;
* эффективные параметры чтения;
* SHA-256 исходного файла;
* deterministic snapshot fingerprint;
* количество строк;
* количество колонок;
* runtime `DataFrame` либо эквивалентную безопасную runtime-ссылку.

Не содержит:

* target;
* positive class;
* identifier semantics;
* split;
* `FeatureRegistry`;
* `EvaluationPopulation`.

Fingerprint должен учитывать как минимум:

```text
source file identity
+
physical format
+
effective read options
```

Поэтому, например, выбор другого Excel sheet является другим snapshot.

---

### `DatasetInspectionReport`

Назначение: сериализуемый factual report о структуре `TabularSnapshot`.

`DatasetInspectionReport` является **единственным factual input**
для `DatasetPreparationAnalyzer`.

Analyzer не получает `DataFrame`, исходный файл или иной скрытый источник фактов.

Report содержит:

- `snapshot_fingerprint`;
- `inspection_policy_version`;
- `row_count`;
- `column_count`;
- `columns`;
- `relation_blocks`;
- `physical_warnings`.

Для каждой колонки `ColumnInspection` содержит как минимум:

- `column_name`;
- `column_position`;
- `physical_dtype`;
- `inferred_logical_type`;
- `logical_type_evidence`;
- `non_null_count`;
- `missing_count`;
- `missing_fraction`;
- `unique_non_null_count`;
- `unique_fraction`;
- `is_unique`;
- `is_constant`;
- `is_near_unique`;
- `is_all_missing`;
- `value_counts`, если `unique_non_null_count <= 50`;
- `representation_profile`;
- `safe_examples`;
- `examples_redacted`;
- `column_warnings`.

`value_counts` является factual evidence, необходимым Analyzer для
low-cardinality rules. Это не то же самое, что `safe_examples`.

`safe_examples` предназначен для безопасного отображения пользователю.
Analyzer не должен использовать отсутствие `safe_examples` как отсутствие
фактических значений.

`representation_profile` содержит только технические наблюдения,
вычисленные `DatasetInspector`, например:

- `observed_value_type_families`;
- `mixed_value_types`;
- `numeric_all_integral`;
- `numeric_has_fractional_values`;
- `string_all_digits`;
- `median_string_length`.

Эти поля не задают business semantics.

### Pairwise factual relation blocks

Некоторые Analyzer Policy rules требуют совместного распределения двух
колонок. Такие данные нельзя восстановить из per-column marginal statistics.

Поэтому `DatasetInspector` детерминированно формирует `relation_blocks`
для ограниченного набора структурно подходящих пар колонок.

Для каждой колонки с ровно двумя непустыми уникальными значениями она может
выступать как `binary_reference_column`.

Для неё Inspector строит factual relation block с другой колонкой, если
другая колонка имеет от 2 до 50 непустых уникальных значений.

`PairwiseRelationInspection` содержит как минимум:

- `binary_reference_column`;
- `source_column`;
- `overlap_non_null_rows`;
- `coverage_fraction`;
- `joint_counts`;
- `source_value_counts_on_overlap`;
- `reference_value_counts_on_overlap`.

`joint_counts` содержит наблюдаемые количества комбинаций:

`(source_value, reference_value, count)`.

Inspector не называет `binary_reference_column` target и не делает вывод
о leakage.

Он только сохраняет фактическую совместную частотную таблицу, достаточную
для последующего deterministic Analyzer rule.

Relation blocks строятся без ML, correlation, SHAP или causal interpretation.

Таким образом:

DatasetInspector
→ считает factual marginal и pairwise evidence;

DatasetPreparationAnalyzer
→ только применяет Analyzer Policy к этому evidence.

`DatasetInspectionReport` не содержит подтверждённых:

- target;
- positive class;
- identifier;
- FeatureUsageStatus;
- business semantics;
- observation date;
- leakage status.

---

### `DatasetPreparationProposal`

Назначение: сериализуемый набор неподтверждённых предложений analyzer.

Содержит как минимум:

* target candidates;
* positive-class candidates;
* identifier candidates;
* proposed column roles;
* proposed groups;
* potential leakage warnings;
* confidence;
* machine-readable reason codes;
* human-readable reasons;
* evidence;
* analyzer policy identity/version;
* ссылку на snapshot/inspection identity.

Для критических предложений должно быть явно видно, что они требуют последующего подтверждения.

Proposal не создаёт и не изменяет подтверждённые runtime contracts.

---

### Граница с `ReadyDatasetAdapter`

`ReadyDatasetAdapter` остаётся путём для **уже подготовленного и подтверждённого dataset**.

Допустим только узкий рефакторинг общего низкоуровневого физического чтения, если он:

* реально уменьшает дублирование;
* не меняет public API `ReadyDatasetAdapter`;
* не меняет его validations;
* не меняет fingerprint semantics;
* не меняет его существующее поведение.

---

### Граница с `DatasetContract`

`DatasetContract` представляет подтверждённый паспорт dataset и требует уже определённые:

* target;
* positive class;
* identifier;
* feature registry identity;
* validation state.

Dataset Onboarding V1 `DatasetContract` не создаёт.

---

### Граница с `FeatureRegistry`

`FeatureRegistry` хранит явные `FeatureSpec` и `FeatureGroup` без heuristic reassignment.

Dataset Onboarding V1:

* не создаёт `FeatureSpec`;
* не создаёт подтверждённые `FeatureGroup`;
* не назначает `FeatureUsageStatus`;
* не регистрирует автоматические догадки в `FeatureRegistry`.

Для предложений используются отдельные proposal contracts.

---

### Граница с `EvaluationPopulation`

`EvaluationPopulation` относится к уже определённой evaluation population/split semantics.

Dataset Onboarding V1:

* не создаёт population;
* не делает split;
* не определяет working/final-test rows;
* не использует final test.

---

## MODULE BOUNDARIES

Предполагаемое размещение ответственности:

```text
src/komus_risk/
│
├── data/
│   ├── ready_dataset.py
│   ├── tabular.py
│   └── inspection.py
│
└── preparation/
    ├── __init__.py
    ├── contracts.py
    └── service.py
```

### `src/komus_risk/data/tabular.py`

Ответственность:

* поддерживаемые физические форматы;
* параметры чтения;
* physical file validation;
* duplicate-header protection;
* фактическое чтение;
* raw file SHA-256;
* snapshot fingerprint;
* создание `TabularSnapshot`.

Не знает:

* target;
* positive class;
* identifier semantics;
* FeatureRegistry;
* ML training;
* UI.

---

### `src/komus_risk/data/inspection.py`

Ответственность:

* построение `DatasetInspectionReport`;
* per-column physical facts;
* deterministic logical-type inference;
* missing/cardinality statistics;
* constant / near-unique facts;
* safe-example handling;
* physical/structural warnings;
* low-cardinality value counts;
* representation profiles;
* deterministic pairwise relation blocks для policy V1.

`DatasetPreparationAnalyzer` не получает `DataFrame` и не вычисляет новые row-level или pairwise statistics самостоятельно.

Не предлагает подтверждённые ML-роли.

---

### `src/komus_risk/preparation/contracts.py`

Ответственность:

* DTO/enums для Dataset Preparation proposal layer;
* proposal candidates;
* reason/evidence structures;
* proposed roles/groups;
* warnings;
* policy metadata.

Не должен переиспользовать `FeatureUsageStatus` как статус автоматической догадки.

---

### `src/komus_risk/preparation/service.py`

Ответственность:

* deterministic `DatasetPreparationAnalyzer`;
* применение `Analyzer Policy V1`;
* target/identifier/role/group proposals;
* potential leakage warnings;
* confidence/reasons;
* deterministic ordering.

Не занимается чтением файла, Streamlit, ML training или materialization подтверждённых contracts.

---

### `src/komus_risk/preparation/__init__.py`

Только публичные exports preparation layer.

---

### Возможное изменение `src/komus_risk/data/ready_dataset.py`

Допустимо только делегирование общей physical-I/O логики новому низкоуровневому reader.

Обязательный invariant:

> Публичное поведение существующего `ReadyDatasetAdapter` не меняется.

---

## FAILURE SEMANTICS

Dataset Onboarding V1 различает три класса состояний.

### 1. Блокирующие ошибки чтения

Примеры:

* файл не существует;
* путь не является файлом;
* формат не поддерживается;
* параметры чтения невалидны;
* указанный sheet отсутствует;
* файл повреждён или физически не читается;
* duplicate headers делают исходную schema неоднозначной.

При blocking error:

```text
TabularSnapshot не считается валидно построенным
→ inspection не продолжается
→ proposal не строится
```

Ошибки должны иметь:

* стабильный machine-readable code;
* понятное human-readable описание.

---

### 2. Неблокирующие предупреждения

Примеры:

* all-missing column;
* constant column;
* near-unique column;
* mixed/unknown logical type;
* высокая доля пропусков;
* несколько возможных target candidates;
* несколько возможных identifier candidates;
* target-like колонка с пропусками;
* потенциальная leakage-like связь.

Warnings описывают observed risk/ambiguity.

Они **не должны превращаться в доказанный semantic fact**.

Например:

```text
potential_target_proxy
```

означает необходимость проверки происхождения признака, а не установленный leakage.

---

### 3. Недостаточность данных

Файл может быть физически корректным, но не содержать достаточного evidence для meaningful proposals.

Например:

* таблица без строк;
* нет binary target candidates;
* все колонки пусты;
* структура слишком неоднозначна.

Это не обязательно technical exception.

Backend должен иметь возможность вернуть корректный analysis state наподобие:

```text
INSUFFICIENT_DATA
```

с фактами и объяснением, почему предложения не сформированы или ограничены.

---

## PRIVACY / SAFE EXAMPLES

Inspection не должен без необходимости передавать в UI произвольные сырые значения.

Особенно защищаются:

* high-cardinality columns;
* identifier-like columns;
* near-unique columns;
* свободный текст.

Для таких колонок raw examples по умолчанию не публикуются.

Report должен уметь явно сообщить:

```text
examples_redacted = true
```

и при необходимости причину redaction.

Для безопасных low-cardinality технических данных допускается ограниченный набор distinct examples.

Для numeric high-cardinality данных предпочтительнее агрегированные summaries вместо произвольных raw values.

`value_counts` и `relation_blocks` являются внутренним factual evidence, а не автоматическим содержимым UI.

Сырые значения high-cardinality / identifier-like колонок в них не хранятся: relation blocks ограничены колонками с cardinality <= 50.

`safe_examples` остаётся отдельным presentation-safe полем.

Dataset Onboarding V1 не является механизмом классификации персональных данных, но не должен создавать дополнительную ненужную экспозицию содержимого файла.

---

## DETERMINISM

Обязательный контракт V1:

```text
одинаковые file bytes
+
одинаковые effective read options
+
одна и та же версия analyzer policy
=
одинаковый результат analysis/proposal
```

Детерминированными должны быть:

* source identity;
* snapshot fingerprint;
* inspection facts;
* logical-type inference;
* candidate membership;
* warnings;
* confidence;
* reason codes;
* reason ordering;
* proposed groups;
* group membership;
* output ordering;
* proposal serialization;
* analyzer policy identity/hash.

Analyzer не должен зависеть от:

* random;
* LLM;
* ML model inference;
* Streamlit state;
* внешних API;
* недетерминированного `set`/`dict` ordering.

Точные числовые пороги, scoring rules, tie-breaking и sorting rules определяются только в:

```text
docs/workstreams/dataset_onboarding_v1/04_ANALYZER_POLICY.md
```

---

## TEST STRATEGY

### Synthetic fixtures

Минимальный набор synthetic fixtures должен покрывать:

* обычную binary classification таблицу;
* несколько потенциальных targets;
* отсутствие target candidate;
* target-like колонку с пропусками;
* несколько возможных identifiers;
* near-unique колонку, которая не должна автоматически становиться identifier;
* constant column;
* categorical;
* numeric;
* boolean;
* datetime;
* high-cardinality/text;
* suspicious leakage-like column;
* inconsistent naming;
* duplicate headers;
* empty/header-only dataset.

### Форматы

Один physical-reading path должен поддерживать:

* CSV;
* XLSX;
* XLSB;
* Parquet.

Формат-specific различия должны оставаться внутри data/reader layer.

### Ошибочные входы

Должны отдельно проверяться:

* duplicate headers;
* unsupported format;
* missing file;
* invalid read options;
* corrupted/unreadable source;
* invalid Excel sheet.

### Determinism

Повторный анализ одинакового snapshot при одной policy должен давать идентичные:

* candidates;
* scores/confidence;
* reasons;
* warnings;
* groups;
* ordering.

### Regression/reference check на `Data_final.xlsb`

`Data_final.xlsb` используется только как regression/reference evidence.

Ожидание:

* `DefMark` должен оказаться разумным target candidate;
* `INN` должен оказаться разумным identifier candidate.

Запрещены специальные implementation rules:

```text
if column == "DefMark"
if column == "INN"
```

Reference check не должен требовать автоматического подтверждения:

* `DefMark` как final target;
* `INN` как final identifier;
* `1` как positive class.

### Existing-path regression

После возможного выноса общего physical reader существующие tests `ReadyDatasetAdapter` должны оставаться зелёными.

Особенно сохраняются:

* CSV reading;
* XLSX reading;
* XLSB dispatch;
* Parquet reading;
* source fingerprint behaviour;
* duplicate-header checks;
* current validation semantics.

### Не затрагиваемые проверки

Dataset Onboarding V1 не должен требовать изменений:

* `ExperimentRunner`;
* model adapters;
* model registry;
* LLM/interpreter;
* final-test semantics;
* existing experiment artifacts.

---

## INVARIANTS

1. Dataset Onboarding V1 **только анализирует и предлагает**.

2. Target, positive class, identifier и feature semantics не становятся подтверждёнными без будущего явного пользовательского подтверждения.

3. `DatasetPreparationProposal` не является source of truth.

4. Backend Dataset Onboarding не импортирует Streamlit или другую UI-логику.

5. UI не должен самостоятельно реализовывать heuristic analysis.

6. Существующий ML pipeline не меняется.

7. `ExperimentRunner` не участвует в V1.

8. Модели не обучаются и не используются для анализа onboarding.

9. LLM не участвует.

10. Final test не используется.

11. Split/folds/seed/evaluation protocol не определяются.

12. `FeatureRegistry` не наполняется автоматически.

13. `DatasetContract` не создаётся автоматически.

14. `EvaluationPopulation` не создаётся автоматически.

15. Никаких специальных правил только для `Data_final`, `DefMark`, `INN`, `Q_B1_norm` или `Q_B2_norm`.

16. Unique/near-unique является структурным фактом, а не автоматически identifier semantics.

17. Сильная статистическая связь не объявляется доказанным leakage.

18. Logical datetime не объявляется observation date.

19. Название колонки не является доказательством бизнес-смысла.

20. Proposal не удаляет и не преобразует исходные колонки.

---

## OUT OF SCOPE

Dataset Onboarding V1 не проектирует и не реализует:

* Streamlit/UI wizard;
* пользовательское подтверждение;
* `DatasetPreparationSpec` materialization;
* `DatasetContract` creation;
* `FeatureRegistry` creation;
* `EvaluationPopulation` creation;
* split semantics;
* final-test semantics;
* model training;
* hyperparameter tuning;
* imputation;
* encoding;
* feature engineering;
* автоматическое удаление признаков;
* LLM interpretation;
* SPARK integration;
* business semantics proposed groups;
* database;
* production upload service;
* queues/orchestration;
* Docker/infrastructure.

---

## HANDOFF

После принятия:

1. этого Backend Design;
2. отдельного `04_ANALYZER_POLICY.md`;

Coordinator может собрать узкий Implementation Spec для Codex.

Implementation Spec должен реализовать зафиксированные contracts/module boundaries и Analyzer Policy без самостоятельного изменения архитектуры, thresholds, scoring rules или scope V1.

---

## EVIDENCE / REFERENCES

Проверенные существующие repo paths и contracts:

```text
docs/ARCHITECTURE.md
docs/CURRENT_STATE.md

src/komus_risk/hashing.py

src/komus_risk/contracts/dataset.py
src/komus_risk/contracts/feature.py

src/komus_risk/data/__init__.py
src/komus_risk/data/ready_dataset.py

src/komus_risk/registries/feature_registry.py
src/komus_risk/registries/model_registry.py

src/komus_risk/application/contracts.py
src/komus_risk/application/service.py

src/komus_risk/experiments/runner.py

app/bootstrap.py

tests/test_ready_dataset_adapter.py
tests/test_pipeline_contracts.py
tests/test_application_service.py

pyproject.toml
```

Ключевые существующие contracts/components, с которыми сохраняется граница:

```text
ReadyDatasetAdapter
LoadedDataset
DatasetContract

FeatureSpec
FeatureGroup
FeatureUsageStatus
FeatureRegistry

ModelRegistry

ExperimentConfig
ExperimentRunner
EvaluationPopulation

ExperimentArtifactStore
ExperimentComparisonService
```

---

READY_FOR_COORDINATOR
