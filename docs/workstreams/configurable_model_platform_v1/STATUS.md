# Configurable Model Platform V1 — STATUS

Phase: **MP-A ACCEPTED / MP-B IMPLEMENTATION COMPLETE / READY FOR REVIEW**

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

MP-A is implemented and **ACCEPTED**. It adds immutable declarative parameter,
recommended-profile, capability, input-contract and trusted-plugin contracts plus a
fail-closed `ModelPluginRegistry`. CatBoost, XGBoost, LightGBM and GBDT Mean are
registered in frozen-compatible mode with payloads exactly equal to their existing
accepted profiles. The existing `ModelRegistry`, runner, persistence, inference,
Local SHAP and UI are intentionally untouched.

MP-B is implemented and ready for review. It resolves `model_id` + mode + sparse
overrides through the trusted plugin registry into an immutable resolved configuration,
passes its exact full profile into `ExperimentConfig.model_parameters`, and permits only
the accepted GBDT estimator parameters (including nested GBDT Mean components). The
Recommended no-override path remains payload-identical to the accepted profiles.

MP-C (configuration provenance and smoke), MP-D (provider-based persistence) and MP-E
(catalog/runtime integration) remain intentionally unimplemented.

Final Reviewer verdict after corrective review: **ACCEPT**.

Accepted MP-A head: `078adc4d009068cd4eb3b3886ec20b2e9aa46017`.

Verification evidence after correction:

- focused MP-A: 14 passed;
- existing GBDT/planning/runner: 30 passed, 22 subtests;
- full suite: 276 passed, 108 subtests;
- Ruff/format: PASS;
- `compileall src app tests`: PASS;
- `git diff --check`: PASS.

Corrective fixes closed contract deep immutability, bidirectional
provider/capability consistency, schema/profile recommended-value consistency and
configuration-validator identity. No later stage was implemented inside MP-A.

## Next implementation stage

**MP-C — Provenance + Smoke**

MP-C remains the next stage. It must not be pulled forward into MP-B.
