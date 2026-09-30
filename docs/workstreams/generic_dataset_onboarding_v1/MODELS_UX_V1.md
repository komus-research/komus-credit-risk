# Models UX V1 — Product / Visual Lock

Status: **ACCEPTED PRODUCT / VISUAL LOCK — BACKEND IMPLEMENTATION PENDING**

Primary visual references:

- `docs/design/screens/models/01_models_hub_v1.png`
- `docs/design/screens/models/02_algorithm_detail_v1.png`
- `docs/design/screens/models/02_algorithm_detail_highlight_v1.png`
- `docs/design/screens/models/03_model_version_detail_v1.png`
- `docs/design/screens/models/04_saved_model_inference_v1.png`
- `docs/design/screens/models/05_saved_model_inference_result_v1.png` — DESIGN REFERENCE; threshold lifecycle/persistence pending Architect decision

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

## 10. Saved Model Inference Result V1 — current design reference

Reference:

`05_saved_model_inference_result_v1.png`

The owner accepted the screen composition and current visual language. It is intentionally recorded as a **DESIGN REFERENCE**, not yet a full semantic visual lock, because threshold lifecycle/persistence is awaiting a separate Architect decision.

Stable semantics already visible in the reference:
- targetless inference result shows immutable model scores for new objects;
- no TP/TN/FP/FN, Recall, Precision, F1 or OOF quality may be inferred for the new dataset without target;
- table exposes identifier, model score and position relative to an explicit analytical threshold;
- score range filters the list and does not change scores or retrain the model;
- object-level Local Explanation / SHAP and Result Interpreter are downstream capabilities after selecting an object;
- the current summary uses plain counts for objects above/below threshold plus percentages and score range.

Open Architect decision:
- whether inference result is automatically persisted as immutable result evidence;
- whether threshold is transient view state or a persisted scenario over one immutable result;
- what the top action `Сохранить` means;
- where the initial targetless-inference threshold comes from;
- `Изменить порог` must not be implemented as a model retraining action unless a future accepted decision explicitly changes this.
