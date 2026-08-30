UX_CONTRACT
PRIMARY_USER=An operator turning a story or approved narration into a finished video without learning internal pipeline terminology.
PRIMARY_JOURNEY=New video source -> input -> output and quality -> review -> create video -> state-driven production workspace -> final video.
PRIMARY_SURFACE=Home opens New video; a created project opens its production workspace.
INFORMATION_HIERARCHY=Source, progress, current action, blocker, output, and effective project settings are primary; implementation evidence is Advanced/Diagnostics/History.
SCOPE_MODEL=Runtime defaults affect future projects only; each newly created project snapshots its effective production settings.
PRIMARY_CONTROLS=Create video, Continue production, Review visuals, Reconnect Flow, Open final video, and project More actions.
ADVANCED_CONTROLS=Technical state and provider detail are native disclosures, loaded only when opened.
STATES=Loading shell, disabled with a readiness reason, active progress, actionable blocker, manual decision, and completed output.
BULK_DESTRUCTIVE=NOT_APPLICABLE.
DISCOVERABILITY=The three source intents are the first visible New video choices; production action is the dominant project CTA.
ACCESSIBILITY=Semantic buttons, labelled choices, keyboard-native disclosures and dialog focus, text status, and explicit disabled reasons.
OWNER_PREFERENCE=NONE.

CREATE_FLOW_CONTRACT
TASK_GOAL=Create a video project from story content, existing audio, or audio plus matching SRT.
LINEAR_OR_NONLINEAR=linear; source validity determines input, output choices, review, and creation.
STEPS=Source -> Input -> Output & quality -> Review.
STEP_DEPENDENCIES=Only the selected source fields are required; imported sources require backend readiness before next/create.
BACK_BEHAVIOR=Back preserves the in-memory draft and selected files while the dialog remains open.
NEXT_VALIDATION=Server-owned import readiness gates continuation and is rechecked before creation.
FINAL_REVIEW_STEP=Review summarizes source, duration when known, output, quality, waveform, Flow readiness, and stage behaviour.
PRIMARY_COMMIT_ACTION=Create video creates a project with a durable snapshot of the effective defaults.
CANCEL_EXIT_BEHAVIOR=Cancel discards only the in-memory draft.
DRAFT_PERSISTENCE=The draft remains in memory for the open dialog only.
POST_SUBMIT_DESTINATION=The created project's production workspace.

WORKSPACE_CONTRACT
PRIMARY_TASK=Understand the current production state and take the one correct next action.
PRIMARY_WORKSPACE=Current action plus stage progression and blocker/owner decision.
PERSISTENT_REGIONS=Project title, status, stage progression, and primary CTA for orientation.
CONTEXTUAL_REGIONS=Blocker, preview, final output, and More actions appear only when relevant.
NAVIGATION_MODEL=Home and Settings remain top-level; project review and diagnostics are contextual.
LAYOUT_ARCHETYPE=Stacked production workspace with progressive disclosure.
VIEWPORT_BUDGET=Current action and blocker lead; technical controls do not occupy the default viewport.
CONTENT_REPLACEMENT_STRATEGY=Creation, active production, manual review, and completion use distinct primary states.
ADVANCED_CONTROL_STRATEGY=More actions and Advanced/Diagnostics/History contain compatibility controls and raw evidence.
EXPECTED_SCROLL_BEHAVIOR=Ordinary project operation remains within focused status, action, output, and summary sections.
ARCHETYPE_RATIONALE=The operator needs a single linear outcome, not simultaneous editing of internal pipeline modules.
