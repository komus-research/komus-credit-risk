# Parameter Presentation / Identity V1 — ARCHITECT LOCK

Status: **READY_FOR_REVIEW**

Base main: `49c208a003a910054f54a67fddc5051d7a1ad3ab`

This is a narrow prerequisite for Algorithm UX V1.
It does not reopen accepted MP-A..MP-E architecture and does not implement UI.

---

## 1. Actual problem

Current `ModelParameter` mixes two different concerns:

1. behavioral/configuration metadata:
   - `parameter_path`;
   - value type;
   - required / nullable / editable;
   - default / recommended values;
   - bounds / choices;
   - visibility condition;
2. user-facing copy:
   - `display_name_ru`;
   - `description_ru`.

Current `ModelParameter.to_dict()` contains both groups.

Current `ModelParameterSchema.schema_hash` is:

```text
stable_hash(schema.to_dict())
```

Current `ModelPlugin.plugin_contract_hash` also includes
`parameter_schema.to_dict()`.

Therefore editing only copy such as:

```text
learning_rate
→ Скорость обучения
```

currently changes scientific/runtime provenance even though the executable
configuration did not change.

That consequence is not acceptable for a presentation-only correction.

---

## 2. Chosen boundary

Use a separate trusted backend presentation projection.

Do **not** edit existing identity-bearing
`ModelParameter.display_name_ru / description_ru` merely to localize UI.

Introduce a narrow presentation contract conceptually equivalent to:

```text
ModelParameterPresentation
- parameter_path
- display_name_ru
- description_ru

ModelPresentationProfile
- presentation_schema_version
- presentation_profile_id
- presentation_profile_version
- model_id
- model_version
- adapter_version
- schema_id
- schema_version
- schema_hash
- parameters[]
- presentation_hash
```

and a small trusted `ModelPresentationRegistry`.

The presentation profile is backend-owned declarative metadata.
It contains no executable code and no model configuration values.

Canonical flow:

```text
ModelPluginRegistry
        ├─ behavioral ModelParameterSchema
        └─ recommended profile

ModelPresentationRegistry
        └─ Russian presentation by parameter_path

                ↓

ModelCatalogService
        ↓
CatalogParameter
- behavioral fields from ModelParameterSchema
- display_name_ru / description_ru from ModelPresentationProfile
```

Frontend continues to consume only `ModelCatalogEntry / CatalogParameter`.
No frontend translation dictionary is allowed.

---

## 3. Why this boundary

This is the smallest safe separation because it leaves the accepted
configuration/provenance chain byte-for-byte unchanged.

It does not require:

- a new model version;
- a new adapter version;
- a new parameter-schema behavioral version;
- a compatibility bypass;
- rewriting old ExperimentArtifact V2;
- rewriting old ModelVersion V2;
- repeating smoke solely because wording changed.

It also gives future trusted plugins a generic place to provide localized
human-facing metadata without introducing `model_id` branches in Streamlit.

---

## 4. Exact source of Russian presentation metadata

For Algorithm UX V1, authoritative parameter copy comes from
`ModelPresentationProfile`, not from legacy identity-bearing
`ModelParameter.display_name_ru / description_ru`.

Lookup key:

```text
(model_id, model_version, adapter_version,
 schema_id, schema_version, schema_hash,
 parameter_path, locale="ru")
```

V1 may implement locale as an explicit fixed `ru` profile rather than a
general localization platform.

For every catalog-visible trusted plugin, the Russian presentation profile
must have exact one-to-one coverage of the current parameter schema:

- every schema `parameter_path` has exactly one presentation entry;
- no presentation entry references an unknown path;
- no duplicate path is allowed;
- `display_name_ru` is non-empty;
- `description_ru` is non-empty;
- profile model/schema identity exactly matches the trusted plugin schema.

Missing or mismatched presentation metadata is a trusted catalog-composition
error. It must not silently fall back to a frontend dictionary.

---

## 5. Built-in coverage requirement

The first accepted Russian presentation profile must cover all current built-in
schema parameters, including at least the editable paths for:

### CatBoost

- `iterations`;
- `learning_rate`;
- `depth`.

### XGBoost

- `n_estimators`;
- `learning_rate`;
- `max_depth`;
- `min_child_weight`;
- `subsample`;
- `colsample_bytree`;
- `reg_alpha`;
- `reg_lambda`.

### LightGBM

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

### GBDT Mean

All component parameter paths plus its locked composition metadata.

Exact Russian wording is product copy, not scientific semantics.
It must be reviewed as user-facing text, but changing approved copy later
must not change behavioral model identity.

---

## 6. Generic future-plugin behavior

A future trusted `ModelPlugin` remains registered through the existing
`ModelPluginRegistry`.

To be exposed through the user-facing catalog, the same trusted composition
must also provide a matching Russian `ModelPresentationProfile`.

Conceptually:

```text
trusted ModelPlugin
+ trusted ModelPresentationProfile
        ↓
catalog-ready model
        ↓
configuration
→ smoke
→ experiment
```

The presentation profile is not executable and does not participate in
factory/provider dispatch.

A new fifth/sixth plugin therefore requires no frontend branch.
It provides its own schema and matching presentation profile.

Historical/backend operations that resolve a model artifact by trusted plugin
identity do not depend on presentation metadata.

---

## 7. Behavioral identity vs presentation identity

### Behavioral/scientific identity

The accepted behavioral identity remains defined by the current MP-A..MP-E
contracts.

For this corrective stage, do not change:

- `ModelParameter.to_dict()`;
- `ModelParameterSchema.to_dict()`;
- `ModelParameterSchema.schema_hash`;
- `ModelPlugin.declarative_payload()`;
- `ModelPlugin.plugin_contract_hash`;
- Recommended profile identity;
- resolver formulas;
- configuration-record formulas;
- smoke identity formulas.

The legacy `display_name_ru / description_ru` fields embedded in
`ModelParameter` remain frozen identity-bearing legacy metadata for
compatibility. They are no longer authoritative user-facing copy in the
catalog.

Removing or redefining those legacy fields would be a separate future schema
migration and is explicitly out of scope.

### Presentation identity

`ModelPresentationProfile` has its own independent identity:

```text
presentation_hash =
stable_hash(
    presentation_schema_version
    + presentation_profile_id/version
    + bound model/schema identity
    + exact parameter_path → Russian copy
)
```

A copy edit changes only:

- presentation profile version, when intentionally released;
- `presentation_hash`;
- catalog-visible text.

It does not change executable/configuration identity.

---

## 8. Exact hash / version consequences

For a presentation-copy-only correction under this design:

| Identity | Consequence |
| --- | --- |
| `schema_id` | unchanged |
| `schema_version` | unchanged |
| `schema_hash` | unchanged |
| `plugin_contract_hash` | unchanged |
| `profile_id` | unchanged |
| `profile_version` | unchanged |
| `profile_hash` | unchanged |
| `model_version` | unchanged |
| `adapter_version` | unchanged |
| `resolved_configuration_hash` | unchanged |
| `configuration_record_id` | unchanged |
| `smoke_identity` | unchanged |
| ExperimentArtifact V2 identity/content | unchanged except no rewrite occurs |
| existing ModelVersion V2 identity/content | unchanged |
| new presentation profile version/hash | new presentation-only identity |

No technical smoke is invalidated merely because Russian copy changed.

No old experiment/model artifact is rewritten.

---

## 9. Resolver / runtime invariants

The correction must preserve exactly:

- `parameter_path`;
- value type;
- required;
- nullable;
- editable;
- minimum / maximum / exclusivity;
- choices;
- default value;
- recommended value;
- recommended profile payload/hash;
- visibility-condition behavior;
- resolver behavior;
- factory behavior;
- training behavior;
- GBDT Mean equal weights `1/3 + 1/3 + 1/3`;
- mandatory smoke semantics.

Current `ui_level`, `group_id`, `display_order` and
`visibility_condition` remain in the accepted identity-bearing schema in this
narrow correction.

This stage separates **copy** only.
Reclassifying other schema fields as presentation-only would require a separate
migration and is not implied here.

---

## 10. Catalog projection rule

`ModelCatalogService` remains the generic frontend boundary.

When building each `CatalogParameter`:

### From behavioral `ModelParameter`

Take:

- `parameter_path`;
- `value_type`;
- `required`;
- `nullable`;
- `editable`;
- `default_value`;
- `recommended_value`;
- bounds;
- choices;
- `ui_level`;
- `group_id`;
- `display_order`;
- `visibility_condition`.

### From matching `ModelParameterPresentation`

Take only:

- `display_name_ru`;
- `description_ru`.

The frontend receives the same `CatalogParameter` shape it already expects.

No model-specific translation logic exists in Streamlit.

---

## 11. Compatibility rule

No compatibility exception is introduced because behavioral identities do not
change.

This is important: historical compatibility is preserved by **not changing**
the identities current final-fit / persistence validation already checks.

Current final-fit validation may continue requiring exact:

- `plugin_contract_hash`;
- `schema_id`;
- `schema_version`;
- `schema_hash`;
- Recommended profile identity;
- `resolved_configuration_hash`.

Current ModelVersion V2 validation may continue requiring the same exact values.

The presentation registry is not consulted by:

- `ModelConfigurationService`;
- `ModelConfigurationRecord`;
- `ModelConfigurationSmokeTestService`;
- `FinalModelTrainingService`;
- `ModelVersionStore`;
- inference;
- local explanation.

Therefore missing/changing copy cannot create a scientific compatibility bypass.

---

## 12. Required historical regression tests

Implementation must prove both **READ COMPATIBILITY** and
**CONTINUING OPERATIONS**.

### A. Identity freeze — built-ins

Capture pre-change behavioral identity expectations from base
`49c208a003a910054f54a67fddc5051d7a1ad3ab`.

After adding Russian presentation metadata, for every current built-in plugin
assert exact equality of:

- `schema_id`;
- `schema_version`;
- `schema_hash`;
- `plugin_contract_hash`;
- `profile_hash`;
- Recommended resolved configuration hash;
- Advanced resolved configuration hash for a representative accepted override;
- corresponding `configuration_record_id`;
- matching smoke identity.

### B. Catalog copy changes independently

Change only a test presentation label/description.

Assert:

- presentation hash changes;
- `CatalogParameter.display_name_ru / description_ru` changes;
- all behavioral hashes above remain unchanged.

### C. Read compatibility — ExperimentArtifact V2

Load an accepted/pre-change V2 experiment artifact or a frozen fixture carrying
pre-change configuration provenance.

Assert it remains readable with the corrected code.

### D. Continuing operation — final fit

Using a pre-change V2 ExperimentArtifact with matching source/context:

```text
FinalModelTrainingService.train(...)
→ PASS
→ ModelVersion V2 saved
```

The current trusted plugin/schema exact checks must pass without a
compatibility bypass.

### E. Read compatibility — ModelVersion V2

Load an accepted/pre-change ModelVersion V2 fixture through current
`ModelVersionStore`.

Assert integrity/trusted-plugin validation still passes.

### F. Smoke reuse semantics

For the same context/features/config/seed, pre-change matching SmokeEvidence
remains current because its identity inputs are unchanged.

A presentation copy edit alone must not require a new smoke run.

### G. Generic future plugin

A test-only fifth plugin with a matching presentation profile:

```text
catalog
→ Russian CatalogParameter
→ configuration
→ smoke
→ experiment
```

works without frontend/model-id branches.

Missing or mismatched presentation coverage fails the trusted catalog
composition instead of falling back to hardcoded UI copy.

---

## 13. Minimal implementation scope

Expected narrow scope:

### New / changed backend presentation boundary

- new small module, preferably:
  `src/komus_risk/model_platform/presentation.py`;
- built-in trusted Russian presentation declarations;
- `src/komus_risk/model_platform/catalog.py` to compose behavioral parameter
  metadata with presentation copy;
- minimal composition wiring so `ExperimentPlanningService.list_models()`
  receives a presentation-aware catalog;
- model-platform exports if required.

### Tests

Focused tests for:

- presentation registry/profile validation;
- catalog Russian projection;
- behavioral identity freeze;
- historical V2 read compatibility;
- historical V2 final-fit/save continuation;
- ModelVersion V2 read compatibility;
- smoke identity stability;
- generic test plugin.

### Must not change for behavior

No behavioral changes to:

- GBDT estimator profiles;
- parameter paths/ranges/defaults/recommended values;
- resolver logic;
- Runner;
- smoke policy;
- persistence format;
- experiment scientific protocol.

If implementation requires changing any accepted behavioral hash merely to
display Russian copy, STOP and return to architecture.

---

## 14. Explicit non-goals

Not part of this prerequisite:

- Algorithm Streamlit implementation;
- `ALGORITHM_UX_V1.md` completion;
- changing model cards;
- hidden-model implementation;
- generic i18n/localization framework;
- arbitrary locales;
- schema-hash migration;
- plugin-contract-hash migration;
- ModelConfigurationRecord V2;
- SmokeEvidence V2;
- ExperimentArtifact migration;
- ModelVersion migration;
- compatibility allowlists;
- model/adapter version bump;
- parameter-path rename;
- parameter range changes;
- Recommended profile changes;
- model training changes;
- GBDT Mean semantics changes.

---

## 15. Architect decision

Chosen solution:

> **Backend-owned presentation projection separate from behavioral
> ModelParameterSchema identity.**

This implements the rule:

```text
PRESENTATION COPY CHANGE
≠
MODEL / SCIENTIFIC BEHAVIOR CHANGE
```

without weakening the accepted exact-identity checks used by smoke, final fit,
ExperimentArtifact V2 or ModelVersion V2.

Architecture status:

```text
Parameter Presentation / Identity V1: READY_FOR_REVIEW
Implementation: NOT STARTED
```

After Reviewer ACCEPT and implementation/review of this prerequisite, resume
Algorithm UX V1 and finish the visual lock using the already approved designer
reference.
