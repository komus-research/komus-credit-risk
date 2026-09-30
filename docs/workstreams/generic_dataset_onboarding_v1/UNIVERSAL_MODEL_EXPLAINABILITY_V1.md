# Universal Model Explainability V1 — Architecture Lock

Status: **ACCEPTED ARCHITECTURE LOCK / IMPLEMENTATION PENDING**

Основание: owner requirement — любая модель, доступная пользователю как полноценная модель AXION, обязана иметь единый путь:

```text
prediction
→ validated Local Explanation
→ human-readable Result Interpreter
```

Этот lock не меняет принятый `ExperimentArtifact V3` и не расширяет уже закрытый R2-BE1.

## 1. Главное решение

Используется отдельная trusted explainability boundary:

```text
ModelPlugin
→ local_explanation_provider descriptor
→ ModelExplanationProviderRegistry
→ executable ModelExplanationProvider
→ normalized LocalExplanationEvidence V2
→ ResultInterpreterService
```

Frontend не выбирает SHAP implementation и не ветвится по model family.

Полноценная модель AXION должна поддерживать:
- persistence;
- loading;
- targetless inference;
- local explanation.

Для Experiment/Quality flow дополнительно сохраняются training / configuration / smoke-test capabilities.

Prediction-only модель не считается полноценной моделью основного Result flow.
## 2. Readiness / availability semantics

Модель может быть `AVAILABLE` в основном Result flow только если одновременно:

- trusted persistence provider зарегистрирован;
- trusted explanation provider зарегистрирован;
- model / provider identities согласованы;
- persistence round-trip воспроизводит prediction;
- Local Explanation reconstructs тот же prediction;
- explanation provenance воспроизводим;
- normalized evidence принимается общим Result Interpreter.

Используются существующие catalog semantics:
- `AVAILABLE` — полный контракт выполнен;
- `UNAVAILABLE` — обязательная capability отсутствует;
- `MISCONFIGURED` — capability заявлена, но provider / identity / runtime validation не проходит.

Отдельный постоянный `PREDICTION_ONLY` state не вводится.

## 3. ModelExplanationProvider

Новая backend boundary зеркальна persistence-provider architecture.

Executable provider должен декларировать минимум:
- provider_id / provider_version;
- model_id / model_version / adapter_version;
- explanation_method_id / version;
- output_space.

Provider обязан:
- проверять совместимость trusted loaded predictor;
- строить Local Explanation;
- работать в exact feature order;
- подтверждать reconstruction prediction;
- возвращать provider provenance;
- поддерживать OOF batch path для Global explanation.

`ModelPluginRegistry` fail-closed валидирует explanation provider так же, как persistence provider.
## 4. GBDT Mean

Прежнее постоянное состояние `GBDT Mean OOF SHAP = UNSUPPORTED` superseded этим lock.

GBDT Mean должен получить validated Local Explanation в probability space.

Для equal-weight ensemble:

```text
P(x) = (P_CB(x) + P_XGB(x) + P_LGB(x)) / 3
```

Запрещено усреднять существующие raw-margin SHAP.

Каждый component объясняется:
- в одном output space = probability;
- с одним feature binding;
- с одной deterministic background policy;
- с одной masking / interventional semantics.

Ensemble explanation строится как среднее component base values и component SHAP values только после подтверждения одинаковой explanation game.

Mandatory checks:
- component base + Σ component SHAP ≈ component probability;
- mean(component probabilities) ≈ stored ensemble OOF probability;
- ensemble base + Σ ensemble SHAP ≈ stored ensemble OOF probability.

Любой mismatch → fail closed.

Provenance включает:
- ensemble fold-model identity;
- identities component models;
- explanation-provider identities;
- weights;
- output space;
- background policy / hash;
- feature binding hash;
- method/version.

Если pinned runtime конкретного backend не проходит эти проверки, GBDT Mean не объявляется `AVAILABLE` до исправления provider.

Допустимый резервный путь — отдельный trusted model-agnostic probability SHAP непосредственно над ensemble predictor, со своей method identity и теми же reconstruction gates. Скрытый fallback запрещён.
## 5. Background policy для GBDT Mean V1

Background:
- только outer-train population того же fold;
- никогда validation row объясняемого OOF объекта;
- никогда final test;
- deterministic selection;
- versioned `background_policy_id`;
- actual selected row positions / background hash входят в provenance.

## 6. Connected Model onboarding

Будущая функция «Подключить модель» не принимает произвольный executable Python / pickle из browser.

V1 package:

```text
native model artifact(s)
+
declarative manifest
+
reference to already trusted plugin/providers
```

Пользователь предоставляет:
- native model files разрешённого registered format;
- model/version identity;
- feature binding;
- declarative metadata.

Reviewed AXION installation / plugin author предоставляет:
- trusted model adapter;
- persistence/load provider;
- explanation provider или разрешённый generic explanation provider;
- input contract;
- capability manifest.

Новый executable provider попадает в систему только через reviewed code/deployment path.
Перед registration connected model проходит:

```text
manifest / hashes
→ trusted load
→ prediction
→ save/reload round-trip
→ same prediction
→ Local Explanation
→ reconstruction
→ feature-order validation
→ provenance validation
→ Result Interpreter compatibility
→ registration
```

Если Local Explanation gate не проходит, registration в основной model catalog запрещена.

Generic explanation provider допустим только как trusted implementation над фактическим predictor output с reproducibility/reconstruction gate. Это не означает поддержку произвольного файла модели.

## 7. Normalized LocalExplanationEvidence V2

Evidence должен быть model-family independent.

Минимальная логическая структура:

```text
evidence_version

source_kind
source_artifact_id
model_binding_id

model_id
model_version
dataset_fingerprint
feature_set_hash

object_id
identifier metadata

prediction_probability

explanation_method_id
explanation_method_version
output_space
base_value
explained_output_value

features[]
  feature_id
  column_name
  display_name_ru
  description_ru
  raw_value
  shap_value
  direction
  abs_rank

provider_id
provider_version
provenance
evidence_hash
```

`model_binding_id` связывает evidence либо с exact OOF fold model, либо с persisted ModelVersion.

`direction` означает только увеличение/уменьшение model output. Без отдельной semantic contract нельзя переименовывать это в «повышает/снижает риск».

Failed integrity не публикуется как evidence object: failure остаётся отдельным application outcome.
## 8. Object Detail: auto Local Explanation

Accepted product semantics:

```text
open Object Detail
→ basic OOF facts immediately
→ Local Explanation request automatically
→ neutral loading state
→ validated evidence appears
```

Не вводится отдельная queue/background-job subsystem.

V1 достаточно двух независимых frontend requests:
- object detail;
- local explanation.

Основной detail не блокируется вычислением explanation.

При failure:
- basic prediction остаётся доступным;
- explanation становится unavailable/error;
- final/refit fallback запрещён.

Разрешён derived cache.

Минимальный cache key:
- artifact_id;
- object_id;
- model_binding_id;
- provider_id/version;
- explanation_method/version;
- background_hash;
- feature_binding_hash.

Threshold в cache key не входит.

V1 достаточно process-local cache + in-flight deduplication.
Cache не является source of truth.
## 9. Result Interpreter / LLM

Local Explanation запускается автоматически.

External LLM вызов выполняется только по explicit user action.

Причины:
- внешний provider call;
- стоимость;
- privacy event.

Flow:

```text
Object Detail
→ Local Explanation auto
→ evidence READY
→ user action «Сформировать объяснение»
→ Result Interpreter
```

LLM:
- не predictor;
- не пересчитывает prediction;
- не пересчитывает SHAP;
- не исправляет contribution;
- не выбирает threshold;
- не принимает approve/deny decision.

`REDACTED_V1` policy сохраняется.
Identifier / raw values / base / full provenance не должны уходить наружу сверх уже принятого provider-safe contract.

Полностью поддержанная модель не требует включённого external provider в конкретный момент. Требование — её validated evidence совместимо с Result Interpreter contract; policy/provider availability остаётся отдельной runtime capability.
## 10. Global OOF explanation

Global OOF explanation остаётся:

```text
row-weighted mean(abs(local SHAP))
```

по всем OOF rows.

Local SHAP теперь всегда получается через generic ExplanationProvider boundary.

Для GBDT Mean используется validated probability-space ensemble explanation.

Global provenance включает:
- artifact identity;
- model/provider/method identities;
- output space;
- background policy;
- fold model identities;
- feature binding;
- row count.

Нельзя сравнивать абсолютные SHAP magnitudes двух моделей как одну шкалу, если различаются output space или explanation protocol.

Global explanation описывает поведение модели, не причинность.

## 11. Implementation order

R2-BE1 — OOF Evidence Artifact V3: **ACCEPTED / CLOSED**.

Следующий backend stage:

**UME-BE1 — Universal Model Explainability V1**

Scope:
1. ModelExplanationProvider + registry.
2. ModelPlugin fail-closed provider binding.
3. FULLY_SUPPORTED readiness rule.
4. LocalExplanationEvidence V2.
5. Existing CatBoost / XGBoost / LightGBM через новый registry.
6. GBDT Mean probability-space provider.
7. Result Interpreter adaptation.
8. Generic connected-model validation contract.
9. Tests.

После ACCEPT UME-BE1:

**R2-BE2 — Result Read + OOF Explainability**

Он использует universal provider boundary для:
- Object Detail;
- auto Local Explanation;
- Global OOF explanation;
- public Result API.

Connect Model UI/onboarding можно реализовать позже без пересмотра explainability architecture.
## 12. Acceptance

- UI не знает model family.
- ModelPlugin ссылается на trusted explanation-provider descriptor.
- Executable provider разрешается только через trusted registry.
- Plugin с заявленным Local Explanation без valid provider fail closed.
- Prediction-only model не становится AVAILABLE в основном Result flow.
- CatBoost / XGBoost / LightGBM сохраняют рабочий Local Explanation.
- GBDT Mean получает validated probability-space Local Explanation.
- Ensemble explanation reconstructs exact ensemble probability.
- Raw-margin SHAP компонентов GBDT Mean не усредняется.
- Same background/masking semantics проверяются.
- OOF explanation использует assigned fold model.
- Final/refit fallback отсутствует.
- LocalExplanationEvidence V2 model-family independent.
- Result Interpreter не содержит model-specific branches.
- REDACTED_V1 privacy scope не расширен.
- Local Explanation на Object Detail запускается автоматически.
- Basic detail не блокируется explanation calculation.
- Cache identity содержит artifact/model/provider/explanation provenance.
- External LLM запускается только explicit user action.
- Global OOF explanation доступна для каждой AVAILABLE model.
- Connected model не регистрируется без prediction/reload/explanation consistency gate.
- Arbitrary executable Python/pickle upload через UI запрещён.
