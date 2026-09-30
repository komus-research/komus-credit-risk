# Models UX V1 — Product / Visual Lock

Status: **ACCEPTED PRODUCT / VISUAL LOCK — BACKEND IMPLEMENTATION PENDING**

Primary visual references:

- `docs/design/screens/models/01_models_hub_v1.png`
- `docs/design/screens/models/02_algorithm_detail_v1.png`
- `docs/design/screens/models/02_algorithm_detail_highlight_v1.png`
- `docs/design/screens/models/03_model_version_detail_v1.png`
- `docs/design/screens/models/04_saved_model_inference_v1.png`
- `docs/design/screens/models/05_saved_model_inference_result_v1.png` — VISUAL LOCK; saved targetless inference Result with `Сохранить конфигурацию`; demo threshold `0.37` represents a changed/saved view, while no-config default remains `0.50`

## 1. Product model

AXION distinguishes two entities:

```text
Algorithm / ModelPlugin
→ registered algorithm definition

ModelVersion
→ one concrete trained and saved model produced by one training run
```

One algorithm can have many trained ModelVersion records on different datasets, feature sets and configurations.

Example:

```text
CatBoost
├─ ModelVersion A → Data_final / 47 features
├─ ModelVersion B → clients_aug / 41 features
└─ ModelVersion C → sample_2026 / 35 features
```

The UI must never merge these two identities.

## 2. Models Hub

Visual lock:

`01_models_hub_v1.png`

The sidebar route **«Модели»** opens the models library.

Header:
- title **«Модели»**;
- subtitle about available algorithms and saved trained models;
- primary action **«Подключить алгоритм»**.

Tabs:
- **«Обученные модели»**;
- **«Алгоритмы»**.

The accepted base mockup shows **«Обученные модели»** active.

### Trained models list

Each row is one saved ModelVersion.

Canonical list fields:
- user-facing model name;
- algorithm;
- dataset;
- predictor feature count;
- training date;
- explicitly OOF-labelled quality metric;
- row action / open detail.

Search and compact filters may include:
- model name;
- algorithm;
- dataset;
- training date.

No automatic winner, best-model ranking or final-test metric is inferred from this catalog.

## 3. Algorithm Detail

Visual locks:

- default state: `02_algorithm_detail_v1.png`;
- metric-highlight state: `02_algorithm_detail_highlight_v1.png`.

Purpose:

> The user knows the algorithm, for example CatBoost, but does not remember which dataset / training run produced the required saved model.

Route:

```text
Модели
→ Алгоритмы
→ CatBoost
```

The screen shows:
- trusted algorithm identity and version;
- source: built-in or connected;
- category;
- supported capabilities;
- compact summary: saved ModelVersion count, dataset count, feature-count range, last training date;
- action **«Новый анализ с CatBoost»**;
- table of all saved ModelVersion records produced by that algorithm.

### ModelVersion table

Canonical columns:
- model display name;
- dataset;
- feature count;
- training date;
- OOF Gini;
- ROC-AUC;
- PR-AUC;
- actions.

Metric values are descriptive facts from each saved run. They are not an automatic ranking and do not imply final-test performance or temporal stability.

A row opens the future ModelVersion Detail screen.

## 4. Metric Highlight

Default state:

`Подсветка метрик = Выкл`.

The default screen remains the canonical neutral view.

When enabled:
- only metric cells are highlighted;
- OOF Gini, ROC-AUC and PR-AUC are compared separately inside their own columns;
- comparison is relative to the **currently displayed / filtered list**;
- filtering recomputes the relative presentation;
- sorting remains independent from highlighting;
- the model row itself is not assigned an overall class or rank.

Accepted visual direction:
- upper relative values: stronger cyan / teal tint;
- middle values: restrained neutral teal/slate;
- lower values: weak / near-neutral tint;
- no red/green traffic-light semantics;
- no A/B/C labels;
- no aggregate score;
- no winner badge.

Tooltip may say, for example:

> **2-е по величине из 8 в текущем списке**

The tooltip describes only the selected metric column.

Metric highlighting is a presentation aid, not a scientific or business conclusion.

## 5. Algorithm action

**«Новый анализ с CatBoost»** opens a new analysis with the algorithm preselected.

It does not:
- start training automatically;
- select a dataset automatically;
- select features automatically;
- select hyperparameters outside accepted defaults.

The user continues through the normal AXION analysis flow.

## 6. Connected algorithms

The **«Подключить алгоритм»** action uses the single accepted Connect Algorithm flow:

`docs/workstreams/generic_dataset_onboarding_v1/CONNECT_ALGORITHM_UX_V1.md`.

The same flow is reachable from:
- `Новый анализ → Алгоритм`;
- `Модели`.

No duplicate onboarding implementation is introduced.

## 7. Backend gap / implementation boundary

The visual/product lock does **not** mean the current backend already supports the models library.

Current accepted backend lacks a public trusted browse/list/history contract for all persisted ModelVersion records.

Therefore implementation must first provide an application-facing read contract. It must not:
- scan artifact directories from UI;
- infer catalog rows from filesystem filenames;
- fabricate counts or dates;
- treat current-session `loaded_model_version` as the full library.

The backend remains source of truth for:
- ModelVersion identity;
- dataset identity;
- feature binding;
- configuration/provenance;
- stored OOF metrics;
- creation/training timestamps.

## 8. ModelVersion Detail

Visual lock:

`03_model_version_detail_v1.png`

Purpose:

> One concrete saved ModelVersion: what it is, what data/configuration produced it, what OOF quality it achieved, and what the user can do next.

Accepted information hierarchy:
- header identifies saved model display name, algorithm, saved-model version and saved status;
- compact quick summary shows dataset, predictor feature count, training date and OOF Gini;
- primary actions: **«Использовать для прогноза»**, **«Новый запуск на основе модели»**, **«Открыть результаты»**;
- **«Качество модели (OOF)»** is the single detailed quality block for Gini / ROC-AUC / PR-AUC / Precision / Recall / F1;
- **«Данные и признаки»** is the source for dataset, working population, target, identifier and feature preview;
- **«Параметры обучения»** is collapsed by default and contains saved configuration / seed / training facts;
- **«Объяснимость»** stays compact and reports Local Explanation / SHAP and Result Interpreter compatibility;
- **«Технические сведения»** stays collapsed for IDs, hashes, folds, provider/runtime provenance.

The screen intentionally removes a separate duplicate «Обзор модели» block.

`OOF Gini` may appear once in the quick summary as a fast orientation and again inside the detailed OOF quality block; that duplication is intentional. Other quality metrics are not repeated in the quick summary.

### Actions semantics

**«Использовать для прогноза»** starts a future inference flow using the saved ModelVersion; it does not retrain the model.

**«Новый запуск на основе модели»** creates a new analysis seeded from the saved model configuration where supported. It must never mutate or overwrite the current ModelVersion; a completed new training produces a new ModelVersion.

**«Открыть результаты»** opens the saved experiment/result associated with this ModelVersion when the trusted artifact identity is available.

The visual lock does not itself create missing backend contracts for model-library browse/detail/inference or lifecycle actions.

### Runtime action-copy rule

Accepted PNG labels define action semantics, not an obligation to preserve every long phrase literally. During implementation, when the surrounding screen already makes the action unambiguous, AXION may use a shorter human-facing CTA with a clear icon — for example `▶ Анализ` for applying the selected saved ModelVersion to already loaded new data. The shorter label must not change the underlying action, skip compatibility checks, start training, or hide important consequences. Supporting text/tooltip is used only where needed for clarity.

## 9. Saved Model Inference V1

Visual lock:

`04_saved_model_inference_v1.png`

Purpose:

> Apply one already-trained saved ModelVersion to a new compatible dataset without retraining it.

Accepted screen semantics:
- the selected saved ModelVersion is read-only and shows its display name, algorithm, saved-model version, **training dataset**, training date and **model feature count**;
- the new dataset is separate from the training dataset and may omit target completely;
- identifier may be used for object display when available;
- compatibility check validates required model features, trusted feature binding/order, compatible input types, row readiness and identifier handling;
- extra columns are allowed but are explicitly excluded from model input;
- missing/incompatible required model inputs fail closed;
- the model is not retrained in this flow;
- Local Explanation / SHAP and Result Interpreter are shown only as capabilities available after successful inference.

Primary runtime CTA follows the AXION short-action style:

`▶ Анализ`

On this screen the surrounding context already establishes that the user selected a saved model and loaded new data, so the short CTA is preferred over a verbose technical label.

The screen title may remain **«Прогноз на новых данных»** as the name of the inference scenario, while row-level outputs are described as **оценки модели** where technical precision matters.

### Backend boundary

This visual lock does not mean targetless inference workflow is already implemented end-to-end.

Future backend implementation must provide a trusted application contract for:
- loading the exact saved ModelVersion;
- validating a new dataset against its saved model input/feature binding;
- deterministic targetless prediction;
- storing or returning prediction-result identity;
- opening object-level explanations from those prediction results.

The UI must not infer compatibility from column count alone and must not silently remap missing model features.

## 10. Saved Model Inference Result V1 — visual lock

Reference:

`05_saved_model_inference_result_v1.png`

The owner accepted the final screen composition and current visual language. This PNG is the **VISUAL LOCK** for Saved Model Inference Result V1. The top action is `Сохранить конфигурацию`. Conditional `Сбросить настройки` remains inside the existing `⋯` menu and therefore does not need a separate always-visible control in the locked base state. Demo threshold `0.37` represents a changed/saved view; runtime default without saved configuration remains `0.50`.

Stable semantics already visible in the reference:
- targetless inference result shows immutable model scores for new objects;
- no TP/TN/FP/FN, Recall, Precision, F1 or OOF quality may be inferred for the new dataset without target;
- table exposes identifier, model score and position relative to an explicit analytical threshold;
- score range filters the list and does not change scores or retrain the model;
- object-level Local Explanation / SHAP and Result Interpreter are downstream capabilities after selecting an object;
- the current summary uses plain counts for objects above/below threshold plus percentages and score range.

### Accepted inference-result / saved view-configuration lifecycle

Canonical model:

```text
Saved ModelVersion
+ targetless inference dataset
→ immutable SavedModelInferenceResult
    ├─ object identities
    └─ immutable model scores

SavedModelInferenceResult
    ↓
mutable SavedInferenceResultViewConfiguration
    ├─ threshold
    ├─ score range
    ├─ above/below/all filter
    ├─ sort
    └─ search
```

Accepted semantics:
- successful inference automatically persists one immutable `SavedModelInferenceResult` with exact `ModelVersion`, targetless dataset identity/fingerprint, input-contract provenance, object identities and immutable scores;
- changing threshold, filters, score range, sorting or search never creates a new prediction run or duplicate Result, never changes scores and never retrains/reconfigures the ModelVersion;
- `Изменить порог` is an inline analytical control on the current Result;
- targetless threshold derives only `выше / ниже порога`, counts, shares, filters and threshold-relative sorting; no TP/TN/FP/FN, Recall, Precision or F1 are available without `y_true`;
- threshold is not a property of `ModelVersion`; a future approved operating-threshold policy would be a separate explicit contract;
- initial V1 threshold is technical default `0.50`, explicitly described as an analytical boundary, not an automatically selected business/optimal threshold;
- accepted OOF diagnostic threshold does not automatically become targetless inference threshold.

### Saved configuration V1

The Result header action is:

**`Сохранить конфигурацию`**

It saves the current analytical view settings for this exact inference Result. V1 stores one active saved configuration per `inference_result_id`; repeated save updates/replaces that configuration instead of creating scenario history.

Minimum V1 fields:

```text
inference_result_id
threshold
min_score
max_score
position_filter   # ALL / ABOVE / BELOW
sort              # accepted list sort
search            # current identifier search text
updated_at
```

Not part of saved configuration:
- immutable scores/object rows themselves;
- model parameters or ModelVersion state;
- training/inference rerun;
- selected object/detail route;
- scroll position / offset / transient loading state.

When the same Result is opened later:
- if a saved configuration exists, AXION restores it automatically;
- if none exists, AXION opens defaults: threshold `0.50`, score range `0.00–1.00`, `Все`, score descending, empty search.

### Reset settings

`Сбросить настройки` is available only when a saved configuration exists for the current Result. It should live in the existing `⋯` menu rather than compete with the primary action.

Reset behavior:
- delete the saved view configuration for this Result;
- immediately restore the V1 defaults;
- keep the immutable `SavedModelInferenceResult` and all scores untouched.

A lightweight undo/toast is allowed, but a blocking confirmation dialog is not required for V1 because no prediction evidence is deleted.

### Dirty/saved state

If the user changes any saved field after the last save, `Сохранить конфигурацию` becomes actionable again. After successful save, the UI may briefly show `Конфигурация сохранена` and return to the normal button state.

Canonical distinction:

```text
SavedModelInferenceResult R123  # immutable prediction evidence
└─ Saved view configuration     # mutable convenience state
   threshold = 0.37
   range = 0.10–0.85
   filter = ABOVE
   sort = SCORE_DESC
```

Saving/changing this configuration does not create another prediction Result.

Implementation direction:
- `SavedModelInferenceResultService` owns create/load of immutable inference evidence;
- a small Result-view service derives threshold counts/list/filter from explicit current view state;
- a separate lightweight configuration persistence boundary stores/loads/resets one saved view configuration per Result;
- the configuration layer must never mutate `SavedModelInferenceResult` or `ModelVersion`.

Visual lock notes for `05_saved_model_inference_result_v1.png`:
- `Сохранить конфигурацию` is the canonical top action;
- `Сбросить настройки` is conditional inside `⋯` and appears only when a saved configuration exists;
- `0.37` in the locked PNG is demo saved-view state; default without saved configuration is `0.50`;
- the accepted composition must not be reinterpreted as a new prediction run when view settings change.
