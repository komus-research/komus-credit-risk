# Configurable Model Platform V1 — STATUS

Phase: **MP-A IMPLEMENTATION COMPLETE / READY FOR REVIEW**

Architecture: **ACCEPTED**

Owner decisions: **RESOLVED 2026-09-27**

## READ FIRST

1. [ARCHITECT_LOCK.md](ARCHITECT_LOCK.md)
2. [../../CURRENT_STATE.md](../../CURRENT_STATE.md)
3. [../../ROADMAP.md](../../ROADMAP.md)

## Current state

The existing ML-core remains accepted and is not being rewritten.

The open work is the product model layer:

- trusted ModelPlugin registration;
- declarative parameter schema;
- Recommended / Advanced resolution;
- generic capabilities;
- mandatory configuration smoke gate;
- provider-based persistence;
- model catalog DTO;
- backward-compatible migration of the current four GBDT models.

MP-A is implemented and ready for review. It adds immutable declarative parameter,
recommended-profile, capability, input-contract and trusted-plugin contracts plus a
fail-closed `ModelPluginRegistry`. CatBoost, XGBoost, LightGBM and GBDT Mean are
registered in frozen-compatible mode with payloads exactly equal to their existing
accepted profiles. The existing `ModelRegistry`, runner, persistence, inference,
Local SHAP and UI are intentionally untouched.

MP-B (override resolution/configurable adapters), MP-C (configuration provenance and
smoke), MP-D (provider-based persistence) and MP-E (catalog/runtime integration)
remain intentionally unimplemented.

Verification evidence: focused MP-A contract tests and existing GBDT/planning
regression tests are run before review, followed by the full suite and static checks.

## Next implementation stage

**MP-A — Contracts + Plugin Registry**

The implementation must be narrow, regression-safe and preserve exact current behavior for Recommended/no-overrides.

After implementation, use the normal Developer → Reviewer cycle before advancing to MP-B.
