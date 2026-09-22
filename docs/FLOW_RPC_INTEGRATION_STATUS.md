# Flow RPC audit and isolated integration — 2026-09-20

## Current verdict

### 2026-09-21 economical ship checkpoint

FINAL ENGINEERING RESULT: main-checkout full regression 863/863 PASS in 307.597s,
exit code 0. Durable log: `D:\Story Auto\evidence\flow-stable-regression-20260921.log`.
All eight Flow source files match `flow-rpc-source-manifest-20260920.json` at this
checkpoint. Quality/security gates PASS. Installed experimental release candidate
is engineering-verified; production/owner acceptance is NOT claimed. Default gate
remains OFF. No new paid/provider generation, commit or push this turn.

Remaining before stable production: verify the supported reference-video path
with production QC and the user-facing end-to-end workflow on the intended runtime;
resolve any resulting defects and record owner acceptance where required. Current
local UI preview runtime lacks Kokoro models and Dola accounts; its engineering
fixture is not proof of the owner's full production configuration. Do not expand
provider scope or silently accept visual QC to label this stable.

No new provider generation or upload this turn. Main checkout targeted suite:
43 tests PASS (Flow RPC, canonical recovery/batch, Dola, readiness). Quality gate
PASS; security gate PASS (its credential scan is tracked-file based, not a claim
that every untracked artifact was scanned). Full main-checkout regression restarted
with durable log at `D:\Story Auto\evidence\flow-stable-regression-20260921.log`;
the preceding worktree test process no longer had a retrievable final result and
must not be counted as PASS.

Readiness corrections verified: Gemini configuration no longer means live Ready;
ConnectionError/TimeoutError during Flow setup preserves the already saved local
project. Existing Dola code remains intact. Actual candidate preview on port8783
shows AI brain / Configured in Settings, with ordinary provider warnings preserved.
See STABLE_READINESS_UX.md. No production promotion or global feature activation.

## Stable delivery plan (active)

1. Composed canonical service recovery test, actual LiveFlowGenerator opt-in route,
   independent code review and fixes. No provider changes in main/Dola.
2. Live wrapper qualification: at most three new shots, one injected process exit
   after submit response and before journal acknowledgement; subsequent invocation
   must recover the same attempt without another upload/submit. Each shot has a
   separate immutable evidence directory. Stop the sequence on uncertainty.
3. Run regression gates; update architecture and operational activation/rollback
   documentation. Production promotion requires canonical end-to-end acceptance,
   resolved review findings and exact candidate identity, not merely three videos.
4. Integrate only after checking current main/Dola changes; preserve owner edits.
   Stable means supported 8-second PNG-reference scope, verified restart/recovery,
   no unresolved attempts or known critical defects, usable activation and rollback.
   Broader formats/models remain explicitly unsupported.

Composed offline service test now PASS: execute_generation -> LiveFlowGenerator ->
RPC journal -> lost response -> canonical AMBIGUOUS -> reconcile -> selected_asset;
one canonical attempt and one upload/submit total. This adds service-level evidence
to the earlier isolated transport tests, but does not replace live service acceptance.

AUDIT_FINDINGS_FIXED. LIVE_QUALIFICATION_IN_PROGRESS. PRODUCTION_PROMOTION_HOLD.
This record supersedes the pasted claim of unconditional PREINTEGRATION_QUALIFIED
for decisions about this integration. Original research evidence is preserved.
Initial audit performed no provider mutation. Subsequent bounded live canaries
are recorded below. No cookie export, commit/push or production activation.

## Isolation and scope

- Source checkout: `D:\Story Auto\story-auto`, HEAD `5464cbb`.
- Candidate: `D:\Story Auto\flow-batchexecute-integration`.
- Branch: `codex/flow-batchexecute-integration`, same base HEAD.
- Existing uncommitted Flow cdp/live/service, response_model, video_acquisition,
  video_identity and corresponding tests plus ADRs 0009/0010/0012 were copied as
  dependencies. These are inherited changes, not all authored in this integration.
- Dola, shared routing, operator, UI and main-checkout edits are excluded.

## Independent evidence audit

The reviewed evidence root is
`D:\Story Auto\evidence\transport_probe_20260920`.

Confirmed: 20 JSON files parse; eight MP4s have valid containers. Declared
hashes/sizes checked for reconstructed/post-restart sequences and recovery match.
Recovery source contains no generation submit call.

Qualification gaps:

1. The first contract check creates its baseline. The later six-round soak only
   compares samples with one another, not explicitly with the saved baseline.
2. Eight synthetic drift cases mutate a derived dictionary, not actual RPC wire
   framing/request slots. They do not qualify the generation/upload contract.
3. Research catalog matching uses a marker substring and does not enforce exact
   prompt/reference/model. A literal zero duplicate field is not an eventual
   duplicate detection measurement.
4. Reconstructed sequence3 references a durable job artifact unavailable in this
   workspace. Existing media corroborates it, but original trace is not independently
   reproducible here.
5. Handoff and ADR refer to different ten-/six-round checkpoints. Counts are local
   adapter invocations, not independent backend submission counts.

Evidence source references: `flow_preintegration_qualification.py` lines 102-136
and 177-188; `flow_transport_stability.py` lines 398-439, 490-516, 567-598.

## Design and milestones

1. Audit and isolation: complete; production hold retained.
2. Pure bounded RPC builders/parser, adversarial contract tests: implemented.
3. Opt-in transport and canonical service integration: implemented, reviewed.
   Durable per-attempt journal precedes upload/submit. Lost responses do not authorize
   retry. Recovery only reads/acquires. Exact prompt, reference and model membership,
   project, local request hash, reference hash, attempt directory and result hash are
   bound before selecting output. Checksums detect accidental corruption, not hostile
   local tampering. They are not signatures or independent provider attestations.
4. Independent implementation review: findings fixed, re-review PASS. Flow regression
   checkpoint: 361 tests PASS (this run included duplicate imported test collection;
   import subsequently fixed, do not treat the count as 361 unique cases).
5. Fresh live baseline: PASS. Strict structural lineage added using a redacted live
   catalog fixture. Live crash-recovery PASS; canonical-service live test in progress.

Candidate scope is PNG single-reference VIDEO, 8 seconds, 16:9, one output,
`abra_r2v_8s`. Unsupported intent stops without UI fallback. Normal route remains
unchanged unless BOTH `STORY_AUTO_FLOW_RPC_EXPERIMENTAL=1` and
`STORY_AUTO_FLOW_RPC_PROJECT=<exact provider project UUID>` are set. Do not set these
in production yet. Existing UI capability preflight remains; this is not a proven
end-to-end UI-independent production path.

This still attaches to the authenticated Chrome session via CDP for session metadata
and normal reCAPTCHA token acquisition. It removes compositor interactions, not the
CDP/browser dependency. No CAPTCHA bypass or cookie rotation is implemented.

## Acceptance evidence

Focused suite: 139 tests PASS (contract, transport, response model, video identity,
video acquisition, current editor contract, Flow service). Transport cases include
lost-response recovery, pending recovery, upload uncertainty, missing boundary,
request mismatch, corruption and feature-gate defaults. Fixtures are offline and do
not prove live provider compatibility. Final review/rerun results follow below.

## Review checkpoint

Independent evidence audit completed. Reviewer resumed successfully and identified
three P1 findings: recursive string membership, missing terminal-status contract,
and missing runtime baseline enforcement. All three fixed and re-review PASS.
Captured redacted field paths now drive attribution tests; exact canonical slots
and CAE status are required. Every real catalog read checks the baseline fingerprint.
Compilation passes. Production activation remains withheld pending full acceptance.

## Next activation gate

### Delivery milestone — 2026-09-20

- Three additional live videos completed in order: injected-crash canary12,
  wrapper shot13, canonical-service shot14. Separate directories preserved.
  Each has one local submit boundary. This is three bounded sequential runs,
  not a large-load soak or statistical reliability guarantee.
- Crash12: process exit 86 immediately after POST response and before local ack;
  fresh-process LiveFlowGenerator.reconcile recovered ACQUIRED with counters 1/1.
- Canonical14: actual capability preflight, execute_generation, live wrapper,
  strict RPC attribution, ffprobe and canonical selected_asset succeeded. One
  attempt/one submit. Reinvocation from both candidate and main returned zero new
  submissions. Engineering fixture QC is explicit; production visual QC was not
  silently accepted.
- Restored Chrome with its normal exact localhost allowed-origin flag after
  finding the legacy inspector could not attach to the previous launch. No other
  browser profile was closed, modified or copied.
- Independent re-review PASS after three P1 fixes. Additional owned-output guard
  prevents a prior request's provider identity being attached to another request.
- Flow regression checkpoint: 291 tests PASS after removing duplicate imported
  test collection. Additional focused tests: 17 PASS. Main Flow RPC plus Dola:
  40 tests PASS. Full repository suite in progress.
- Integration copied only reviewed Flow hooks/new RPC files/tests/tools into main
  after exact diff comparison. Dola and shared UI/provider routing remain untouched.
  Feature gate OFF globally; no staging/commit/push. This is installed experimental
  candidate, not a production stable release declaration.

Remaining stable gates: full regression result, exact source fingerprint record,
production-QC/user-facing journey on the intended configuration and acceptance of
the limited supported scope. Do not equate engineering selected_asset with owner
acceptance or broadly stable private API behavior.

### Live transport canary — 2026-09-20

`tools/flow_rpc_canary.py` exercised the actual candidate FlowRpcGenerator against
the existing research project. Evidence directory:
`D:\Story Auto\evidence\transport_probe_20260920\integrated-transport-canary-11`.
Initial attempt with a wrong local reference path failed before journal creation
and before network writes; preserved its result. Corrected the path to the existing
stability-qualification-09/stable-reference.png, without creating another shot.
Live outcome PASS: journal ACQUIRED, upload_attempts=1, submit_attempts=1,
output identity 5d9a632a-7c60-42ff-880d-c2b18b42f505. Local video validation enforced
8-second duration, 16:9 dimensions and SHA-256. Exact prompt/reference/model catalog
membership passed. Fresh-process recovery-only rerun PASS, same output and no new
upload/submit branch. This is completed-output recovery, NOT a crash-during-submit
test. Counters describe local adapter boundaries, not independently measured backend
calls. Thirteen focused RPC tests reran PASS.

Scope remains transport canary, not full canonical service/UI journey. Remaining:
independent implementation review, integrated canonical crash/recovery and multi-shot
sequence. Production stays disabled. Historical NOT RUN statements above describe
the earlier checkpoint and are superseded only for this single-shot transport test.

### Automatic session recovery — 2026-09-20

Resolved the unavailable CDP endpoint locally: verified no Chrome process owned
the dedicated flow-profile, launched the existing profile without copying or
clearing credentials, then reran the candidate read-only check. Session survived;
36 catalog records parsed successfully. A second check compared the actual shape
with the pre-existing baseline: baseline_match=true and observed fingerprint
78ca7a1c3048b2c86802981696ca7e196752a661a027d3f11b8b5edece84e049.
Evidence: `flow-rpc-readiness-restart-20260920.json` and
`flow-rpc-baseline-restart-20260920.json`. Zero uploads/generations. Operator login
was not needed. This closes only the live baseline gap, not semantic lineage or
integrated generation acceptance. The earlier unavailable result is preserved.

### Accelerated ship check — 2026-09-20

Added `tools/flow_rpc_readiness.py`, a bounded read-only candidate check which
refuses to overwrite evidence and never uploads, generates or mints CAPTCHA.
Actual run: BLOCKED / FLOW_RPC_SESSION_UNAVAILABLE. Independent HTTP check of
127.0.0.1:9222 confirmed CDP_9222_UNREACHABLE. See
`flow-rpc-readiness-20260920.json`. Zero upload/generation attempts.
Next operational prerequisite is to restore the dedicated authenticated Flow
Chrome session before repeating readiness with a new evidence filename. Do not
interpret historical Chrome health as current readiness. Independent code review
and live integrated acceptance remain outstanding; no production ship claimed.

Persist a fresh read-only comparison with the saved baseline without overwriting
old evidence; verify actual catalog semantic field placement against captured wire
responses; then run a bounded integrated reference-video canary and crash recovery,
followed by sequential shots. Count attempted writes separately from acknowledged
and attributed outputs. Keep production HOLD until these steps succeed.
