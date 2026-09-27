# Feature Grouping Propagation V1 — STATUS

Phase: **DESIGN**

Status: **IMPLEMENTATION OPEN — ARCHITECT LOCK REQUIRED**

## READ FIRST

1. [SPEC.md](SPEC.md)
2. [../../workstreams/dataset_onboarding_v1/04_ANALYZER_POLICY.md](../dataset_onboarding_v1/04_ANALYZER_POLICY.md)
3. [../generic_dataset_onboarding_v1/FEATURE_SELECTION_UX_V1.md](../generic_dataset_onboarding_v1/FEATURE_SELECTION_UX_V1.md)
4. [../../CURRENT_STATE.md](../../CURRENT_STATE.md)

## Actual state

Already implemented:

- `DatasetPreparationAnalyzer` creates `DatasetPreparationProposal.technical_groups`;
- grouping cascade is structural stem → repeated token → logical type → fallback;
- Feature Selection is already contractually group-first and reads downstream groups from `FeatureRegistry`.

Not yet implemented end-to-end:

- propagation of Analyzer technical groups through generic materialization into the final `FeatureRegistry → FeatureGroup` consumed by Feature Selection.

Current generic materializer primarily groups registry entries by confirmed usage status, so the useful Analyzer grouping is lost before the downstream feature screen.

## Next action

Create an Architect Lock for the narrow propagation/migration contract, then implement through Developer → Reviewer.
