# HOME UX V1 — Functional Lock

Status: **HOME UX V1 — ACCEPTED / READY_FOR_IMPLEMENTATION**

Scope: функциональное поведение главной AXION V1 без изменения принятой визуальной композиции.

Visual source of truth: `docs/design/screens/home/01_home_axion_v1.png`.
Visual system: `docs/design/DESIGN_SYSTEM_V1.md`.

## 1. Purpose

Home V1 — верхний presentation/navigation layer над существующим Streamlit wizard.

Главная должна:
- быть первой страницей при новом запуске приложения;
- давать реальный вход в новый анализ;
- позволять безопасно уйти на Главную и вернуться в уже начатый анализ текущей сессии;
- показывать только сведения, для которых есть доверенный текущий источник;
- честно оставлять неподдерживаемые части mockup в empty/future state.

Home V1 не является Project Manager, каталогом артефактов или диспетчером фоновых задач.
Открытие Home само по себе не меняет dataset/model/scientific state.

## 2. Actual backend capability map

### Реально доступно сейчас

- Последовательный wizard: `Данные → Признаки → Алгоритм → Проверка качества → Результат`.
- Session state хранит текущий шаг, dataset context/preparation, выбранные признаки/модель, experiment plan/result и локальный saved-model flow.
- `ExperimentArtifactStore` имеет доверенные операции `save(...)` и `load(artifact_id)`.
- `ExperimentApplicationService.load_experiment(artifact_id)` умеет загрузить только заранее известный artifact ID.
- `ModelVersionStore` имеет доверенные операции `save(...)` и `load(model_version_id)`.
- `ModelVersionSummary` содержит `model_version_id`, `experiment_artifact_id`, `model_id`, `model_version`, `feature_ids`.
- `IntegrationWorkflowService` умеет сохранить итоговую модель текущего результата и сразу вернуть доверенный `LoadedModelVersion`.
- Если `loaded_model_version` уже находится в текущей сессии, Home может безопасно прочитать его `summary`.
- Experiment execution и final-fit/save выполняются синхронно; accepted background-job state отсутствует.

### Недоступно как принятый public contract

- Project entity / ProjectRepository / project status lifecycle.
- List/history API для ExperimentArtifactStore.
- List/history API для ModelVersionStore.
- Application-level каталог сохранённых ModelVersion.
- Trusted «последний проект».
- Trusted counts проектов, проектов в работе, завершённых проектов или всех сохранённых моделей.
- Background jobs / queue / process registry.
- Home notification feed.
- Searchable Home collection.

Следствие: содержимое `.streamlit-artifacts` не является Home API. Streamlit не сканирует каталоги и не выводит filesystem-derived records/counts.

## 3. Home V1 active blocks

### AXION shell и hero

Активны как presentation:
- sidebar AXION;
- заголовок `Главная`;
- approved hero asset из `app/assets/images/home-hero-banner.webp` (PNG допустим как lossless source);
- верхняя primary action `Новый анализ`.

Hero не содержит выдуманных продуктовых данных.

### Quick Start — «Новый анализ»

Активен. Все визуальные точки входа `Новый анализ` используют один и тот же session transition contract.

### Возврат в текущий анализ

Если в текущей Streamlit-сессии уже существует начатый анализ, Home показывает отдельное действие `Продолжить текущий анализ`.
Оно возвращает пользователя ровно на сохранённый `current_step` без пересоздания dataset context, model selection, experiment state или result state.

Это не «последний проект» и не история: это только текущая in-session работа.
### Saved models area — только доверенная модель текущей сессии

Если `loaded_model_version` отсутствует, блок показывает empty state.

Если `loaded_model_version` присутствует, Home может показать **одну** запись с явной пометкой `Текущая сессия`, используя только:
- display name модели через текущий trusted ModelRegistry;
- `model_version`;
- число `feature_ids`;
- при необходимости технический `model_version_id`.

Это не считается каталогом всех сохранённых моделей и не используется для общего count.

Если текущий `loaded_artifact.artifact_id` совпадает с `summary.experiment_artifact_id`, допустимо действие `К результату`: оно только переводит wizard на шаг `Результат`.
Standalone «открытие модели из хранилища» в Home V1 отсутствует.

## 4. Home V1 empty / future blocks

### Summary cards

Четыре карточки сохраняются композиционно, но не показывают fabricated values:

| Карточка | V1 |
| --- | --- |
| Проектов | `—`, future metric |
| Сохранённых моделей | `—`, future metric |
| Проектов в работе | `—`, future metric |
| Завершённых проектов | `—`, future metric |

Под `—` или в tooltip/caption должно быть кратко указано, что сводная история ещё не подключена.
Числа из mockup `12 / 8 / 3 / 7` запрещены.

### Quick Start — «Открыть модель»

В текущем runtime disabled/future.
Причина: persisted ModelVersion можно загрузить только по уже известному ID; trusted browse/list/open backend flow ещё не реализован.
Product/visual lock будущего каталога уже принят в `docs/workstreams/generic_dataset_onboarding_v1/MODELS_UX_V1.md`, но это не разрешает обходить application boundary сканированием filesystem.
Нельзя просить Streamlit искать модели по filesystem.

### Quick Start — «Продолжить последний проект»

Как «последний проект» — disabled/future.
Project domain и trusted project history отсутствуют.
Когда текущая сессия содержит начатый анализ, рядом/в том же Quick Start layout допускается session-only action `Продолжить текущий анализ`; оно не меняет смысл «последнего проекта».

### «Выполняется сейчас»

На Home V1 показывает empty state: `Сейчас нет фоновых операций`.

Синхронный fold/train/final-fit progress показывается только на том wizard-экране, где операция реально выполняется.
Home не восстанавливает progress из прошлого события и не изображает background execution.

### «Требует внимания»

На Home V1 показывает empty state: `Нет уведомлений, требующих внимания`.

Текущие локальные wizard warnings/errors не превращаются в Home notification feed.
Новый warning можно выводить здесь только после появления отдельного принятого typed/read contract либо явно утверждённого session-state source.

### «Последние проекты»

Блок сохраняется визуально, но содержит empty/future state и не показывает строки.
ExperimentArtifact не считается Project по умолчанию.

## 5. Sidebar behavior

| Пункт | V1 behavior |
| --- | --- |
| Главная | Active route. Открывает Home и ничего не сбрасывает. |
| Новый анализ | Active action. Запускает explicit new-analysis transition. |
| Модели | В текущем runtime остаётся disabled до trusted browse/list backend contract. Product/visual lock каталога уже принят в `MODELS_UX_V1.md`. |
| Проекты / История | Disabled/future. Project/history contract отсутствует. |
| Настройки | Disabled/future. Глобального settings contract нет. |

Disabled items должны визуально выглядеть недоступными и не открывать пустые псевдостраницы.
Допустим короткий hint `Будет доступно позже`.

На Home active navigation item — `Главная`.
Во время wizard Home остаётся доступной, а `Новый анализ` остаётся явным действием создания нового анализа, а не скрытым reset текущего.

## 6. New Analysis navigation

Top-level navigation имеет два presentation states:
- `HOME`;
- `ANALYSIS`.

Wizard step (`current_step = 0..4`) остаётся отдельным под-состоянием анализа.
### First launch

После `initialize(...)` первый отображаемый surface — `HOME`.
Сам факт первого показа Home не вызывает dataset resolution, не выбирает модель и не создаёт experiment state.

### Home → Новый анализ

Если session analysis ещё свежий и содержательной работы нет:
1. пометить analysis session как начатую;
2. перейти в `ANALYSIS`;
3. открыть step 0 `Данные`.

Если в session уже есть содержательная работа, `Новый анализ` не сбрасывает её молча.
Показывается подтверждение:
- `Отмена` — оставить всё без изменений и остаться на текущем surface;
- `Начать новый анализ` — выполнить полный analysis-session reset и открыть step 0.

Содержательная работа есть, если присутствует хотя бы одно из следующего:
- пользователь уже выбрал источник данных, включая browser staged upload до появления `dataset_source_preparation`;
- в session сохранён selected/resolved source locator, который указывает на реально выбранный dataset;
- существует checked/prepared dataset state (`dataset_source_preparation` / `dataset_context`);
- достигнут wizard step > 0;
- выбрана модель либо существуют experiment inputs/plan;
- существует experiment artifact/result/comparison;
- существует loaded ModelVersion/inference/explanation state.

**SELECTED DATASET SOURCE = MEANINGFUL USER WORK**, даже если пользователь ещё не нажал `Проверить файл`.

Поэтому пустым считается только step 0, где нет выбранного/staged/resolved dataset source и нет checked/prepared dataset state. Один лишь source error без оставшегося выбранного/staged source сам по себе подтверждения перед reset не требует.

### Wizard → Home

`Главная` меняет только top-level presentation state на `HOME`.
`current_step` и весь analysis/session state остаются неизменными.

### Home → existing in-session analysis

`Продолжить текущий анализ`:
- меняет только presentation state на `ANALYSIS`;
- сохраняет exact `current_step`;
- не повышает и не понижает `highest_reached_step`;
- не перестраивает context;
- не делает load/save автоматически.

## 7. Session preservation / reset rules

### Home navigation preserves

При переходе на Home сохраняются без изменений:
- `current_step`, `highest_reached_step`;
- `dataset_context`, `dataset_source_preparation` и подтверждённая preparation state;
- selected features/model;
- experiment inputs, planning snapshot и plan;
- loaded artifact, comparison, last successful artifact id;
- loaded ModelVersion;
- inference batch, selected row, local explanation и role interpretation state;
- persisted ExperimentArtifact/ModelVersion на диске.

### Explicit new-analysis reset

После подтверждённого `Начать новый анализ` новый анализ не наследует scientific state предыдущего.

Сбрасываются analysis-scoped session values к fresh defaults:
- dataset/preparation context и preparation transients;
- selected features/model;
- experiment inputs/plan;
- loaded artifact/comparison/current last-result reference для нового анализа;
- active/loaded ModelVersion;
- inference/explanation/interpreter state;
- wizard step/history availability.

Также UI layer обязан:
- очистить dataset/inference browser-upload widget state;
- cleanup контролируемые staged upload files;
- очистить source locator/error/recheck и прочие analysis-scoped widget keys;
- увеличить/сменить revision так, чтобы старые widget values не ожили в новом анализе.

Reset **не удаляет** ранее сохранённые ExperimentArtifact или ModelVersion из persistent stores.

После reset:
- surface = `ANALYSIS`;
- `current_step = 0`;
- пользователь видит чистый экран `Данные`.

## 8. Saved model treatment

Home V1 не создаёт backend model catalog.

Причина:
- `ModelVersionStore.load(model_version_id)` требует заранее известный ID;
- accepted `list()` отсутствует;
- IntegrationWorkflow не предоставляет browse/list/open-by-choice use case;
- filesystem ordering нельзя трактовать как recency/history.

Разрешено только отображение уже доверенно загруженного `loaded_model_version` текущей session, как описано выше.

Никакие Gini/ROC-AUC/PR-AUC, дата обучения, dataset name или статус «готова к использованию» не добавляются в Home card, если они не читаются из уже доступного доверенного объекта без нового semantic join.

Future prerequisite для полноценного `Модели`/Home list: отдельный application read boundary, возвращающий валидированные model summaries с чётко определёнными ordering/metadata semantics.
Он не является blocker для Home V1.

## 9. Project / history treatment
В Home V1 **нет Project entity**.

Поэтому:
- ExperimentArtifact ≠ Project;
- ModelVersion ≠ Project;
- dataset context ≠ Project;
- session analysis ≠ persisted Project.

Запрещено:
- генерировать project records из artifact folders;
- считать artifact count числом проектов;
- использовать mtime/имя каталога как «последнее изменение проекта»;
- определять «последний проект» по filesystem ordering;
- присваивать project status по wizard step.

`Последние проекты`, project counts, project search и sidebar `Проекты / История` остаются future/empty.

Future Project contract должен проектироваться отдельно только при реальной продуктовой необходимости.

## 10. Search treatment

Header search field сохраняется в принятой композиции, но в V1 disabled.

Placeholder можно оставить `Поиск проектов и моделей...`.
Рядом/в help допустим текст: `Поиск станет доступен после подключения истории проектов и каталога моделей`.

Поле:
- не фильтрует session state;
- не сканирует filesystem;
- не выполняет fake search;
- не принимает ввод, который затем игнорируется без объяснения.

## 11. Error / empty states

Home V1 использует короткие truthful states:
- no current analysis → действие `Продолжить текущий анализ` не показывается;
- no loaded model in session → `Сохранённые модели: в текущей сессии модель ещё не сохранена`;
- no background job → `Сейчас нет фоновых операций`;
- no trusted attention feed → `Нет уведомлений, требующих внимания`;
- no project history → `История проектов пока не подключена`;
- disabled search/models/history/settings → явный future/disabled state.

Home не должен превращать отсутствие backend contract в error.
Ошибкой считается только фактический failure доверенного действия, например невозможность продолжить уже существующий session state из-за нарушенной внутренней согласованности.

## 12. Implementation boundary
Разрешённый implementation scope для Home V1:
- `app/streamlit_app.py`;
- `app/session_state.py`;
- focused Streamlit/session tests;
- при необходимости один небольшой presentation helper/module, если это реально уменьшает сложность Home rendering.

Допустимо добавить только presentation/session navigation state и explicit reset transition.
Это не новый backend/domain contract.

Запрещено в этой задаче:
- изменения model/scientific logic;
- изменение dataset/feature/model/evaluation semantics;
- Project persistence;
- DB;
- background-job subsystem;
- authentication;
- React/FastAPI rewrite;
- list/history API в artifact/model stores;
- filesystem scanning из Streamlit.

## 13. Acceptance criteria

1. На чистой session первым отображается Home AXION, а не step 0 wizard.
2. Home соответствует принятому visual reference и использует production assets из `app/assets/`.
3. Ни один mockup count/record не захардкожен и не синтезируется из filesystem.
4. `Новый анализ` реально приводит к step 0 `Данные`.
5. Переход wizard → Home не меняет ни одного scientific/analysis value, кроме top-level presentation/navigation state.
6. При наличии текущего анализа Home предлагает `Продолжить текущий анализ`; возврат открывает exact сохранённый `current_step`.
7. Explicit new analysis при содержательной текущей работе требует подтверждения; cancel сохраняет state, confirm создаёт чистый analysis session.
8. Confirmed reset очищает старые upload/widget transients, но не удаляет persisted artifacts/models.
9. `Открыть модель`, `Продолжить последний проект`, `Модели`, `Проекты / История`, `Настройки` и search не притворяются работающими.
10. Summary cards показывают `—`, а не invented counts.
11. `Выполняется сейчас` не изображает background jobs; `Требует внимания` не создаёт invented warnings.
12. `Последние проекты` не отображает ExperimentArtifact как Project.
13. Saved-model area не сканирует store: допускается только trusted `loaded_model_version` текущей session с явной пометкой scope.
14. Existing wizard behavior после входа в analysis остаётся совместимым с текущими тестами и accepted contracts.
15. Для Home V1 не добавляется новый backend/domain read contract.

## 14. Non-goals

- Project entity и project persistence.
- История/каталог проектов.
- Каталог всех ExperimentArtifact.
- Каталог всех ModelVersion.
- Поиск проектов/моделей.
- Фоновое выполнение экспериментов.
- Центр уведомлений.
- Global settings page.
- Standalone saved-model workspace.
- Multi-user/auth.
- Изменение текущего research/scientific protocol.
- Изменение accepted visual direction.

## Architectural decision

**Home AXION V1 реализуется без нового backend contract.**

Полезная V1 получается из:
1. реальной top-level Home navigation;
2. реального `Новый анализ`;
3. безопасного preserve/resume текущего session analysis;
4. честных empty/future states;
5. optional display только уже загруженной trusted model текущей session.

Project/history/model-catalog contracts откладываются до отдельной задачи, где они будут нужны как реальные продуктовые сущности, а не как способ заполнить mockup.

**HOME UX V1 — ACCEPTED / READY_FOR_IMPLEMENTATION**
