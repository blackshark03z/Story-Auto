# Cookie Flow product acceptance delivery

Status: ACTIVE, not product accepted. Source baseline HEAD 5464cbb with substantial
pre-existing uncommitted Flow/Dola/UI work; preserve all owner work. 2026-09-23.

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
There are zero configured Dola accounts, so do not infer a Dola live pass.
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
