# Generic Dataset Onboarding V1 — SPEC

## 1. Цель и canonical flow

Generic Dataset Onboarding V1 даёт пользователю понятный путь от файла до результата эксперимента, сохраняя принятые backend contracts и их границы.

Canonical flow:

`Файл → автоматическая подготовка → при необходимости подтвердить/исправить target / positive class / identifier → Проверка и подтверждение подготовки → Признаки → Модель → Эксперимент → Результат`.

Подготовка датасета и выбор признаков — разные уровни состояния:

- Dataset Preparation создаёт подтверждённый `PreparedDatasetContext` с dataset-level permissions.
- Feature Selection после `PreparedDatasetContext` создаёт только `selected_feature_ids` конкретного эксперимента.

Полноценный ручной feature-selection внутри Dataset Preparation не входит в основной пользовательский путь. Единственный основной экран выбора признаков находится после `PreparedDatasetContext` и описан в `FEATURE_SELECTION_UX_V1.md`.

---

## 2. Неизменяемые backend-границы

Dataset Preparation остаётся отдельным backend layer. Сохраняется принцип:

`FACT ≠ PROPOSAL ≠ AUTO-FILLED USER DRAFT ≠ HUMAN FINAL CONFIRMATION`.

Система формирует полный preparation draft автоматически. Она по возможности предлагает и подставляет target, positive class и identifier; пользователь видит эти значения и может их подтвердить или исправить. Это человеческое решение, поскольку оно зависит от бизнес-смысла данных.

`PreparedDatasetContext` создаётся только после human final confirmation через существующий `confirm_dataset_preparation`. До этого действуют существующие fail-closed validation и stale-source checks.

Сохраняются без изменения:

- `DatasetPreparationProposal`;
- `ConfirmedDatasetPreparation`;
- `DatasetContract`;
- `FeatureSpec`;
- `FeatureUsageStatus`;
- `FeatureRegistry`;
- `EvaluationPopulation`;
- `PreparedDatasetContext`;
- `PlanningRequestMetadata`;
- `ExperimentConfig`;
- `ExperimentResult`;
- `ArtifactStore`;
- comparison semantics.

Historical `Data_final` остаётся internal compatibility profile и не меняет generic UX. После `PreparedDatasetContext` UI не различает historical и arbitrary dataset.

---

## 3. Автоматическая подготовка датасета

### 3.1. Начальный экран — файл

Основное действие: **«Загрузите файл»**. Нет отдельного пользовательского выбора между «историческим набором данных» и «другим локальным файлом».

После загрузки система проверяет файл и показывает краткую сводку: имя файла, число строк и столбцов, а также агрегированные проблемы. Повторяющиеся предупреждения объединяются в понятные сообщения, а технические детали доступны только в отдельном блоке «Технические детали».

### 3.2. Экран «Подготовка»

После анализа показывается автоматически заполненный draft подготовки:

- target;
- positive class, зависящий от выбранного target;
- identifier;
- автоматически сформированные permissions колонок;
- только вопросы, которые действительно требуют решения пользователя.

При смене target выбранный positive class сбрасывается и выбирается заново. Target и identifier не могут совпадать.

Пользователь не классифицирует вручную десятки колонок как пригодные или непригодные для модели. Редкие dataset-level изменения допустимы только как advanced controls «Ограничения признаков»; они не являются основным feature selection и не заменяют автоматический draft.

### 3.3. Dataset-level permissions

В `FeatureRegistry` сохраняются dataset-level статусы:

- `TARGET` — выбранный target;
- `IDENTIFIER` — выбранный identifier;
- `MODEL_ALLOWED` — обычная predictor-колонка, для которой существующая техническая validation допускает predictor representation и нет явного project/backend запрета;
- `DIAGNOSTIC_ONLY` — колонка, которую текущий backend технически не может использовать predictor’ом, но которую допустимо сохранить для анализа;
- `BLOCKED` — только явный project/backend запрет с причиной.

Эти статусы являются permissions датасета, а не feature subset конкретного эксперимента. Auto draft формирует система.

`proposal.column_roles[*].predictor_eligibility` остаётся recommendation/proposal signal. В частности, `REVIEW_REQUIRED`, `UNKNOWN` и `NOT_RECOMMENDED_CANDIDATE` сами по себе не переводят колонку в `DIAGNOSTIC_ONLY` или `BLOCKED`.

Нельзя вводить новую UI eligibility-эвристику или описывать две реализации одной проверки. Определение реальной predictor compatibility использует то же authoritative technical rule, что применяется materializer при final validation. Если для автоматической подготовки нужен reusable helper, существующая predictor-representation validation переиспользуется или выносится в единый внутренний источник истины без изменения public backend contracts.

### 3.4. Экран «Проверка» и подтверждение

Отдельный onboarding-step «Оценка» не создаётся, если его единственная функция — acknowledgement evaluation policy. Вместо этого на финальной «Проверке» показаны:

- краткая сводка файла, target, positive class и identifier;
- сводка автоматически сформированных dataset permissions и ссылка на advanced «Ограничения признаков»;
- понятное объяснение evaluation policy;
- обязательное acknowledgement policy;
- human final confirmation.

Для Generic Dataset V1 применяется `FULL_OOF_NO_PROTECTED_FINAL_TEST`: все строки используются для OOF-оценки, а отдельная защищённая финальная тестовая выборка автоматически не создаётся. Пользователь подтверждает это условие до final confirmation; отдельный экран ради одного checkbox не нужен.

Нажатие final confirmation вызывает существующий `confirm_dataset_preparation`, выполняет authoritative validation и materialization полного draft. При успехе создаётся `PreparedDatasetContext`. При ошибке UI объясняет, что исправить, и возвращает к соответствующему решению; traceback и технические коды не выводятся в основной интерфейс.

---

## 4. Experiment-level feature selection

После `PreparedDatasetContext` начинается единственный основной экран «Признаки». Его canonical downstream source selectable features:

`PreparedDatasetContext → FeatureRegistry → только FeatureUsageStatus.MODEL_ALLOWED`.

Canonical source доступных downstream groups — `FeatureRegistry → FeatureGroup`. Experiment-level экран не требует для работы `DatasetPreparationProposal`, `DatasetPreparationProposal.technical_groups`, inspection report или Analyzer state. После `PreparedDatasetContext` UI не различает происхождение датасета.

Инициализация зависит от сценария:

- первый эксперимент после создания нового `PreparedDatasetContext` начинает с `selected_feature_ids`, содержащего все доступные IDs с `MODEL_ALLOWED`;
- «Новый эксперимент на этих данных» для того же context начинает с предыдущего `selected_feature_ids` и предыдущей выбранной модели.

Чекбокс означает только: «Использовать этот разрешённый признак в текущем эксперименте». Он меняет только `selected_feature_ids`.

Чекбокс не меняет `FeatureUsageStatus`, `FeatureRegistry`, `ConfirmedDatasetPreparation` или `PreparedDatasetContext`. `TARGET`, `IDENTIFIER`, `DIAGNOSTIC_ONLY` и `BLOCKED` не являются selectable predictors на основном experiment feature screen.

Детали экрана, навигации, сообщений и его инварианты определены в `FEATURE_SELECTION_UX_V1.md`.

---

## 5. Новый эксперимент

После результата пользователь может выбрать **«Новый эксперимент на этих данных»**. При этом сохраняются:

- `PreparedDatasetContext`;
- `DatasetContract`;
- `FeatureRegistry`;
- `EvaluationPopulation`.

Не нужно повторно выбирать файл или проходить Dataset Preparation. Сбрасывается только run-specific state, включая plan, result, comparison result и иное состояние завершённого запуска.

Стартовая конфигурация нового эксперимента наследует предыдущие `selected_feature_ids` и выбранную модель. Это позволяет изменить ровно один параметр и провести контролируемое сравнение. `PreparedDatasetContext`, `FeatureRegistry` и `EvaluationPopulation` остаются теми же. Feature subset остаётся частью experiment configuration, а не новой подготовкой датасета.

---

## 6. Правило UI-сообщений

Информация, которая не меняет состояние, не блокирует продолжение и не требует решения пользователя, не занимает основной экран.

| Категория | Представление |
| --- | --- |
| Требуется действие | Показать явно. |
| Блокирует продолжение | Показать явно и объяснить, что исправить. |
| Автоматически принято системой | Краткая сводка и возможность изменить. |
| Informational warning | Компактно, с «Подробнее». |
| Technical evidence | Только в «Технических деталях». |

Большие warnings без действия не должны занимать основной flow.

---

## 7. Что не входит в этап

Не реализуются и не меняются:

- backend/scientific contracts и materializer semantics;
- новый `FeatureUsageStatus`, eligibility API или UI eligibility-эвристика;
- ручная массовая классификация dataset permissions в основном пути;
- Dataset History / Persistence, база данных и similarity matching;
- новые ML-исследования или модели;
- evaluation protocol;
- production frontend;
- масштабный backend refactoring.

---

## 8. Acceptance criteria

Работа принимается, если:

1. arbitrary dataset получает автоматически заполненный preparation draft;
2. пользователь не классифицирует вручную десятки колонок;
3. target, positive class и identifier можно проверить и исправить;
4. final preparation требует human confirmation и acknowledgement population policy;
5. `PreparedDatasetContext` создаётся только после confirmation;
6. после него существует один основной экран «Признаки»;
7. первый experiment feature screen после нового `PreparedDatasetContext` начинает со всеми `MODEL_ALLOWED` features, включёнными по умолчанию;
8. experiment checkbox меняет только `selected_feature_ids`;
9. experiment checkbox не меняет dataset permissions;
10. новый эксперимент на том же `PreparedDatasetContext` наследует предыдущие feature subset и модель без повторной подготовки;
11. feature subset является experiment configuration, а не новой dataset preparation;
12. reproducibility и comparison semantics сохранены;
13. нет двух canonical feature-selection screens и нет отдельного acknowledgement-only шага «Оценка»;
14. `FeatureRegistry` permissions не слиты с `selected_feature_ids`;
15. downstream groups берутся из `FeatureRegistry → FeatureGroup`, а не из `DatasetPreparationProposal.technical_groups`.
