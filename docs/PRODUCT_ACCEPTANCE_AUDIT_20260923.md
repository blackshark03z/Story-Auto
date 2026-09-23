# Product acceptance audit — 2026-09-23

Status: **NOT PRODUCT_ACCEPTED**. This is the exact current local candidate,
not a merge, tag, push, default production activation, or legal clearance.
This whole-product status does **not** revoke acceptance of the existing Flow
final: that exact MP4 is technically complete and Owner quality-accepted.

## Identity and boundaries

- Candidate branch `codex/product-acceptance-candidate`; latest tested code
  baseline `3759fa2f92c353900543e5bc8467433a0aa1ab14`, tree
  `feeb9f0e696a0de42c6ef9c8201e7d1348d86f36`. Working tree was clean
  before this audit-only update; its commit changes documentation only.
- Source `main` remains HEAD `5464cbb1d1c11a550b5e096647b9f94587de5bfe`.
  A fresh release preflight found 92 dirty/untracked entries, including six
  untracked temporary directories; 86 of 87 candidate-changed paths overlap
  source dirt. Byte comparison found 78 identical files, 8 files differing
  between source and candidate, and this audit file absent from source.
  These are current-state observations, not permission to overwrite any path.
  Do not merge, reset, clean, or stage source without an exact
  Owner-authorized promotion scope and file-by-file reconciliation.
- The earlier UI snapshot on `127.0.0.1:8778` ran in process 19580. The
  candidate UI was restarted after the Dola safety gate, preserving the Flow
  RPC gate for the same bound Google project. Runtime check reports process
  15548, Flow generation gate true, Dola generation gate false, and the
  accepted final hash unchanged.
  Process IDs are observation evidence, not durable release identity.

## Gate-by-gate result

| Gate | Evidence | Classification |
| --- | --- | --- |
| Current Flow final media | `evidence/flow-real-product-journey-20260921/projects/prj_flow_real_product/output/final.mp4` SHA-256 `de1679ad0307e13ad8fd5a240b62af3dbb39d654a17a6a1b9559c44852acd132` equals `final_manifest.json`; fresh ffprobe H264/AAC 1280x720, 39.583333 s, 22,131,107 bytes; full ffmpeg decode exit 0 | PASS |
| Current served project | After the latest 8778 restart, production query `pipeline_status=COMPLETE`, `final_output.present=true`, Flow gate true, Dola gate false; accepted final file SHA-256 still matches. Earlier asset range probe returned 206 video/mp4, bytes 0-1023/22131107 | PASS at current runtime check; range evidence from prior checkpoint |
| Owner visual acceptance | Owner explicitly accepted that exact final MP4 on 2026-09-23, with Opening/body traveler continuity note disclosed | PASS for that MP4 only |
| Code validation | Latest full suite 938/938 PASS in 321.585 s; focused provider/registry 42/42 PASS; quality/security and JS syntax PASS. Safe response diagnostics and unverified-session submission guard regression-tested. Rendered 1440/576px Opening Builder and Settings reviewed; see `docs/DOLA_UNVERIFIED_UX_REVIEW_20260923.md` | Engineering PASS for current code; live Dola pending |
| Browser playback | Supported Chrome inline playback and seek PASS; Codex IAB inline Play still crashes, while direct media view works | PARTIAL; IAB limitation disclosed |
| Flow closed-Chrome canary | `evidence/flow-cookie-closed-chrome-canary-20260923/result.json`: one upload, one submit, no exact output. A 2026-09-23 recovery-only re-entry preserved counters 1/1 and still found no asset; the independent current named-cookie read returned `FLOW_COOKIE_SESSION_UNAVAILABLE`, so this latest recovery is inconclusive, not proof of absence | AMBIGUOUS; no retry |
| Dola account/live canaries | One encrypted account saved. Old attempt `ba87f1eb...` remains ambiguous. Owner-approved separate canary `9a849c09...` observed HTTP 200 but no parseable SSE receipt; one submit, no task ID/asset. Fresh positive/negative control showed login-required UI in both contexts, withdrawing the earlier HTTP-200 auth claim. Owner reports no job/credit deduction. Product UI and server now block fresh Dola submission until verification; confirmed receipt can still be polled. See `evidence/dola-cookie-approved-canary-20260923/POST_DISPATCH.md` | AMBIGUOUS; auth NOT PASS; no retry |
| Dola provider permission | Owner reports direct Dola confirmation that cookie integration is allowed; no written scope is recorded here. Owner explicitly approved one separate new canary after the unresolved-effect warning | OWNER-ATTESTED; production scope unverified |
| Release promotion | Source has 92 dirty/untracked entries and 86/87 candidate-path overlap at the previous preflight. Dola cookie path remains chosen; no exact Owner authorization to promote this new candidate | PENDING OWNER DECISION |

## Next decision and allowed work

The real Flow final and its quality are accepted, but that does not accept the
whole product or unresolved provider attempts. The Owner chose Dola cookie
integration and authorized exactly one new, separate canary after the risk was
disclosed. That canary has now stopped at HTTP 200 without receipt and is
AMBIGUOUS. Preserve both Dola attempts and the Flow ambiguous journal; do not
retry, rotate accounts, or submit a replacement. Production promotion remains
on HOLD pending live result identity, quality, scope, and exact release approval.
The scoped 8778 candidate can be reviewed without altering source main. The
next safe technical gate is Owner login to a dedicated Dola profile, followed
by read-only auth and restart controls; no new generation is implied. An
unsent, secret-free vendor inquiry remains in
`docs/DOLA_INTEGRATION_AUTHORIZATION_REQUEST.md` for clarifying written scope;
the Owner's direct-confirmation report is a separate attestation.

Flow credential refresh is **not required** to accept or view the completed
Flow final. It is relevant only to a future generation or a separately scoped
reliability/recovery qualification. The closed-Chrome canary is a different
attempt; its ambiguity does not change the completed project's result. The saved
`flow-product-20260923` revision 1 currently fails a read-only project check;
the dedicated Chrome profile is not listening on port 9333. Do not silently
rewrite revision 1 because the unresolved attempt is pinned to it. If the
Owner later chooses to refresh that exact profile for future work, use a new
alias or explicitly reviewed same-owner recovery design before any journal
recovery; no new generation is implied by a refresh.

Canonical context: `TASK.md`, `docs/COOKIE_FLOW_PRODUCT_ACCEPTANCE_PLAN.md`,
`docs/FLOW_RPC_OPERATIONS.md`, and the cited evidence files. Current Dola Terms:
`https://www.dola.com/legal/terms/en`.
