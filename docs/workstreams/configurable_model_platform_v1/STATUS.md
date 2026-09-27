# Configurable Model Platform V1 — STATUS

Phase: **MP-A ACCEPTED / MP-B ACCEPTED / MP-C READY_FOR_IMPLEMENTATION**

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

MP-B is implemented and **ACCEPTED**. It resolves `model_id` + mode + sparse
overrides through the trusted plugin registry into an immutable resolved configuration,
passes its exact full profile into `ExperimentConfig.model_parameters`, and permits only
the accepted GBDT estimator parameters (including nested GBDT Mean components). The
Recommended no-override path remains payload-identical to the accepted profiles.

Corrective review fixes applied: non-finite numeric Advanced values now fail through a
stable configuration error before hashing, factories independently reject non-finite
editable values, and GBDT Mean component envelopes require their exact canonical keys.

Final MP-B Reviewer verdict after corrective review: **ACCEPT**.

Accepted MP-B head: `340b362179714d92dcd5afafb8e2d14155e35d52`.

MP-C (configuration provenance and smoke), MP-D (provider-based persistence) and MP-E
(catalog/runtime integration) remain intentionally unimplemented.

Accepted MP-A head: `078adc4d009068cd4eb3b3886ec20b2e9aa46017`.

MP-A final verification included 276 passed, 108 subtests plus static checks.
Its corrective review closed contract deep immutability, bidirectional
provider/capability consistency, schema/profile recommended-value consistency and
configuration-validator identity.

MP-B final verification after corrective review:

- focused: 79 passed, 53 subtests;
- full suite: 288 passed, 128 subtests;
- `compileall src app tests`: PASS;
- `git diff --check`: PASS;
- focused new resolver/test Ruff + format: PASS;
- unrelated historical Ruff findings remained untouched.

No MP-C/MP-D/MP-E behavior was implemented inside MP-B.

## Next implementation stage

**MP-C — Provenance + Smoke**

MP-C remains the next stage. It must not be pulled forward into MP-B.
