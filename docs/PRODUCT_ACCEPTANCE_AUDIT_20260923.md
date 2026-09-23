# Product acceptance audit — 2026-09-23

Status: **NOT PRODUCT_ACCEPTED**. This is the exact current local candidate,
not a merge, tag, push, default production activation, or legal clearance.
This whole-product status does **not** revoke acceptance of the existing Flow
final: that exact MP4 is technically complete and Owner quality-accepted.

## Identity and boundaries

- Candidate branch `codex/product-acceptance-candidate`; audited code/document
  baseline `f36c9060911978fba10fca1e451a334aa7edf6de`, tree
  `8600a898b83605e70f13227769a3b98051f12fd9`. Working tree was clean
  before this audit file was added; the audit commit changes documentation only.
- Source `main` remains HEAD `5464cbb1d1c11a550b5e096647b9f94587de5bfe`
  with 86 pre-existing dirty entries. Do not merge, reset, clean, or stage it
  without an exact Owner-authorized promotion scope.
- Local UI on `127.0.0.1:8778`, process 19580, imports Flow from this candidate.
  The Flow RPC gate is process-scoped to the bound Google project; not global.

## Gate-by-gate result

| Gate | Evidence | Classification |
| --- | --- | --- |
| Current Flow final media | `evidence/flow-real-product-journey-20260921/projects/prj_flow_real_product/output/final.mp4` SHA-256 `de1679ad0307e13ad8fd5a240b62af3dbb39d654a17a6a1b9559c44852acd132` equals `final_manifest.json`; fresh ffprobe H264/AAC 1280x720, 39.583333 s, 22,131,107 bytes; full ffmpeg decode exit 0 | PASS |
| Current served project | 8778 production query `pipeline_status=COMPLETE`, `final_output.present=true`, `next_action=open_final`; asset single range returns 206 video/mp4, bytes 0-1023/22131107 | PASS |
| Owner visual acceptance | Owner explicitly accepted that exact final MP4 on 2026-09-23, with Opening/body traveler continuity note disclosed | PASS for that MP4 only |
| Code validation | Full candidate suite 927/927 at code commit `5b141a8`; subsequent commits are documentation-only. Current quality and security gates PASS; JS syntax and rendered 576/1440px Dola Settings preview PASS | Engineering PASS |
| Browser playback | Supported Chrome inline playback and seek PASS; Codex IAB inline Play still crashes, while direct media view works | PARTIAL; IAB limitation disclosed |
| Flow closed-Chrome canary | `evidence/flow-cookie-closed-chrome-canary-20260923/result.json`: one upload, one submit, no exact output. A 2026-09-23 recovery-only re-entry preserved counters 1/1 and still found no asset; the independent current named-cookie read returned `FLOW_COOKIE_SESSION_UNAVAILABLE`, so this latest recovery is inconclusive, not proof of absence | AMBIGUOUS; no retry |
| Dola account/live canary | One encrypted account saved. `evidence/dola-live-qualification-20260923/canary-attempt-ba87f1eb43ea4c018491cd80d3d45d7a.json`: one submit attempt, no provider receipt or asset, external effect unknown | AMBIGUOUS; no retry |
| Dola provider permission | Official Dola Terms (2026-09-04) restrict automation, reverse engineering, incorporation and automated output extraction; no vendor-approved integration contract recorded | HOLD; risk inference, not legal ruling |
| Release promotion | Candidate is clean but source is dirty; no exact Owner authorization to promote this HEAD/tree or redefine Dola as manual-only | PENDING OWNER DECISION |

## Next decision and allowed work

The real Flow final and its quality are accepted, but that does not accept the
whole product or unresolved provider attempts. No further Dola private requests,
account rotation, or attempts to bypass service controls. Preserve both Dola and
Flow ambiguous journals. The Owner needs to decide whether Dola is manual-only
for this release or provide a vendor-authorized integration path, and separately
approve the exact release/promotion scope. Until then keep production promotion
on HOLD. The scoped 8778 candidate can be reviewed without altering source main.

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
