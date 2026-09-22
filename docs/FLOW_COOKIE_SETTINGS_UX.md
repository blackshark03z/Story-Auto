# Flow cookie Settings delivery contract

UX_CONTRACT
PRIMARY_USER=Owner maintaining a valid Flow session without leaving Chrome open.
PRIMARY_JOURNEY=Settings -> name session -> choose Cookie Editor JSON -> review/save -> test exact Flow project.
PRIMARY_SURFACE=Settings, adjacent to existing Flow session section.
INFORMATION_HIERARCHY=Saved sessions and import first; experimental scope and no-generation connection check second.
SCOPE_MODEL=One named local session; refresh increments revision. Saving does not switch existing projects or start generation.
PRIMARY_CONTROLS=Session name, cookie file, Preview, Save session, saved session selector, Flow project URL, Test connection.
ADVANCED_CONTROLS=No raw cookie text displayed; detailed integration remains explicitly experimental.
STATES=Empty/import validation/saving/configured/checking/verified now/error with sign-in-and-export remedy.
BULK_DESTRUCTIVE=No bulk or deletion in this increment; replacing same name requires review/confirmation.
DISCOVERABILITY=Visible Flow cookie section in Settings, not hidden in Diagnostics.
ACCESSIBILITY=Native labels and file input; keyboard controls; status aria-live; buttons disabled while request pending.
OWNER_PREFERENCE=NONE for reusing established Settings layout; owner product acceptance still pending.

CREATE_FLOW_CONTRACT
TASK_GOAL=Securely save one reusable Flow session and verify access without generation.
LINEAR_OR_NONLINEAR=Linear import/review/save, then optional live connection check.
STEPS=Choose name/file -> review replacement scope -> Save -> test target project.
STEP_DEPENDENCIES=Valid parsed cookie export before save; saved account and exact Flow project URL before test.
BACK_BEHAVIOR=Cancel confirmation preserves selected file until leaving Settings.
NEXT_VALIDATION=Server validates every import; safe error text never echoes secret content.
FINAL_REVIEW_STEP=Preview identifies name/replacement; confirmation immediately before save.
PRIMARY_COMMIT_ACTION=Save session encrypts for current Windows user; no provider generation.
CANCEL_EXIT_BEHAVIOR=Leaving Settings discards unsaved import; saved sessions remain.
DRAFT_PERSISTENCE=Never persist cookie drafts in localStorage, project files, or logs.
POST_SUBMIT_DESTINATION=Settings saved sessions list; test result is transient current evidence, not permanent Ready.

EXECUTION_CONTRACT
TRIGGER=Test connection.
RUNNING_STATE=Checking access; disable duplicate activation.
STATUS_SURFACE=Inline status beside the session controls.
LOGS_DETAIL=Safe error code only, never cookies or raw provider response.
CANCEL_OR_STOP=Bounded read-only timeout, no queued generation to cancel.
COMPLETED_STATE=Read verified for exact project; does not imply production promotion.
FAILED_STATE=Refresh export after confirming Flow login; saved session remains intact.
RETURN_PATH=Stay in Settings.

RESOURCE_LIBRARY_CONTRACT
RESOURCE_SCOPE=Named local Flow sessions.
ROW_OR_ITEM_ACTIONS=Select for read-only check, refresh by saving the same name.
STATUS_AND_OUTPUT=Configured and revision, never raw values.
EMPTY_STATE=No sessions saved; choose a cookie JSON file.
SEARCH_FILTER=Not needed for current small account set.

Review/render evidence will be recorded after implementation. No owner UX or
product acceptance is inferred from this contract or unit tests.

## Hybrid Opening integration contract

PRIMARY_JOURNEY=Opening slot -> choose Flow session/project/reference PNG -> confirm one8-second video -> preview normalized clip.
PRIMARY_SURFACE=Existing Opening Builder slot; available under Auto provider policy.
SCOPE_MODEL=One slot, one named revision, one exact provider project and PNG. No global route change.
ADVANCED_CONTROLS=Optional Flow reference-video disclosure; not part of image/body routing.
STATES=No session: Settings remedy; >8-second slot: unsupported; pending: recover same video; ready: existing clip preview.
REVIEW_BEFORE_COMMIT=Confirmation names slot, account, provider project, reference filename and one8-second output; allowance may be consumed.
EXECUTION_STATE=Existing project action progress; persisted slot status survives reload; no provider switch while unresolved.
RESOURCE_MANAGEMENT=Canonical opening source and normalized clip with existing project output library.
CANCEL_EXIT_BEHAVIOR=Cancel leaves local selected reference unsent; generation confirmation is the effect boundary.
OWNER_PREFERENCE=NONE; retain existing provider choices and canonical compositor. Product acceptance still pending.

Settings visual checkpoint: candidate localhost8786 inspected at1280x900 and
760x900, empty/disabled and missing-input states. Fields reflow from two columns
to one; session name/file and remedies remain reachable. Full saved-session and
Opening action journey still requires rendered verification.

## Implementation review checkpoint

Lifecycle increment contract: Settings -> selected saved session -> Remove saved
session -> review exact alias/revision and local-only effect -> confirm or cancel.
Server requires the displayed revision; concurrent refresh blocks deletion.
Only encrypted secret is removed; a non-secret revision tombstone prevents old
attempts using a newly imported same-name account. No remote logout/cancellation.
Use an in-page modal with Cancel focused, Escape cancellation, named destructive
CTA and focus return; replace only Flow native confirmations after browser modal
control stalled during the previous preview. Saved/import drafts stay untouched
on cancel. Rendered verification remains mandatory; no owner preference change.

Evidence: FLOW_COOKIE_OPENING_DELIVERY_20260921.md; actual candidate Settings8786
and no-effect Opening fixture53138, inspected2026-09-21. This is an interim review.

UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: Settings Flow section and per-slot disclosure rendered.
SCOPE_CLARITY=PASS: exact slot/account/project/reference; no default routing change.
APPLY_REAPPLY_RESET_EXPLICITNESS=PASS: explicit zero-effect-only reset, history preserved, backend tests.
ADVANCED_WITHOUT_DOMINATING=PASS: optional Flow disclosure stays closed initially.
DISABLED_STATE_EXPLANATION=PASS: no-session/gate/duration remedies in primary surface.
BULK_DESTRUCTIVE_SAFETY=NOT_APPLICABLE: no bulk action; revoke still outstanding.
VISIBLE_HIERARCHY=PASS: existing slot headers/actions preserved in rendered desktop.
CONTROL_DENSITY=PASS: only selected slot disclosure adds configuration controls.
COHERENT_APPLICATION_COMPOSITION=PASS: existing Opening/Settings surfaces reused.
DESTRUCTIVE_DIFFERENTIATION=NOT_APPLICABLE: reset archives rather than deletes.
EXISTING_WORKFLOW_PRESERVATION=PASS: existing Opening/Dola regression87 PASS.
INFORMATION_ARCHITECTURE=PASS: credentials Settings; per-slot generation Opening.
NAVIGATION=PASS: Home -> project -> Opening; no new independent workspace.
WORKSPACE_LAYOUT=PASS: scoped CSS corrects inherited absolute-input overlap; desktop rechecked.
VIEWPORT_BUDGET=PASS: collapsed advanced controls do not consume persistent setup space.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: setup only unbound slots; recovery only existing attempt.
LAYOUT_ARCHETYPE_FIT=PASS: reuse existing slot master/detail cards and optional disclosure.
RESPONSIVE_WORKSPACE_BEHAVIOR=FAIL: Settings1280/760 verified; enabled Opening narrow recheck outstanding.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE: no sprawl redesign claimed.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE: no whole-workspace redesign claimed.
TASK_FLOW_ARCHITECTURE=PASS: configure -> confirmation -> canonical execution/preview.
LINEAR_MULTISTEP_REASONING=PASS: one short optional slot form; no artificial wizard stages.
REVIEW_BEFORE_COMMIT=FAIL: confirmation implemented but live dialog interaction timed out; verification pending.
EXECUTION_STATE_SEPARATION=PASS: reuses project busy/action state and durable slot state, offline recovery tested.
RESOURCE_MANAGEMENT_SEPARATION=PASS: canonical source/normalized preview retained after success.
POST_COMPLETION_DESTINATION=PASS: same project Opening normalized clip, proven via composed service tests.

technical_validation=PASS for stated focused/regression scope, not full-product acceptance.
candidate_preview=PARTIAL (real rendered empty/enabled forms; confirmation/narrow gap).
levels1-4=PARTIAL across full journey; function exists, visible entry, scope and desktop hierarchy inspected.
level5_owner_ux_accepted=NO.
owner_ux_gate=NOT_REQUIRED for these reversible engineering/layout corrections;
owner_product_acceptance=PENDING.
SHOULD_FIX_BEFORE_ACCEPTANCE=Finish enabled narrow/confirmation journey; add revoke lifecycle.
BLOCKER=No proven product-UX preference blocker; real credential-save confirmation pending separately.

Lifecycle follow-up: removal implemented as LOCAL_ONLY, expected-revision guarded,
secret-free tombstone; no Google logout claim. Independent review PASS and final
focused65 tests PASS. In-page confirmation rendered in actual fixture: exact
Generate scope, Cancel initial focus, Escape returns to Generate with draft intact;
local-remove scope rendered desktop and760-wide, Cancel shows unchanged session.
Scoped compact dialog CSS added after initial preview; async Settings focus
restoration corrected after buttons re-enable. That final focus change still needs
rendered recheck. Previous REVIEW_BEFORE_COMMIT failure is resolved for displayed
generation scope and cancel path; actual confirmed live dispatch still pending.
technical_validation=PASS (stated scope); candidate_preview=PARTIAL;
owner_product_acceptance=PENDING. No real cookies or provider effects exercised.

### Rendered gap closure, 2026-09-21

Fresh server at localhost51189, runtime cookie-opening-enabled-ui-20260921,
started from current checkout using flow_cookie_opening_preview.py. Its Flow
generation method is replaced by an unconditional no-effect error; account is
explicitly ui-fixture-not-a-real-account. No Generate or removal was confirmed.
At760x900, screenshot shows all expanded OPENING_O1 Flow session/project/reference
fields, allowance warning and Generate CTA without overlap or horizontal clipping.
Removal dialog also fits: exact account/revision, local-only effect and recovery
warning, Cancel initially focused. Clicking Cancel closes the dialog, displays
unchanged-session status, and returns focus to removeFlowCookie after re-enable.
Read-only DOM observation confirmed focus and closed dialog; screenshot supplied
visual evidence separately. These observations close the previously outstanding
enabled-narrow and final Settings focus checks, not live generation acceptance.

RESPONSIVE_WORKSPACE_BEHAVIOR=PASS for tested desktop history and current760px.
REVIEW_BEFORE_COMMIT=PASS for displayed scope and safe cancellation only.
technical_validation=PASS for the observed cancel/focus behavior; no suite rerun.
candidate_preview=PASS for these bounded interface gaps; full journey PARTIAL.
levels1-4=PASS for these controls; level5_owner_ux_accepted=NO.
information_architecture/navigation/workspace_layout/task_flow=UNCHANGED.
execution_state/resource_management=NOT_RETESTED for real provider completion.
vertical_sprawl_reduced=NOT_APPLICABLE; owner_ux_gate=NOT_REQUIRED for gap checks.
owner_product_acceptance=PENDING; no new UX blocker found in this bounded review.

Source provenance: dirty HEAD5464cbb1d1c11a550b5e096647b9f94587de5bfe.
SHA256 app.js E4F598AB0B936BCCD7EB5FC53789BF53F7953A5D4B325CB1DE7A17CF3E218228;
styles.css 18D57E048EF9109C4AD9B5F19ACCE45599EEA4D66E05837FF989E90C2BF46767;
fixture AA6A51870A2C120690E9DEF60B9DD0096F2AA6CB69DFE2022A468563FA17D4B9.
