# Algorithm UX V1 — UX / VISUAL LOCK

Status: **UX / VISUAL LOCK — ACCEPTED / READY_FOR_IMPLEMENTATION**

Base main: `f32ec4a98d08b47940ceb6ab95956ac80a97e410`

Primary visual reference: supplied designer mockup for screen **«3. Алгоритм»**.

This document resumes the previously stopped Algorithm UX V1 work after
Parameter Presentation / Identity V1 was implemented and accepted.

Accepted prerequisite:

```text
Parameter Presentation / Identity V1
implementation: 3ff6582c39d795b16afb634f10c9dd74c507f973
status: CLOSED / ACCEPTED
```

The visual reference defines composition and hierarchy.
Accepted backend contracts remain the source of truth for content and behavior.

---

## 1. Product question and boundary

The screen answers one question:

> Какой зарегистрированный алгоритм и какую поддерживаемую конфигурацию использовать в текущем эксперименте?

Canonical flow remains:

```text
Данные
→ Признаки
→ Алгоритм
→ Проверка качества
→ Результат
```

Algorithm UX:

- reads model discovery only through `ExperimentPlanningService.list_models()`;
- renders generic `ModelCatalogEntry` cards;
- selects exactly one model for the current experiment;
- lets the user choose `RECOMMENDED` or `ADVANCED`;
- edits only backend-declared configurable parameters;
- stores only run-intent state needed by the next step;
- does not train;
- does not run technical smoke;
- does not calculate model quality;
- does not change feature permissions;
- does not change protocol / folds / seed;
- does not contain model-specific scientific logic.

Frontend never creates estimator objects and never branches on model IDs.

---

## 2. Already accepted UX decisions

The following decisions are preserved and are not reopened:

1. model cards replace the model selectbox;
2. cards are rendered generically from `ModelCatalogEntry`;
3. Recommended is the default configuration mode;
4. Advanced renders backend-declared editable parameters only;
5. Russian parameter copy is backend-owned and comes through `CatalogParameter`;
6. unavailable/misconfigured models remain visible but disabled;
7. selected feature count and dataset are shown as a compact context summary;
8. hidden models are session-only presentation preference;
9. hiding the currently selected model requires confirmation;
10. hidden models can be restored;
11. «Подключить модель» is reserved for a future trusted-plugin flow only;
12. Algorithm is separate from Quality;
13. technical details remain collapsed;
14. no model-specific icons, descriptions, badges, parameters or validation rules are hardcoded in Streamlit;
15. no automatic «best model» recommendation/ranking is introduced.

---

## 3. Actual backend sufficiency

Current main now provides all backend contracts required for this UX.

### Catalog

`ExperimentPlanningService.list_models()` returns trusted `ModelCatalogEntry`
objects with model identity, Russian name/description, availability, task/runtime
metadata, capabilities, parameter schema projection and Recommended profile metadata.

### Parameter presentation

Accepted Parameter Presentation / Identity V1 supplies Russian
`CatalogParameter.display_name_ru / description_ru` without changing
behavioral model identity.

### Configuration handoff

`PlanningRequestMetadata` already accepts:

```text
configuration_mode
user_overrides
```

and `ExperimentPlanningService.build_plan()` resolves them through the trusted
`ModelConfigurationService`.

Therefore no new backend API or DTO is required for Algorithm UX V1.

---

## 4. Screen hierarchy

Preserve the designer composition.

### Header

Title:

> **Выбор алгоритма**

Subtitle:

> **Выберите алгоритм и настройки для текущего эксперимента.**

### Compact context summary

Show:

- **Признаков выбрано** — selected count / all selectable MODEL_ALLOWED count;
- **Датасет** — current `DatasetContract.dataset_name`;
- secondary action **«Изменить признаки»**.

The summary is read-only.
«Изменить признаки» navigates to Feature Selection and does not mutate
`selected_feature_ids` by itself.

### Model section

Heading:

> **Выберите алгоритм**

Caption:

> **Алгоритмы из реестра для текущего эксперимента.**

### Configuration section

Heading:

> **Настройки модели**

Mode switch:

- **Рекомендуемые**
- **Расширенные**

### Secondary details

Collapsed:

- **Возможности**
- **Технические сведения**

### Navigation

- **← Назад к признакам**
- **Далее: проверка качества →**

---

## 5. Generic model cards

Every visible registered model uses one generic card template.

Card content:

- one neutral generic model icon;
- `display_name_ru`;
- `description_ru`;
- generic badges derived only from catalog truth;
- availability state;
- selected state;
- secondary `⋯` menu for presentation-only actions.

The whole AVAILABLE card is one selection action.

A radio/check mark may exist only as a visual indicator, not as a second
independent control.

Selected card has highlighted state and explicit **«Выбрана»** label.

No frontend branch may inspect specific `model_id` values.

---

## 6. Responsive model grid

Desktop:

- up to four equal-width cards per row;
- extra models wrap to following rows.

Narrow viewport:

- two columns, then one.

No horizontal scrolling is required.

A future fifth/sixth trusted plugin appears through the same template without
frontend changes.

---

## 7. Model description, icon and badges

Normal model description comes only from
`ModelCatalogEntry.description_ru`.

Frontend must not invent claims such as «самая быстрая», «самая точная»,
«лучше для больших данных» or similar.

V1 uses one neutral generic model icon.
Library-specific icons in the mockup are visual placeholders only.

Generic badges may use catalog fields, for example:

- CPU runtime → **CPU**;
- binary task → **Бинарная классификация**.

No special «Ансамбль» badge without generic backend metadata.

---

## 8. Availability

Backend catalog state is authoritative.

### AVAILABLE

Visible and selectable unless hidden.

### UNAVAILABLE

Visible but disabled.

Primary message:

> **Алгоритм недоступен в текущей среде.**

Known missing-runtime case may show:

> **Не установлены необходимые компоненты.**

### MISCONFIGURED

Visible but disabled.

Primary message:

> **Алгоритм установлен, но конфигурация среды не соответствует требованиям.**

Raw reason codes belong only to technical details.

Unavailable/misconfigured models are not silently hidden.

---

## 9. Hidden models — session-only state

Add one UI/session concept:

```text
hidden_model_ids
```

It is presentation preference only and:

- never unregisters plugin;
- never changes catalog truth;
- never changes scientific identity;
- never changes historical artifacts;
- survives normal navigation;
- survives «Новый эксперимент на этих данных» in the same app session;
- is not persisted across app restarts in V1.

No DB/preferences subsystem is introduced.

---

## 10. Hide model

Card secondary action:

> **Скрыть из списка**

Do not call it «Удалить модель».

For a non-selected model: hide immediately after explicit action.

For the selected model require confirmation:

> **Скрыть «{display_name_ru}» из списка?**
>
> **Эта модель сейчас выбрана для эксперимента. После скрытия потребуется выбрать другую модель.**

On confirm:

- add ID to hidden state;
- clear `selected_model_id`;
- reset active model configuration draft;
- invalidate plan/result;
- do not auto-select another model.

Cancel changes nothing.

---

## 11. Restore hidden models

If any model is hidden show:

> **Скрытые модели · N**

Management list shows model name, current availability and action:

> **Вернуть в список**

Restore only removes presentation preference.
It does not select model or alter configuration.

Historical results remain identifiable regardless of current hidden state.

---

## 12. Future «Подключить модель»

Reserve layout space near hidden-model management for future:

> **+ Подключить модель**

No active V1 action.

V1 must not upload arbitrary model code, install packages, load untrusted
pickle, dynamically import user classes or register arbitrary adapters from UI.

---

## 13. Recommended mode

Fresh model selection:

```text
model_configuration_mode = "RECOMMENDED"
model_user_overrides = {}
```

Primary explanation:

> **Использовать проверенные настройки проекта.**

Recommended has no editable fields.

Read-only summary is generated from backend catalog parameters with
`editable == True` and BASIC `ui_level`, ordered by backend
`display_order`.

Use `display_name_ru` and `recommended_value`.

Do not hardcode parameter names, values or number of summary tiles.

If no BASIC editable parameters exist, show only Recommended explanation.

No active **«Восстановить рекомендуемые»** button while already in Recommended.

---

## 14. Advanced mode

Selecting **«Расширенные»** sets:

```text
model_configuration_mode = "ADVANCED"
```

Entering Advanced alone does not change effective model behavior.

Controls start from backend Recommended values.
Only actual user changes become sparse `model_user_overrides`.

Returning a field exactly to Recommended removes its override.

Advanced → Recommended:

- if no overrides: switch directly;
- if overrides exist: require confirmation that manual changes will be reset.

On confirm:

```text
model_configuration_mode = "RECOMMENDED"
model_user_overrides = {}
```

Frontend never recreates defaults independently.

---

## 15. Generic Advanced controls

Only `CatalogParameter.editable == True` is editable.

| value_type | V1 control |
| --- | --- |
| boolean | checkbox / toggle |
| integer | integer numeric input |
| float | numeric input |
| enum | selectbox from backend choices |

Ranges and choices come only from catalog metadata.

Nullable parameters expose **«Не задавать»** and send `None` when active.

Locked parameters are not normal Advanced controls; they may appear read-only
in technical details.

---

## 16. ui_level / group / order / visibility

Within Advanced:

- BASIC → **Основные настройки**, expanded;
- ADVANCED → **Дополнительные настройки**, collapsed initially.

Do not render empty sections.

`group_id` may be used only for generic adjacency/layout.
Do not show raw group IDs or invent model-specific translations.

Follow backend `display_order`, then deterministic parameter-path tie-break.

Honor accepted declarative `visibility_condition`.
When inactive, dependent control is not emitted as an override.

No expression language is introduced.

---

## 17. Validation UX

Frontend may block only obvious invalid input derivable from catalog metadata:

- wrong primitive type;
- non-nullable null;
- invalid enum;
- below/above declared bound.

Short Russian messages are sufficient.

Backend resolver remains authoritative.

Algorithm V1 does not add a second configuration-resolver API.

If deep/cross-parameter validation fails during planning on Quality, show safe
validation there and return user to Algorithm for correction.

No raw traceback in normal UI.

---

## 18. Capabilities

Capabilities are secondary information.

Selected model may expose collapsed **«Возможности»** based only on
`ModelCatalogEntry.capabilities`.

Useful labels:

- targetless inference → **Прогноз на новых данных**;
- persistence/loading → **Сохранение и загрузка модели**;
- local explanation → **Локальное объяснение результата**.

Provider IDs and raw requirements stay in technical details.

---

## 19. Technical details

Collapsed **«Технические сведения»** may show structured metadata:

- model_id;
- model version;
- adapter version;
- schema ID/version/hash;
- Recommended profile identity;
- plugin contract hash;
- input contract;
- runtime requirements;
- capability technical details;
- current configuration mode;
- current sparse overrides.

Do not dump giant raw JSON as primary representation.

Never display secrets or runtime objects.

---

## 20. Session-state contract

Algorithm UX V1 needs only:

```text
selected_model_id: str | None
model_configuration_mode: "RECOMMENDED" | "ADVANCED"
model_user_overrides: dict[str, JSON-safe value]
hidden_model_ids: session-only collection[str]
```

Existing `selected_model_id` remains authoritative model selection.

Fresh PreparedDatasetContext:

```text
selected_model_id = None
model_configuration_mode = "RECOMMENDED"
model_user_overrides = {}
```

`hidden_model_ids` may survive dataset changes because it is not scientific
state.

---

## 21. Model/config invalidation

Selecting a different AVAILABLE model:

```text
selected_model_id = new_model_id
model_configuration_mode = "RECOMMENDED"
model_user_overrides = {}
```

Then clear downstream plan/result/integration state only.

Do not reset selected features or Quality input controls.

Any configuration mode/override change:

- preserves dataset;
- preserves feature subset;
- preserves selected model;
- preserves protocol/seed/folds UI input;
- invalidates stale plan/result/integration output.

No per-model configuration cache is required in V1.

---

## 22. Navigation and re-entry

### Algorithm → Features → Algorithm

Preserve:

- selected model;
- configuration mode;
- overrides;
- hidden-model preference.

Feature changes invalidate downstream plan/result under existing rules but do
not silently reset model/config.

### Algorithm → Quality

Next does not train and does not run smoke.

It forwards current:

```text
selected_feature_ids
selected_model_id
model_configuration_mode
model_user_overrides
```

Quality owns protocol, seed, folds, comparison metadata, planning, resolved
configuration, mandatory smoke and run readiness.

### Quality → Algorithm

Going back preserves Quality inputs and Algorithm draft.

Changing Algorithm config invalidates old plan/smoke applicability but does not
erase unrelated Quality inputs.

---

## 23. New experiment on same data

«Новый эксперимент на этих данных» reuses current PreparedDatasetContext and
preserves:

- feature subset;
- selected model;
- configuration mode;
- user overrides;
- hidden-model preference.

It clears only run-specific downstream state.

Reason: silently resetting Advanced to Recommended would introduce an extra
experiment change not chosen by the user.

---

## 24. Different/new DatasetContext

When PreparedDatasetContext changes:

- feature subset reinitializes from new registry;
- selected model clears;
- configuration mode resets to RECOMMENDED;
- overrides clear;
- plan/result/integration clear.

`hidden_model_ids` may remain session-level.

No model is auto-selected for the new context.

---

## 25. Stale selection

Do not silently choose a replacement.

If remembered model remains registered but is now unavailable/misconfigured:

> **Ранее выбранный алгоритм сейчас недоступен. Выберите другой алгоритм для продолжения.**

Next is disabled until explicit AVAILABLE selection.

If model disappeared from registry:

> **Ранее выбранный алгоритм отсутствует в текущем реестре. Выберите другой алгоритм.**

If selected model was explicitly hidden, hide action already clears selection.

---

## 26. Error and empty states

### Catalog composition failure

> **Каталог алгоритмов временно недоступен.**

No partial catalog and no Next.
Stable diagnostic may appear only in technical details.

### Empty catalog

> **В реестре нет зарегистрированных алгоритмов.**

### No AVAILABLE models

> **Нет алгоритмов, готовых к запуску в текущей среде.**

Known disabled cards remain visible.

### All models hidden

> **Все модели скрыты из рабочего списка. Верните нужную модель, чтобы продолжить.**

Show hidden-model management; do not auto-restore.

### Advanced has no editable fields

> **Для этой модели нет параметров, доступных для ручной настройки.**

Advanced may be disabled.

### Invalid Advanced draft

Keep entered values where safe.
Do not silently clamp or replace them.

---

## 27. Next-button rule

**«Далее: проверка качества →»** is enabled only when:

- at least one feature is selected;
- one current model is selected;
- model exists in current catalog;
- model state is AVAILABLE;
- model is not hidden;
- configuration mode is valid;
- current visible draft can be represented as sparse overrides.

Warnings/info do not block by themselves.

Deep configuration validity remains backend-owned on Quality.

---

## 28. PlanningRequest handoff

Algorithm state maps directly to accepted fields:

```text
selected_feature_ids
selected_model_id        → model_id
model_configuration_mode → configuration_mode
model_user_overrides     → user_overrides
```

Quality supplies existing:

```text
protocol_id
protocol_version
seed
folds
evaluation_level
reference_artifact_id
changed_dimension
changed_elements
```

No additional backend contract is required.

---

## 29. Quality boundary

Quality performs:

```text
PlanningRequestMetadata
→ ExperimentPlanningService.build_plan()
→ resolved model configuration
→ mandatory technical smoke
→ run readiness
→ ExperimentApplicationService
```

Smoke is technical readiness, not quality evaluation.

Planning/config error does not mutate Algorithm draft or auto-fix values.

---

## 30. Relationship to designer mockup

Keep:

- overall dark graphite/emerald visual direction from the designer mockup; product name/logo remain a replaceable global branding layer;
- current four-card desktop row;
- selected card highlight;
- compact dataset/feature summary;
- separate settings block;
- Recommended/Advanced segmented control;
- compact Recommended values;
- collapsed technical area;
- bottom navigation.

Do not implement literally:

- library-specific icons;
- hardcoded model descriptions;
- hardcoded «Ансамбль» badge;
- hardcoded parameter list/value/count;
- L2 tile unless catalog actually declares it;
- active restore button in Recommended;
- duplicate independent radio + button selection semantics.

The mockup is visual reference, not backend truth.

---

## 31. Acceptance criteria

Algorithm UX V1 is accepted only if:

1. cards are generated only from current `ModelCatalogEntry`;
2. future trusted plugin needs no frontend model-id branch;
3. descriptions come only from backend catalog;
4. Russian parameter text comes only from accepted presentation projection;
5. no model-specific icon/badge/parameter dictionary exists in frontend;
6. whole AVAILABLE card is one selection action;
7. UNAVAILABLE/MISCONFIGURED stay visible and disabled by default;
8. raw reason codes are not primary user copy;
9. hidden-model state is session-only presentation state;
10. hiding selected model requires confirmation and clears active model/config;
11. hide never auto-selects replacement;
12. restore never auto-selects;
13. hidden and unavailable are distinct;
14. Recommended is fresh-model default;
15. Recommended uses empty overrides;
16. Recommended summary is generated from BASIC editable catalog parameters;
17. no active restore action appears while already Recommended;
18. Advanced controls come only from editable catalog parameters;
19. type/range/choices/order/visibility come only from catalog;
20. Advanced → Recommended with overrides confirms reset;
21. model change resets active configuration only;
22. back/forward preserves model/config draft;
23. feature changes do not silently reset model/config;
24. new experiment on same context preserves feature subset, model, mode and overrides;
25. new DatasetContext clears model/config but may preserve hidden preference;
26. stale/unavailable selection never causes silent fallback;
27. catalog/empty/no-available/all-hidden states have explicit Russian messages;
28. Algorithm does not train or run smoke;
29. Algorithm → Quality forwards accepted mode/override fields;
30. Quality owns protocol/seed/folds/smoke/run readiness;
31. no active arbitrary «Подключить модель» path exists;
32. existing backend contracts remain unchanged.

---

## 32. Non-goals

Not part of Algorithm UX V1:

- model-platform redesign;
- parameter-presentation redesign;
- new planning DTO;
- resolver changes;
- smoke redesign;
- model training;
- feature-permission changes;
- semantic model ranking;
- auto best-model selection;
- persistent user preferences / DB;
- model marketplace;
- arbitrary plugin upload/install;
- model-specific icon metadata contract;
- threshold/business decision;
- SHAP/LLM changes;
- application-wide branding redesign.

---

## 33. Implementation scope after review

Expected narrow implementation scope:

- `app/streamlit_app.py`;
- `app/session_state.py`;
- focused Streamlit/session-state tests.

Consume current accepted:

- `ExperimentPlanningService.list_models()`;
- `ModelCatalogEntry / CatalogParameter`;
- `PlanningRequestMetadata.configuration_mode`;
- `PlanningRequestMetadata.user_overrides`;
- existing Quality/planning/application services.

If implementation finds a locked behavior that current contracts cannot
represent, STOP and return the exact gap rather than inventing frontend truth.

---

## 34. Final status

No new backend blocker was found on current main.

```text
Algorithm UX V1:
UX / VISUAL LOCK — ACCEPTED / READY_FOR_IMPLEMENTATION

Implementation:
NOT STARTED
```

Next:

```text
Codex implementation
→ Reviewer
→ manual visual acceptance
```
