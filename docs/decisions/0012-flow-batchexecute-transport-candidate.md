# ADR-0012 — Google Flow batchexecute transport research candidate

**Date:** 2026-09-20

**Status:** INTEGRATED EXPERIMENTAL (default OFF) — bounded live qualification PASS; production promotion HOLD

**Scope:** Google Flow transport only
**Conflict boundary:** This record must not modify or redirect the concurrent Dola AI implementation. Dola files, provider registry wiring, operator/UI behavior, and current production routing remain out of scope until an explicit promotion gate is passed.

## Decision under research

Current delivery update: see `../FLOW_RPC_INTEGRATION_STATUS.md` for audited
qualification corrections, independent review fixes, strict structural lineage,
runtime baseline enforcement, live crash/recovery and canonical service evidence.
Earlier NOT INTEGRATED/qualification-complete checkpoints below are historical,
not the current promotion decision. Dola routing remains unchanged.

Preferred Google Flow control architecture:

    Dedicated authenticated Chrome profile
      ├─ owns Google login/session
      ├─ exposes current WIZ_global_data (at / f.sid / bl)
      └─ mints fresh reCAPTCHA Enterprise tokens
                  │
                  ▼
    Playwright BrowserContext.request / APIRequestContext
                  │
                  ▼
    flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute
      ├─ maseQ   : image upload -> media_id
      ├─ MZZa6b  : reference-video generation
      ├─ Zzl0ze  : project media catalog / recovery evidence
      └─ as29s   : media lookup / signed content URLs

The browser is treated as an **authentication/reCAPTCHA enclave**, not as the primary UI-control transport. DOM automation is not part of the intended happy path.

## Evidence already proven on the owner session

Evidence is kept outside production source under:

    D:\Story Auto\evidence\transport_probe_20260920\

1. **Read-only migrated transport observation**
   - 17 POST requests observed to /_/AiSandboxAngularFrontend/data/batchexecute.
   - Requests carried rpcids, f.sid, bl, source-path, at, and f.req.
   - at length observed as 42.
   - Responses were HTTP 200 anti-XSSI framed payloads.
   - No generation submit occurred.

2. **Zero-credit reference-video capture**
   - Current reference-video RPC observed as MZZa6b.
   - Exact prompt marker present.
   - One fresh reCAPTCHA Enterprise token observed in the generation request.
   - Request was aborted before backend delivery.
   - Backend generation count remained zero.

3. **Same-origin page fetch generation canary**
   - One backend submit attempt.
   - HTTP 200, anti-XSSI response, wrb.fr envelope.
   - One unique fresh rendered identity reconciled after 55.9 s.
   - Exact MP4 acquired: 2,831,001 bytes.
   - SHA-256: 77285d073b997a19f59e7a01ef318034b2eabcc40c345b0bebdec9fc19670c9f.
   - Retry count: zero.

4. **APIRequestContext generation canary**
   - Request sent via BrowserContext.request, sharing the authenticated browser cookie jar.
   - One backend submit attempt.
   - HTTP 200, anti-XSSI response, wrb.fr envelope.
   - One unique fresh rendered identity reconciled after 55.8 s.
   - Exact MP4 acquired: 4,110,307 bytes.
   - SHA-256: e7c490d454682ef68953450199a555648655ee06dcd7ddab172e2237ff6be41d.
   - Retry count: zero.
   - UI Generate request reaching backend: zero.

5. **Direct upload canary**
   - maseQ sent through APIRequestContext.
   - One upload attempt, zero retry.
   - HTTP 200 and valid media_id returned.
   - as29s read-back HTTP 200.
   - Returned image content matched source with dHash distance 0.
   - No generation submit occurred.

6. **Read-only media catalog mapping**
   - Zzl0ze exposed 27 project media candidates.
   - 27/27 candidate media ids resolved through as29s with HTTP 200.
   - 27/27 returned image URLs.
   - Demonstrates server-side content/media recovery can avoid picker/CDN-DOM inference.

7. **UI failure reproduced before submission**
   - Existing Flow attachment path again produced FLOW_REFERENCE_UPLOAD_FAILED after the asset was found but before composer commit.
   - No generation occurred.
   - This is direct evidence that attachment UI/DOM state is a real failure domain and that changing CDP to another browser-control protocol alone would not remove the root cause.

## Current technical conclusion

The owner-session evidence supports all of the following:

- Shared authenticated cookies/session are sufficient for Flow batchexecute reads and generation submits when the request also carries current WIZ metadata and a fresh reCAPTCHA token.
- The actual generation POST does **not** need to originate from a UI click or CDP-controlled DOM interaction.
- BrowserContext.request is currently preferred to raw cookie export because it shares the browser cookie jar without persisting cookie material separately.
- The browser remains necessary for login/session lifecycle and fresh reCAPTCHA minting.
- Media upload, lookup, catalog reconciliation, and generation transport can be implemented without the Flow picker/composer happy path.
- Duplicate uploads should be prevented with a local content-hash -> verified Flow media_id cache.

## Not yet claimed

This ADR does **not** claim STABLE, SEALED, PRODUCT_ACCEPTED, or production activation.

Current verdict:

    QUALIFIED_TRANSPORT_CANDIDATE / NOT_YET_PROMOTED

## Promotion gates

All gates below must pass before production routing may change:

1. **No-UI builder gate**
   - Build versioned MZZa6b and upload requests from local inputs without first capturing a UI Generate request.
   - Validate model/reference semantics, not only payload shape.

2. **Sequential reliability gate**
   - Multiple bounded sequential submissions on an isolated Flow project.
   - Exactly one backend submit per logical attempt.
   - Zero duplicate remote generations.
   - Exact output identity for every accepted submit.

3. **Restart/recovery gate**
   - Persist the durable remote acceptance identity before entering normal polling.
   - Terminate controller after acceptance.
   - Restart and reconcile/download without redispatch.
   - Required invariant: accepted attempt -> zero additional submit attempts after restart.

4. **Session lifecycle gate**
   - Reload/refresh browser session between canaries.
   - Re-read WIZ metadata and mint a new captcha.
   - Never reuse stale captcha or stale per-page metadata.

5. **Fail-closed drift gate**
   - Missing/changed at, f.sid, bl, captcha capability, RPC envelope, model/reference shape, or response identity must stop before an uncertain redispatch.
   - No blind retry across an irreversible boundary.

6. **Isolation gate**
   - All research and verification remain isolated from the concurrent Dola implementation and production provider routing until promotion.

## Required recovery invariant

Once a Flow generation request may have been accepted remotely:

    SUBMITTING
      -> ACCEPTED_REMOTE_ID_DURABLE
      -> RECONCILING
      -> OUTPUT_IDENTIFIED
      -> ACQUIRED

If transport fails after the irreversible boundary, the next action is **reconcile**, never automatic resubmit.

## Security / secret handling

- Do not persist raw Google cookies.
- Do not persist raw at tokens.
- Do not persist raw reCAPTCHA tokens.
- Do not persist full authenticated request bodies unless explicitly redacted.
- Evidence should retain hashes, lengths, RPC ids, response status, durable non-secret provider identities, and output hashes only.

## Stability qualification result — 2026-09-20

Controlled transport qualification has now passed.

Verdict:

    TRANSPORT_STABILITY_PROVEN_IN_CONTROLLED_MATRIX
    PRODUCTION_PROMOTION = HOLD

Evidence report:

    D:\Story Auto\evidence\transport_probe_20260920\STABILITY_QUALIFICATION.md

Qualification summary:

- fail-closed contract checks: 5/5 PASS, zero network mutations
- session/captcha refresh: 3/3 PASS, three unique captcha tokens
- direct maseQ upload/read-back: PASS
- sequential no-UI MZZa6b generation: 3/3 PASS
- logical attempts: 3
- backend generation submits: exactly 3
- retries: 0
- duplicate causal-marker records: 0
- output resolution times: 40.36 s, 36.80 s, 39.59 s
- controller crash/restart recovery: PASS
- submit attempts before crash: 1
- recovery submit attempts: 0
- recovered output resolution: 29.64 s
- server-side lineage: 4/4 records contained exact attempt marker, expected reference media id, model abra_r2v_8s, and a distinct output media id

The controlled evidence therefore proves the transport-level recovery invariant:

    irreversible request boundary
      -> durable local journal
      -> process restart
      -> server-side marker/catalog reconciliation
      -> exact media acquisition
      -> zero redispatch

This upgrades the research status from merely PROVEN_CANDIDATE to **QUALIFIED TRANSPORT CANDIDATE**.

It does not upgrade the Google Flow private wire contract itself to a long-term STABLE provider contract. Production promotion remains blocked on drift handling, reauthentication lifecycle, and longer soak across time/session turnover.

## Pre-integration qualification completion — 2026-09-20 PM

Status after the extended qualification:

    INTEGRATION_READY / NOT_INTEGRATED
    PRODUCTION_PROMOTION = HOLD

Additional evidence beyond the earlier controlled matrix:

### Reauthentication / session classifier

Synthetic classifier matrix: 7/7 PASS.

States proven:
- READY
- REAUTH_REQUIRED
- PROJECT_MISMATCH

A fresh cookie-less browser context was also tested against the bound Flow project URL. It reached flow.google.com but lacked authenticated at/captcha capability and was correctly classified REAUTH_REQUIRED. No upload or generation mutation occurred.

A missing dedicated browser instance was also observed live when port 9222 was down. Qualification failed before any provider mutation. The pre-integration contract now treats this condition as BROWSER_UNAVAILABLE rather than a generation/provider failure.

### Live contract soak

Authenticated read-only soak: 10/10 PASS over repeated reload/session cycles.

Every round proved:
- local classification READY
- at length 42
- f.sid present
- bl present
- reCAPTCHA Enterprise execute capability present
- Zzl0ze HTTP 200 with anti-XSSI framing
- catalog record lengths remained exactly 7/8
- catalog statuses remained CAE
- observed reference-video model set remained abra_r2v_8s
- as29s HTTP 200
- flow-content.google media resolution remained available

Fresh captcha tokens:
- 10 rounds
- 10 unique token hashes
- zero captcha reuse

Normalized live contract fingerprint:
- unique fingerprint count across all 10 rounds: 1
- fingerprint: ff8640967ac2a845af8e8a746436cb387b87a7646f3080ad60f9e961234c6218

Provider mutations during soak:
- generation submissions: 0
- upload submissions: 0

### Full browser restart after irreversible generation boundary

An additional fault test extended the prior controller-process recovery test.

Process A:
- submitted one MZZa6b generation
- persisted the crash journal after the irreversible boundary
- generation submit attempts: exactly 1
- retry count: 0

Then:
- every Chrome process associated with remote-debugging-port 9222 was terminated
- port 9222 was confirmed unavailable
- the same dedicated Story Auto Chrome profile was relaunched
- the isolated Flow project was restored

Process B:
- performed recovery only
- MZZa6b redispatch attempts: 0
- catalog marker first seen after restart: 4.91 s
- exact output resolved after restart: 10.20 s
- output bytes: 1,349,519
- output SHA-256: eb799181794a0adc79e9de99b5731c0c2814c40c84ee0aabbc56339da8492514
- final state: RECOVERED_WITHOUT_REDISPATCH

This proves the stronger invariant:

    remote submit accepted
      -> controller ends
      -> authenticated browser is fully terminated
      -> same browser profile restarts
      -> new controller process reconciles provider state
      -> exact output acquired
      -> zero redispatch

### Integration boundary

Research/qualification work stops here.

No production Flow routing has been changed.
No Dola provider, provider registry, operator, UI, or shared production wiring was modified by this qualification phase.

The next phase is integration, and must begin only after a new explicit decision to proceed.

## Pre-integration qualification checkpoint — 2026-09-20 18:xx +07

The requested stop point has been reached.

Current state:

    PREINTEGRATION_QUALIFIED
    INTEGRATION_NOT_STARTED
    PRODUCTION_ROUTING_UNCHANGED

Additional gates completed after the controlled stability matrix:

### Dedicated-browser restart lifecycle

PASS.

The listener on 127.0.0.1:9222 was verified to belong to the dedicated Story Auto Flow Chrome process using:

    --remote-debugging-port=9222
    --user-data-dir=D:\Story Auto\story-auto\runtime\browser\flow-profile

Only that dedicated process tree was restarted.

After relaunch:

- Google/Flow session persisted.
- at length = 42.
- f.sid present.
- bl present.
- grecaptcha.enterprise.execute available.
- Zzl0ze catalog returned HTTP 200 with anti-XSSI framing.
- no generation was performed by the restart/session check.

### Contract fingerprint / drift detector

PASS.

Current contract fingerprint:

    78ca7a1c3048b2c86802981696ca7e196752a661a027d3f11b8b5edece84e049

Fingerprint shape includes:

- host = flow.google.com
- source path prefix = project
- at length = 42
- f.sid present
- bl present
- reCAPTCHA Enterprise execute available
- catalog record lengths = 7 or 8
- project id slot = 1
- catalog status type = string
- anti-XSSI framing present

Synthetic drift matrix: 8/8 PASS fail-closed.

Detected and blocked:

- at shape drift
- missing f.sid
- missing bl
- missing captcha API
- host drift
- catalog record-length drift
- project-id slot drift
- catalog framing drift

Network mutations during synthetic drift checks: zero.

### Unauthenticated / reauth behavior

PASS.

A fresh Playwright browser context with no authenticated storage was navigated to the Flow project URL.

Observed:

- redirected/landed at flow.google.com/about
- at length = 0
- captcha execute unavailable
- authenticated = false

Decision:

    NEEDS_OPERATOR

No upload or generation RPC was attempted.

This proves an unauthenticated state is distinguishable from a transport error and can stop before mutation.

### Read-only soak after browser restart

PASS 6/6 rounds.

- six reload/catalog observation rounds
- 20 second spacing between rounds
- one unique contract fingerprint across all rounds
- 34 catalog records every round
- 16 read RPC ids observed every round
- zero generation submissions
- zero upload submissions

### Post-restart direct generation

PASS.

After the dedicated browser restart and qualification checks, one direct no-UI generation was executed:

- one upload attempt
- one generation submit attempt
- retry count = 0
- HTTP 200 / anti-XSSI / wrb.fr
- catalog causal marker first seen = 4.80 s
- output resolved = 37.05 s
- duplicate marker records = 0
- output bytes = 1,559,978
- output SHA-256 = ce320f2bd4863a1f33981c32603cd2a94acddfb92331ceb4c09dc64cdfce1b95

This demonstrates the complete lifecycle:

    dedicated Chrome restart
      -> authenticated session recovered from persistent profile
      -> WIZ/captcha contract reacquired
      -> direct upload
      -> direct MZZa6b submit
      -> server-side causal reconciliation
      -> exact MP4 acquisition
      -> zero retry

### Evidence integrity note

The stability harness originally reused result.json for later runs. The later post-restart run overwrote the raw three-run result file.

This was repaired without inventing evidence:

- the post-restart result was preserved separately;
- the original three-run result was reconstructed from durable ChatCode job evidence:
  local-execution:flow-stability-sequence3-20260920
- the recovered file explicitly records that provenance.

Files:

    evidence/transport_probe_20260920/preintegration-qualification-10/contract-baseline.json
    evidence/transport_probe_20260920/preintegration-qualification-10/result.json
    evidence/transport_probe_20260920/preintegration-qualification-10/synthetic-drift.json
    evidence/transport_probe_20260920/preintegration-qualification-10/unauthenticated.json
    evidence/transport_probe_20260920/preintegration-qualification-10/soak.json
    evidence/transport_probe_20260920/stability-qualification-09/postrestart-generation.json
    evidence/transport_probe_20260920/stability-qualification-09/sequence-3-recovered-from-job-evidence.json

## Integration hold

No production integration is authorized by this checkpoint.

Before integration begins, re-run all of the following against the then-current working tree:

1. confirm the concurrent Dola worker has completed or establish a non-overlapping isolated worktree;
2. re-read git status and current HEAD;
3. verify ADR-0012 and evidence hashes;
4. run the live contract fingerprint and require an exact baseline match;
5. confirm the dedicated Flow profile is authenticated;
6. confirm no unresolved production-flow or Dola changes would be overwritten;
7. create an isolated integration branch/worktree;
8. only then implement the transport adapter behind an explicit non-default feature gate.

Until those checks pass:

    DO_NOT_INTEGRATE

## Production impact

None at this stage.

The existing production Flow adapter remains authoritative until every promotion gate above passes and an explicit activation decision is recorded.
