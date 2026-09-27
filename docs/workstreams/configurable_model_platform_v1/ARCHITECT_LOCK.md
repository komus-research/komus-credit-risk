# Configurable Model Platform V1 — ARCHITECT LOCK

STATUS: **ACCEPTED / READY_FOR_IMPLEMENTATION**

Owner decisions resolved: **2026-09-27**

Baseline at architecture review: `93823becde40d70a5e6dc189a3a127141128726f`.

---

## 1. Purpose

Current ML-core is not replaced. The accepted experiment/inference chain remains the foundation.

The open product gap is the model integration layer:

- current `ModelSpec` contains identity, presentation metadata, `default_profile` and runtime requirements, but no parameter schema;
- current GBDT adapters validate a frozen profile;
- frontend cannot discover editable parameters, ranges, capabilities or unavailable reasons from backend metadata;
- native persistence still contains model-specific dispatch;
- there is no generic configuration smoke test before a full experiment.

The goal is a model platform in which a trusted backend plugin declares everything the application needs, while frontend remains model-agnostic.

---

## 2. Canonical architecture

```text
trusted model code
        ↓
ModelPlugin
        ↓
ModelPluginRegistry
        ├─ model catalog DTO
        ├─ configuration resolver
        ├─ capability resolver
        ├─ smoke-test service
        ├─ planning / application
        ├─ persistence provider
        └─ optional local explanation provider
        ↓
ResolvedModelConfiguration
        ↓
ExperimentConfig.model_parameters
        ↓
existing ExperimentRunner
```

The frontend never constructs estimators and never contains branches such as `if model_id == "catboost"`.

---

## 3. Registration unit

`ModelPlugin` is the trusted registration unit for one model integration.

It aggregates:

- `ModelSpec` — model identity and presentation metadata;
- `ModelParameterSchema` — user-configurable parameter contract;
- `RecommendedModelProfile` — accepted ready-to-run configuration;
- `ModelAdapterFactory` — creates the adapter;
- `ModelCapabilityManifest` — supported capabilities;
- `ModelInputContract` — predictor input requirements;
- trusted cross-parameter validator;
- optional persistence provider;
- optional local explanation provider;
- smoke-test metadata/policy compatibility.

The registry must fail closed on inconsistent identities, invalid recommended profiles, missing providers for declared capabilities, incompatible duplicate registration or invalid plugin metadata.

User-uploaded Python plugins, arbitrary class paths, dynamic imports from user values and arbitrary executable configuration are not supported.

---

## 4. Capabilities

Capabilities are backend facts, not frontend guesses.

Minimum V1 capability domains:

- training;
- configuration;
- persistence;
- loading;
- targetless inference;
- local explanation;
- smoke test.

Static support may be `SUPPORTED`, `UNSUPPORTED` or `CONDITIONAL`.

Runtime availability is resolved separately, with a stable state/reason such as:

- `AVAILABLE`;
- `UNAVAILABLE`;
- `MISCONFIGURED`.

Task types remain part of model identity/presentation. Input requirements are owned by `ModelInputContract`.

---

## 5. Parameter schema

Every user-visible model parameter is declared by backend schema.

Minimum metadata:

```text
parameter_path
display_name_ru
description_ru
value_type
required
nullable
editable
default_value
recommended_value
minimum / maximum when applicable
choices for enum
ui_level = basic | advanced
group_id
display_order
optional visibility condition
```

Canonical parameter paths use deterministic JSON-pointer-style paths, for example:

```text
/estimator_params/learning_rate
/components/xgboost/profile/estimator_params/max_depth
```

Frontend validation is convenience only. Backend validation is authoritative.

Unknown parameters, wrong types, invalid bounds, locked mutations, invalid enum values, unsatisfied dependencies and invalid nested paths fail closed.

Complex cross-parameter rules are implemented by trusted backend validator code, not an expression language or `eval()`.

---

## 6. Recommended and Advanced

### Recommended

```text
mode = RECOMMENDED
user_overrides = {}
resolved_parameters = exact recommended profile
```

For the current four models, zero overrides must reproduce the accepted Stage 1 V2 runtime recipe exactly.

### Advanced

```text
recommended profile
+ sparse validated overrides
→ canonical resolved configuration
```

No silent ignore is permitted.

### Owner decision — Advanced boundary

The product is designed to expose **all model parameters that the trusted plugin explicitly declares safely editable**.

The current V1 schemas begin with the verified estimator parameters listed below, but the architecture must not freeze the product forever to that initial subset. A later schema version may expose additional safe parameters without frontend redesign.

The following remain outside ordinary Advanced model configuration unless a separate architecture decision changes their ownership:

- target / positive class / identifier semantics;
- FeatureRegistry permissions and selected feature set;
- outer OOF/evaluation protocol;
- final-test policy;
- evaluation population;
- experiment seed/fold semantics;
- input/runtime invariants;
- current fit-recipe invariants.

---

## 7. Current GBDT migration

Zero overrides preserve current accepted behavior.

### CatBoost

Initial editable schema:

- `iterations`;
- `learning_rate`;
- `depth`.

Locked in current V1:

- loss/objective semantics;
- evaluation metric;
- thread/runtime policy;
- file-writing/verbosity policy;
- random seed ownership;
- fit/input/runtime recipe.

### XGBoost

Initial editable schema:

- `n_estimators`;
- `learning_rate`;
- `max_depth`;
- `min_child_weight`;
- `subsample`;
- `colsample_bytree`;
- `reg_alpha`;
- `reg_lambda`.

Objective, evaluation metric, tree method, job/runtime policy, random state and fit/input/runtime recipe remain locked in V1.

### LightGBM

Initial editable schema:

- `n_estimators`;
- `learning_rate`;
- `num_leaves`;
- `max_depth`;
- `min_child_samples`;
- `subsample`;
- `subsample_freq`;
- `colsample_bytree`;
- `reg_alpha`;
- `reg_lambda`.

Runtime/job policy and fit/input/runtime recipe remain locked in V1.

Ranges/constraints are backend schema facts and must be based on real library constraints plus explicit product constraints; frontend must not invent them.

---

## 8. GBDT Mean

GBDT Mean remains a composite plugin.

V1 mathematical semantics are locked:

```text
aggregation = arithmetic_mean_positive_probability
weights = 1/3, 1/3, 1/3
```

### Owner decision

- equal weights remain locked in V1;
- component model identities remain locked;
- Advanced may change parameters of CatBoost/XGBoost/LightGBM components through nested parameter paths;
- changing ensemble weights is a future explicit model-version/semantics change, not a hidden UI option.

---

## 9. Resolved configuration and reproducibility

`ResolvedModelConfiguration` contains at minimum:

```text
model_id
model_version
adapter_version
schema_id / schema_version / schema_hash
recommended_profile_id / recommended_profile_hash
mode
user_overrides
resolved_parameters
resolved_configuration_hash
```

Behavioral identity is based on exact resolved behavior, not on the user's navigation path:

```text
resolved_configuration_hash =
stable_hash(
    model identity
    + schema hash
    + exact resolved_parameters
)
```

`user_overrides` are preserved as provenance but are not part of the behavioral hash when two input paths resolve to the same exact configuration.

Existing `ExperimentConfig.model_parameters` remains the full exact resolved runtime profile and continues to participate in `config_hash`.

Schema/profile provenance is added through a separate immutable configuration record/artifact version rather than silently changing hashes of legacy artifacts.

---

## 10. Smoke test

A generic `ModelConfigurationSmokeTestService` performs a bounded technical preflight:

```text
PreparedDatasetContext
+ selected_feature_ids
+ ResolvedModelConfiguration
+ seed
        ↓
controlled deterministic sample
        ↓
factory.create()
        ↓
fit()
        ↓
predict_positive_proba()
        ↓
shape / finite / [0,1] validation
        ↓
PASS | FAIL
```

The smoke test does **not** report model quality. It is not ROC-AUC/Gini/PR-AUC/F1/Precision/Recall evaluation.

The accepted initial smoke policy is deterministic, stratified and bounded; final-test rows must never be used.

### Owner decision — smoke gate

A matching smoke PASS is required before **every full experiment**, including both Recommended and Advanced modes.

Recommended mode may make this preflight nearly invisible in UX, but the backend gate is the same.

A smoke PASS becomes stale whenever its canonical identity changes, including relevant dataset/context identity, feature registry, evaluation population, ordered selected features, plugin contract, resolved configuration, seed or smoke-policy identity.

Frontend does not determine stale state manually; backend/application state is authoritative.

---

## 11. Persistence

Persistence becomes provider-based.

A model-specific `ModelPersistenceProvider` owns:

- provider identity/version;
- fitted-model validation;
- declared native artifact format/files;
- save;
- load predictor.

`ModelVersionStore` continues to own immutable storage, metadata, manifest/hashes, feature order and atomic publication, but no longer grows a central model-id `if/elif`.

Legacy ModelVersion V1 remains readable through a compatibility provider/path.

No arbitrary pickle or unsafe user-provided deserialization is introduced.

---

## 12. Explainability boundary

Local explanation is an optional capability/provider of a model plugin.

Current rule:

- CatBoost: supported by accepted native Local SHAP path;
- XGBoost / LightGBM: capability becomes supported only after the corresponding provider work is accepted;
- GBDT Mean: unsupported until a mathematically accepted ensemble explanation method exists.

The Model Platform does not invent or duplicate explainability semantics.

---

## 13. Frontend/application DTO

The application exposes a read-only model catalog DTO sufficient to build the Algorithm screen without model-specific frontend constants.

It includes:

- identity and display metadata;
- task types;
- availability and reason code;
- capabilities;
- input-contract summary;
- parameter schema identity and parameter metadata;
- recommended profile identity/summary;
- runtime requirements summary.

Implementation objects, factories, provider objects, callables, Python classes, secrets and raw estimator objects are never exposed.

---

## 14. Adding a new model

A trusted developer adds:

1. adapter;
2. adapter factory;
3. ModelSpec;
4. parameter schema;
5. recommended profile;
6. input contract;
7. capability manifest;
8. optional persistence provider;
9. optional explanation provider;
10. ModelPlugin registration;
11. integrity/smoke/regression tests.

After registration, the model must flow through catalog → configuration → smoke → experiment without a model-specific frontend branch.

---

## 15. Implementation stages

### MP-A — Contracts + Plugin Registry

- plugin/schema/capability/input contracts;
- plugin registry;
- current four models registered in frozen-compatible mode;
- zero behavior change.

### MP-B — Configuration Resolver + Configurable GBDT

- configuration resolver;
- resolved configuration;
- current model parameter schemas;
- Advanced overrides;
- nested GBDT Mean component configuration;
- planning/application handoff.

### MP-C — Provenance + Smoke

- immutable model configuration record;
- artifact-version migration;
- generic smoke service;
- smoke identity/stale rules;
- mandatory matching PASS gate for every full experiment.

### MP-D — Persistence Provider Boundary

- generic persistence provider;
- legacy V1 load compatibility;
- new configurable ModelVersion metadata;
- current GBDT native providers.

### MP-E — Catalog DTO + Integration Regression

- model catalog DTO;
- runtime capability/availability resolution;
- dummy model plugin acceptance;
- application/composition cleanup;
- docs/regression.

Frontend implementation is not part of MP-A…E.

---

## 16. Non-goals

This workstream does not change:

- Dataset Preparation semantics;
- FeatureRegistry permission semantics;
- target/identifier semantics;
- accepted outer OOF scientific protocol without a separate decision;
- role-based Result Interpreter semantics;
- external-data/redaction policy;
- Result UX;
- production React/FastAPI implementation.

---

## 17. Acceptance summary

The workstream is complete only when:

- Recommended/no overrides reproduces the current accepted profile;
- valid overrides reach the actual estimator through the trusted resolver;
- invalid/unknown/locked values fail before Runner;
- resolved config/hash is deterministic;
- a new dummy model can register and flow without frontend model-id logic;
- every full experiment requires a matching technical smoke PASS;
- persistence dispatch is provider-based;
- existing experiment/inference paths remain regression-clean;
- legacy artifacts/models remain readable according to the migration contract.
