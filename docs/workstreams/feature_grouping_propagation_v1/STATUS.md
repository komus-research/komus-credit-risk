# Feature Grouping Propagation V1 — STATUS

Phase: **READY_FOR_REVIEW**

Architecture: **ACCEPTED**

Implementation: **COMPLETE / READY FOR REVIEW**

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

Implemented:

- fail-closed validation and V2 projection of trusted Analyzer technical groups into final generic `FeatureRegistry → FeatureGroup`;
- MODEL_ALLOWED-only technical/fallback grouping, status-group projection for non-model columns, and V2 materialization identities;
- focused propagation acceptance coverage plus unchanged selection/planning regression coverage.

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
- exact acceptance tests and narrow implementation scope;
- fail-closed validation of malformed technical-group structure, including duplicate `(group_kind, group_key)` identities and multiple proposed fallback groups, using the stable code `INVALID_TECHNICAL_GROUP_STRUCTURE`.

Reviewer FIX was incorporated and the corrected Architect Lock received final Reviewer **ACCEPT**. Architecture is **ACCEPTED**; implementation is complete and ready for review.

## Next action

Reviewer handoff. Implementation follows [ARCHITECT_LOCK.md](ARCHITECT_LOCK.md).
