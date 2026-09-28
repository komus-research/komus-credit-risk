# Configurable Model Platform V1 — STATUS

Phase: **MP-A ACCEPTED / MP-B ACCEPTED / MP-C ACCEPTED / MP-D IMPLEMENTATION COMPLETE / READY FOR REVIEW / MP-E UNIMPLEMENTED**

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

MP-C is implemented and **ACCEPTED**. It adds immutable trusted configuration
provenance, deterministic bounded stratified technical smoke evidence, the
matching-PASS gate in `ExperimentApplicationService` for both Recommended and
Advanced runs, backend-owned prepared-context authority, and additive V2 experiment
artifacts. V1 artifacts remain readable without rewrite or manufactured provenance.
MP-D (provider-based persistence) and MP-E (catalog/runtime integration) remain
intentionally unimplemented.

Corrective review fixes bind smoke matching to the exact ordered population rows,
require an authoritative prepared context for locked final-test data, remove the
unconfigured application full-run fallback, and declare smoke support truthfully.

The final corrective review fix establishes backend-owned authority for prepared
dataset contexts. Trusted historical and confirmed generic preparation publish the
exact context to the runtime authority; smoke and full runs resolve by that trusted
reference and reject caller-forged or conflicting contexts before fitting or
persisting an artifact.

The application no longer self-registers caller-provided data for unlocked
datasets. It only resolves contexts already published by trusted preparation, so
caller-only data cannot create smoke evidence or a V2 artifact.

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

Final MP-C Reviewer verdict after all corrective reviews: **ACCEPT**.

Accepted MP-C head: `a45013ccb037852b1c26bf49dddf73724bc04926`.

Final MP-C verification evidence includes:

- focused: 83 passed, 17 subtests;
- full suite: 297 passed, 128 subtests;
- `compileall src app tests`: PASS;
- `git diff --check`: PASS;
- focused Ruff/import-order/backend format checks: PASS.

## Next implementation stage

**MP-D — Provider-based persistence**
