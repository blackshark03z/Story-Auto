# Dola cookie account settings

## Mixed-version local window guard, 2026-09-23 — pre-implementation contract

UX_CONTRACT
PRIMARY_USER=Owner importing a Dola Cookie-Editor export while two local Story Auto windows run different server code.
PRIMARY_JOURNEY=Settings Dola -> see whether this window supports import -> use the compatible window -> preview/save.
PRIMARY_SURFACE=Existing Dola Settings import form.
INFORMATION_HIERARCHY=If unsupported, the reason and remedy replace the normal ready state; account details remain visible.
SCOPE_MODEL=Only the current local server capability, not the saved account or production routing, changes.
PRIMARY_CONTROLS=Import fields and Preview/Save remain available only when the backend advertises raw-export support.
ADVANCED_CONTROLS=NONE.
STATES=Compatible server: normal form; stale server: disabled form, nearby plain-language reason and updated-window remedy; saved accounts unchanged.
BULK_DESTRUCTIVE=No destructive action.
DISCOVERABILITY=Warning appears inside the same Dola section before an unsupported save attempt.
ACCESSIBILITY=Disabled controls have a nearby live-status reason; no inaccessible hover-only explanation.
OWNER_PREFERENCE=NONE; prevent a known false-positive UI/server mismatch.

CREATE_FLOW_CONTRACT
TASK_GOAL=Prevent an unsupported import on a stale local server.
LINEAR_OR_NONLINEAR=Linear setup action with a capability precondition.
STEPS=Open Settings -> confirm server supports import -> paste -> preview -> save.
STEP_DEPENDENCIES=Backend capability must be true before any import action.
BACK_BEHAVIOR=No account changes when switching windows.
NEXT_VALIDATION=Disabled before preview/save when capability absent.
FINAL_REVIEW_STEP=Existing account-change preview and confirmation on compatible server.
PRIMARY_COMMIT_ACTION=Save accounts only on a compatible server.
CANCEL_EXIT_BEHAVIOR=Unsaved cookie text is not persisted.
DRAFT_PERSISTENCE=NONE; raw cookie remains only in current unsaved field.
POST_SUBMIT_DESTINATION=Existing Settings account list.

### Mixed-version guard review

The old 8775 process serves the current static JavaScript from disk but retains
its old Python backend. Synthetic raw-export preview returned a format error
there and succeeded on the newly started 8778 backend. The new Settings
response advertises `cookie_editor_import_supported=true`; a server without
that flag disables the import fields and Preview/Save, with a visible remedy.
Rendered 576px screenshots prove 8775 disabled and 8778 enabled:
`D:\Story Auto\evidence\dola-live-qualification-20260923\mixed-version-{8775,8778}.png`.
No account or cookie was saved by this check.

UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: compatibility notice appears in Dola Settings.
SCOPE_CLARITY=PASS: notice names this window and says nothing was saved.
APPLY_REAPPLY_RESET_EXPLICITNESS=PASS: Save is disabled on the stale server.
ADVANCED_WITHOUT_DOMINATING=PASS: no advanced controls added.
DISABLED_STATE_EXPLANATION=PASS: visible remedy immediately before disabled actions.
BULK_DESTRUCTIVE_SAFETY=NOT_APPLICABLE: no bulk or destructive action.
VISIBLE_HIERARCHY=PASS: warning and disabled actions render together at 576px.
CONTROL_DENSITY=PASS: no new persistent controls.
COHERENT_APPLICATION_COMPOSITION=PASS: existing Settings section retained.
DESTRUCTIVE_DIFFERENTIATION=NOT_APPLICABLE.
EXISTING_WORKFLOW_PRESERVATION=PASS: compatible 8778 form remains enabled.
INFORMATION_ARCHITECTURE=PASS: status stays with account setup.
NAVIGATION=PASS: existing Settings route unchanged.
WORKSPACE_LAYOUT=PASS: same narrow form, no overflow.
VIEWPORT_BUDGET=PASS: notice and actions fit owner-width pane.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: compatibility state is contextual to Dola.
LAYOUT_ARCHETYPE_FIT=PASS: short stacked form.
RESPONSIVE_WORKSPACE_BEHAVIOR=PASS: rendered at 576px.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE.
TASK_FLOW_ARCHITECTURE=PASS: capability precondition before Preview/Save.
LINEAR_MULTISTEP_REASONING=PASS: no stepper needed for short setup.
REVIEW_BEFORE_COMMIT=PASS: compatible path retains preview/confirmation.
EXECUTION_STATE_SEPARATION=NOT_APPLICABLE.
RESOURCE_MANAGEMENT_SEPARATION=PASS: account list remains visible.
POST_COMPLETION_DESTINATION=PASS: compatible save still refreshes Settings.

technical_validation=rendered stale/new comparison PASS; focused and full
candidate tests to be rerun at final commit. Candidate preview=PASS.
Five levels: function=PASS; discoverable=PASS; understandable=PASS;
hierarchy=PASS; Owner UX accepted=UNVERIFIED. owner_ux_gate=NOT_REQUIRED.

## Cookie-Editor export repair, 2026-09-23 — pre-implementation contract

UX_CONTRACT
PRIMARY_USER=Owner who exported Dola cookies from Cookie-Editor and needs to save one named account without hand-building a Cookie header.
PRIMARY_JOURNEY=Settings Dola -> name the account -> paste the raw JSON export -> preview account scope -> save -> see only the saved name.
PRIMARY_SURFACE=Existing Dola accounts section in Settings.
INFORMATION_HIERARCHY=Name, import field, Preview changes, and Save accounts remain the short primary path; legacy named-header syntax stays available.
SCOPE_MODEL=One raw browser export updates exactly the entered alias; other aliases remain unchanged.
PRIMARY_CONTROLS=Account name, paste field, Preview changes, Save accounts.
ADVANCED_CONTROLS=Existing named-header and named-JSON bulk formats stay documented as alternatives.
STATES=Empty explains accepted formats; invalid/expired/wrong-domain exports get sanitized remedies; preview names additions/updates; save clears raw input.
BULK_DESTRUCTIVE=Preview and confirmation identify the alias that will be created or refreshed; no account is removed.
DISCOVERABILITY=Raw Cookie-Editor JSON is explicitly named at the current Dola paste field.
ACCESSIBILITY=Visible label for account name; existing labeled textarea and live preview status; keyboard order name -> paste -> preview -> save.
OWNER_PREFERENCE=NONE; the screenshot establishes the intended raw-export import path.

CREATE_FLOW_CONTRACT
TASK_GOAL=Save one Dola browser export as a reusable named account.
LINEAR_OR_NONLINEAR=Linear short form within existing Settings.
STEPS=Enter/keep account name -> paste export -> preview account change -> save.
STEP_DEPENDENCIES=Valid Dola-domain, unexpired export containing sessionid before preview/save.
BACK_BEHAVIOR=Cancel save confirmation preserves input and saved accounts.
NEXT_VALIDATION=Preview validates and reports a sanitized format/domain/session error.
FINAL_REVIEW_STEP=Existing confirmation shows new/updated count and account name.
PRIMARY_COMMIT_ACTION=Save accounts; encrypts only the named account's cookie header.
CANCEL_EXIT_BEHAVIOR=Leaving Settings without saving makes no change.
DRAFT_PERSISTENCE=Raw export stays only in the unsaved field; no localStorage or logs.
POST_SUBMIT_DESTINATION=Existing Settings account list and configured count.

## Cookie-Editor import candidate review, 2026-09-23

The Owner's 576px screenshot showed a raw Cookie-Editor JSON array pasted into
the legacy named-header field, followed by a generic error. The candidate now
offers an explicit account-name field, accepts the raw JSON without manually
joining values, previews create/update scope, and preserves the legacy named
formats. A Dola-domain, unexpired `sessionid` is required; other-domain
cookies are excluded and raw values do not appear in preview, storage JSON,
or sanitized errors. Rendered source candidate on port 8777 was inspected at
1440px, 760px, and 576px; no horizontal overflow at owner width. Synthetic
valid preview showed one new `dola-main` account; synthetic invalid preview
showed the specific sign-in/session remedy. Neither preview saved an account.
Evidence: `D:\Story Auto\evidence\dola-live-qualification-20260923\dola-cookie-editor-preview-{desktop,narrow,owner-width}.png`.

UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: existing Settings Dola section names Cookie-Editor export at the input.
SCOPE_CLARITY=PASS: alias field and preview identify one new or updated account.
APPLY_REAPPLY_RESET_EXPLICITNESS=PASS: same alias refreshes only that account; confirmation names it.
ADVANCED_WITHOUT_DOMINATING=PASS: legacy named format remains supporting text below the primary import field.
DISABLED_STATE_EXPLANATION=NOT_APPLICABLE: no disabled control was added.
BULK_DESTRUCTIVE_SAFETY=PASS: import does not remove accounts; preview precedes save.
VISIBLE_HIERARCHY=PASS: name, paste, preview, save appear in that order at 576px.
CONTROL_DENSITY=PASS: one added field in the existing section; no extra workspace.
COHERENT_APPLICATION_COMPOSITION=PASS: Settings remains the credential owner.
DESTRUCTIVE_DIFFERENTIATION=NOT_APPLICABLE: no destructive action added.
EXISTING_WORKFLOW_PRESERVATION=PASS: existing named-header/JSON paths remain tested.
INFORMATION_ARCHITECTURE=PASS: account configuration remains separate from generation.
NAVIGATION=PASS: unchanged Settings entry.
WORKSPACE_LAYOUT=PASS: form reflows at 576px without horizontal overflow.
VIEWPORT_BUDGET=PASS: import controls are legible in the owner's narrow pane.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: existing Settings-only placement.
LAYOUT_ARCHETYPE_FIT=PASS: short stacked configuration form.
RESPONSIVE_WORKSPACE_BEHAVIOR=PASS: rendered 1440px/760px/576px inspections.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE: no sprawl goal.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE: no layout redesign.
TASK_FLOW_ARCHITECTURE=PASS: name -> paste -> preview -> save.
LINEAR_MULTISTEP_REASONING=PASS: short form does not need a stepper.
REVIEW_BEFORE_COMMIT=PASS: alias/new/update confirmation before encryption.
EXECUTION_STATE_SEPARATION=NOT_APPLICABLE: this saves configuration, not generation.
RESOURCE_MANAGEMENT_SEPARATION=PASS: saved aliases list remains in Settings.
POST_COMPLETION_DESTINATION=PASS: saved account list and count refresh in Settings.

technical_validation=25 focused Dola tests and JS syntax PASS; full suite pending.
candidate_preview=PASS at desktop, narrow and owner-width using synthetic data.
Five levels: function=PASS; discoverable=PASS; understandable=PASS;
hierarchy=PASS; Owner UX accepted=UNVERIFIED.
owner_ux_gate=NOT_REQUIRED for this import-format repair; whole-product
acceptance remains PENDING until real account save and live qualification.

UX_CONTRACT
PRIMARY_USER=Owner who occasionally refreshes a Dola browser session before creating video.
PRIMARY_JOURNEY=Settings -> paste named cookie accounts -> preview additions and updates -> save -> see configured account names.
PRIMARY_SURFACE=Settings, under Video generation providers.
INFORMATION_HIERARCHY=Account count and configured names are primary; cookie text is a one-time input and is never shown again.
SCOPE_MODEL=Saving updates only the named aliases supplied; other saved accounts remain unchanged.
PRIMARY_CONTROLS=Account list, paste field, Preview changes, Save accounts, and one Remove button per alias.
ADVANCED_CONTROLS=JSON import is optional and described beside the paste field for bulk account management.
STATES=Empty explains the format; preview names additions/updates; save clears input; errors explain the correct format without showing a cookie.
BULK_DESTRUCTIVE=Each removal names its single account and requires confirmation; paste/save is additive by alias.
DISCOVERABILITY=The Dola provider appears in Settings with its configured/not configured state.
ACCESSIBILITY=Textarea has a visible label; buttons have descriptive names; status is visible text; confirmation names the account.
OWNER_PREFERENCE=NONE

CREATE_FLOW_CONTRACT
TASK_GOAL=Configure named Dola accounts and generate one opening clip.
LINEAR_OR_NONLINEAR=Linear within each action; accounts are reusable resources.
STEPS=Paste accounts -> preview counts and aliases -> confirm save; choose an account on an opening slot -> review one generation -> generate.
STEP_DEPENDENCIES=Valid session header for save; configured account and <=10-second slot for submit.
BACK_BEHAVIOR=Cancel confirmation retains pasted input and existing saved accounts.
NEXT_VALIDATION=Invalid alias/header returns a sanitized input error.
FINAL_REVIEW_STEP=Confirmation names account changes or the exact video slot and consequence.
PRIMARY_COMMIT_ACTION=Save accounts / Generate with Dola.
CANCEL_EXIT_BEHAVIOR=Cancel confirmation leaves saved state unchanged.
DRAFT_PERSISTENCE=Cookies are not saved until confirmation; pending video receipt persists immediately.
POST_SUBMIT_DESTINATION=Opening slot status and Check / recover Dola video.

EXECUTION_CONTRACT
TRIGGER=Confirmed single-slot generation.
RUNNING_STATE=Submitting then Generating; no fictional percentage.
STATUS_SURFACE=Existing opening slot.
LOGS_DETAIL=Sanitized reason code only; cookies and signed URLs never displayed.
CANCEL_OR_STOP=No provider cancellation contract is asserted.
COMPLETED_STATE=Normalized preview on the same slot.
FAILED_STATE=Refresh cookie for access failure; uncertain submit cannot be repeated.
RETURN_PATH=Settings for cookie renewal; original slot for poll-only recovery.

RESOURCE_LIBRARY_CONTRACT
RESOURCE_SCOPE=Named accounts and existing per-project Opening slots.
ROW_OR_ITEM_ACTIONS=Refresh named cookie, remove account, recover clip.
STATUS_AND_OUTPUT=Configured does not mean authenticated; completed slot shows video.
EMPTY_STATE=Paste named accounts; generation remains unavailable until configured.
SEARCH_FILTER=Not introduced for this bounded first integration.

## Candidate review, 2026-09-20

Parent inspected rendered Settings at localhost:8781 at 1265px and 760px.
Labels, focus, input and actions remain legible; the narrow layout reflows.
The empty configured-account state was visible. Live Dola and Owner acceptance
remain unverified. Skill influence: preview/count confirmation, named scope,
distinct configured/live status and reuse of the existing Opening workspace.

UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: Settings Dola accounts rendered.
SCOPE_CLARITY=PASS: named additions/updates and single slot confirmation.
APPLY_REAPPLY_RESET_EXPLICITNESS=PASS: same alias updates, removal names alias.
ADVANCED_WITHOUT_DOMINATING=PASS: JSON import optional beside field.
DISABLED_STATE_EXPLANATION=PASS: configure Dola in Settings before generation.
BULK_DESTRUCTIVE_SAFETY=PASS: counts/names reviewed before save or removal.
VISIBLE_HIERARCHY=PASS: rendered Dola section with label/input/actions.
CONTROL_DENSITY=PASS: existing Settings section composition.
COHERENT_APPLICATION_COMPOSITION=PASS: existing Settings and Opening surfaces.
DESTRUCTIVE_DIFFERENTIATION=PASS: named removal confirmation.
EXISTING_WORKFLOW_PRESERVATION=PASS: related provider/application regression tests.
INFORMATION_ARCHITECTURE=PASS: settings own credentials; slots own generation.
NAVIGATION=PASS: Settings in primary navigation.
WORKSPACE_LAYOUT=PASS: existing layout reused.
VIEWPORT_BUDGET=PASS: rendered desktop and narrow Settings.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: generation attached to individual slots.
LAYOUT_ARCHETYPE_FIT=PASS: existing stacked Settings.
RESPONSIVE_WORKSPACE_BEHAVIOR=PASS: 760px Settings screenshot.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE: no layout redesign claimed.
TASK_FLOW_ARCHITECTURE=PASS: explicit setup then per-slot generation.
LINEAR_MULTISTEP_REASONING=PASS: short action with contextual confirmation.
REVIEW_BEFORE_COMMIT=PASS: account counts/aliases and video consequence confirmation.
EXECUTION_STATE_SEPARATION=PASS: existing runAction and slot state.
RESOURCE_MANAGEMENT_SEPARATION=PASS: accounts in Settings, clips in project.
POST_COMPLETION_DESTINATION=PASS: normalized slot preview in composed fixture.

technical_validation=PASS; candidate_preview=SETTINGS_DESKTOP_AND_NARROW.
Five levels: function=PASS; Settings discoverable=PASS; Settings understandable=PASS;
Settings hierarchy=PASS; Owner UX accepted=UNVERIFIED. Opening visual preview is
not yet observed with a real configured account. owner_ux_gate=NOT_REQUIRED.
