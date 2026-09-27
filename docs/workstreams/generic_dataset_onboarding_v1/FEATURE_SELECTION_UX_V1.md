# Feature Selection UX V1 — SPEC

## 1. Назначение и граница

Feature Selection UX V1 описывает только experiment-level выбор признаков. Экран доступен только после создания `PreparedDatasetContext`; он не является шагом Dataset Preparation и не редактирует preparation draft.

Источник selectable features:

`PreparedDatasetContext → FeatureRegistry → FeatureUsageStatus.MODEL_ALLOWED`.

Для первого эксперимента после создания нового `PreparedDatasetContext` начальное состояние:

```text
selected_feature_ids = все доступные MODEL_ALLOWED feature IDs
```

Для «Нового эксперимента на этих данных» на том же `PreparedDatasetContext` начальное состояние другое: используются предыдущие `selected_feature_ids` и предыдущая выбранная модель. Повторная Dataset Preparation не выполняется.

Единственный смысл checkbox: **«Использовать этот разрешённый признак в текущем эксперименте»**. ON/OFF меняет только `selected_feature_ids` данного эксперимента.

Этот экран не меняет:

- `FeatureUsageStatus`;
- `FeatureRegistry`;
- `ConfirmedDatasetPreparation`;
- `PreparedDatasetContext`;
- dataset-level permissions.

`TARGET`, `IDENTIFIER`, `DIAGNOSTIC_ONLY` и `BLOCKED` не являются selectable predictors на основном экране. Он не создаёт новых scientific/business смыслов, eligibility-эвристик или backend contracts.

---

## 2. Предпосылки и границы состояния

Dataset Preparation уже завершён и подтверждён человеком. Его состояние сохраняет границу:

`FACT ≠ PROPOSAL ≠ AUTO-FILLED USER DRAFT ≠ HUMAN FINAL CONFIRMATION`.

Dataset-level permissions определяются в подготовке и являются authoritative границей списка признаков. Experiment feature selection не повторяет её и не просит пользователя повторно подтверждать permissions.

Upstream recommendations Dataset Preparation, включая `REVIEW_REQUIRED`, `UNKNOWN` и `NOT_RECOMMENDED_CANDIDATE`, не создают отдельного обязательного решения на этом экране и не меняют membership в `selected_feature_ids` без действия пользователя. Experiment-level экран не требует proposal, inspection report или Analyzer state для своей работы.

---

## 3. Основной экран

Экран имеет следующий canonical вид:

```text
Признаки                                  Выбрано N из M

[Поиск] [Группа]

▼ group_name
☑ feature_1
☑ feature_2
☑ feature_3

▶ next_group

[Далее: модель →]
```

Для первого эксперимента после нового PreparedDatasetContext все разрешённые MODEL_ALLOWED признаки включены по умолчанию. Для последующего эксперимента на тех же данных экран стартует с унаследованным selected_feature_ids предыдущего эксперимента.

Обычный сценарий пользователя — снять отметки с ненужных признаков, а не заново классифицировать колонки датасета.

`N` — количество feature IDs в `selected_feature_ids`; `M` — количество доступных `MODEL_ALLOWED` features. Счётчик обновляется после каждого изменения checkbox и не изменяет состояние сам по себе.

### 3.1. Поиск и группы

Панель содержит:

- поиск по имени признака;
- фильтр технической группы, включая «Все группы» и «Без группы»;
- compact accordion groups.

Canonical source доступных downstream groups — `FeatureRegistry → FeatureGroup`. Если `FeatureRegistry` предоставляет группы, UI использует `FeatureGroup` как backend grouping boundary. Experiment-level экран не требует `DatasetPreparationProposal`, `DatasetPreparationProposal.technical_groups`, inspection report или Analyzer state.

Дополнительная presentation-only группировка допустима только для уже доступных feature IDs. Она не меняет `FeatureRegistry`, `FeatureUsageStatus` или `selected_feature_ids`, не требует `DatasetPreparationProposal` и не становится scientific/business семантикой. «Без группы» — presentation bucket, а не новая technical group.

Нельзя создавать semantic/business groups или hardcode конкретные датасеты, колонки и признаки. Группы, поиск, фильтры, accordion и переход к группе меняют только представление списка; они никогда не меняют `selected_feature_ids`.

Для большого числа признаков группы первоначально могут быть свёрнуты. При непустом поиске показываются и раскрываются только группы с совпадениями. В заголовке группы отображаются её имя и количество доступных признаков; при фильтрации можно дополнительно показать число совпадений.

### 3.2. Строка признака и групповые действия

В раскрытой группе строка содержит checkbox inclusion и имя feature. Checkbox доступен только для `MODEL_ALLOWED` feature и выполняет одно действие:

- ON добавляет feature ID в `selected_feature_ids`;
- OFF удаляет feature ID из `selected_feature_ids`.

Допустимы явные групповые действия «Включить все в эксперимент» и «Убрать все из эксперимента». Они меняют только IDs разрешённых features соответствующей группы. Ни поиск, ни фильтрация, ни grouping не являются групповым действием и не меняют selection.

В основном UX не входят row selection, временное `feature_selection`, bulk action panel для выбранных строк, dropdown «Решение», «Принять решение» и массовое переключение `MODEL_ALLOWED ↔ DIAGNOSTIC_ONLY`.

---

## 4. Warnings и сообщения

Информационное предупреждение показывается компактно и может раскрывать «Подробнее». Оно не меняет checkbox, не меняет dataset permission и само по себе не блокирует переход. Technical evidence отображается только в «Технических деталях».

Если состояние требует действия пользователя, оно показывается явно. Если оно блокирует продолжение, UI явно объясняет, что исправить. Информация, принятая автоматически Dataset Preparation, показывается краткой сводкой с возможностью перейти к соответствующему advanced control, но не как второй feature-selection экран.

Большие warnings, которые не требуют действия и не влияют на выбор, не должны занимать основной flow.

---

## 5. Переход к модели и новый эксперимент

Внизу находится действие **«Далее: модель →»**. Оно сохраняет текущий `selected_feature_ids` в configuration эксперимента и переводит пользователя на выбор модели. Оно не вызывает `confirm_dataset_preparation`, не materialize-ит датасет и не создаёт новый `PreparedDatasetContext`.

После результата действие **«Новый эксперимент на этих данных»** сохраняет тот же `PreparedDatasetContext`, `DatasetContract`, `FeatureRegistry` и `EvaluationPopulation`; повторная загрузка файла и Dataset Preparation не нужны. Сбрасывается только run-specific state: plan, result, comparison result и иное состояние завершённого запуска.

Новый эксперимент начинает работу с предыдущими `selected_feature_ids` и предыдущей моделью. Пользователь может изменить один параметр и получить контролируемое сравнение без изменения dataset permissions.

---

## 6. Инварианты

1. Экран существует только после `PreparedDatasetContext`.
2. В основной список входят только `FeatureUsageStatus.MODEL_ALLOWED` features.
3. Первый эксперимент для нового prepared context начинает со всеми доступными `MODEL_ALLOWED` feature IDs в `selected_feature_ids`.
4. Последующий эксперимент на том же prepared context наследует предыдущие `selected_feature_ids` и предыдущую модель.
5. Один checkbox меняет только `selected_feature_ids` текущего эксперимента.
6. `FeatureRegistry` permissions и `selected_feature_ids` — разные backend concepts и никогда не сливаются.
7. TARGET, IDENTIFIER, DIAGNOSTIC_ONLY и BLOCKED не становятся predictors через experiment checkbox.
8. Search, filter, group и warning не меняют selection сами по себе.
9. Групповое изменение происходит только после явного действия пользователя и касается только `MODEL_ALLOWED` features.
10. В этом UX нет подтверждения Dataset Preparation или повторного acknowledgement evaluation policy.
11. Backend contracts, reproducibility и comparison semantics сохраняются.

---

## 7. Не входит в этап

- изменение Dataset Preparation, materializer или validation semantics;
- изменение `FeatureRegistry` и `FeatureUsageStatus`;
- новый eligibility API или UI eligibility-эвристика;
- ручная классификация dataset-level permissions;
- новый Analyzer algorithm или semantic/LLM grouping;
- повторная загрузка или подготовка датасета для нового эксперимента;
- models/training, SHAP, LLM interpreter и изменение evaluation protocol;
- History/Persistence.

---

## 8. Acceptance criteria

Работа принимается, если:

1. после `PreparedDatasetContext` существует один основной экран «Признаки»;
2. его selectable list состоит только из `MODEL_ALLOWED` features;
3. первый feature screen после нового `PreparedDatasetContext` начинает со всеми этими features, включёнными по умолчанию;
4. пользователь может снять или вернуть отметку, меняя только `selected_feature_ids`;
5. TARGET, IDENTIFIER, DIAGNOSTIC_ONLY и BLOCKED отсутствуют среди selectable predictors;
6. поиск, технические группы и явные групповые действия удобны для 50–200 признаков и не изменяют dataset permissions;
7. warnings не требуют ritual confirmation и не блокируют переход сами по себе;
8. переход к модели сохраняет только configuration эксперимента и не создаёт новый `PreparedDatasetContext`;
9. «Новый эксперимент на этих данных» использует тот же prepared context, `FeatureRegistry` и `EvaluationPopulation`, наследуя предыдущие feature subset и модель;
10. downstream groups берутся из `FeatureRegistry → FeatureGroup` без зависимости от `DatasetPreparationProposal` или Analyzer state;
11. нет второго canonical feature-selection screen внутри Dataset Preparation;
12. reproducibility и comparison semantics не изменены.
