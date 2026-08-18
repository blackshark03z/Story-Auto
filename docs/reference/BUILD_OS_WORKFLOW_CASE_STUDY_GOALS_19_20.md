# Build OS and workflow case study — Goals 19–20

Status: `CAPTURED_FOR_FUTURE_BUILD_OS_UPGRADE`

This is a project-local field record. It does not modify or override Build OS.
The canonical executor remains the external package declared by
`.buildos-authority.json`. Product/runtime truth remains in the Story Auto
artifacts and the immutable `.buildos` generation/evidence chain.

`unpersisted_os_findings=0`

## Evidence index

- Goal 19 source base: `53f15f27fdb114d221ad91d9df199cd60b942cc7`.
- Goal 19 final source anchor: `2a009c2329005b9f667805bbeff65af9aec8fa41`.
- Goal 19 terminal lifecycle evidence: Build OS generation 172, phase `ABORTED`,
  lease `RELEASED`, with the Trial A production block preserved in
  `abort_reason`.
- Goal 19 external review:
  `.buildos/evidence/STORY-AUTO-GOAL-19-TRIAL-A-RECOVERY-AND-PRODUCTION-CLOSEOUT/r003/external-techlead-review-2a009c2329005b9f667805bbeff65af9aec8fa41.json`.
- Goal 19 validation and executable rollback proof:
  `.buildos/evidence/STORY-AUTO-GOAL-19-TRIAL-A-RECOVERY-AND-PRODUCTION-CLOSEOUT/r003/validation-775f8732d08f0cbe37e9c043.json`.
- Canonical package authority: `.buildos-authority.json`; Build OS package
  `D:\Youtube\_packages\build-os-v1.22-lifecycle-v1.1.2`, kernel commit
  `e41ca10826b32b2d46a3b859345f734c113e00ae`.
- Goal 20 source base: `2a009c2329005b9f667805bbeff65af9aec8fa41`;
  lifecycle task `STORY-AUTO-GOAL-20-FLOW-EVIDENCE-AND-UNRESOLVED-REPLAY`.
- Trial A blocker: project `prj_4f895eb1436c42c4ba5b908381b14fd1`, request
  `req_8842b45b5666c9677562`, one attempt, `AMBIGUOUS /
  OUTPUT_ATTRIBUTION_UNCERTAIN`, no `selected_asset`.

## Case 1 — R3 correctly rejected worker self-review

- Origin: Story Auto Goal 19.
- Classification: `BUILD_OS`.
- Verified symptom: the sole implementation worker could not satisfy the R3
  independent-review gate; the lifecycle recorded
  `BLOCK_OFFLINE_VALIDATION` until external review evidence existed.
- Evidence: Goal 19 generations 168–171 and the r003 external-review/validation
  files in the evidence index.
- Root cause status: verified; R3 policy requires a reviewer distinct from the
  Worker.
- Control that worked: validation failed closed and preserved source/runtime.
- Gap: the recovery path and expected external-review artifact were not
  discoverable enough from the generated next action.
- Reusable recommendation: generate a concrete R3 review packet template and
  command at `PRODUCT_COMMITTED` when independent review is missing.
- Severity/priority: `HIGH / P1`.
- Status: `CONTROL_WORKED_DISCOVERABILITY_GAP`.

## Case 2 — `THREAD: NEW` is not a new Build OS principal

- Origin: Goals 19–20 handoff.
- Classification: `WORKFLOW`.
- Verified symptom: starting a new Codex task/thread did not itself create a
  distinct attested Build OS worker or reviewer principal; lifecycle identity
  remained the explicit `worker_id` in canonical state.
- Evidence: Goal 20 bootstrap generation 173 records worker
  `CODEX-GPT-5.6-TERRA-HIGH`; thread wording is absent from kernel identity.
- Root cause status: verified; UI/thread lifecycle and Build OS worker identity
  are separate namespaces.
- Control that worked: R3 reviewer independence used lifecycle fields rather
  than the phrase `THREAD: NEW`.
- Gap: operator terminology can imply an identity boundary that does not exist.
- Reusable recommendation: display `thread identity`, `worker principal`, and
  `reviewer principal` as separate fields in R3 guidance.
- Severity/priority: `HIGH / P1`.
- Status: `DOCUMENTED`.

## Case 3 — reviewer fields are opaque, not attested

- Origin: Goal 19 R3 validation.
- Classification: `BUILD_OS`.
- Verified symptom: `reviewer` and review `reference` are stored and compared as
  strings; the accepted external review names `STORY-AUTO-TECHLEAD`, but the
  kernel does not cryptographically attest that identity.
- Evidence: r003 external-review JSON and validation JSON; Build OS validation
  accepts the supplied reviewer/reference fields.
- Root cause status: verified architectural limit, not an incident claim.
- Control that worked: non-empty, distinct reviewer metadata prevented ordinary
  self-review.
- Gap: a worker able to author arbitrary evidence can also author opaque identity
  strings unless the workflow supplies external custody.
- Reusable recommendation: optionally bind R3 review to an externally produced
  signed receipt, connector identity, or owner-attested review artifact hash.
- Severity/priority: `HIGH / P1`.
- Status: `OPEN_BUILD_OS_RECOMMENDATION`.

## Case 4 — external Tech Lead review is the working R3 pattern

- Origin: Goal 19 revisions 2–3.
- Classification: `WORKFLOW`.
- Verified symptom: independent review found safety defects, the Worker produced
  corrective commits, and a later Tech Lead review approved exact commit
  `2a009c2329005b9f667805bbeff65af9aec8fa41` before canonical validation.
- Evidence: Goal 19 revision reasons in generations 168 and 170, the commit
  history, and the r003 review file.
- Root cause status: verified.
- Control that worked: exact-commit review plus fresh validation prevented an
  earlier candidate from being treated as final.
- Gap: review packet assembly was manual and terminology varied across handoffs.
- Reusable recommendation: standardize an exact-commit R3 packet containing
  base/head, full diff, complete critical functions, focused tests, rollback
  command, and runtime/provider-call counters.
- Severity/priority: `HIGH / P1`.
- Status: `PROVEN_PATTERN`.

## Case 5 — canonical package/hash audit resolved stale-OS suspicion

- Origin: Goal 19 lifecycle diagnosis.
- Classification: `BUILD_OS`.
- Verified symptom: project-local archived Build OS copies existed, but the
  authority record resolved exactly one external executor and its SHA-256,
  package root, kernel commit, and lifecycle-kit version.
- Evidence: `.buildos-authority.json`, `PACKAGE_MANIFEST.json`,
  `PACKAGE_CONTENTS.sha256`, and `PACKAGE_VALIDATION.json` in the canonical
  package.
- Root cause status: verified; the suspected stale executor was not canonical.
- Control that worked: `SINGLE_ACTIVE_EXECUTION_AUTHORITY` failed closed against
  project-local fallback.
- Gap: the authoritative package identity was not surfaced prominently in normal
  task handoff language.
- Reusable recommendation: include resolved package root, executor hash, kernel
  commit, lifecycle version, and authority verdict in every R3 start/status
  packet.
- Severity/priority: `MEDIUM / P2`.
- Status: `RESOLVED_CONTROL_WORKED`.

## Case 6 — `rollback_check` must be executable

- Origin: Goal 19 R3 validation.
- Classification: `BUILD_OS`.
- Verified symptom: prose describing rollback was insufficient; validation used
  a distinct command that checked Git ancestry/cleanliness, protected runtime
  paths and hashes, request states, attempt counts, and absence of replacement
  metadata.
- Evidence: r003 validation JSON `rollback_check.command` and
  `ROLLBACK_CHECK=PASS` output.
- Root cause status: verified.
- Control that worked: executable evidence was captured separately from ordinary
  acceptance checks.
- Gap: constructing the command was cumbersome and easy to confuse with a prose
  recovery plan.
- Reusable recommendation: provide project templates for executable rollback
  assertions and label prose only as `rollback_plan`, never `rollback_check`.
- Severity/priority: `HIGH / P1`.
- Status: `PROVEN_PATTERN`.

## Case 7 — Token Router/Qwen route discovery was not self-evident

- Origin: Goal 19 review workflow handoff.
- Classification: `WORKFLOW`.
- Verified symptom: the intended Token Router/Qwen review route was not
  discoverable from the project knowledge pack or generated Build OS next
  action and required out-of-band handoff context.
- Evidence: the Goal 19/20 owner handoff records this discovery failure; no
  Story Auto or canonical Build OS document names that route.
- Root cause status: hypothesis supported by the documentation absence; the
  router implementation itself was not audited in these goals.
- Control that worked: work stopped instead of fabricating an independent
  reviewer.
- Gap: route name, availability, and invocation ownership were undocumented.
- Reusable recommendation: R3 packets should list available independent-review
  routes or explicitly state `EXTERNAL_REVIEW_ROUTE_UNDISCOVERABLE` without
  weakening independence.
- Severity/priority: `MEDIUM / P2`.
- Status: `OPEN_WORKFLOW_RECOMMENDATION`.

## Case 8 — handoff terms conflated different authorities

- Origin: Goals 17–20 continuity.
- Classification: `WORKFLOW`.
- Verified symptom: handoffs used Goal 17/Goal 18 labels inconsistently, mixed a
  planned queue with the manifest entries actually touched, used “safe to
  resume” as if it meant safe to click Generate, and blurred request, attempt,
  activation, and output ownership.
- Evidence: `PROJECT_STATUS.md` and `OPERATIONS.md` previously named older Trial
  A barriers while live evidence advanced to `req_8842b45b5666c9677562`; Goal
  20’s mandatory case inventory calls out the four distinctions.
- Root cause status: verified documentation drift; no evidence supports treating
  the terms as synonyms.
- Control that worked: request-ID queue barriers and attempt-level provenance
  prevented terminology from authorizing a provider call.
- Gap: handoff prose lacked a compact glossary and “resume” safety level.
- Reusable recommendation: every production handoff should state Goal/source
  anchor, planned requests, manifest-touched requests, current barrier request,
  attempt count, activation proof, attribution proof, and one of
  `READ_ONLY_RESUME`, `RECONCILIATION_ONLY`, or `GENERATION_ALLOWED`.
- Severity/priority: `HIGH / P1`.
- Status: `DOCUMENTED_PROJECT_DOCS_UPDATED`.

## Case 9 — R3 positive control found real product defects

- Origin: Goal 19 revisions 1–3.
- Classification: `BOTH`.
- Verified symptom: independent review found real queue/recovery defects,
  including transaction publication/recovery, canonical classification,
  target-path validation, and stale request selection; corrective commits
  `88c7e426e03d0753eca3c40cb27bd6a336dbcc20` and
  `2a009c2329005b9f667805bbeff65af9aec8fa41` followed.
- Evidence: Goal 19 revision reasons in immutable lifecycle generations, commit
  diffs, and `tests/test_goal19_legacy_supersession.py`.
- Root cause status: verified product defects plus a workflow control that found
  them.
- Control that worked: independent review was not ceremonial; it changed the
  implementation and expanded fault-injection coverage.
- Gap: Build OS records approval metadata but not a structured taxonomy of
  findings-to-corrective-commit closure.
- Reusable recommendation: add an optional R3 finding ledger binding finding ID,
  severity, affected commit, corrective commit, test, and disposition.
- Severity/priority: `CRITICAL / P0`.
- Status: `PRODUCT_FIXED_OS_UPGRADE_RECOMMENDED`.

## Case 10 — fresh attribution polls were overwritten

- Origin: Goal 20, discovered from Goal 19 Trial A request
  `req_8842b45b5666c9677562`.
- Classification: `PRODUCT`.
- Verified symptom: the final attempt retained only the last values for
  attribution state, lineage card, candidates, and stable-poll count. An earlier
  transient `new_attributable_job_state` set `dispatch_confirmed=true`, but the
  final record had no `provider_job_id` or lineage card, reducing forensic
  certainty.
- Evidence: preserved Trial A `generation_manifest.json` at Goal 20 Phase A and
  the Goal 19 source implementation of `LiveFlowGenerator._record_observation`
  and `DispatchEvidenceTracker`.
- Root cause status: verified; each poll called `dict.update`, overwriting the
  preceding decision evidence, and a boolean job signal could confirm dispatch.
- Control that worked: output attribution remained separate and failed closed;
  no arbitrary candidate became `selected_asset`.
- Gap: no bounded immutable poll timeline or durable dispatch-identity rule.
- Reusable recommendation: persist a bounded, hash-chained, URL-free observation
  timeline per poll; distinguish `SIGNAL_OBSERVED` from `DISPATCH_CONFIRMED` and
  require serialized stable identity for job/card confirmation.
- Severity/priority: `CRITICAL / P0`.
- Status: `GOAL20_CANDIDATE_IMPLEMENTED_AWAITING_EXTERNAL_R3`.

## Case 11 — the fail-closed queue prevented a blind retry

- Origin: Goals 17, 19, and 20 Trial A.
- Classification: `PRODUCT`.
- Verified symptom: after request `req_8842b45b5666c9677562` became unresolved,
  the five later planned requests had no manifest entries/provider attempts.
- Evidence: Goal 20 Phase A read-only manifest inspection: one target attempt,
  `selected_asset` absent, one quarantined foreign identity, and later requests
  untouched; focused Goal 17/19/20 queue tests.
- Root cause status: verified positive control.
- Control that worked: the earliest unresolved request remained a project-wide
  barrier, so no blind retry and no later activation occurred.
- Gap: operators still need a separately authorized, cost-acknowledged recovery
  for irreducible fresh uncertainty.
- Reusable recommendation: preserve the barrier and add only a manual
  PREPARED/COMMITTED fresh-epoch replay that keeps historical truth unresolved,
  performs zero provider calls, and requires explicit possible-cost ownership
  acknowledgements.
- Severity/priority: `CRITICAL / P0`.
- Status: `CONTROL_WORKED_GOAL20_RECOVERY_CANDIDATE_ADDED`.

## Upgrade backlog summary

1. `P0`: retain R3 positive-control independence and add structured
   finding-to-fix closure.
2. `P1`: clarify thread/worker/reviewer identity and offer an attested reviewer
   receipt path.
3. `P1`: generate exact-commit R3 packets and executable rollback templates.
4. `P1`: standardize production handoff glossary and resume safety levels.
5. `P2`: expose canonical package identity in normal status and document
   independent-review route discovery.

