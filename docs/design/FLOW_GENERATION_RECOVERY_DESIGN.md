# Flow generation recovery design

Status: FROZEN FOR TECH LEAD REVIEW — no implementation authorized.

Scope: Google Flow visual generation and its Story Auto recovery boundary. This design derives from source at c52c4bdf2d3188cacbc568af2648db8c50e503cd. It does not alter any runtime project or provider account.

## 1. Executive decision

Adopt one pure deterministic RecoveryDecision boundary between canonical generation evidence and any recovery executor. It decides from durable evidence; it must not click Flow, download media, or mutate artifacts. An executor may perform only the action explicitly authorized by the decision.

The canonical model has three independent dimensions:

1. Attempt outcome: NOT_STARTED, DISPATCHING, PROVIDER_ACTIVE, PROVIDER_SUCCEEDED, PROVIDER_FAILED, or LOCAL_FAILED.
2. Dispatch certainty: NOT_DISPATCHED, DISPATCH_CONFIRMED, DISPATCH_UNCERTAIN, or TERMINAL_CONFIRMED.
3. Recovery disposition: DISPATCH_INITIAL, RESUME_POLLING, RECONCILE_FIRST, REACQUIRE, REVALIDATE, REPOSTPROCESS, AUTO_RETRY_AFTER, PROMPT_REPAIR, OWNER_ACTION, or NO_RETRY.

Current request status is a compatibility projection during migration, not retry authority. In particular, FAILED_RETRYABLE is neither an active operation nor permission to issue a new provider request.

Frozen invariant: no new Flow activation without an explicit evidence-based safe_to_dispatch=true decision bound to the exact logical request, prompt revision, Flow connection revision, and attempt cause.

R3 authority amendment: request status never grants dispatch authority. Only a fresh RecoveryDecision with safe_to_dispatch=true may do so, and the executor must revalidate its relevant request, attempt, connection, queue, and evidence bindings immediately before it crosses the provider boundary.

## 2. Current architecture findings

providers/flow/service.py owns the generation manifest, append-only attempts, local image/video repair, serial Flow queue barrier, reconciliation, and execution. It persists provider_execution_state=NOT_STARTED, then PROVIDER_BOUNDARY_ENTERED immediately before the provider-capable call. canonical_no_dispatch_proof accepts only durable pre-boundary evidence; _provider_generation_retry_authorized permits an initial attempt or that proof.

live.py extracts cards from data-tile-id: usable media is READY, empty cards are PENDING, and the icon combination warning + refresh + delete_forever becomes FAILED / PROVIDER_VISIBLE_TERMINAL_FAILURE. attribution.py separately requires a stable pre-activation baseline and a unique request-epoch card/asset delta before selection. DispatchEvidenceTracker distinguishes observed UI activity from durably confirmed dispatch.

ProductionStateReconciler builds a compact projection, not canonical evidence. ProductionCoordinator.run_until has a 12-operation bound and stops on no meaningful state change. continue_production is currently an alias of run_to_final. The UI allows one in-flight action per tab, polls while its HTTP action is outstanding, and clears busy state on response.

### Actual current request-state machine

| Status | Current source/evidence | Dispatch may have happened? | Current new-dispatch position | Projection/UI |
| --- | --- | --- | --- | --- |
| PENDING | Initial/planned manifest entry | No | Initial attempt possible | Shown RUNNING for shots |
| GENERATING | Persisted SUBMITTED attempt and boundary marker | Possibly | Prohibited; unresolved barrier | Omitted from clear RUNNING/BLOCKED mapping |
| NOT_DISPATCHED | Proven pre-boundary interruption/reconciliation | No if canonical proof valid | Permitted only with that proof | Shown RUNNING though idle |
| AMBIGUOUS | Timeout/attribution ambiguity or fail-closed correction | Yes or unknown | Prohibited; reconcile/manual only | BLOCKED |
| FAILED_RETRYABLE | Local postprocess, invalid asset, creative rejection, stale result, or provider error | Depends | Only proof-gated; otherwise local/barrier | Shown RUNNING |
| QC_PENDING | Valid selected asset awaiting QC | Yes, successful | Prohibited; reuse/review only | VISUALS complete |
| SUCCEEDED | Accepted selected asset | Yes, successful | Prohibited; reusable | Complete |
| AUTH_REQUIRED | Flow error mapping | Not represented precisely | Prohibited pending repair/revalidation | Auth blocker |
| CREDIT_BLOCKED | Declared final status; no ordinary Flow writer found | Unknown | Prohibited pending account evidence | Provider blocker |
| FAILED_PERMANENT | Capability/project mismatch or stop-loss | May have | Prohibited except proved-pre-dispatch reopen | Blocked |
| CANCELLED | Declared final status | Unknown | Prohibited | Blocked |
| Replacement/supersession | Transactional QC/ambiguity parent history | Parent may have | Never reopen parent | Not uniformly projected |

PROVIDER_VISIBLE_TERMINAL_FAILURE is a failure class, not a request status. Its generic catch path can become FAILED_RETRYABLE, which proves neither transient failure nor redispatch authority.

## 3. Confirmed defects and gaps

1. FAILED_RETRYABLE conflates provider, acquisition, validation, postprocess, attribution, creative-QC, and operator actions.
2. Production state maps PENDING, NOT_DISPATCHED, and FAILED_RETRYABLE to VISUALS=RUNNING; it does not explicitly project GENERATING. Retryability is presented as activity.
3. FAILURE_RECOVERY_V1.md and frozen product design say maximum automatic attempts is 2; Flow code defaults flow.max_attempts to 12. R3 resolves this: 2 is the maximum automatic transient redispatch budget, while 12 is an absolute lifetime provider-attempt stop-loss. The source must be aligned in a later implementation.
4. The terminal-card parser stores no raw visible failure text, locale, terminal timestamp, complete card lineage, or provider job identity. It cannot safely classify terminal failure as transient, policy, credit, or auth.
5. The generic retry utility has no manifest safety, causal lineage, recovery budget, or UI role. It cannot be recovery authority.
6. Continue Production has a useful no-progress stop but no explicit recovery-plan/action result; it invokes a broad VISUALS operation.
7. Existing attempts have strong dispatch/attribution evidence but lack one required cause, parent attempt, policy version, prompt revision identity, and budget-consumption record.

## 4. Frozen state model

Add append-only attempt fields plus a current recovery record on each request. Existing status remains derived for old readers.

| Dimension | Required values | Authority |
| --- | --- | --- |
| attempt_outcome | NOT_STARTED, DISPATCHING, PROVIDER_ACTIVE, PROVIDER_SUCCEEDED, PROVIDER_FAILED, LOCAL_FAILED | Attempt evidence |
| dispatch_certainty | NOT_DISPATCHED, DISPATCH_CONFIRMED, DISPATCH_UNCERTAIN, TERMINAL_CONFIRMED | Pre-dispatch or hash-bound provider evidence |
| asset_state | NONE, REMOTE_IDENTIFIED, ACQUIRING, RAW_VALID, SELECTED_VALID, SELECTED_INVALID | Asset/hash/validation |
| qc_state | NOT_READY, TECHNICAL_PENDING, TECHNICAL_FAILED, CREATIVE_PENDING, CREATIVE_REJECTED, ACCEPTED | QC records |
| recovery_disposition | Section 6 action | Pure decision version |

Missing historic dimensional evidence is UNKNOWN, not inferred from a legacy status. It may be projected for reading but cannot authorize a new dispatch. Corrections append observations; history is never rewritten.

## 5. Failure taxonomy

Each classification carries family, stable detail code, evidence IDs, classifier version, confidence (CONFIRMED or UNKNOWN), and safe diagnostic text. Text never alone authorizes dispatch.

| Family | Default disposition | New provider dispatch |
| --- | --- | --- |
| PRE_DISPATCH_FAILURE | Dispatch/retry exact logical request | Only positive no-dispatch proof |
| DISPATCH_AMBIGUOUS | RECONCILE_FIRST | Prohibited |
| PROVIDER_IN_PROGRESS | RESUME_POLLING | Prohibited |
| PROVIDER_TERMINAL_TRANSIENT | AUTO_RETRY_AFTER | Bound terminal evidence and budget only |
| PROVIDER_POLICY_BLOCK | PROMPT_REPAIR | New authorized prompt revision only |
| PROVIDER_AUTH_BLOCK / PROVIDER_CREDIT_BLOCK | OWNER_ACTION | Prohibited pending repair |
| PROVIDER_RATE_LIMIT | WAIT_AND_RETRY | Bounded backoff and budget |
| PROVIDER_UI_CHANGED | OWNER_ACTION | Prohibited |
| PROVIDER_TERMINAL_UNKNOWN | OWNER_ACTION or NO_RETRY | Prohibited |
| ASSET_ACQUISITION_FAILURE | REACQUIRE | Prohibited |
| LOCAL_VALIDATION_FAILURE / LOCAL_POSTPROCESS_FAILURE | REVALIDATE / REPOSTPROCESS | Prohibited while output exists |
| QC_TECHNICAL_FAILURE | Local repair/review | No automatic generation |
| QC_CREATIVE_REJECTION | Owner-approved replacement | Never same-attempt retry |
| PROMPT_SEMANTIC_REPAIR_REQUIRED | OWNER_ACTION | Prohibited |

## 6. RecoveryDecision contract

RecoveryDecision is preferred over RetryDecision because it also handles reconciliation, local recovery, and owner/account actions. It is pure, versioned, serializable, and deterministic for identical canonical input.

| Required output | Meaning |
| --- | --- |
| action | One disposition from section 1 |
| safe_to_dispatch | True only for the exact proposed attempt |
| provider_generation_required and consumes_provider_attempt | Explicit cost boundary |
| reconciliation_required | Inspection must precede provider action |
| prompt_revision_required and owner_decision_required | Authority boundaries |
| retry_after and budget | Monotonic deadline/counter or null |
| reason_code, evidence_ids, policy_version | Reproducible explanation |
| target attempt/asset/prompt/connection IDs | Exact bound target |

Inputs are immutable request/attempt history; request and prompt lineage; connection provenance; provider observations; local asset, validation, and QC evidence; clock; and configured budgets. Incomplete, contradictory, stale-connection, or unverified input yields RECONCILE_FIRST or OWNER_ACTION, never a guess.

No model or LLM result can authorize redispatch. A decision that authorizes dispatch is valid only for its bound evidence revision; it expires when the request, prompt revision, connection revision, queue position, attempt record, or required dependency evidence changes.

## 7. Safe redispatch rules

safe_to_dispatch=true additionally requires canonical current logical request, valid dependencies, bound current prompt revision and Flow connection revision, no earlier queue barrier, and unexhausted budget.

| Case | Additional authorization |
| --- | --- |
| Proven pre-dispatch failure | Latest attempt has canonical no-dispatch proof; cause PRE_DISPATCH_RETRY |
| Confirmed transient terminal | Exact bound terminal identity, confirmed classification, resolved output ownership, and transient redispatch budget |
| Rate limit | Exact attribution plus NOT_DISPATCHED or positively terminal rejection, no ambiguity, elapsed bounded retry-after, and shared transient redispatch budget |
| Policy block | Approved/revalidated prompt revision and remediation budget |
| Creative regeneration | Explicit owner action or preapproved policy; new replacement epoch |
| Manual regenerate | Explicit owner cost acknowledgement; distinct replacement lineage |

Redispatch is categorically forbidden for unresolved ambiguity, active generation, output-acquisition failure, local postprocess/derivative failure with recoverable raw bytes, unknown terminal cause, stale connection, auth/credit blockers, and exhausted budget. FAILED_RETRYABLE alone is never a rule. A rate-limit decision additionally carries bounded wait-count, total elapsed-recovery-time, and redispatch-count limits; exhaustion is NEEDS_ATTENTION / RATE_LIMIT_BUDGET_EXHAUSTED with safe_to_dispatch=false.

## 8. Prompt remediation model

A policy recovery is a new prompt revision, not transport retry or policy evasion. Keep immutable original_prompt, effective prompt hash, remediation record, and prompt_revision_id; never edit an old attempt.

Automatic provider-only transformations are allowed only when they are deterministic and preserve a pre-approved structured semantic contract. The required slots are subject/identity, action, event, setting, time/context, relationship, emotional intent, and visual objective, together with continuity references, media type, and safety constraints. Examples can include removing unsupported non-story formatting or substituting neutral provider-supported camera wording.

Any material change to a semantic slot, required media, or continuity reference is PROMPT_SEMANTIC_REPAIR_REQUIRED and requires Owner approval. Policy text is diagnostic evidence, not sole authority: policy classification requires a positively terminal provider state, exact attempt/card attribution, and high-confidence mapping to the POLICY family. Unknown terminal reason is PROVIDER_TERMINAL_UNKNOWN with safe_to_dispatch=false and NEEDS_ATTENTION. Approval binds the exact prompt revision and becomes invalid if that prompt changes. A revised prompt gets new fingerprint plus PROMPT_REPAIR child/replacement lineage.

## 9. Retry budgets

Separate, persisted counters; proposed defaults pending approval:

| Budget | Default | Provider attempt? |
| --- | ---: | --- |
| Initial provider attempt | 1; not a retry | Yes |
| Automatic transient redispatches per logical visual request | 2; rate-limit redispatch shares this budget | Yes |
| Reconciliation polls per unresolved attempt | 6 bounded observations | No |
| Rate-limit waits | 2; bounded exponential backoff with jitter, provider retry-after wins within max wait | No |
| Automatic provider-only prompt remediation revisions per originating policy failure | 1 | Yes for the new revision |
| Local acquisition retries | 3 | No |
| Validation/postprocess retries | 3 each | No |
| Creative correction epochs | Retain existing 3, owner-governed | Yes, replacement only |
| Absolute lifetime provider attempts per logical lineage | 12; includes owner manual regeneration | Yes |

Twelve is not the automatic retry budget. It is the absolute provider-attempt lifetime stop-loss. Reconciliation/polling, acquisition/download, validation, and postprocess work consume no provider attempt. Exhaustion creates deterministic NO_RETRY / NEEDS_ATTENTION with the named exhausted budget, never an unexplained permanent state.

## 10. Attempt lineage

Every provider attempt records attempt_id, logical_visual_id, cause (INITIAL, PRE_DISPATCH_RETRY, TRANSIENT_RETRY, PROMPT_REPAIR, CREATIVE_REGENERATION, MANUAL_REGENERATE, RECOVERY_REPLAY), parent attempt where relevant, triggering decision/failure, prompt revision/hash, request fingerprint, connection provenance/revision, dispatch proof, job/card/asset identity, policy version, budget before/after, and owner authorization where required. Owner authorization persists its exact request ID and prompt revision ID.

RECOVERY_REPLAY is a distinct approved replacement, never a hidden retry. The parent remains immutable and visibly charged as potentially dispatched. Manual regeneration after prior success is append-only and must not destroy or deselect the currently valid asset until its replacement is accepted. Asset lineage binds raw bytes, derivative, selected asset, and QC records to the originating attempt.

## 11. Local recovery rules

| Durable reality | Permitted recovery | New Flow attempt |
| --- | --- | --- |
| Bound provider output; download failed | Reacquire exact provider asset and validate | No |
| Raw bytes valid; postprocess failed | Re-run postprocess and append local record | No |
| Selected derivative corrupt; raw valid | Invalidate derivative, regenerate from raw, revalidate/QC | No |
| Raw corrupt; exact remote asset retrievable | Reacquire then validate/postprocess | No |
| Output exists but metadata persistence failed | Reconcile same attempt and atomically repair fields | No |
| Attribution incomplete | Reconcile same epoch; unresolved identity remains ambiguous | No |
| Remote asset unavailable and all local evidence invalid | Owner decision; replacement last resort | Only explicit authorization |

Raw bytes and completed assets are not deleted/replaced to make recovery look clean. Reacquisition does not consume generation budget.

### Failure evidence retention

Immutable causal evidence is retained for dispatch certainty, terminal classification, retry authorization/denial, and reconciliation. Bounded poll noise may be retained only up to its evidence and elapsed-time limit. A canonical terminal-evidence record includes request and attempt identity, provider/project connection revision, provider card/job identity, timestamp, structural provider state, raw provider-visible message, locale, classification, classification-rule version, attribution evidence, dispatch certainty, and evidence digest. A screenshot is optional diagnostic evidence, never mandatory canonical authority.

## 12. ProductionState semantics

ProductionState remains a derived compact read model.

| Product state | Definition | UI |
| --- | --- | --- |
| RUNNING | A confirmed existing attempt is actively progressing | Working, poll |
| RECOVERING | Bounded reconciliation/acquisition/validation/postprocess executing | Recovering with item/action |
| RECOVERY_READY | Safe automatic recovery exists but no operation is active | Ready to continue |
| NEEDS_ATTENTION | Owner/operator decision is required | One next action |
| BLOCKED | Environment/provider prerequisite blocks progress | States no provider call |
| COMPLETE | All required visual obligations are satisfied | Complete |

Remove the current FAILED_RETRYABLE -> RUNNING projection and add explicit GENERATING handling. Client-side Working exists only while its actual action is in flight.

## 13. Continue Production semantics

Continue Production means: single-flight boundary; reread durable evidence; reconcile; issue a fresh RecoveryDecision; execute safe provider-free recovery; resume confirmed active work; perform only explicitly authorized provider dispatch; reproject state; then stop at the first safety or Owner boundary. It never reruns VISUALS from scratch.

Accepted assets remain byte/hash stable. The earliest unresolved Flow barrier is reconciled; local-only recovery precedes any generation; independent later requests run only when queue/dependency rules permit; final render remains blocked while required media is unresolved. Keep the current no-progress fingerprint, but return the last RecoveryDecision rather than only STAGE_NO_PROGRESS.

Evolve the existing coordinator to call a narrow recovery-aware VISUALS operation and re-query. Do not build a second coordinator or lifecycle system.

## 14. UI behavior

Use ordinary labels: Creating visuals, Checking existing Flow result, Repairing downloaded asset, Ready to continue, and Action needed. Diagnostics holds IDs, hashes, classifier evidence, and policy version.

Retain one active UI action. Duplicate clicks join/read the current durable run/recovery result; they do not start a second dispatch. Polling is only for a known in-flight operation and ends with its response. A ready or blocked recovery must render promptly and never remain Working because something is retryable. Required visual media may not silently skip to final render.

## 15. Concurrency and crash recovery

Retain project lock, serial queue barrier, atomic writes, and durable pre-boundary marker. Add a mandatory backend single-flight/operation lease bound to the decision; the frontend runToken is insufficient. Concurrent callers can observe or join the current action but cannot create duplicate dispatches. Hold the global dedicated Flow-profile lock for browser reconciliation and dispatch.

Immediately before provider dispatch, the backend verifies the decision is still current, its request/attempt/connection evidence still matches, and no other dispatch crossed the boundary. A second caller resolves as NOOP, already-active, or conflict, never dispatch. After restart, recompute from manifest/evidence. NOT_STARTED before the boundary may become proven no-dispatch; post-boundary state is DISPATCH_UNCERTAIN until reconciliation. A crash after output before persistence performs same-attempt reconciliation, never Generate. Changed card order is irrelevant: stored baseline/identity, not recency, controls attribution. Intentional same-prompt regeneration requires explicit Owner cause and fresh lineage.

## 16. Build OS boundary

Integrate Simplified Build OS Effect Safety now: NO. The generation manifest, attribution evidence, prompt revisions, assets, QC, and queue are product-domain state with richer causal detail than a generic effect guard. Dual authority would create conflicting ledgers/state migration without solving the current retry problem.

A future generic guard may consume a read-only summary only if it binds to the same attempt identity and never becomes a second retry authority. Legacy v1.23 records remain provenance only.

## 17. Fault-injection acceptance matrix

All cases use fake/offline Flow fixtures and temporary runtimes. Delta A is provider-attempt count delta.

| # | Initial evidence | Decision / dispatch / Delta A | Asset, production, UI assertion | Invariant |
| ---: | --- | --- | --- | --- |
| 1 | Six accepted, one policy terminal | Prompt repair/owner; 0 then +1 approved | Six hashes unchanged; Needs Attention | Partial batch preserved |
| 2 | Canonical pre-dispatch proof | Dispatch; +1 | Same logical request | Positive proof |
| 3 | Timeout after boundary, no binding | Reconcile; no; 0 | Blocked/recovering, not idle Working | Ambiguity barrier |
| 4 | Bound job active | Poll; no; 0 | Running only during polling | No parallel generation |
| 5 | Bound asset, download fails | Reacquire; no; 0 | QC after recovery | Acquisition != generation |
| 6 | Raw valid, postprocess fails | Reprocess; no; 0 | Local record appended | Local != provider failure |
| 7 | Selected corrupt, raw valid | Reprocess; no; 0 | Selected hash repaired/QC | Reuse raw |
| 8 | Rate limit with exact attribution and retry-after | Bounded exponential backoff with jitter; dispatch only after fresh decision; +1 | Recovery Ready before deadline; NEEDS_ATTENTION / RATE_LIMIT_BUDGET_EXHAUSTED when any wait/time/transient budget is exhausted | Shared transient budget |
| 9 | Credit exhausted | Owner action; no; 0 | Needs Attention | No automatic spend |
| 10 | Auth expires | Owner action; no; 0 | Sign-in/revalidate action | Account repair separate |
| 11 | UI boundary unidentifiable | Owner action; no; 0 | Blocked diagnostics | Fail closed |
| 12 | Terminal classification unknown | Owner/no-retry; no; 0 | Never transient-labelled | Unknown fails closed |
| 13 | Policy block + safe transform | Prompt repair then dispatch; +1 | Both prompt revisions retained | No semantic drift |
| 14 | Transform changes story meaning | Owner action; no; 0 | Semantic repair state | Owner owns semantics |
| 15 | Creative QC rejection | Owner replacement; +1 only approved | Parent retained/child current | Not transport retry |
| 16 | Two concurrent Continue callers at the dispatch boundary | One backend lease holder may dispatch; second is NOOP/already-active/conflict; Delta A <= 1 | Same durable result visible; pre-dispatch decision is revalidated | Backend single-flight |
| 17 | Crash after boundary | Reconcile; no; 0 | Restart recovery state | Durable boundary |
| 18 | Crash after output before write | Same-attempt reconcile; no; 0 | Original attempt owns asset | No duplicate cost |
| 19 | Restart unresolved | Same rebuilt decision; no | Correct recovery/block | Restart safe |
| 20 | One request recovers in completed batch | Targeted action | Other hashes stable | No restart |
| 21 | Budget exhausted | No retry; 0 | Blocked with named counter | No infinite loop |
| 22 | Stale Flow connection revision | Owner action; 0 | Future rebind only | Exact binding |
| 23 | Terminal card different locale | Structural evidence; unknown until classified; 0 | Text/locale in diagnostics | Text not authority |
| 24 | Owner regenerates success | Replacement; +1 | Old history preserved | Explicit intent |

Every fixture asserts decision object, safe_to_dispatch, adapter call log, manifest deltas, rebuilt production state, UI outcome, and zero real provider calls. Include restart fixtures that reload only durable artifacts.

The preserved live fixture req_c25fc3d16b0d3a621267 remains an explicit no-blind-dispatch acceptance fixture: GENERATING / SUBMITTED with the provider boundary entered and dispatch_confirmed=false. It is read-only evidence for the ambiguous-dispatch scenarios; this design and its future fault injection must not reconcile, supersede, cancel, or mutate it.

## 18. Future implementation impact map

| Class | Modules |
| --- | --- |
| MUST_CHANGE | providers/flow/service.py, providers/flow/live.py, core/project/production_state.py, application/production_coordinator.py, application/operator.py, ui/static/app.js, focused Flow/production/UI tests |
| MAY_CHANGE | providers/flow/attribution.py, connection.py, session.py, manifest/schema docs, CLI recovery commands, core/retry.py only as local scheduling helper |
| SHOULD NOT CHANGE | Timeline/continuity/shot/media planning, render/compositor, TTS, Gemini planning, unrelated publishing, Simplified Build OS |

Put the pure decision module beside the Flow service or in a provider-neutral generation domain package, then route existing writers through it. Do not create a parallel manifest, coordinator, or workflow ledger.

## 19. Migration and backward compatibility

Read legacy manifests without ordinary-query rewrite. Missing dimensions are UNKNOWN; existing canonical_no_dispatch_proof remains the only compatibility route to safe retry. A controlled recovery write appends a versioned observation rather than normalizing historical fields. Existing owner/operator decision surfaces are extended with exact request/prompt-revision binding; no parallel workflow system is introduced.

Rebuild old ProductionState as BLOCKED/Needs Attention for unknown attempts, not RUNNING. Preserve current validated replacement transactions. Introduce budget settings explicitly; do not silently count historic max_attempts=12 against the new policy.

## 20. Explicit non-goals

- No live Flow reconciliation, dispatch, cancellation, supersession, or mutation of the preserved fixture.
- No policy evasion or automatic change to story meaning.
- No planning/render redesign, provider-routing change, or QC-authority change.
- No Build OS lifecycle reconstruction or dual-ledger migration.
- No stage-wide retry, unbounded polling, or automatic cost recovery after ambiguous dispatch.

## 21. R3 decisions and open blockers

All five previously open Tech Lead/Owner decisions are CLOSED by this R3 amendment: the automatic transient budget is two redispatches (not the initial attempt), the absolute provider-attempt lifetime stop-loss is 12, owner authorization binds exact request/prompt revision, unqualified terminal failures remain PROVIDER_TERMINAL_UNKNOWN, terminal evidence retention is frozen, and rate-limit retry is bounded automatic recovery under the shared transient budget.

There are no new design blockers. Implementation remains blocked only on the required final Tech Lead approval, not on an unresolved architecture decision.

## Design validation basis

This design was checked against the current Flow service/executor, live surface and attribution logic, production reconciler/coordinator, operator/UI action lifecycle, focused Flow/QC/production tests, FAILURE_RECOVERY_V1.md, and OPERATIONS.md. Proposed items are architecture decisions; unsupported persisted facts are UNKNOWN and fail closed.
