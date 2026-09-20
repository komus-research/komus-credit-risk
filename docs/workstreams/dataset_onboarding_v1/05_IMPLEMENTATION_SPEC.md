# Implementation Spec — Dataset Onboarding V1

STATUS: READY_FOR_IMPLEMENTATION
OWNER: Technical Coordinator
DATE: 2026-09-19

## 1. Цель

Реализовать backend-этап `Dataset Onboarding V1` для произвольного поддерживаемого табличного файла:

```text
TabularReader
→ TabularSnapshot
→ DatasetInspector
→ DatasetInspectionReport
→ DatasetPreparationAnalyzer
→ DatasetPreparationProposal
→ STOP
```

Результат этапа — только факты и неподтверждённые предложения системы.

## 2. Архитектурная граница

В текущий этап НЕ входят:

- пользовательское подтверждение;
- `DatasetPreparationSpec`;
- `DatasetContract`;
- `FeatureRegistry`;
- `EvaluationPopulation`;
- `PreparedDatasetContext`;
- split/final test;
- запуск моделей;
- Streamlit wizard;
- LLM.

Главный invariant:

```text
FACT != PROPOSAL != CONFIRMED
```

## 3. Разрешённые backend-файлы

Основной scope:

```text
src/komus_risk/data/tabular.py
src/komus_risk/data/inspection.py
src/komus_risk/data/__init__.py
src/komus_risk/preparation/__init__.py
src/komus_risk/preparation/contracts.py
src/komus_risk/preparation/service.py
```

Допустимо минимально изменить:

```text
src/komus_risk/data/ready_dataset.py
```

только если общий низкоуровневый reader реально переиспользуется и публичное поведение `ReadyDatasetAdapter` полностью сохраняется.

Тесты добавлять/изменять только в `tests/` для нового onboarding и регрессии `ReadyDatasetAdapter`.

Документация workstream:

```text
docs/workstreams/dataset_onboarding_v1/STATUS.md
docs/workstreams/dataset_onboarding_v1/05_IMPLEMENTATION_SPEC.md
```

## 4. Что реализовать

### 4.1 TabularReader / TabularSnapshot

Поддержать CSV, XLSX, XLSB, Parquet.

Обязательны:

- проверка существования/формата/параметров чтения;
- защита от duplicate headers;
- SHA-256 исходного файла;
- deterministic snapshot fingerprint с учётом file identity + format + effective read options;
- Excel sheet как часть effective read options;
- отсутствие target/identifier/split/feature semantics в snapshot.

### 4.2 DatasetInspector / DatasetInspectionReport

Analyzer получает только `DatasetInspectionReport`; `DataFrame` и исходный файл ему недоступны.

Для каждой колонки рассчитать факты, перечисленные в `02_BACKEND_DESIGN.md` и `04_ANALYZER_POLICY.md`, включая:

- dtype/logical type + evidence;
- missingness/cardinality;
- constant/unique/near-unique/all-missing;
- `value_counts` только при `unique_non_null_count <= 50`;
- `representation_profile`;
- presentation-safe `safe_examples` и redaction;
- warnings.

Построить `relation_blocks` детерминированно для всех структурно подходящих пар:

```text
binary_reference_column: unique_non_null_count == 2
source_column: 2 <= unique_non_null_count <= 50
```

Block содержит factual joint counts и overlap statistics. Inspector не называет reference target и не утверждает leakage.

### 4.3 DatasetPreparationAnalyzer

Реализовать `04_ANALYZER_POLICY.md` буквально как единственный источник числовых правил:

- нормализация имён;
- fixed token dictionaries;
- structural/missingness rules;
- target candidate gate/scoring;
- positive class только как две неподтверждённые альтернативы;
- identifier gate/scoring;
- target/identifier ambiguity;
- predictor eligibility;
- representation warnings;
- pairwise proxy warnings;
- technical groups;
- confidence;
- reason codes/reasons;
- deterministic tie-breaking и ordering;
- policy identity/hash.

Analyzer не вычисляет новые row-level/pairwise statistics. Если factual evidence отсутствует, соответствующее правило просто не применяется.

### 4.4 DatasetPreparationProposal

Сериализуемый proposal должен содержать как минимум:

- target candidates;
- positive-class candidates;
- identifier candidates;
- proposed column roles;
- proposed technical groups;
- potential leakage-like warnings;
- confidence;
- machine-readable reason codes;
- human-readable Russian reasons;
- evidence;
- analyzer policy id/version/hash;
- snapshot/inspection identity;
- явный `requires_confirmation` для критических предложений.

Не использовать `FeatureUsageStatus` как статус автоматической догадки.

## 5. Ошибки и недостаточность данных

Блокирующие ошибки чтения должны иметь стабильный код и понятное описание. При них snapshot/proposal не строятся.

Физически корректный, но недостаточный файл возвращает анализируемое состояние (`INSUFFICIENT_DATA`/эквивалент по контракту), а не притворяется ML-ready.

Warnings не являются подтверждённой business/scientific semantics.

## 6. Запрещено

Не менять:

- `ExperimentRunner`;
- модели/профили/registry;
- experiment/comparison/artifact semantics;
- final-test semantics;
- Streamlit flow;
- LLM interpreter;
- research protocol.

Не добавлять специальные правила для `Data_final`, `DefMark`, `INN`, `Q_B1_norm`, `Q_B2_norm`.

Не использовать LLM, external API, ML inference, SHAP, feature importance или random.

Не объявлять correlation/proxy warning доказанным leakage или causal fact.

## 7. Тесты

Нужны targeted synthetic tests, покрывающие:

- обычную binary classification таблицу;
- несколько/отсутствие target candidates;
- target-like column с missing;
- несколько/отсутствие identifiers;
- near-unique, constant, all-missing;
- categorical/numeric/boolean/datetime/text/unknown;
- high-cardinality;
- mixed types;
- pairwise proxy warnings;
- duplicate headers;
- empty/header-only dataset;
- unsupported/missing/corrupted source;
- invalid Excel sheet/read options;
- deterministic repeatability;
- existing `ReadyDatasetAdapter` regression.

`Data_final.xlsb` — только reference evidence: generic rules должны поставить `DefMark` в target candidates, а `INN` в identifier candidates. Это не должно достигаться exact-name special cases и не означает confirmation.

## 8. Приёмка

Stage считается реализованным, если:

1. arbitrary supported file проходит `Reader → Inspector → Analyzer → Proposal`;
2. Analyzer получает только report, не `DataFrame`;
3. одинаковый report + policy даёт byte/logically equivalent deterministic proposal;
4. все scoring/threshold/order rules соответствуют `04_ANALYZER_POLICY.md`;
5. никакие confirmed ML contracts не создаются;
6. существующий `ReadyDatasetAdapter` не сломан;
7. UI/Runner/LLM/research semantics не изменены.

## 9. Следующая архитектурная граница

После ACCEPT текущего Stage отдельно открывается:

```text
Confirmation + Context Materialization
→ DatasetPreparationSpec
→ DatasetContract
→ FeatureRegistry
→ EvaluationPopulation
→ PreparedDatasetContext
```

Это не часть текущей реализации.
