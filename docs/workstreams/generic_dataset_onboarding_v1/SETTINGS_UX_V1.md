# Settings UX V1 — Product / Architecture / Visual Lock

Status: **ACCEPTED PRODUCT / ARCHITECTURE / VISUAL LOCK — BACKEND IMPLEMENTATION PENDING**

Visual sources of truth:
- `docs/design/screens/settings/01_settings_v1.png` — основной collapsed state;
- `docs/design/screens/settings/02_settings_privacy_expanded_v1.png` — тот же экран с раскрытым privacy explanation.

## 1. Product decision

`Настройки` остаются отдельным top-level разделом AXION.

V1 — это небольшой, но реальный control center, а не read-only диагностическая страница и не свалка параметров анализа.

В Settings V1 входят только:
1. **Интерфейс** — global presentation preference;
2. **Интеграции / Интерпретатор результатов** — global controls внешнего LLM Result Interpreter.

LLM не является credit predictor. Он используется только для текстовой интерпретации уже рассчитанного validated ML / SHAP evidence.

## 2. Account / profile boundary

В текущем продукте нет принятого authentication / login / account / users / permissions contract.

Поэтому V1:
- не показывает fake avatar, имя, роль пользователя или profile menu в sidebar;
- не обещает личный кабинет, login/logout или персональный account;
- не называет persistence буквально `per-user`, пока не появится trusted user identity.

Editable preferences V1 трактуются как **local application preferences** текущего экземпляра AXION. Будущий auth workstream может позже дать им настоящий user scope.

## 3. Section «Интерфейс»

Один V1 control:

`Показывать технические сведения развёрнутыми по умолчанию`.

Это presentation preference для technical expanders/provenance blocks.

Он не меняет:
- dataset;
- model;
- metrics;
- prediction;
- threshold;
- SHAP;
- scientific evidence.

Theme, light mode, language, startup page, notifications и font/density не входят в V1 без отдельной продуктовой потребности.

## 4. Section «Интеграции / Интерпретатор результатов»

### 4.1. Использовать интерпретатор

Editable toggle.

Semantics:
```text
effective external LLM permission =
deployment policy permits
AND local preference enabled
AND provider configured
AND supported model selected
AND credential available
AND prompts valid
```

Пользователь может **запретить** внешние LLM-вызовы для текущего приложения, но не может этим toggle ослабить deployment/security policy.

Если deployment policy = `DISABLED`, control disabled и UI показывает понятную причину.

### 4.2. Provider

Read-only, пока trusted registry содержит только один provider.

Текущий demo `OpenAI` в PNG не является hardcoded product truth.

Provider selector появляется только при наличии 2+ trusted user-selectable providers.

Никакого silent fallback между providers.

### 4.3. Модель интерпретатора

Editable только через trusted supported-model catalog.

Canonical catalog item:
```text
SupportedInterpreterModel
- model_id
- display_name
- provider_id
- status
```

Free-text model name запрещён.

Если разрешена одна модель — показывается read-only. При 2+ поддерживаемых моделях тот же control становится selector.

### 4.4. Роль по умолчанию

Editable global default initial selection:
- Кредитный контролёр;
- Менеджер по продажам;
- Юрист;
- Информационная безопасность.

Это только initial UI selection для нового Result Interpreter action.

Конкретный Result по-прежнему может выбрать другую роль.

Изменение default role:
- не вызывает LLM;
- не меняет prediction/SHAP;
- не меняет сохранённые ответы.

### 4.5. External-data policy

Read-only system/deployment state.

Например `REDACTED_V1`, `DISABLED`, `INVALID`.

Пользователь не может сделать policy более разрешающей.

Action `Подробнее` раскрывает единственный privacy block **«Как защищаются данные?»**.

Основной Visual Lock — privacy collapsed.
Expanded Visual Lock фиксирует содержание раскрытого состояния.

### 4.6. Credentials

Credentials являются отдельным security boundary, не обычной preference.

Для local application допустимые actions:
- `Подключить API-ключ`;
- `Заменить`;
- `Удалить`.

Backend должен использовать secure credential storage, предпочтительно OS credential vault.

UI никогда не получает secret обратно и никогда не показывает:
- полный API key;
- masked prefix/suffix вроде `sk-••••`;
- reveal/copy secret.

После set/replace поле ввода очищается.

Если credentials заданы централизованно runtime/admin:
`Учётные данные управляются системой`,
редактирование отключено.

### 4.7. Проверить подключение

Явное user action.

Проверка должна быть реальной:
`provider + selected model + effective credential → minimal synthetic request`.

Запрещено отправлять client/model data.

Результат текущего check может показываться transient state:
`Соединение работает`.

V1 не обещает persisted history вида `Последняя проверка ...`, пока отдельный contract не принят.

## 5. Privacy disclosure

Expanded privacy state объясняет accepted `REDACTED_V1` boundary.

Передаются только разрешённые interpreter facts, например:
- выбранная роль;
- model score / probability;
- output-space context;
- identity/названия значимых признаков;
- SHAP-вклады;
- trusted descriptions.

Не передаются:
- identifier / ИНН;
- row identity;
- raw feature values;
- SHAP base value;
- raw model output;
- полная model/dataset provenance.

Точная outbound semantics остаётся source of truth backend policy contract; PNG не расширяет policy.

## 6. Storage decision

Canonical AXION stores для `ExperimentArtifact`, `ModelVersion`, History — application-managed.

Settings V1 не содержит `Папку сохранения моделей` и не переключает внутренний store root.

`Сохранить модель` означает добавить `ModelVersion` в библиотеку AXION.

Будущий внешний file output — отдельное действие `Экспортировать`. Default export folder имеет смысл только после принятого export/runtime contract.

## 7. Что НЕ находится в Settings

Dataset / Analysis:
- target;
- positive class;
- identifier;
- dataset roles;
- feature selection.

Algorithm / Quality:
- model choice;
- hyperparameters;
- folds;
- seed;
- protocol.

Result:
- OOF threshold;
- filters;
- selected object;
- quick views;
- SHAP presentation;
- role конкретного Result Interpreter call.

Models / inference:
- selected ModelVersion;
- inference dataset;
- inference threshold;
- score range;
- saved inference Result configuration.

## 8. Visual semantics

Основной экран:
- без analysis wizard stepper;
- без fake user profile/login block;
- `Интерфейс` — отдельная компактная секция;
- `Интеграции` — отдельная секция;
- editable controls визуально отличаются от read-only system state и actions;
- privacy по умолчанию collapsed;
- Graphite + Emerald остаётся canonical AXION shell.

Footer guarantee:
изменение настроек интерфейса и интерпретатора не меняет сохранённые результаты, model scores или SHAP.

## 9. Backend implementation order

Visual/Product Lock принят до runtime implementation.

Следующие stages:

### SET-BE1 — Local Preferences + Interpreter Settings

Минимальный public boundary:
```text
LocalPreferencesStore
ResultInterpreterSettingsService

get()
update_preferences()
supported_models()
runtime_status()
```

До появления auth это local application profile/preferences store, не account/user database.

### SET-BE2 — Secure Credentials + Connection Check

```text
CredentialStore
set / replace / delete / configured

ResultInterpreterConnectionCheck
```

Без secure credential backend UI input API key не реализуется.

### SET-UI1

Подключить accepted Settings Visual Lock к принятым SET-BE1 / SET-BE2 contracts.

## 10. Out of scope V1

- authentication / login / registration;
- users / permissions / account profile;
- provider marketplace;
- arbitrary provider/model free-text;
- theme/light mode;
- language/i18n;
- notifications;
- startup page;
- canonical store root editing;
- export preferences до export contract;
- diagnostics page без отдельной product need.
