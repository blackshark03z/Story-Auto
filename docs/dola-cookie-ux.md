# Dola cookie account settings

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
