# Result V2 — Architecture Lock

Status: **ACCEPTED ARCHITECTURE LOCK**

Основание: Architect decision по Result V2 / OOF Result Contract + accepted Object List delta.

## 1. Главное решение

Canonical persisted source Result V2 — immutable **ExperimentArtifact V3**.

Не вводить:
- новую БД;
- отдельный Result store;
- отдельную pagination subsystem;
- cursor pagination для V1;
- новый ModelVersion на каждый fold.

Поверх Artifact V3 используются две application boundaries:

```text
OOFResultService
→ summary
→ threshold
→ objects
→ object detail

OOFExplanationService
→ Local OOF SHAP
→ Global OOF SHAP aggregate
```

UI работает только через public services/API DTO.
## 2. ExperimentArtifact V3

Существующие facts сохраняются:
- artifact_id;
- ExperimentConfig / config_hash;
- DatasetContract / dataset_fingerprint;
- EvaluationPopulation / population_fingerprint;
- ExperimentResult;
- configuration + smoke provenance;
- OOF score;
- fold assignments;
- row positions.

Добавить:
- `oof_y_true`;
- `identifier_display`;
- exact aligned OOF model input matrix только selected predictors;
- minimal ordered feature binding;
- exact persisted evaluation model каждого fold.

Техническая identity строки:
```text
artifact_id + dataset_fingerprint + row_position
```

Public `object_id` — opaque deterministic identity, не identifier_display.

Все row-aligned arrays/inputs обязаны иметь одну canonical row alignment.
## 3. Fold model provenance

Fold model — часть evaluation evidence ExperimentArtifact и не является final/refit ModelVersion.

Для каждого fold сохраняется exact fitted model через trusted persistence provider chain.

Canonical invariant:

```text
object
→ OOF prediction
→ fold assignment
→ exact fold model
→ exact persisted input
→ explanation
```

Перед Local SHAP reloaded fold model обязан воспроизвести stored OOF probability.
Mismatch → fail closed.

Запрещён fallback:
```text
OOF prediction → final/refit model SHAP
```

CatBoost / XGBoost / LightGBM Local OOF SHAP поддерживаются при валидном provenance.

Прежнее решение `GBDT Mean OOF SHAP = UNSUPPORTED` superseded архитектурным lock `UNIVERSAL_MODEL_EXPLAINABILITY_V1.md`: после UME-BE1 GBDT Mean должен иметь validated probability-space Local Explanation через universal provider boundary.
## 4. Threshold semantics

Canonical stored facts:
- `y_true`;
- immutable OOF probability.

Для explicit threshold `t`:
```text
predicted_positive = score >= t
```

Derived only:
- TP / TN / FP / FN;
- Recall;
- Precision;
- F1;
- above_threshold_count;
- above_threshold_share.

Threshold:
- finite;
- `0 <= t <= 1`;
- не переобучает модель;
- не меняет score;
- не использует final test;
- не выбирает business optimum.

При `threshold=0.5` derived values должны воспроизводить canonical ExperimentResult, иначе Artifact V3 не публикуется.
## 5. Object List public contract

Logical contract:

```text
objects(
    artifact_id,
    threshold,
    offset,
    limit,
    search=None,
    target=None,
    outcomes=None,
    min_score=None,
    max_score=None,
    sort="SCORE_DESC",
)
```

Response:
```text
artifact_id
threshold
total_count
filtered_count
offset
limit
returned_count
items[]
```

Item:
```text
object_id
identifier_display
y_true
score
predicted_positive
outcome
```

Fold остаётся detail/provenance field и не обязан входить в list DTO.
## 6. Object List query semantics

Search V1:
- только `identifier_display`;
- trimmed literal substring;
- case-insensitive / Unicode casefold;
- без regex/fuzzy/feature search.

Target:
- ANY;
- POSITIVE → `y_true == 1`;
- NEGATIVE → `y_true == 0`.

Outcomes:
- множество из TP/TN/FP/FN;
- всегда derived от current explicit threshold.

Score range:
- optional `min_score`, `max_score`;
- inclusive;
- значения в [0,1];
- если оба заданы, `min_score <= max_score`.

Sorting V1:
- SCORE_DESC;
- SCORE_ASC;
- DISTANCE_TO_THRESHOLD_ASC = `abs(score-threshold)`.

Всегда deterministic tie-break:
```text
row_position ASC
```
## 7. Quick views

Quick views — frontend presets над public query contract, не отдельный backend domain.

- «Ошибки модели» → outcomes={FP,FN}
- «Пропущенные события» → outcomes={FN}
- «Ложные срабатывания» → outcomes={FP}
- «Пограничные» → sort=DISTANCE_TO_THRESHOLD_ASC
- «Высокая оценка модели» → sort=SCORE_DESC
- «Все объекты» → снимает quick-view outcome/sort preset

Запрещены hidden magic values:
- никакого `score >= 0.8`;
- никакого `threshold ± 0.05`;
- никаких других незафиксированных cutoffs.
## 8. Random access / virtualization

Используется offset/limit, не cursor.

`offset` — zero-based позиция внутри уже filtered + sorted view.

Backend обязан уметь запросить большой offset напрямую:
```text
offset=120000, limit=50
```
без последовательного чтения предыдущих chunks.

Counts:
- `total_count` = OOF population данного artifact;
- `filtered_count` = число строк после search/filters;
- sorting count не меняет.

Frontend:
- не загружает полный Result;
- не сортирует/фильтрует canonical Result локально;
- не читает artifact files/runner internals;
- может использовать virtualized/windowed rendering;
- page number не является domain concept.
## 9. Global OOF SHAP

Canonical derived metric для поддерживаемых моделей:

**OOF mean absolute local SHAP**

Каждая OOF строка объясняется своей fold model, затем считается row-weighted:
```text
mean(abs(SHAP))
```
по всем OOF rows для каждого feature.

Это:
- cross-validated aggregate OOF local attributions;
- не final-model SHAP;
- не causal importance.

После UME-BE1 тот же aggregate contract применяется и к GBDT Mean через validated probability-space ensemble explanation.

При невалидном fold весь aggregate fail closed.
## 10. Lifecycle / errors

Result публикуется только после:
- завершения всех folds;
- OOF arrays;
- fold model capture;
- fold model round-trip verification;
- OOF/result validation;
- manifest hashes.

Новый run не удаляет старый artifact.
Upstream scientific change очищает только active result pointer/session-derived state.

Legacy incomplete artifacts не достраиваются по догадке.

Stable error families включают:
- RESULT_NOT_FOUND / RESULT_INTEGRITY_ERROR;
- OOF_RESULT_EVIDENCE_INCOMPLETE;
- INVALID_THRESHOLD / OBJECT_NOT_FOUND;
- LOCAL_OOF_EXPLANATION_UNSUPPORTED;
- FOLD_MODEL_UNAVAILABLE / PROVENANCE_MISMATCH;
- OOF_PREDICTION_MISMATCH;
- GLOBAL_OOF_EXPLANATION_UNSUPPORTED / INCOMPATIBLE.
## 11. Preserved invariants

- Final test не участвует в OOF Result.
- Historical KOMUS Result V3 содержит только working population.
- Threshold explorer работает по OOF evidence.
- LLM не predictor.
- SHAP не причинность.
- Final/refit SHAP не выдаётся за OOF SHAP.
- UI не видит filesystem paths, native filenames, Runner или registry objects.
- DB / Project-history subsystem не вводятся ради Result V2.

## 12. Implementation order

Quality V1A — **ACCEPTED**, source commit `d3d001b4e6ab1a927b0289d1020c2415d7a41448`.

R2-BE1 — OOF Evidence Artifact V3 — **ACCEPTED / CLOSED**, source commit `5e4fff6e38d4d31b6c24dc83c6b154cb9d0706ab`.

UME-BE1 — Universal Model Explainability V1 — **ACCEPTED / CLOSED**, source commit `2bc4e175911cec29bf3c21aa129a40609b0ee4b7`.

R2-BE2A — OOF Result Read Core — **ACCEPTED / CLOSED**, source commit `81707dc14edf678db39a3ba71f5aad0c50c36eab`.

R2-BE2B — Local OOF Explainability — **ACCEPTED / CLOSED**, source commit `1ee6e10f581e5281fc63f21a6a86c7cffcfe0e05`.

R2-BE2C — Global OOF SHAP Aggregate — **ACCEPTED / CLOSED**, source commit `3de33309`. Reviewer corrective cycle закрыт: valid multi-feature Local Explanation может приходить в SHAP-ranked order; Global validation проверяет exact complete `feature_id → column_name` binding без требования positional order.

Принятый backend теперь покрывает:
- summary;
- explicit threshold metrics;
- random-access object list;
- object detail с Fold provenance;
- exact persisted fold model reload;
- strict OOF probability replay;
- validated `LocalExplanationEvidence V2` через trusted `explain_batch()` path;
- Global OOF SHAP как row-weighted `mean(abs(local SHAP))` по всем OOF rows, каждая строка через exact assigned fold model.

Final/refit fallback для OOF explanation отсутствует.

Result V2 backend contract закрыт. Следующий отдельный этап — native Result implementation поверх принятых public Result/Explanation boundaries.
