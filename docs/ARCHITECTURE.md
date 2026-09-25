# Архитектура

## Статус документа

Актуальная архитектурная основа проекта. Фиксирует границы ответственности и направление развития, но не требует создавать инфраструктуру заранее.

## 1. Главный принцип

Проект развивается из исследования в инструмент без переписывания ML-логики.

Целевой поток:

```text
notebooks
   ↓
reusable data / feature / ML logic
   ↓
ExperimentRunner
   ↓
ExperimentResult
   ├─ explainability
   ├─ artifacts
   ├─ business policy evaluation
   └─ LLM interpretation
   ↓
backend
   ↓
future frontend
```

Notebook рассказывает исследование. ML-core выполняет вычисления. Backend вызывает ML-core. Frontend управляет backend и отображает результат.

## 2. Архитектурные принципы

1. **Разделение ответственности.** Один модуль — одна понятная причина для изменения.
2. **Research first, reuse second.** Новая гипотеза сначала проверяется в notebook; стабильная повторяемая логика выносится в Python-модуль.
3. **Нет дублирования ML-логики.** Метрики, split, feature filtering, training и explanations не копируются отдельно для notebook/API/UI.
4. **Конфигурация явная.** Model, features, seed, folds, threshold и business policy не прячутся в глобальных переменных.
5. **Артефакт важнее stale output.** Результат считается существующим только при сохранённой конфигурации/metadata и проверяемом происхождении.
6. **Final test изолирован от выбора.** Research layer не должен случайно использовать final test для model selection.
7. **CPU — first-class requirement.** Время и ресурсы измеряются наравне с качеством.
8. **Explainability — first-class component.** Объяснение не добавляется декоративно в самом конце.
9. **Business policy отделена от model training.** Threshold, стоимости ошибок и ручная ёмкость меняются без переобучения.
10. **LLM отделена от кредитного решения.** Она интерпретирует уже рассчитанные результаты и не меняет их.
11. **Никакой сложной инфраструктуры без текущей необходимости.** БД, Docker, очередь задач и orchestration появляются только когда возникает проверяемая потребность.

## 3. Минимальная структура репозитория

Структура вводится постепенно. Целевая ранняя форма:

```text
komus-credit-risk/
├── README.md
├── .gitignore
├── docs/
├── notebooks/
│   ├── baseline/
│   └── research/
├── src/
│   └── komus_risk/
├── configs/
├── tests/
├── data/
├── artifacts/
└── reports/
```

Пустые каталоги не создаются только ради красоты. Они появляются вместе с первой реальной ответственностью.

## 4. `notebooks/`

Назначение — исследовательский narrative.

Предпочтительный паттерн:

```text
Markdown: исследовательский вопрос
↓
Code: контролируемый эксперимент
↓
Markdown: факты / интерпретация / ограничения / следующий вопрос
```

### `notebooks/baseline/`

Только frozen исторические ноутбуки и их документация. Они не являются местом текущей разработки.

Historical baseline №06 должен храниться как неизменяемая reference-копия, если политика хранения позволяет поместить сам notebook в Git. Исходный `Data_final.xlsb` в Git не помещается.

### `notebooks/research/`

Текущие исследовательские итерации. Notebook не должен содержать копии большой стабильной функции, уже существующей в `src/`.

## 5. `src/komus_risk/`

Модули создаются по мере появления реальной повторяемой логики.

Планируемые ответственности:

### `data`

- чтение поддерживаемых форматов;
- schema validation;
- dataset identity/SHA-256;
- базовые проверки target/identifier;
- подготовка безопасного ML-frame.

Не знает про UI и не обучает модели.

### `features`

- именованные `FeatureSet`;
- allow/deny rules;
- feature provenance;
- добавление и вычисление новых признаков;
- защита от `Q_B1_norm`/`Q_B2_norm` в frozen historical working scenario.

Не выбирает threshold и не считает бизнес-стоимость.

### `models`

- единый model registry;
- фабрики/адаптеры CatBoost, XGBoost, LightGBM и будущих кандидатов;
- train/predict contract;
- сериализация модели по необходимости.

Каждый adapter скрывает библиотечные особенности, но не меняет evaluation protocol.

### `evaluation`

- CV/OOF;
- ROC-AUC/Gini/PR-AUC;
- Precision/Recall/F1;
- confusion matrix;
- calibration/Brier;
- bootstrap/seed stability;
- runtime measurement;
- общий формат metrics.

Evaluation level всегда маркируется явно.

### `explainability`

- SHAP;
- permutation importance;
- глобальные объяснения;
- локальные объяснения;
- унифицированный `ExplanationResult`.

Не делает причинных выводов.

### `experiments`

- `ExperimentConfig`;
- `ExperimentRunner`;
- orchestration одного контролируемого запуска;
- связь model + feature set + evaluation + artifacts;
- `ExperimentResult`.

Это центральная точка, которую впоследствии вызывают и notebook, и backend.

### `business`

Появляется, когда будет реализован business-scenario layer.

Ответственность:

- threshold evaluation;
- `CostPolicy`;
- `ManualReviewPolicy`;
- расчёт FP/FN cost;
- расчёт review volume/human-hours;
- выбор threshold по утверждённой политике или ограничению.

Не переобучает модель.

### `artifacts`

- manifest;
- metadata;
- безопасные deterministic paths;
- сохранение configs/metrics/predictions/models;
- SHA-256 sidecars/идентификаторы;
- проверка reload там, где это нужно.

### `interpretation`

- провайдер-независимый интерфейс `ResultInterpreter`;
- формирование structured context;
- OpenAI/local implementation при наличии разрешения;
- cache/metadata;
- human-readable report.

LLM получает business constraints вместе с ML results.

## 6. Концептуальные контракты

Точные классы не создаются заранее, но границы фиксированы.

### `ExperimentConfig`

Должен в перспективе описывать:

- dataset reference/hash;
- target;
- feature set;
- model id;
- model params;
- split/CV protocol;
- seed;
- evaluation options;
- artifact policy.

### `ExperimentResult`

Должен в перспективе содержать:

- experiment id/signature;
- metrics;
- OOF/predictions reference;
- runtime;
- model metadata;
- feature schema;
- evaluation level;
- artifact references;
- explanation references;
- warnings/limitations.

### `BusinessPolicy`

Не входит в параметры обучения.

Содержит по мере реализации:

- threshold mode;
- `C_FN`;
- `C_FP` или ratio;
- manual review cap;
- review minutes per company;
- period/capacity context.

Один и тот же `ExperimentResult` должен можно пересчитывать под разные `BusinessPolicy` без retraining.

## 7. Model registry

Notebook №06 уже доказал полезность единого registry. Новая реализация должна сохранить идею, но вынести её из Colab-specific state.

Model registry отвечает за:

- доступные модели;
- безопасные default параметры;
- поддерживаемые параметры;
- создание estimator/adaptor;
- метаданные о возможностях модели.

Frontend в будущем получает доступные модели из registry, а не держит свой список вручную.

## 8. Feature registry и ограничения

Feature set должен быть объектом конфигурации, а не случайным списком в ячейке notebook.

Нужны уровни:

- historical/reference features;
- allowed working features;
- forbidden final features;
- experimental features.

В frozen historical Data_final profile `Q_B1_norm` и `Q_B2_norm` доступны только в historical/reference-сценариях; generic preparation не применяет name-based restriction.

## 9. Evaluation protocol

Для сравнения моделей сохраняются одинаковые:

- dataset identity;
- working/final partition;
- folds;
- seed;
- preprocessing;
- feature set;
- metrics.

Если один из этих элементов отличается, сравнение должно быть явно помечено как несопоставимое или частично сопоставимое.

## 10. Final test gate

Архитектура должна минимизировать риск случайного использования final test.

До выбора решения доступны working train/CV/OOF/validation artifacts.

Final test вызывается отдельным явно маркированным путём только после фиксации кандидата.

Результат final test не возвращается обратно в tuning/feature selection loop.

## 11. Business policy layer

Модель выдаёт probability. Решение строится отдельным слоем:

```text
probability
   +
BusinessPolicy
   ↓
decision scenario
```

`BusinessPolicy` может быть изменена пользователем во frontend без переобучения модели.

Поддерживаемые концепции:

- manual threshold;
- cost-optimal threshold при утверждённой cost function;
- relative FN/FP ratio;
- maximum manual review volume;
- maximum review human-hours;
- комбинированные ограничения в будущем.

## 12. Explainability flow

```text
trained model + feature values
          ↓
   explainability
          ↓
ExplanationResult
          ├─ global
          └─ local
```

`ExplanationResult` используется и notebook, и backend, и LLM interpreter.

LLM не пересчитывает SHAP и не создаёт «важность» из текста.

## 12.1. Integration V1 — ModelVersion, inference и local explanation

Принятая application-chain отделяет исследовательский результат от deployable model artifact:

```text
ExperimentArtifact
      ↓ explicit final fit
ModelVersion
      ↓ load + verify
LoadedModelVersion + TabularSnapshot
      ↓
PredictionBatch
      ↓ selected row
LocalExplanationEvidence
```

Инварианты:

- `ExperimentArtifact != ModelVersion`;
- `ModelVersion` создаётся отдельным explicit action и фиксирует trusted model/feature/dataset/code identity;
- generic inference не содержит hardcoded `INN`, `DefMark` или конкретных feature names;
- identifier берётся из сохранённого `DatasetContract`;
- duplicate identifier values допустимы; строка различается через row identity/source position;
- canonical inference output — probability, threshold decision является отдельной policy;
- local explanation использует ту же загруженную модель и те же validated feature values, что и prediction;
- local explanation является capability. В V1 CatBoost поддерживает native Local SHAP; отсутствие explainer для другой модели не блокирует inference;
- CatBoost SHAP фиксируется в `raw_margin` и проверяется additivity.

Новая модель подключается через adapter/capability boundary, а не через hardcoded ветвления во frontend или application core.

## 13. LLM boundary

```text
LocalExplanationEvidence
        ↓
ResultInterpreterService
        ↓
ResultInterpreterRequest
        ↓
ResultInterpreterClient
        ↓
provider adapter
        ↓
ResultInterpreterResponse
```

Инварианты:

- Result Interpreter model-independent и не знает конкретный model/explainer;
- probability и SHAP поступают как готовые факты и не пересчитываются;
- SHAP не трактуется как причинность;
- отсутствие trusted description не разрешает выдумывать бизнес-смысл feature;
- request semantic contents защищены deterministic `request_hash`;
- failure LLM/provider не инвалидирует prediction или `LocalExplanationEvidence`;
- provider — заменяемая реализация; ML/application core не содержит OpenAI/Yandex/Qwen-specific кода.

Текущий OpenAI adapter является одной реализацией `ResultInterpreterClient`: model name задаётся конфигурацией, вызов Responses API выполняется с `store=False`. Это не означает Zero Data Retention.

При внешнем API реальные client identifiers/feature values не отправляются без отдельного подтверждённого data-sharing/redaction policy.

## 14. Артефакты

Для важного эксперимента сохраняются как минимум:

- config;
- dataset hash;
- feature schema;
- split/fold metadata;
- parameters;
- metrics;
- runtime;
- library versions;
- experiment signature;
- status/manifest;
- explanation artifacts при наличии.

Исследовательские артефакты делятся на четыре понятных слоя:

- `reports/summary/` — компактные проверенные summaries для восстановления выводов;
- `reports/generated/` — машинно-читаемые результаты запуска, таблицы, диагностические checkpoints и другие артефакты, необходимые для воспроизводимости и повторного анализа;
- `reports/figures/` — отдельные графики/таблицы-изображения, которые поддерживают исследовательские выводы и могут использоваться в отчёте или презентации;
- `reports/presentation/` — при необходимости итоговый отобранный набор материалов непосредственно для защиты.

Эти каталоги **не игнорируются целиком** и могут храниться в Git. Для новых экспериментов важные графики должны по возможности сохраняться отдельным файлом с понятной связью со Stage/версией, а не существовать только как embedded notebook output.

Тяжёлые model binaries/checkpoints и исходный dataset по-прежнему хранятся вне обычного Git и связываются с экспериментом метаданными. Если отдельный generated artifact становится чрезмерно большим, решение о его хранении принимается отдельно, а не через blanket-ignore всего `reports/`.

## 15. Git и данные

В Git хранятся:

- исходный код;
- исследовательские notebooks с сохранёнными outputs, когда это нужно для доказательности;
- docs;
- configs;
- tests;
- `reports/summary/`;
- проверенные machine-readable артефакты из `reports/generated/`, если их размер разумен;
- графики и таблицы из `reports/figures/`;
- итоговые presentation assets из `reports/presentation/`;
- схемы и manifests.

В Git по умолчанию не хранятся:

- `Data_final.xlsb` и другие тяжёлые raw/derived табличные файлы (`*.xlsb`, `*.parquet`, `*.feather`, `*.arrow`);
- секреты и локальные environment-файлы;
- `.venv`;
- caches/logs/temp-файлы;
- тяжёлые models/checkpoints;
- архивы `*.zip`.

Текущее исключение raw dataset связано прежде всего с размером и тем, что его идентичность уже фиксируется SHA-256. Если в проекте позже появляются действительно чувствительные данные, перед их использованием в Git вводится отдельное явное правило в `.gitignore` и документации; отсутствие такого правила нельзя трактовать как разрешение автоматически публиковать новые чувствительные данные.

## 16. Backend evolution

Backend появляется после устойчивого `ExperimentRunner`.

Первая версия может быть FastAPI, но выбор технологии фиксируется только когда начинаем соответствующий этап.

Backend должен:

- валидировать запрос;
- формировать/принимать config;
- вызвать application/experiment service;
- вернуть DTO/result;
- не содержать обучения и расчёта метрик внутри route handler.

## 17. Frontend evolution

Frontend использует application-facing contracts и не знает внутренностей библиотек CatBoost/XGBoost/LightGBM или конкретного LLM provider.

Для Integration V1 принят тонкий application facade:

`IntegrationWorkflowService`

Он оркестрирует уже принятые services/stores и концептуально предоставляет frontend операции:

- `save_model(...)`;
- `predict(...)`;
- `explain(...)`;
- `interpret(...)`;
- `capabilities(...)`.

`streamlit_app.py` не работает напрямую с `ModelVersionStore`, native predictors, `LocalExplanationService`, OpenAI client, provider credentials или model-specific ветвлениями.

Capability contract достаточен в форме `CapabilityStatus(state, reason_code)` со состояниями:

- `AVAILABLE`;
- `WAITING_FOR_INPUT`;
- `UNSUPPORTED`;
- `DISABLED`;
- `MISCONFIGURED`.

Capability проверяется отдельно для:

- final model save;
- inference;
- local explanation;
- result interpretation.

Неподдерживаемая capability справа по цепочке не инвалидирует уже рассчитанный результат слева.

Верхнеуровневый Streamlit flow остаётся:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`.

Новый top-level экран для inference/LLM не создаётся. На `Результат` добавляется последовательный блок **«Применить модель к новым данным»**.

Минимальный downstream session-state:

- active ModelVersion;
- inference snapshot;
- PredictionBatch;
- selected prediction row_id;
- LocalExplanationEvidence;
- ResultInterpreterRequest/Response;
- interpreter error.

Invalidation идёт только вниз по цепочке: новая model version очищает inference и ниже; новый inference batch очищает row/SHAP/interpreter; новая row очищает SHAP/interpreter; LLM failure ничего выше себя не очищает.

UI-компоненты:

- model selector;
- feature selector;
- params form;
- threshold/cost policy controls;
- manual review capacity controls;
- metrics comparison;
- explanations;
- artifact/reproducibility panel.

### External interpretation boundary

Stage III-C2a / External Data Boundary принят Reviewer.

Полный внутренний `ResultInterpreterRequest` сохраняется без урезания и сначала проходит проверку `request_hash`. После этого отдельная outbound policy строит provider-safe payload.

В III-C2 внешний provider по умолчанию отключён: `EXTERNAL_DATA_POLICY=DISABLED`.

Без configured policy provider call не выполняется. Один пользовательский checkbox не является достаточным организационным разрешением.

Defense-ready режим `REDACTED_V1` реализован как **positive allowlist projection**, а не blacklist/delete.

Во внешний provider допускаются только:

- `prediction.probability`;
- `explanation.shap_output_space`;
- для top features: `feature_id`, `column_name`, `shap_value`, `abs_rank`, optional trusted `description_ru`.

Не передаются:

- identifier column/value;
- `row_id`;
- raw feature values;
- evidence/model provenance;
- `raw_model_output`;
- `base_value`.

`ProviderDispatchReceipt` связывает полный `source_request_hash`, policy id/version и deterministic `provider_payload_hash`. Полный raw external sharing до защиты не реализуется.

Следующий этап III-C2b подключает runtime configuration, capability и UI только через уже принятую policy boundary.

## 18. Хранение истории

Требование 3/5 лет учитывается как будущая capability.

До появления реальной необходимости структурированное хранение experiments может использовать файловые artifacts + manifests. Production-БД вводится только отдельным архитектурным решением.

## 19. Тестирование

Минимальная стратегия по мере появления `src/`:

- unit tests для metrics/business calculations/feature restrictions;
- deterministic tests для split/signatures;
- model adapter smoke tests на малом sample;
- artifact save/reload tests;
- integration test одного дешёвого experiment path.

Дорогой полный ML-прогон не должен быть единственным способом проверить инженерное изменение.

## 20. Что сознательно не строим сейчас

- production DB;
- Docker только «потому что так принято»;
- task queue;
- distributed training;
- model registry server;
- MLflow/DVC без доказанной необходимости;
- полноценный frontend до experiment core;
- сложную microservice-архитектуру.

Сначала нужен корректный воспроизводимый baseline и общий experiment contract.

## Dataset Preparation V1

Принятая цепочка подготовки произвольного датасета:

`Tabular source → TabularSnapshot → DatasetInspectionReport → DatasetPreparationProposal → Human Confirmation → materialization → PreparedDatasetContext → Planning / Application / Runner`.

Границы уровней явные:

- **FACT** — snapshot и factual inspection;
- **PROPOSAL** — детерминированные кандидатные роли без runtime semantics;
- **CONFIRMED** — явное решение специалиста о target, positive class, identifier и status каждой physical column;
- **RUNTIME** — DatasetContract, FeatureRegistry, EvaluationPopulation, PreparedDatasetContext и deterministic manifest.

Proposal не является fallback для confirmation. Для arbitrary dataset V1 материализуется полная популяция OOF без automatic protected final test или другого split. Final semantic/predictor validation выполняется по loaded dataframe, который входит в PreparedDatasetContext; snapshot сохраняет physical/provenance identity.

## Generic Prepared Dataset Boundary

`PreparedDatasetContext` является точкой схождения допустимых путей подготовки данных.

До этой границы могут существовать разные preparation adapters:

- generic dataset: inspection → proposal → human confirmation → materialization;
- frozen compatibility profile принятого historical baseline.

После получения `PreparedDatasetContext` downstream не ветвится по признаку «historical / arbitrary».

Общий путь:

`PreparedDatasetContext → Признаки → Модель → Эксперимент → Результат`.

Filename, конкретное имя target, identifier или business-specific feature name не являются основанием для generic downstream behavior.

Historical `Data_final` сохраняется как compatibility adapter для воспроизводимости старого исследования, а не как основной product mode.

## Dataset History / Persistence — architecture direction

Persistence исследовательской истории является отдельным application-layer направлением и не меняет scientific contracts Dataset Preparation.

Инварианты:

- exact dataset identity определяется содержимым, а не filename/path;
- сохранённая preparation переиспользуется только при доказанной совместимости dataset identity и relevant rule/contract versions;
- изменение правил анализа не удаляет историю, но может сделать старый inspection неактуальным;
- сохранённые experiments остаются evidence своих исходных условий;
- comparison учитывает dataset и evaluation compatibility;
- similarity разных dataset не даёт права автоматически переносить `CONFIRMED` semantics;
- similarity reuse допускается только как `PROPOSAL / DRAFT`.

Физическое хранилище пока не фиксируется.

Production DB, MLflow/DVC, orchestration и другая тяжёлая инфраструктура не вводятся без отдельной необходимости.
