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
- защита от запрещённых `Q_B1_norm`/`Q_B2_norm` в рабочих сценариях.

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

`Q_B1_norm` и `Q_B2_norm` разрешены только в historical/reference-сценариях.

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

## 13. LLM boundary

```text
ExperimentResult
BusinessRules snapshot
ExplanationResult
        ↓
ResultInterpreter
        ↓
InterpretationReport
```

Провайдер — заменяемая реализация.

ML-core не импортирует OpenAI/Yandex/Qwen-specific код.

При внешнем API идентификаторы/сырые данные не отправляются без отдельного разрешения.

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

Тяжёлые models/checkpoints/raw datasets хранятся вне обычного Git и связываются с экспериментом метаданными.

## 15. Git и данные

В Git хранятся:

- исходный код;
- notebooks, если в них нет запрещённых данных;
- docs;
- configs;
- tests;
- небольшие метрики/metadata;
- схемы и manifests.

В Git не хранятся:

- `Data_final.xlsb`;
- сырые выгрузки СПАРК;
- секреты;
- `.venv`;
- caches;
- тяжёлые models/checkpoints;
- неотфильтрованные пользовательские/клиентские данные.

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

Frontend использует backend-контракты и не знает внутренностей библиотек CatBoost/XGBoost/LightGBM.

UI-компоненты:

- model selector;
- feature selector;
- params form;
- threshold/cost policy controls;
- manual review capacity controls;
- metrics comparison;
- explanations;
- artifact/reproducibility panel.

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
