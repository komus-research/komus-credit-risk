# Feature Grouping Propagation V1 — STATUS

Phase: **DESIGN**

Architecture: **READY_FOR_REVIEW**

Implementation: **NOT STARTED**

## READ FIRST

1. [ARCHITECT_LOCK.md](ARCHITECT_LOCK.md)
2. [SPEC.md](SPEC.md)
3. [../dataset_onboarding_v1/04_ANALYZER_POLICY.md](../dataset_onboarding_v1/04_ANALYZER_POLICY.md)
4. [../generic_dataset_onboarding_v1/FEATURE_SELECTION_UX_V1.md](../generic_dataset_onboarding_v1/FEATURE_SELECTION_UX_V1.md)
5. [../../CURRENT_STATE.md](../../CURRENT_STATE.md)

## Actual state

Already implemented:

- `DatasetPreparationAnalyzer` creates `DatasetPreparationProposal.technical_groups`;
- grouping cascade remains structural stem → repeated token → logical type → fallback;
- Feature Selection is contractually group-first and consumes downstream groups from `FeatureRegistry`.

Not yet implemented:

- propagation of Analyzer technical groups through generic materialization into the final `FeatureRegistry → FeatureGroup`.

## Locked architecture

The Architect Lock now defines:

- exact `ProposedTechnicalGroup → FeatureGroup` mapping;
- MODEL_ALLOWED-only technical grouping;
- non-model status-group handling;
- singleton preservation and zero-member omission;
- deterministic group IDs/names/descriptions/order/source;
- provenance through the existing preparation manifest;
- Materializer V2 / FeatureRegistry V2 / Manifest V2 identity behavior;
- legacy compatibility;
- unchanged Planning / Feature Selection semantics;
- exact acceptance tests and narrow implementation scope.

## Next action

Reviewer checks [ARCHITECT_LOCK.md](ARCHITECT_LOCK.md).

If accepted:

```text
Architect
→ Technical Coordinator
→ Backend / Codex implementation
→ Reviewer
```

Do not start implementation from STATUS alone.
