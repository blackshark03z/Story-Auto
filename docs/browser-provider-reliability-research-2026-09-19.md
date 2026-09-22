# Browser provider reliability: research and bounded experiment design

Date: 2026-09-19. Status: RESEARCH / PROPOSED, not implementation approval or live qualification.
Scope: main practical transport, observation, authentication and recovery alternatives for
Story Auto Flow and the audited Dola gateway. Not a claim to exhaust every possible technique.
No provider calls, cookie exports, extension installs, proxy changes or paid operations.

## 2026-09-20 bounded implementation outcome

Subsequent owner-authorized experiments proved the current Flow picker attachment
postcondition in 20/20 direct picker cycles and 20/20 named-asset cycles, followed by
three sequential reference-video UI results and three valid 720p, eight-second MP4
downloads. That evidence authorized one narrow source correction: reference attachment
now succeeds only when the exact intended image content is observed in the composer.
The implementation also scopes media reads to observed Google Flow asset hosts through
the existing browser session and selects the structural media-picker overlay rather
than the first generic overlay. A no-Generate canonical adapter smoke passed, followed
by 316 Flow tests plus 163 subtests and the 852-test/304-subtest Git-tracked suite.

This does not promote Flow video routing. Provider job identity, exact request-to-MP4
lineage, interrupted-generation reconciliation, restart durability and unattended
video acquisition remain unqualified. The observer/extension/API alternatives below
retain their original research status for those remaining concerns.

## 2026-09-20 direct transport proof on the owner session

Owner-authorized bounded experiments on the dedicated Story Auto Chrome profile now
establish a stronger result than the original hypotheses in this document.

A read-only reload of the migrated `flow.google.com` project observed 17 POSTs to
`/_/AiSandboxAngularFrontend/data/batchexecute`. All carried the standard Flow
batch shape: `rpcids`, `f.sid`, `bl`, `source-path`, a 42-character `at`
field and `f.req`; all eligible responses were HTTP 200 anti-XSSI framed bodies.
No generation submission occurred.

A zero-credit trusted-click capture then intercepted the reference-video submit before
network delivery. It proved the current owner-session contract is `MZZa6b`, that the
request includes the exact prompt/reference state, one single-use reCAPTCHA Enterprise
token (2425 characters in that capture), the 42-character `at` field and the normal
batch session parameters. The request was aborted in-browser, generation requests
reaching the provider remained zero, and the composer was restored empty.

Two one-submit canaries then tested control transport while retaining the same authenticated
browser session and fresh page-minted reCAPTCHA:

1. MAIN-world same-origin `fetch()`: HTTP 200 with anti-XSSI/`wrb.fr`; one unique
   rendered response identity appeared after 55.9 s; exact-identity acquisition returned
   a 2,831,001-byte MP4 with SHA-256
   `77285d073b997a19f59e7a01ef318034b2eabcc40c345b0bebdec9fc19670c9f`.
2. Playwright `BrowserContext.request` / `APIRequestContext`: HTTP 200 with
   anti-XSSI/`wrb.fr`; one unique rendered response identity appeared after 55.8 s;
   exact-identity acquisition returned a 4,110,307-byte MP4 with SHA-256
   `e7c490d454682ef68953450199a555648655ee06dcd7ddab172e2237ff6be41d`.

Both canaries recorded exactly one backend submit attempt, zero UI Generate requests reaching
the backend, zero retry, and exact passive-response identity before MP4 acquisition. Raw
cookies, auth headers, `at`, reCAPTCHA tokens and full request bodies were not persisted.

This changes the technical conclusion: on the migrated host, Google Flow generation does
not require CDP/UI as the control transport once an authenticated session and one fresh
reCAPTCHA token exist. The browser can be reduced to an authentication/reCAPTCHA enclave.
The strongest current candidate is the BrowserContext-associated `APIRequestContext`
because it shares the browser cookie jar without exporting cookie material and no longer
depends on DOM activation for dispatch.

This is not yet a STABLE/promotion claim. Remaining gates are: eliminate per-run UI payload
capture with a versioned `MZZa6b` builder/upload contract; browser/controller restart after
submit with zero redispatch; sequential canaries; schema-drift fail-closed tests; session
expiry/reauth handling; and representative unattended evidence. Until those gates pass,
the existing UI adapter remains the production path.

## Findings specific to current source

- Flow CdpPage._command_once (providers/flow/cdp.py) consumes socket messages until the
  matching command ID arrives and discards unmatched messages, stopping after a bounded
  count. It is a command transport, not a durable asynchronous event collector.
  Simply enabling Network events on this socket would be unsafe: events could be lost
  and normal traffic could consume the unmatched-message limit. This is a design constraint,
  NOT proof that it caused the existing ambiguous request.
- locator_click attaches a short-lived Playwright-over-CDP connection to the dedicated
  browser. The live generation path observes composer transitions, provider-model/DOM
  evidence and candidate media. It does not contain a continuous Network event journal.
- Project binding already uses a Playwright response observer and cross-checks provider
  list data against DOM. Reuse its observation-first principle rather than adding a
  competing global provider framework.
- Dola checkout 57518aac4e0a150fa54386654ba8738a15d2a2b3 contains a direct cookie-based
  DolaClient.generate_video: HTTP/SSE -> SSE_ACK conversation_id -> polling. The deployed
  server path instead uses the browser pool/UI worker. Existence of cookie client code
  does not prove that it currently works for this user's account or desired model.
- That direct method explicitly errors when no conversation_id returns. Cookie auth
  therefore does not eliminate the accepted-but-unidentified-job problem either.

## Separate four concerns

1. Authentication: who is authorized? Cookies, access tokens or API keys.
2. Control transport: how does the command reach the page/provider? CDP, extension, HTTP.
3. Observation: what proves acceptance and which result belongs to which request?
4. Durability/recovery: what survives client/browser/process failure?

Cookie reuse changes (1), sometimes (2); it is not a solution to (3)/(4).
An API-shaped local gateway also does not automatically solve remote idempotency.

## Alternatives

| Technique | What it can improve | Remaining limitations | Recommendation |
|---|---|---|---|
| Official async API | Explicit operation identity and documented status polling | API cost/entitlement differs from web access; lost initial response still needs idempotency/lookup support | Best baseline where supported and budget-approved |
| Persistent dedicated Playwright session | Avoid repeated short attach/detach; stable listeners and page lifecycle | Browser crashes, UI changes, anti-automation challenges and provider semantics remain | Low-scope candidate experiment, not automatic root-cause fix |
| Raw CDP with real event demultiplexer | Separate command responses from continuous events, deadlines per channel | Requires correct target/session binding, reconnect and bounded queues | Reuse existing adapter; do not just enable Network on current receive loop |
| Passive network observer + durable journal | Capture actual acceptance/job/asset links before UI disappears | Must prove real provider IDs exist in responses; traffic formats may change; no retroactive evidence | Highest-priority hypothesis to test |
| Extension content script | Browser-local DOM observation independent of Python process | Isolated JS world, page changes, reloads; synthetic click need not satisfy trusted-input checks | Secondary DOM evidence, not sole authoritative receipt |
| Extension chrome.debugger + native messaging | Browser-local CDP event capture and local durable handoff | Still CDP; debugger permission is broad, detach/browser exit remain possible | Stage two only if process-disconnect losses justify packaging/security cost |
| webRequest or DevTools network/HAR | Request metadata, diagnostics; DevTools can return response content | webRequest alone is not a response-body reader; DevTools collection depends on its lifecycle | Useful diagnostic tools, not alone a production receipt ledger |
| Page-world fetch/XHR hook | Observe selected frontend calls near source | Misses earlier calls/other workers; injection order/CSP/site changes; page can spoof messages | Diagnostic fallback; never grant provider acceptance based solely on page messages |
| Direct HTTP + session cookies | Remove many DOM/control steps, observe response directly | Expiry, CSRF/device/session context, private protocol changes, challenges, secret exposure | Technically possible; unqualified for Dola under current Decision 0006 |
| TLS-intercepting proxy | Independent view of HTTP payloads across app processes | Trusted CA/HTTPS interception changes security, network compatibility and sensitive-data scope | Not the first production design; no certificate installation proposed |
| Packet capture without TLS decryption | Diagnose DNS/TCP/TLS resets, latency, loss | Cannot normally read encrypted job IDs or repair attribution | Narrow transport diagnostics only |
| Persistent local broker/worker + durable outbox | Survive UI/client restarts, serialize execution, replay observations | Cannot guarantee exactly-once remote effects without remote idempotency; adds process ownership | Start with existing provider boundary/journal; separate process only with evidence |
| Human-assisted acceptance/import | Resolve cases with evidence visible only to operator | Human latency; must record actual review/source mapping, not fabricated acceptance | Keep explicit fallback |

## Proposed first experiment

Hypothesis: capture of real provider acceptance and asset identity, persisted independently
of transient UI control, reduces avoidable ambiguity more than changing providers.

Do not write a new pipeline. Add a versioned observer seam under the existing Flow adapter
only after implementation approval. First prove its data contract with fixtures and one
explicitly scoped observation session. No private endpoint replay, response rewriting,
CAPTCHA solving, quota unlock, cookie export or automatic fallback.

Before any submission: persist request intent/prompt hash/reference hashes + project,
session and adapter identity; arm observer and obtain readiness acknowledgement.
Record DISPATCH_INTENT before the actuator. The unavoidable gap between this write and
actual input must remain uncertain on crash, not treated as proof of non-dispatch.
Observe the actual page's normal request/response, parse allowlisted identifiers only,
and distinguish browser network request ID from provider job/operation ID.
Bind acceptance using exact causal response/request, provider project and reference/prompt
identity where available. A timestamp/newest card alone is insufficient. Parallel requests,
batches, workers, unrelated user actions and page reloads must not cross-bind assets.

Persist each state transition atomically into existing request-attempt evidence. The journal
needs sequence numbers, deduplication and acknowledgements. Durable replay covers only
observations already committed; it cannot recreate a response never observed.

After disconnect: reconnect for read-only reconciliation of known identity; never click
Generate solely because acknowledgement was lost. Accepted/pending job resumes polling;
completed job resumes acquisition; unknown acceptance remains needs attention.
HTTP 200 or successful click is not sufficient provider-acceptance proof.

## Extension option if experiment justifies it

Use browser-local observation plus chrome.runtime native messaging to a narrowly scoped
local host, rather than exposing a general network control service. Allowlist extension ID,
exact domain/tab/project, schema and command set. Debugger permission remains broad at
browser level even with application allowlists; obtain explicit installation/access approval.
Cookies and auth headers stay in browser; remove tokens, signed URLs and unrelated payloads
before any durable evidence write. No general shell/URL proxy command on the native host.
Use bounded chrome.storage/IndexedDB buffering and a disk-backed host journal, replay with
deduplication after host restart. Never claim service worker or browser is immortal.
For SSE or WebSocket transports use compatible event/stream handling; waiting for an
end-of-response body is not sufficient for an indefinitely open stream.

## Acceptance matrix and stop gate

Offline fault cases: interleaved CDP response/events; event backlog; unrelated/batched jobs;
disconnect before submit; disconnect after input before receipt; receipt before disk ack;
restart after durable receipt; browser/tab crash; expired session; changed response schema;
duplicate observation delivery; late result; download interruption; incorrect media metadata.
Expected: zero false result attribution, zero blind second submission, truthful unknown
states, and same provider-job identity on recovery. Passing fixtures is engineering evidence.

Live canary only under an explicit small scope, with pre/post provider counts and exact
artifact hashes. Measure observer coverage, attribution success, reconnect recovery, number
of extra submissions and operator interventions. A small successful sample is not proof of
production reliability; record sample size and remaining uncertainty.

Do not migrate to an extension if no stable provider identity can be observed. If neither
provider history nor receipts support unambiguous reconciliation, choose official API or
explicit manual recovery; no architecture can manufacture missing server-side evidence.

## Decision boundaries

Recommend: passive observer + durable receipt evidence first, inside existing Flow boundary;
extension second only if independently surviving the Python worker is demonstrably needed.
Official API is an alternative budget decision, not a silent fallback. Dola cookie access
is technically investigable, but implementing it requires revisiting Decision 0006 and
qualifying access/security/credit semantics. This research does not change that decision.
Historical ambiguous request remains preserved; future recording cannot retroactively prove it.

## Primary sources consulted

- https://playwright.dev/docs/api/class-browsertype — connectOverCDP fidelity warning.
- https://playwright.dev/docs/auth — session-state reuse and secret handling.
- https://developer.chrome.com/docs/extensions/reference/api/debugger — alternate CDP transport.
- https://chromedevtools.github.io/devtools-protocol/tot/Network/ — network events/body/stream APIs.
- https://developer.chrome.com/docs/extensions/reference/api/webRequest — observation scope.
- https://developer.chrome.com/docs/extensions/reference/api/devtools/network — HAR/content lifecycle.
- https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts — isolated worlds.
- https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle — lifetime limits.
- https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging — local host and allowlists.
- https://docs.mitmproxy.org/stable/concepts/how-mitmproxy-works/ — HTTPS interception/trust model.
- https://ai.google.dev/gemini-api/docs/veo — operation polling for official video generation.
- https://ai.google.dev/gemini-api/docs/pricing — API pricing separate from web usage assumptions.
- https://github.com/coll3879xx-cyber/dola-render-gateway/blob/57518aac4e0a150fa54386654ba8738a15d2a2b3/dola_client.py — cookie HTTP/SSE path.
