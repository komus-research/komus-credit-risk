# Feature Grouping Propagation V1 — ARCHITECT LOCK

Architecture: **ACCEPTED**

Base main: `0888fc6accdcd2519fc460e8dd1408329b298813`

## 1. Proposal

Propagate the already accepted `DatasetPreparationProposal.technical_groups` into the newly materialized generic `FeatureRegistry → FeatureGroup` without changing the Analyzer algorithm, feature permissions, experiment selection semantics, or the Feature Selection UI contract.

Canonical boundary:

```text
DatasetInspectionReport
→ DatasetPreparationAnalyzer
→ DatasetPreparationProposal.technical_groups
→ human-confirmed column statuses
→ DatasetPreparationMaterializer V2
→ FeatureRegistry
→ FeatureGroup
→ existing Planning / Feature Selection
```

Grouping remains **presentation metadata only**.

It must never modify:

- `ConfirmedColumnStatus`;
- `FeatureUsageStatus`;
- predictor eligibility;
- `MODEL_ALLOWED` membership;
- `selected_feature_ids`;
- target / identifier;
- diagnostic / blocked permissions;
- evaluation or scientific semantics.

No second human confirmation of technical groups is introduced.

---

## 2. Why this boundary

The Analyzer already emits deterministic technical groups using the accepted cascade:

```text
structural_prefix
→ repeated_token
→ logical_type
→ fallback
```

The current generic materializer discards this grouping and assigns `FeatureSpec.group_id` primarily from confirmed usage status. The downstream UI already consumes `FeatureRegistry → FeatureGroup`; therefore the correct fix is inside materialization, not in Planning or Streamlit.

The frontend must never depend on Proposal, inspection state, or Analyzer internals after `PreparedDatasetContext` exists.

---

## 3. Exact projection rule

### 3.1. Validate proposal technical groups

Technical-group structure validation occurs **after** exact proposal identity has been verified against the confirmed `proposal_hash`, but **before** any `FeatureGroup` projection or `FeatureRegistry` construction.

Therefore an identity-consistent but structurally malformed Proposal still fails closed at materialization. No partial registry may be created.

Allowed `group_kind` values:

```text
structural_prefix
repeated_token
logical_type
fallback
```

Required conditions:

- `group_key` is a non-empty string;
- every `column_name` exists in the physical snapshot;
- no duplicate column inside one proposed group;
- one physical column appears in at most one proposed technical group;
- for `structural_prefix`, `repeated_token`, and `logical_type`, the pair `(group_kind, group_key)` is unique inside one `DatasetPreparationProposal`;
- at most one proposed group has `group_kind == "fallback"`.

Any violation of the technical-group structure contract raises:

```text
DatasetPreparationError("INVALID_TECHNICAL_GROUP_STRUCTURE")
```

This single stable V1 error code covers:

- unknown `group_kind`;
- empty or otherwise invalid `group_key`;
- unknown physical column;
- duplicate member inside one proposed group;
- one physical column appearing in more than one proposed group;
- duplicate `(group_kind, group_key)` for `structural_prefix`, `repeated_token`, or `logical_type`;
- more than one proposed fallback group.

Malformed proposed groups are never merged, silently deduplicated, or deferred to a later `FeatureRegistry` duplicate-ID failure.

The normal final fallback projection remains unchanged: members of the one valid Analyzer fallback group and MODEL_ALLOWED columns absent from all Analyzer groups may both end in the single canonical `technical_group_v1:fallback`.

No grouping is recomputed from column names inside the materializer.

### 3.2. MODEL_ALLOWED projection

For each confirmed `MODEL_ALLOWED` column:

1. if it belongs to one Analyzer `structural_prefix`, `repeated_token`, or `logical_type` group, it is assigned to the corresponding final technical `FeatureGroup`;
2. if it belongs to Analyzer `fallback`, it is assigned to the canonical final fallback group;
3. if it is not present in any proposed technical group, it is assigned to the same canonical final fallback group.

This last rule is required because the accepted Analyzer only emits a group when its minimum member rule is satisfied; a single leftover physical column may therefore have no `ProposedTechnicalGroup`.

Every confirmed `MODEL_ALLOWED` feature must belong to exactly one final presentation group.

### 3.3. Non-model columns

Confirmed non-model columns do **not** retain Analyzer technical membership downstream.

They keep explicit status groups:

```text
DIAGNOSTIC_ONLY → usage_diagnostic_only
IDENTIFIER      → usage_identifier
TARGET          → usage_target
BLOCKED         → usage_blocked
```

This guarantees that a mixed Analyzer group such as:

```text
feature_a  → MODEL_ALLOWED
feature_b  → DIAGNOSTIC_ONLY
target     → TARGET
```

materializes as:

```text
technical group → feature_a only
usage_diagnostic_only → feature_b
usage_target → target
```

Grouping can never promote a non-model column into a selectable group.

There is no `usage_model_allowed` group for newly materialized generic V2 contexts; MODEL_ALLOWED features use technical/fallback presentation groups instead.

---

## 4. Group shrinkage

The final projection is based on confirmed statuses, so an Analyzer group may shrink.

Locked behavior:

- **2+ surviving MODEL_ALLOWED members** → create the technical group with those members;
- **exactly 1 surviving MODEL_ALLOWED member** → **keep the one-member technical group**;
- **0 surviving MODEL_ALLOWED members** → do not create that technical `FeatureGroup`.

The singleton rule is intentionally option **A**.

Reason: confirmation filters membership but must not invent a second grouping algorithm. Moving a surviving member into a generic fallback would erase valid Analyzer provenance and create a new post-confirmation regrouping rule merely for visual compactness.

A `FeatureGroup` may therefore legitimately contain one feature after confirmation even though the Analyzer required at least two members when originally proposing the group.

---

## 5. Deterministic FeatureGroup identity and presentation

### 5.1. Technical group ID

For `structural_prefix`, `repeated_token`, and `logical_type` groups:

```text
group_id =
"technical_group_v1:"
+ group_kind
+ ":"
+ stable_hash({
    "projection_version": "1",
    "proposal_policy_id": proposal.policy_id,
    "proposal_policy_version": proposal.policy_version,
    "proposal_policy_hash": proposal.policy_hash,
    "group_kind": group_kind,
    "group_key": group_key
  })
```

The full hash is used. It must not be truncated.

Raw `group_key` is never used as an identifier/path component, so unusual column-name tokens cannot create group-ID collisions.

### 5.2. Canonical fallback ID

All MODEL_ALLOWED features that belong to Analyzer `fallback`, plus any MODEL_ALLOWED feature absent from `proposal.technical_groups`, use one group:

```text
group_id = "technical_group_v1:fallback"
```

If no such feature exists, the fallback group is not created.

### 5.3. Exact names

Presentation names are technical, not business-semantic.

| Source kind | `name_ru` |
|---|---|
| `structural_prefix` | `Структура: {group_key}` |
| `repeated_token` | `Общий токен: {group_key}` |
| `logical_type` | `Тип: {group_key}` |
| final fallback | `Другие признаки` |

The Analyzer-produced `group_key` may appear **only as plain presentation text**. It is not translated into a business taxonomy and is not interpreted by an LLM.

### 5.4. Exact descriptions

`structural_prefix`:

> Техническая группа по общей структуре имён колонок; бизнес-смысл не подтверждён.

`repeated_token`:

> Техническая группа по повторяющемуся токену в именах колонок; бизнес-смысл не подтверждён.

`logical_type`:

> Техническая группа по inferred logical type колонок; бизнес-смысл не подтверждён.

final fallback:

> Другие MODEL_ALLOWED признаки без более специфичной финальной технической группы; бизнес-смысл не подтверждён.

Existing non-model status-group names/descriptions remain unchanged.

### 5.5. `source`

Analyzer-derived groups:

```text
dataset_preparation_v2:proposal_technical_group:{group_kind}
```

Final fallback:

```text
dataset_preparation_v2:technical_fallback
```

Non-model status groups:

```text
dataset_preparation_v2:confirmed_usage_status
```

`FeatureGroup.source` identifies the derivation class only. Exact upstream hashes are not duplicated into every group.

### 5.6. Ordering

Technical groups are ordered before non-model status groups.

Canonical technical ordering:

1. `structural_prefix`;
2. `repeated_token`;
3. `logical_type`;
4. fallback.

Within the first three kinds: ascending exact `group_key`.

Zero-survivor groups are omitted before display order is assigned.

Final `display_order` is contiguous from zero.

After all MODEL_ALLOWED technical groups, non-model groups are appended in this fixed order, skipping empty groups:

1. `usage_diagnostic_only`;
2. `usage_identifier`;
3. `usage_target`;
4. `usage_blocked`.

### 5.7. Feature order

`FeatureGroup.feature_ids` preserve physical column order from the trusted snapshot/report.

`FeatureSpec.display_order` remains the physical column position.

---

## 6. FeatureSpec mapping consequence

All existing Dataset Preparation V1 `FeatureSpec` fields remain unchanged except `group_id`.

For a newly materialized generic V2 context:

- `MODEL_ALLOWED` → final technical/fallback group ID;
- `DIAGNOSTIC_ONLY` → `usage_diagnostic_only`;
- `IDENTIFIER` → `usage_identifier`;
- `TARGET` → `usage_target`;
- `BLOCKED` → `usage_blocked`.

No status, blocked reason, dtype, technical semantic type, origin, source reference, formula hash, feature ID, or display order changes because of grouping propagation.

---

## 7. Provenance

Minimum sufficient provenance is split across the existing downstream contracts.

### FeatureRegistry / FeatureGroup

Stores:

- deterministic final group IDs;
- technical name/description;
- derivation class in `FeatureGroup.source`;
- final feature membership/order.

### DatasetPreparationManifest

Remains the authoritative lineage from the final registry/context back to the accepted preparation:

- `snapshot_fingerprint`;
- `inspection_report_hash`;
- `proposal_hash`;
- confirmed preparation, which already contains:
  - proposal policy ID;
  - proposal policy version;
  - proposal policy hash;
- `confirmation_hash`;
- `materializer_version`;
- final `feature_registry_id/hash`;
- final `context_id`;
- `materialization_identity`.

The Proposal itself is not copied into FeatureRegistry.

No new group-confirmation object is added.

---

## 8. Version and identity migration

This workstream changes materialization semantics and therefore must change identity explicitly.

### 8.1. Materializer

```text
DatasetPreparationMaterializer.version:
"1" → "2"
```

### 8.2. FeatureRegistry ID convention

Newly prepared generic contexts use:

```text
feature-registry-v2:
+ stable_hash({
    "snapshot_fingerprint": snapshot.fingerprint,
    "confirmation_hash": confirmation_hash,
    "materializer_version": "2",
    "group_projection_version": "1"
  })
```

Do not reuse `feature-registry-v1:` for V2 materialization.

`confirmation_hash` already binds the exact `proposal_hash` and Analyzer policy identity, so those hashes need not be duplicated in this registry-ID payload.

### 8.3. Registry hash

No `FeatureRegistry.registry_hash` formula change is made.

It already includes both `FeatureSpec` and `FeatureGroup`, so propagated grouping naturally changes the hash.

This is intentional.

### 8.4. DatasetPreparationManifest

```text
manifest_version:
"1" → "2"
```

The dataclass field set does not need to change. The version bump records the new materialization/identity semantics.

### 8.5. Materialization identity

V2 formula:

```text
materialization_identity =
stable_hash({
    "manifest_version": "2",
    "materializer_version": "2",
    "context_id": context_id,
    "confirmation_hash": confirmation_hash,
    "proposal_hash": proposal_hash,
    "delta": proposal_confirmation_delta
  })
```

### 8.6. Dataset / population identity

Keep:

- physical `dataset_fingerprint` unchanged;
- logical `dataset_id` convention unchanged;
- `dataset_version = confirmation-v1:{confirmation_hash}` unchanged;
- population ID/fingerprint formula unchanged.

Grouping is presentation metadata and does not redefine physical data, human-confirmed dataset semantics, or evaluation population.

### 8.7. Context identity

The existing `context_id` formula stays structurally unchanged.

Because it contains `feature_registry_id/hash`, newly materialized V2 contexts naturally receive a new `context_id`.

That identity change is **required**, not hidden.

---

## 9. Legacy compatibility

- Existing historical/frozen FeatureRegistry objects remain unchanged.
- Existing already-materialized generic V1 contexts remain valid.
- Existing experiment/model artifacts are not rewritten.
- No retroactive migration.
- No automatic re-materialization solely to obtain prettier groups.
- Historical compatibility profiles continue supplying their own explicit groups.
- Newly prepared generic contexts after this change use Materializer V2 semantics.

If the same source + confirmation is intentionally materialized again under V2, it receives the V2 registry/context identity. It is not silently treated as the old V1 context.

Because controlled comparison currently treats `feature_registry_hash` as a dataset invariant, an old V1 artifact and a newly materialized V2 artifact are **not** declared controlled-comparable merely because the raw file and feature statuses look equivalent. No comparison exception is added in this workstream.

---

## 10. Downstream boundary

No semantic change is required in:

- `FeatureRegistry`;
- `FeatureGroup`;
- Planning contracts/service;
- Feature Selection selection semantics;
- session-state selection semantics;
- `ExperimentConfig.selected_feature_ids` / feature IDs;
- Runner.

Planning continues:

```text
PreparedDatasetContext
→ FeatureRegistry
→ list_feature_groups()
→ FeatureGroupView
```

Feature Selection continues to select only features whose `FeatureUsageStatus == MODEL_ALLOWED`.

Search/filter/grouping do not change `selected_feature_ids`; only explicit feature/group user actions do.

The existing presentation-only family helper may remain as a compatibility/display layer. It must not become the source of backend group identity and is not redesigned in this workstream.

---

## 11. Exact acceptance tests

Implementation is accepted only if all of the following pass.

### A. structural_prefix

A proposal containing a `structural_prefix` group with confirmed MODEL_ALLOWED members produces one final technical group with:

- deterministic hashed group ID;
- `name_ru = "Структура: {group_key}"`;
- physical-order feature IDs;
- unchanged MODEL_ALLOWED statuses.

### B. repeated_token

Same guarantees for `repeated_token`, with:

`name_ru = "Общий токен: {group_key}"`.

### C. logical_type

Same guarantees for `logical_type`, with:

`name_ru = "Тип: {group_key}"`.

### D. fallback

Analyzer fallback members and any MODEL_ALLOWED physical column absent from all proposal groups end in exactly one final `technical_group_v1:fallback` group named `Другие признаки`.

### E. mixed group

A single Analyzer group containing members that confirmation assigns to MODEL_ALLOWED / TARGET / IDENTIFIER / DIAGNOSTIC_ONLY / BLOCKED is projected so that:

- only MODEL_ALLOWED members remain in the technical group;
- every other member goes to its explicit non-model status group;
- all original confirmed usage statuses remain unchanged.

### F. singleton shrinkage

A two-or-more-member Analyzer technical group that leaves exactly one MODEL_ALLOWED member after confirmation remains a one-member final technical group.

It is not moved to fallback.

### G. zero surviving members

An Analyzer technical group with zero surviving MODEL_ALLOWED members creates no empty FeatureGroup.

### H. complete MODEL_ALLOWED coverage

Every MODEL_ALLOWED physical feature belongs to exactly one final technical/fallback group.

No MODEL_ALLOWED feature is left without a valid `FeatureSpec.group_id`.

### I. no permission leakage

TARGET / IDENTIFIER / DIAGNOSTIC_ONLY / BLOCKED never become selectable and never change status because of technical grouping.

### J. determinism

Identical snapshot + report + proposal + confirmation produce identical:

- final group IDs;
- names/descriptions;
- display order;
- feature order;
- `registry_id`;
- `registry_hash`;
- `context_id`;
- `materialization_identity`.

### K. intentional V2 identity

A newly materialized generic context reports:

- `materializer_version == "2"`;
- `manifest_version == "2"`;
- `feature_registry_id` with `feature-registry-v2:` convention.

Its grouping-bearing registry/context identity is not forced to equal legacy V1 identity.

### L. legacy explicit registry

An existing explicit/legacy FeatureRegistry using its old groups remains readable and usable by Planning without migration.

### M. experiment selection semantics

Feature Selection / session-state regression tests prove:

- merely displaying/searching/filtering groups does not change `selected_feature_ids`;
- only explicit experiment-level feature/group actions change `selected_feature_ids`;
- no Dataset Preparation status changes occur downstream.

### N. provenance

Manifest V2 links the generated registry/context to exact proposal/confirmation hashes and materializer version; no second group-confirmation state exists.

### O. duplicate technical identity

A proposal containing distinct groups with the same technical identity, for example:

```text
structural_prefix / q / (a, b)
structural_prefix / q / (c, d)
```

fails before any FeatureGroup projection / FeatureRegistry construction with:

```text
DatasetPreparationError("INVALID_TECHNICAL_GROUP_STRUCTURE")
```

The test must exercise the invariant generically for the non-fallback technical kinds rather than special-casing only `structural_prefix`. No merge or silent winner is allowed.

### P. multiple proposed fallback groups

A proposal containing more than one distinct `ProposedTechnicalGroup` with:

```text
group_kind == "fallback"
```

fails before projection with:

```text
DatasetPreparationError("INVALID_TECHNICAL_GROUP_STRUCTURE")
```

No upstream fallback groups are merged. The single canonical final fallback remains only a downstream projection target for the one valid Analyzer fallback plus ungrouped MODEL_ALLOWED columns.

---

## 12. Implementation file scope

Expected minimal implementation scope:

### May change

- `src/komus_risk/preparation/materializer.py`;
- `tests/test_dataset_preparation_materialization.py`;
- preferably one focused new test file:
  - `tests/test_feature_grouping_propagation.py`;
- this workstream documentation/status.

### Should not require semantic changes

- `src/komus_risk/preparation/service.py`;
- `src/komus_risk/preparation/contracts.py`;
- `src/komus_risk/preparation/manifest.py`;
- `src/komus_risk/contracts/feature.py`;
- `src/komus_risk/registries/feature_registry.py`;
- `src/komus_risk/planning/*`;
- `app/*`.

If implementation evidence shows one of those files must change for a narrow compatibility reason, Backend must stop and report the exact contract gap rather than redesigning the workstream.

---

## 13. Non-goals

Not part of Feature Grouping Propagation V1:

- new Analyzer grouping;
- semantic/business taxonomy;
- LLM grouping;
- group confirmation UI;
- FeatureUsageStatus changes;
- feature eligibility changes;
- model/training changes;
- Configurable Model Platform changes;
- threshold/business policy;
- frontend redesign;
- DB/history/deployment.

---

## 14. Architect acceptance boundary

This lock is implementation-ready when Reviewer confirms that it resolves:

1. exact Proposal → FeatureGroup mapping;
2. allowed-feature filtering;
3. singleton/empty behavior;
4. group ID/name/description/order/source;
5. provenance;
6. V2 identity/version consequence;
7. legacy compatibility;
8. unchanged downstream semantics;
9. exact tests;
10. narrow implementation scope.

Architect does **not** mark the architecture ACCEPTED.

Final architecture state after this document:

```text
Architecture: READY_FOR_REVIEW
Implementation: NOT STARTED
```
