# Dola unverified-session UI gate — review, 2026-09-23

Scope: only the experimental Dola action in Hybrid Opening and its Settings
readiness copy. UX contract is in `TASK.md`. No broader workflow, navigation,
layout, provider routing, or saved account was changed. No generation was sent.

Rendered evidence: candidate UI on `127.0.0.1:8782`, isolated project
`prj_dola_ui_gate_preview` in
`D:\Story Auto\evidence\dola-cookie-approved-canary-20260923`.
Opening Builder screenshots: `ui-dola-unverified-1440.png`,
`ui-dola-unverified-576.png`; Settings screenshots:
`ui-dola-settings-1440.png`, `ui-dola-settings-576.png`. Actual pixels were
inspected at both widths. All three missing slots retain **Import clip**;
zero **Generate with Dola** buttons render when the saved session is unverified.
The reason sits below each slot's actions. Settings explicitly separates
"Saved, not verified" from connection verification.

## UX implementation review

| Item | Result and smallest evidence |
|---|---|
| PRIMARY_SURFACE_DISCOVERABILITY | PASS — Opening Builder reason beside the affected slot, both widths |
| SCOPE_CLARITY | PASS — message applies to Dola generation; Import clip remains per slot |
| APPLY_REAPPLY_RESET_EXPLICITNESS | NOT_APPLICABLE — no such action changed |
| ADVANCED_WITHOUT_DOMINATING | PASS — one short inline note; no new panel |
| DISABLED_STATE_EXPLANATION | PASS — unavailable action is replaced by reason and manual path, not an unexplained disabled button |
| BULK_DESTRUCTIVE_SAFETY | NOT_APPLICABLE |
| VISIBLE_HIERARCHY | PASS — slot/prompt/actions precede supporting explanation |
| CONTROL_DENSITY | PASS — fewer controls; usable at 576px |
| COHERENT_APPLICATION_COMPOSITION | PASS — existing Opening Builder and Settings surfaces preserved |
| DESTRUCTIVE_DIFFERENTIATION | NOT_APPLICABLE |
| EXISTING_WORKFLOW_PRESERVATION | PASS — manual import and confirmed-job recovery remain; one new submit is blocked |
| INFORMATION_ARCHITECTURE | PASS — existing project/Settings separation unchanged |
| NAVIGATION | PASS — existing Home/Settings navigation unchanged |
| WORKSPACE_LAYOUT | PASS — no new persistent region or viewport compression |
| VIEWPORT_BUDGET | PASS — inspected 1440×900 and 576×900 screenshots |
| PERSISTENT_CONTEXTUAL_CONTROLS | PASS — warning is contextual to unverified Dola slot |
| LAYOUT_ARCHETYPE_FIT | PASS — existing slot-card layout remains appropriate |
| RESPONSIVE_WORKSPACE_BEHAVIOR | PASS — note wraps without hiding Import clip at 576px |
| VERTICAL_SPRAWL_REDUCED | NOT_APPLICABLE — sprawl was not the goal |
| WORKSPACE_LAYOUT_SOLUTION | NOT_APPLICABLE — layout was not the goal |
| TASK_FLOW_ARCHITECTURE | PASS for this gate — unavailable Dola path cannot start, manual import remains reachable |
| LINEAR_MULTISTEP_REASONING | NOT_APPLICABLE — no multistep flow introduced |
| REVIEW_BEFORE_COMMIT | PASS for still-available Dola path — existing confirmation remains; new submission currently unavailable |
| EXECUTION_STATE_SEPARATION | PASS — existing ambiguous/confirmed attempt states remain distinct from fresh setup |
| RESOURCE_MANAGEMENT_SEPARATION | NOT_APPLICABLE — no resource library change |
| POST_COMPLETION_DESTINATION | NOT_APPLICABLE — no completed output produced |

Function exists: PASS (focused tests and server-side guard). Discoverable:
PASS (rendered Opening Builder). Understandable: PASS for the unavailable
state (clear reason/remedy). Hierarchy supports workflow: PASS at both tested
widths. Owner UX accepted: **NOT CLAIMED**; whole-product acceptance still
requires an authenticated Dola path and real result. `owner_ux_gate=NOT_REQUIRED`
for this fail-closed safety state; no aesthetic or workflow preference was
chosen for the Owner.

Technical validation is separate: focused 42 tests, full 938 tests, JS
syntax, quality/security, and diff checks passed after the safety gate.
