# Cookie Flow product acceptance delivery

## Current execution plan — 2026-09-23

This is the active plan; older checkpoints below are provenance. Work in the
isolated `codex/product-acceptance-candidate` clone/branch, preserving the dirty
source checkout. The accepted Flow final is a product asset, while the
separate unresolved Flow canary and three Dola direct-cookie attempts retain
their own ambiguous histories. No cross-provider replacement or blind retry.
The candidate is a separate Git clone whose `origin` points to the dirty
source checkout; it is not registered as one of that checkout's worktrees.
Promotion therefore needs an explicit path/scope reconciliation rather than
assuming a worktree branch is already available in source main.

| Milestone | Current proof | Remaining gate |
| --- | --- | --- |
| Dola browser transport engineering | One external Gemini UI success; Story Auto opt-in Patchright adapter, durable native ID, exact read/poll linkage; focused tests and quality/security pass | Final exact-head full suite and one-shot browser runner review |
| Browser pre-submit stability | Same encrypted alias in a dedicated Patchright profile; three closed/reopened 10s/5s/10s UI preflights PASS with zero sends after hydration fix | No proof yet of Story Auto's actual generation request/receipt |
| Bounded live qualification | Separate canary project prepared; no attempt, task ID, or submission; unacknowledged dispatch refused | Fresh Owner authorization for exactly one potentially charged request, then exact request/receipt/output reconciliation; stop if ambiguous |
| Product integration | Canonical opening manifest, media import and Flow final already exist | Feature-gated operator route and rendered UI journey after live transport qualifies; keep Dola disabled until then |
| Release and acceptance | Flow final accepted by Owner; isolated candidate is not source main | Exact candidate/runtime identity, clean promotion scope, full composed CUJ, explicit Owner product acceptance |

Main agent is the only writer. Use independent read-only review on consequential
changes and only the existing free/approved service allowance. A successful
preflight never authorizes a generation. Any live ambiguity stops new sends.

Status: ACTIVE, not product accepted. Source baseline HEAD 5464cbb with substantial
pre-existing uncommitted Flow/Dola/UI work; preserve all owner work. 2026-09-23.

Current Dola choice: the Owner reports Dola directly confirmed permission for
cookie integration; no written scope is stored here. After disclosure that the
earlier ambiguous attempt might have had an effect or used a credit, the Owner
approved **one separate new canary request**. This is bounded experimental
authorization, not proof of provider output, billing, or product acceptance.
Finish safe HTTP-status journaling and a read-only session check first. Preserve
the old attempt; no retry or account rotation.

Historical permission hold: official terms at `https://www.dola.com/legal/terms/en`
(last updated 2026-09-04) restrict automated use, reverse engineering,
incorporation into another product and automated output extraction. The
candidate's private-endpoint design was not a supportable production assumption
without provider permission or an official API; this was a risk classification,
not legal advice. The newer Owner attestation above supersedes the previous
blanket request hold only for the specifically authorized canary, not for
production promotion. Preserve the ambiguous O1 record below.

2026-09-23 live Dola O1 result: Owner saved `dola-main` (one configured account)
and one bounded canary call recorded attempt
`ba87f1eb43ea4c018491cd80d3d45d7a`, submit_attempts=1,
provider_submissions=0, status/dispatch_state=AMBIGUOUS, no provider task ID.
Neither a replay nor a replacement is authorized. Read-only endpoint/browser
checks did not establish whether the original POST had an external effect.
Reconcile first; Dola live qualification and whole-product acceptance remain
PENDING. This newer checkpoint supersedes the pre-canary account_count=0 below.

Current Dola gate: a signed-in Owner export has exact `sessionid_ss` but no
`sessionid`. Read-only browser positive/negative controls proved it authenticates
the Dola UI on www, not that the private video API accepts it. The isolated
candidate now accepts and forwards either exact cookie name, with encrypted
named save and no provider retry. Synthetic Settings preview passed at 576px
and 1440px. This pre-canary qualification is superseded by the one saved account
and ambiguous live canary above. Dola and whole-product acceptance remain
PENDING. Do not reuse an ambiguous Flow attempt to bridge this gap.

## Latest acceptance checkpoint (2026-09-23)

Real project `prj_flow_real_product` is `FINAL_VIDEO_COMPLETE`: three distinct
Flow Opening clips, three Flow body images, canonical stock fallback, and a
39.58-second H264/AAC final video. Manifest hash and full decode PASS. Home
card shows Complete/100% and the result action is reachable in rendered UI.
The asset route streams single HTTP byte ranges (206; invalid 416). Chrome
independently played the real inline preview and sought to 35 seconds without
media/page errors; evidence is `product-acceptance-audit-20260923.json` and
`chrome-final-preview-20260923.png` under the real-product evidence directory.
The Codex in-app browser still crashes on inline Play, while its direct media
view displayed first/final frames; do not classify that preview path as fixed.
Five focused UI/range and Hybrid CUJ tests PASS after the asset change. No
additional provider generation in this checkpoint.

Owner explicitly accepted the exact current final video's quality on
2026-09-23 (brief Opening/body traveler continuity difference was disclosed).
Accepted MP4 SHA-256 is
`de1679ad0307e13ad8fd5a240b62af3dbb39d654a17a6a1b9559c44852acd132`.
This is not whole-product acceptance. Tracked-source security gate and a
separate scan of64 untracked text files passed with no secret-pattern findings.
Remaining gates include live Dola
qualification if Dola is to be accepted as part of the product, and a
traceable release candidate identity/promotion decision.
One Dola account is now configured, but the sole live canary is ambiguous and
does not prove Dola video generation. The accepted Flow final needs no cookie
refresh or new login; later cookie expiry only affects future generation or a
separately scoped reliability/recovery check.
Fresh 2026-09-23 initial read-only reuse check returned
`FLOW_COOKIE_SESSION_UNAVAILABLE` for saved `flow-product-20260922` revision 1.
Owner signed in on the existing dedicated profile. The new automatic export
passed a fresh 13-record catalog read and was saved as a separate encrypted
alias `flow-product-20260923` revision 1. The application service then
READ_VERIFIED this named account with zero uploads/generations. A scoped 8775
UI candidate now runs with the experimental gate enabled only for the exact
bound project; HTTP200 and Settings exposes the new alias. Existing attempts
are unchanged. Full local unittest discovery passed 923/923. Source-Chrome-
close and repeated-use survival remain unverified; do not generalize from
one successful fresh read or label this default production promotion.
The separate historical ambiguous Flow attempt remains untouched; no retry
or attribution transfer is authorized. Product acceptance stays PENDING.

## Outcome and boundaries

Deliver the supported Story Auto production journey with cookie-seeded Flow,
including reference-video generation, durable result attribution/recovery, final
composition and owner-visible quality review. Existing Dola work remains in scope
of overall delivery, but its live qualification requires a valid configured account.
Do not label tests or authentication alone product acceptance. No new paid service,
no automatic top-up, no blind retries or rotation after uncertain submission.

## Milestones and proof

1. Session qualification: cookie seed into fresh headless browser, negative
   control, restart/reuse and account/project checks. Current evidence proves
   2/2 isolated browser auth reads with a 28-cookie export, negative control /about.
   Source-browser-close and long-duration survival remain unverified.
2. Current surface contract: map actual editor and result lineage before writes;
   do not assume WIZ metadata or historical RPC still applies. Read-only planner
   owns integration design; main agent owns probes and implementation.
3. Bounded live video canary: single output, one submit; reference attachment
   verified when exercised. Persist intent before action and exact result identity
   before acquisition. Stop/reconcile uncertainty, never create replacement jobs.
4. Canonical integration: reuse generation manifest, provider safety, normalization,
   QC and renderer. Opt-in cookie session boundary; preserve existing routing until
   composed evidence qualifies it. Regression tests for auth expiry and recovery.
5. Product journey: supported UI setup -> create/resume -> quality -> current final
   video with traceable inputs. Rendered UI and media evidence, no secret exposure.
6. Acceptance audit: exact candidate identity, targeted/full tests, independent
   review proportional to risk, unresolved jobs reconciled, explicit owner quality
   acceptance where subjective. Only then mark PRODUCT_ACCEPTED.

## Cost and coordination

One main writer; one bounded read-only architectural planner for the session /
transport mismatch. No parallel provider dispatch. Reuse existing assets and runs;
only add live requests needed to close an acceptance gap. No fixed claim of
unlimited/free provider operation. Surface actual quota/error signals and stop
when the already-approved allowance is exhausted.

## Current checkpoint

Latest refresh supersedes the failed revision1 read below: Owner-approved
flow-owner revision2 saved using direct dedicated-profile extraction. Fresh
process Settings service read verified project a94d36d0-5f95-420d-97b4-dc7cf0c87453,
zero media, zero generations. Evidence: flow-owner-refresh-20260920T224400Z.json
under D:\Story Auto\evidence. Save approval resolved; next is bounded composed
product journey, not repeated auth probes. Source-Chrome-close survival unverified.

Latest 2026-09-21: Owner approved actual `flow-owner` save and read-only check.
DPAPI revision1 saved, fresh-process decrypt verified. Live authentication failed:
owned browser reached HTTP200 /about instead of the exact project, with no session
token or enterprise captcha metadata. Zero generations. Saved is not verified;
need refreshed authenticated cookie export/login before the live product journey.
Safe evidence: `D:\Story Auto\evidence\cookie-settings-live-20260921`.
The older successful canaries below remain historical, not current authentication.

Last completed turn was PROGRESS: fresh-cookie auth reproduced and a false
universal-at-field assumption disproved. Evidence:
`D:\Story Auto\evidence\FLOW_COOKIE_AUTH_CHECKPOINT_20260921.md`.
Current progress: plain Playwright (unlike Patchright's evaluate context) sees the
qualified WIZ metadata; fresh cookie plain browser passed RPC metadata and read.
Added experimental CookieBrowserRpcSession session factory, no production routing
change. New cookie/session tests plus RPC contract/transport/service: 30 PASS.
The actual owned CookieBrowserRpcSession then passed a fresh live metadata/catalog
read without external CDP, upload or generation. Evidence:
`D:\Story Auto\evidence\flow-cookie-owned-read-20260920T185530Z.json`.
Independent review found conflicting expiry, normalized-domain duplicates and
falsey partition metadata; all three fixed with regression tests. Exact
new-project catalog envelope and the old
population-sensitive baseline gate must be resolved before any live write.
Milestones 2/3 now have bounded PASS evidence: empty/populated schema validation,
one cookie reference-video plus fresh-process hash-identical recovery, and one
canonical service video plus zero-submit idempotent resume. Final Flow tests309
PASS, focused34 PASS. See FLOW_COOKIE_VIDEO_QUALIFICATION_20260921.md for exact
source/artifact identities and remaining boundaries. No unresolved live attempt
from these two canaries; both are ACQUIRED/SUCCEEDED, one submit each.
Next: integrate encrypted named cookie account and explicit durable session-mode
identity into runtime/recovery, then supported UI setup and real product journey.
Do not reuse canary ENGINEERING_FIXTURE QC as production or owner acceptance.

### Settings checkpoint (2026-09-21)

Named DPAPI storage, same-alias expiry refresh, revision-pinned session factory,
journal identity binding, and Settings preview/save/read-only test endpoints are
implemented. Focused suite45 PASS; app.js syntax check PASS. Candidate8786
rendered empty/disabled state and actionable missing-name/file validation after
reload. An initially generic validation message was corrected without exposing
arbitrary server exceptions. No new generation or production routing change.
Real encrypted-account UI save/check, desktop/narrow visual review, independent
review and canonical product-route selection are still outstanding.

### Integration choice: Hybrid Opening reference-video

Use the existing explicit Hybrid Opening provider boundary, not a project-wide
cookie switch: normal image/body/thumbnail routing is not yet cookie-qualified,
and Full Video remains API-routed. Add one opt-in Flow reference-video slot action
using the existing RPC journal and canonical import/normalization/composition.
Bind alias/revision, exact provider project, slot prompt/duration, durable PNG hash
and attempt UUID before effects. Generate8 seconds only for slots <=8 seconds.
Recovery reads the original attempt only; no new-account/project/ref substitution.
Canonical import must verify acquired journal identity AND output-byte hash.
This milestone does not reduce the final goal: complete product journey, remaining
provider qualification and owner acceptance remain required afterward.
