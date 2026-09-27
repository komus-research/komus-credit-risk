# Feature Grouping Propagation V1 — SPEC

STATUS: **DESIGN CAPTURED / IMPLEMENTATION OPEN**

Date: **2026-09-27**

---

## 1. Purpose

The accepted Feature Selection UX is group-first, but the generic end-to-end backend path does not yet preserve the useful technical groups already produced during Dataset Preparation.

The current code already has deterministic Analyzer grouping:

```text
1. structural stem
2. repeated name token
3. logical type
4. fallback
```

implemented by `DatasetPreparationAnalyzer._groups(...)` and emitted as `DatasetPreparationProposal.technical_groups`.

The current generic materializer then creates `FeatureRegistry → FeatureGroup` mainly from confirmed usage status. As a result, the richer Analyzer grouping is not propagated to the downstream Feature Selection screen.

This workstream closes that gap.

---

## 2. Product invariant

The downstream screen remains:

```text
PreparedDatasetContext
→ FeatureRegistry
→ FeatureGroup
→ group-first Feature Selection UI
```

The frontend must **not** read `DatasetPreparationProposal`, inspection state or Analyzer internals after `PreparedDatasetContext` exists.

`FeatureRegistry` remains the downstream source of truth.

---

## 3. Existing Analyzer cascade

The grouping algorithm itself is not invented by this workstream.

Current Analyzer order:

### A. Structural stem

After normalized tokenization:

- technical suffixes such as `norm`, `normalized`, `scaled`, `std`, `standardized`, `encoded` are removed;
- trailing pure numeric token is removed;
- at least two columns are required.

Examples:

```text
Q_A1_norm + Q_A2_norm → q_a
revenue_2023 + revenue_2024 → revenue
```

### B. Repeated token

For still-unassigned columns, a repeated non-stop token may form a group when it appears in at least two columns.

### C. Logical type

Still-unassigned columns may be grouped by the same inferred logical type when at least two columns remain.

### D. Fallback

Remaining columns go to a technical fallback group.

One column belongs to at most one proposed technical group.

These groups are technical/presentation metadata. They do not assert business semantics.

---

## 4. Required propagation

For a new generic `PreparedDatasetContext`, materialization must preserve the relevant Analyzer technical grouping into downstream `FeatureRegistry → FeatureGroup`.

Important boundaries:

- only confirmed `MODEL_ALLOWED` features are selectable on the main Feature Selection screen;
- target, identifier, diagnostic-only and blocked columns never become selectable because of grouping;
- grouping never changes `FeatureUsageStatus`;
- grouping never changes `selected_feature_ids`;
- grouping never overrides human confirmation;
- grouping never creates business meaning such as “Финансы”, “Поведение” or “Демография” unless such semantics come from a separately trusted source;
- no LLM grouping is introduced in V1.

The architecture must define a deterministic mapping from Analyzer `ProposedTechnicalGroup` metadata to materialized `FeatureGroup` identity/presentation while preserving provenance.

---

## 5. Confirmation semantics

Analyzer groups are not a second human-confirmation workflow.

The user confirms dataset roles/statuses as today.

Technical grouping is presentation metadata and does not require ritual approval because it has no permission/scientific effect.

If a confirmed role removes a column from `MODEL_ALLOWED`, downstream selectable groups simply exclude that column.

---

## 6. Fallback and compatibility

For newly prepared generic datasets, the preferred source is the propagated Analyzer grouping.

For legacy/frozen contexts that do not contain this provenance, existing explicit FeatureRegistry groups remain valid.

Presentation-only family grouping may remain as a compatibility fallback over already allowed feature IDs, but it must not become a second scientific/business taxonomy or mutate registry/status/selection.

The UI always consumes the final downstream group view, not the Analyzer directly.

---

## 7. UX contract

The accepted Feature Selection screen remains unchanged in structure:

- group-first accordion;
- group name;
- total and selected count;
- search;
- group filter;
- explicit “Включить все” / “Убрать все”;
- individual feature checkboxes;
- fallback “Без группы / Другие признаки” when needed;
- first experiment starts with all MODEL_ALLOWED features selected;
- later experiment on the same prepared context inherits the previous subset.

Names such as “Финансовые показатели”, “Поведенческие признаки” etc. are **not frontend constants**. They may appear only if a trusted backend source actually provides such semantics.

---

## 8. Determinism and provenance

The implementation must preserve deterministic behavior.

A grouping result used in `FeatureRegistry` must be reproducible from:

- inspection/proposal identity;
- Analyzer policy identity/hash;
- confirmed column decisions;
- materialization contract/version.

Changing the grouping algorithm or mapping semantics requires an explicit version change.

The implementation must not silently change dataset/feature permission hashes without an intentional migration decision.

---

## 9. Acceptance criteria

The workstream is accepted when:

1. generic Analyzer still produces the current cascade unchanged unless an explicit architecture decision says otherwise;
2. a generic materialized context exposes useful technical groups through `FeatureRegistry → FeatureGroup`;
3. downstream UI does not depend on Proposal/Analyzer objects;
4. group membership cannot change `FeatureUsageStatus`;
5. only MODEL_ALLOWED features are selectable;
6. target/identifier/diagnostic/blocked columns cannot leak into selectable groups;
7. each selectable feature appears in exactly one final presentation group;
8. fallback behavior is deterministic;
9. no business/LLM semantic grouping is invented;
10. existing historical/legacy contexts remain compatible;
11. tests cover structural-stem, repeated-token, logical-type and fallback propagation;
12. tests prove grouping changes presentation only and not experiment selection unless the user explicitly changes a checkbox/group action.

---

## 10. Before implementation

This is a cross-layer change:

```text
Analyzer proposal
→ confirmation/materialization
→ FeatureRegistry
→ planning DTO
→ Feature Selection UI
```

Before code, the Architect must lock:

- exact mapping into `FeatureGroup`;
- group IDs/names/descriptions/source provenance;
- compatibility behavior for legacy registries;
- whether any registry/hash/version migration is required;
- exact tests and stage boundary.

No code should be started from this document alone.
