# Configurable Model Platform V1 — STATUS

Phase: **CLOSED — MP-A / MP-B / MP-C / MP-D / MP-E ACCEPTED**

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
MP-D is implemented and **ACCEPTED**. Provider-based ModelVersion V2 persistence now
supports exact Recommended/Advanced configuration provenance for CatBoost, XGBoost,
LightGBM and GBDT Mean while legacy ModelVersion V1 remains readable unchanged.
MP-E is implemented and **ACCEPTED**. It adds a deterministic, read-only catalog
projection from the trusted plugin registry, generic runtime package/version
availability resolution, and makes planning/UI model discovery use that same registry
rather than caller-supplied model maps. A test-only fifth plugin proves the generic
catalog → configuration → smoke → planning → runner → V2 artifact flow without
production registration or model-id branches.

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

Final MP-D Reviewer verdict after corrective review: **ACCEPT**.

Accepted MP-D head: `ba43b8ef91c39b61c3d728afe690add8ad0023af`.

Final MP-D verification evidence includes:

- corrective focused: 46 passed, 30 subtests;
- full suite: 301 passed, 133 subtests;
- `compileall src app tests`: PASS;
- `git diff --check`: PASS;
- focused Ruff import/unused-import checks: PASS;
- legacy V1 ModelVersion compatibility preserved;
- Advanced CatBoost/XGBoost/LightGBM/GBDT Mean V2 save/load confirmed with prediction parity.

Final MP-E Reviewer verdict: **ACCEPT**.

Accepted MP-E head: `0622d944dd0dd4a194fce1dd12c037bf9ad0a0af`.

Final MP-E verification evidence:

- focused regression set: 95 passed, 38 subtests;
- full suite: 305 passed, 133 subtests;
- `compileall src app tests`: PASS;
- `git diff --check`: PASS;
- changed-file Ruff/format checks: PASS.

## Workstream result

**Configurable Model Platform V1 — CLOSED / ACCEPTED.**
## Narrow follow-up prerequisite — Parameter Presentation / Identity V1

Status: **ARCHITECTURE ACCEPTED / READY_FOR_IMPLEMENTATION**

Implementation: **NOT STARTED**

The accepted MP-A..MP-E workstream remains CLOSED / ACCEPTED.
This narrow prerequisite does not reopen model-platform behavior.

Reason: current `ModelParameter.display_name_ru / description_ru` participate in
`schema_hash` and `plugin_contract_hash`, so editing them directly for Russian UI copy
would incorrectly change configuration provenance and could break continuing operations
from existing ExperimentArtifact V2 / ModelVersion V2 state.

Architect decision:

- keep current behavioral schema/plugin identities unchanged;
- introduce separate trusted backend parameter-presentation metadata for catalog copy;
- keep presentation identity independent from behavioral/scientific identity;
- require historical V2 read + final-fit/save continuation regression before ACCEPT.

Reviewer corrective FIX incorporated:

- atomic fail-closed composition of the complete trusted plugin/presentation set;
- stable INVALID_MODEL_PRESENTATION_COMPOSITION error contract;
- presentation failure blocks only the user-facing catalog, not behavioral services;
- exact canonical presentation_hash payload with parameters sorted by exact parameter_path;
- explicit presentation_profile_version release semantics and no version-only churn;
- presentation identity remains backend/debug-only and is not added to catalog/scientific artifacts;
- negative composition and hash-determinism acceptance tests are explicit.

Final corrective architecture Reviewer verdict: **ACCEPT**.

Accepted architecture head: `6ccad971882901ff779c82a08b22a2699e24f70e`.

Next: Backend / Codex implementation → Reviewer. Implementation remains **NOT STARTED**.

Source:

`PARAMETER_PRESENTATION_IDENTITY_V1.md`
