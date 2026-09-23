# Dola browser-UI operator candidate review — 2026-09-23

Scope: the exact-project/account, default-off candidate gate and its Opening
Builder controls. This is pre-submit UX evidence, not Dola video acceptance.
The candidate server at `127.0.0.1:8780` was stopped after the review.

Rendered evidence in
`D:\Story Auto\evidence\dola-browser-ui-canary-20260923`:
`ui-check-1440.png`, `ui-check-576.png`, `ui-verified-1440.png`,
`ui-verified-576.png`, `ui-review-1440.png`, `ui-review-576.png`.
The separately restarted default-off surface is `ui-gate-off-576.png`:
zero Check/Generate buttons, manual Import clip available, and an explicit
paused reason on each slot. Its test server at `127.0.0.1:8781` was stopped.
Before check, all three slots offered **Check Dola session** and no Generate.
After a signed-in, zero-submit check, only `OPENING_O1` offered Generate; the
other two still required their own check. The confirmation dialog exposed
the selected slot, named account, full prompt, requested length, quota risk
and no-blind-retry consequence. Cancel left the canary manifest at zero
attempts/submissions. At 576px the controls reflowed without hidden action;
the Opening heading is no longer obscured by the sticky navigation when
focused. A separate partly prepared project initially rendered a generic
error because its production `next_action` was null; the candidate now uses
a safe Review project action and shows the Opening slots.

UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: Check appears beside each eligible Opening slot.
SCOPE_CLARITY=PASS: One slot/account/profile and exact prompt are named in the review dialog.
APPLY_REAPPLY_RESET_EXPLICITNESS=NOT_APPLICABLE: No apply-all or reset action added.
ADVANCED_WITHOUT_DOMINATING=PASS: Profile and attempt IDs stay out of primary controls.
DISABLED_STATE_EXPLANATION=PASS: Gate-off state explains why generation is paused; gated unverified state offers Check.
BULK_DESTRUCTIVE_SAFETY=NOT_APPLICABLE: No bulk/destructive action.
VISIBLE_HIERARCHY=PASS: Slot and prompt precede Check/Generate; import remains alongside.
CONTROL_DENSITY=PASS: 1440px and 576px screenshots show usable spacing and reflow.
COHERENT_APPLICATION_COMPOSITION=PASS: Existing Opening Builder surface reused.
DESTRUCTIVE_DIFFERENTIATION=PASS: Potential quota use and uncertainty appear in the final review.
EXISTING_WORKFLOW_PRESERVATION=PASS: Manual clip import and other providers remain available.
INFORMATION_ARCHITECTURE=PASS: No new top-level destination; this is a slot-specific action.
NAVIGATION=PASS: Existing project-to-Opening route and focus target remain reachable.
WORKSPACE_LAYOUT=PASS: No competing permanent pane; controls remain contextual to each slot.
VIEWPORT_BUDGET=PASS: 1440px two-column and 576px one-column slot views stay legible.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: Check/Generate appear only for eligible gate/state.
LAYOUT_ARCHETYPE_FIT=PASS: Existing stacked Opening workflow fits three sequential clips.
RESPONSIVE_WORKSPACE_BEHAVIOR=PASS: 576px check and review controls are visible and operable.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE: No sprawl-reduction goal.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE: No workspace-replacement goal.
TASK_FLOW_ARCHITECTURE=PASS: Check -> review -> explicit single Create; no silent provider send.
LINEAR_MULTISTEP_REASONING=PASS: Short dependent flow; a separate wizard would add friction.
REVIEW_BEFORE_COMMIT=PASS: Modal identifies effect and has Cancel/Create one Dola video.
EXECUTION_STATE_SEPARATION=OWNER_REVIEW_REQUIRED: Existing manifest states render, but no Story Auto live submit was authorized or observed.
RESOURCE_MANAGEMENT_SEPARATION=OWNER_REVIEW_REQUIRED: Actual Dola output acquisition and result inspection await live qualification.
POST_COMPLETION_DESTINATION=OWNER_REVIEW_REQUIRED: No Story Auto Dola output exists yet.

Function exists and pre-submit discoverability/understandability/hierarchy
pass on this candidate. Owner real-use UX acceptance and live execution/result
states are pending. `owner_ux_gate=NOT_REQUIRED` for the constrained workflow
choice; `owner_acceptance=PENDING`. No provider generation was sent in this
review, and no production gate was enabled.

After independent review, the candidate additionally requires the saved
cookie/profile binding to remain unchanged through the final pre-submit check.
Only a persisted, provably unsent failure can expose Check again and then an
explicitly reviewed retry; an ambiguous attempt exposes no new-submit action.
Focused regression tests cover the refresh race and this state boundary.

The follow-up rendered regression used a disposable project and mocked Dola
client, never a real provider send. At 1440px and 576px,
`ui-known-unsent-1440.png` / `ui-known-unsent-576.png` show **NOT SENT** with
**Create one Dola video** only after a successful per-slot check. Clicking it
opened Review; Cancel left the durable submit count at one historical
zero-effect attempt. `ui-ambiguous-1440.png` / `ui-ambiguous-576.png` show
**OUTCOME UNCERTAIN**, plain-language reconciliation guidance, and no Check,
Create, or Import action on the ambiguous slot. Other empty slots still offer
their own Check. The DOLA-only Opening guidance now names the real check/review/
create journey instead of suggesting unavailable providers. This closes the
pre-submit error-state wording gap, not live execution/result acceptance.
