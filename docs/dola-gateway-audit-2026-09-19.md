# Dola Render Gateway: audit and Story Auto integration design

Date: 2026-09-19. Status: AUDITED_STATIC / DESIGN_PROPOSED / DO_NOT_ENABLE.

## Scope and authority

Upstream: https://github.com/coll3879xx-cyber/dola-render-gateway
Audited SHA: `57518aac4e0a150fa54386654ba8738a15d2a2b3`.
Read-only checkout: `D:/Story Auto/evidence/dola-audit-6d99c8f7`.
Story Auto candidate: `5464cbb1d1c11a550b5e096647b9f94587de5bfe`.
Existing owner test edits, handoff, and temporary folders are preserved.

Method: source/contract/lifecycle inspection; no dependency installation, module import,
gateway execution, extension installation, login, credential transfer, CAPTCHA operation,
or provider generation. Findings are static code evidence, not claimed live exploit results.
No throughput, account safety, credit cost, output quality, or upstream permission verified.

Decision 0006 remains accepted authority: Dola requires a qualified official API contract;
unofficial cookie/private-endpoint adapters are excluded. This audit does not supersede it.

## Actual architecture

Client -> FastAPI -> SQLite task row -> asyncio background task -> account pool
-> persistent Patchright browser -> UI submission + private protocol polling
-> local MP4 -> unauthenticated static URL.

The external JSON interface is useful isolation, but does not transform its upstream
transport into an official Dola API. The active server imports the UI worker through
browser_pool; that worker also uses private protocol polling from video_worker.
The optional-by-config extension is enabled by default and intercepts provider responses
with debugger privileges to supply duration capability data and alter media handling.

Useful patterns: account-level exclusion, per-client concurrency, persistent conversation
identity, poll-only resume when identity exists, pending-task cap, client ownership on
GET task, reference download limits, redirect validation, and isolated provider adapter.
Reuse these concepts, not the browser/extension implementation wholesale.

## Findings (FACT vs INFERENCE)

| Priority | Evidence | Consequence |
|---|---|---|
| P1 security | FACT: config.py defaults to 0.0.0.0, empty API/admin keys. server.py:109-137 permits anonymous API when no env keys AND no enabled stored keys; admin gate is independent and optional. server.py:502 returns stored key records; store.py stores raw service keys. | With reachable port and default config, admin actions and stored keys are exposed. Disabling the last stored key also reopens anonymous API unless environment keys remain. Set explicit deny-by-default authentication; do not expose this service. |
| P1 duplicate effect | FACT: server.py:287-335 accepts no idempotency key/client request identity, allocates a new UUID and schedules work for each POST. | INFERENCE trace: commit succeeds -> client loses response -> identical retry creates another provider job. Story Auto cannot safely retry ambiguous POST. |
| P1 interrupted dispatch | FACT: server.py marks processing before submission; video_worker_ui.py:425 sends Enter, but persists conversation only at 465. store.py:233-250 recovers processing rows only with conversation/account, and otherwise only queued rows. | Crash before conversation commit leaves processing/no-ID outside both recovery sets, including before dispatch. Must expose reconciliation-required, never guess failed/not-dispatched. |
| P1 hidden redispatch | FACT: video_worker_ui.py raises RiskControlError after submission/CAPTCHA attempts; browser_pool.py:364-371 then rotates to another account. Credit/daily-limit exceptions can also arise while polling. | INFERENCE: downstream uncertainty can become a second account submission. Need phase-aware errors and no rotation after submission unless provider confirms non-acceptance. Timeout itself is NOT automatically retried by the pool; preserve that positive distinction. |
| P1 false contract completion | FACT: ratio/duration selection failures log and use defaults (video_worker_ui.py:404-420). Download completion becomes task completed (server.py:204-209); video_worker.py:143-155 writes bytes without ffprobe/duration/hash validation. | Returned requested duration/model metadata is not proof of actual media properties. Validate exact output and reject mismatch; never silently stretch a wrong-duration result. |
| P1 artifact privacy | FACT: /videos StaticFiles is mounted outside API auth (server.py:38); filenames use account + second timestamp (video_worker.py:147). | Task ownership checks do not protect final files. Require authenticated asset delivery or short-lived scoped URLs; unique immutable attempt paths. |
| P2 network boundary | FACT: media.py validates DNS, then aiohttp/proxy separately resolves the hostname; proxy failure falls back direct. | INFERENCE: DNS rebinding/time-of-check gap and proxy/egress-policy mismatch remain despite useful SSRF checks. Pin validated addresses/egress and forbid silent direct fallback. Not an exploit claim. |
| P2 operations | FACT: locks/semaphores are in-process; startup scans resumable jobs without distributed lease; requirements are unpinned; no tracked tests found in this checkout. | INFERENCE: multi-worker/multi-instance deployments can race or resume the same job twice. Keep single-process until leases/fencing and restart tests exist. |
| Qualification blocker | FACT: private /im/chain/single polling, response-interception extension, automatic CAPTCHA handling; README only says educational/internal testing and no standalone LICENSE found. | Does not meet Decision 0006. Provider-supported access and redistribution rights remain unverified; do not infer legal violation, official support, or production readiness. |

## Design compatible with Story Auto

### Implement now: no new runtime dependency

Keep `dola_official` disabled and `manual_external` enabled. Existing Hybrid Opening
already accepts externally produced clips, normalizes them, checks slot fit, binds hashes,
and converges into canonical rendering. No new Dola UI page, second scheduler, browser
pool, cookie importer, or extension is needed to ship this path.

### Conditional future integration (not authorized by this document)

Only after the official-access gate is satisfied, add a thin provider-specific adapter
behind `providers/video_generation.py`. Do not use the existing `dola_official` identity
for an unofficial gateway. Any separately proposed gateway gets its own explicit identity,
transport and provenance, and requires an explicit revision of Decision 0006 first.
An owner decision is necessary but not sufficient: technical/security/access gates remain.

Keep Story Auto responsible for project intent, slot timing, QC, reconciliation decisions,
and canonical local assets. Gateway owns only its accepted job, provider session and polling.
Never expose the gateway admin interface or browser cookies to Story Auto.

Required adapter contract:
- preflight returns real availability, supported model/mode/durations, auth and quota state;
- submit accepts durable client_request_id + immutable payload hash; same identity/same
  payload returns same job; same identity/different payload conflicts;
- persist intent before network, gateway job ID and upstream account/conversation/message
  identity before claiming accepted; lookup by client_request_id survives lost POST response;
- read-only poll/reconcile never submit; separate confirmed-not-dispatched, accepted,
  dispatch-unknown, provider-failed, completed, and acquisition-failed states;
- downloads resume acquisition without regeneration; bounded size, content validation,
  ffprobe, expected duration/aspect/audio checks, local hash, and atomic finalization;
- auth required for API/admin/assets; loopback by default, DPAPI credentials on Windows,
  sanitized logs, bounded concurrency=1 for first canary, no account auto-rotation;
- provenance records configured model versus observed provider model separately;
  store selected trim range, requested slot duration and actual source duration.

Duration mismatch: this gateway accepts only 10/15/30s, while the default Hybrid opening
is three 6s slots. A future adapter may acquire a longer valid clip and trim deliberately
through the existing normalizer, with explicit cost and selected-range accounting. It
must not silently substitute one 30s clip for three separately prompted semantic slots.

### Required offline qualification cases

Lost POST response with same-id replay; crash before/after provider acceptance; restart
with processing/no-upstream-ID; timeout and risk-control with zero second submission;
duplicate worker claim; no credits; expired authentication/CAPTCHA handoff; truncated
download; wrong duration/aspect; forbidden/private/redirected media URLs; disabled last
key denies access; unauthorized admin and asset reads; acquisition retry reuses same job.

## Delivery sequence

1. NOW: finish current Story Auto Full Image acceptance/recovery. Do not put Dola on the
   critical shipping path. Preserve Flow request req_c9c289e303f19dbfd946, currently
   AMBIGUOUS / OUTPUT_ATTRIBUTION_AMBIGUOUS. No blind retry or provider switch.
2. NEXT: close real-use blockers (truthful readiness, secure Gemini setup experience,
   create/reopen safety) in bounded batches; keep evidence separate from owner acceptance.
3. OPTIONAL: use existing manual external video import when the owner supplies clips.
4. LATER: re-evaluate Dola when official supported access, license clarity, durable
   effect identity and security gates are met. Then run isolated offline adapter tests,
   one separately budgeted live canary, restart/reopen checks, and explicit promotion.

Trigger-based scheduling is preferable to promising an integration date before these gates.
This audit/design adds no provider calls and changes no production routing or defaults.

## Return-to-shipping check

Canonical production query on this host reports NEEDS_ATTENTION at VISUALS,
recovery reason DISPATCH_AMBIGUOUS, automatic_recovery_available=false and
requires_owner_decision=true. The UI-oriented recheck is not available in this state
(it accepts STUCK_PENDING only). Flow connected status is not proof of asset ownership.
No generation or fallback was dispatched during this audit. Resolve the existing effect
with attributable provider evidence or an explicit owner recovery decision before shipping
this live project; the earlier offline acceptance does not remove that boundary.
