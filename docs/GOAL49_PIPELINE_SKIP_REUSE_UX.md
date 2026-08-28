# Goal49 Pipeline Skip / Reuse UX contract

UX_CONTRACT
PRIMARY_USER=Story Auto operator who already owns narration or accepted visuals and needs a predictable, lower-cost path to a finished video.
PRIMARY_JOURNEY=New video -> choose format, narration source, and execution intent -> review the exact work Story Auto will perform -> create video -> run/review project.
PRIMARY_SURFACE=New Video setup, Format and Voice step; persisted project overview shows the current stage policy.
INFORMATION_HIERARCHY=Format and Execution / Reuse are primary; Full Image duration is contextual to Full Image; technical provenance remains in review detail.
SCOPE_MODEL=Execution intent and imported narration bind to one project only; a later render setting affects only its render output.
PRIMARY_CONTROLS=Execution / Reuse choice, narration audio selection, clear unavailable reasons, Full Image scene duration and cadence.
ADVANCED_CONTROLS=NONE; provenance is visible as a concise state rather than a setup burden.
STATES=Unavailable modes name their missing prerequisite and remedy; imported audio is validated before project creation; invalid media remains untrusted and blocks creation.
BULK_DESTRUCTIVE=NOT_APPLICABLE.
DISCOVERABILITY=Execution / Reuse is a labelled choice group beside format and narrator in the normal New Video path.
ACCESSIBILITY=Native labelled radio/select/file controls, keyboard reachable disabled-state explanations, validation messages in the existing wizard alert area.
OWNER_PREFERENCE=NONE.

CREATE_FLOW_CONTRACT
TASK_GOAL=Create a video project that truthfully reuses supplied work and states what will run next.
LINEAR_OR_NONLINEAR=linear.
STEPS=Content -> Format, narration, and execution intent -> Review and create.
STEP_DEPENDENCIES=Approved narration precedes setup; each execution intent validates its required audio/assets before Review.
BACK_BEHAVIOR=Preserves content, format, narration selection, execution intent, and Full Image settings.
NEXT_VALIDATION=Intent and audio requirements are checked before Review; errors keep focus in the setup step with a direct correction.
FINAL_REVIEW_STEP=Summarizes narration source, execution intent, visual work, and Full Image duration before Create video.
PRIMARY_COMMIT_ACTION=Create video; creates and validates only local canonical project artifacts, without provider submission.
CANCEL_EXIT_BEHAVIOR=Closes the wizard without creating a project.
DRAFT_PERSISTENCE=Values remain in the open wizard; imported source is copied into the project only after Create video.
POST_SUBMIT_DESTINATION=Project execution state with a concise What Story Auto will do indicator.

UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: New Video setup exposes Execution / Reuse beside Format; project overview exposes persisted intent.
SCOPE_CLARITY=PASS: choices state which project artifacts are reused and disabled render-only states name the missing prerequisite.
APPLY_REAPPLY_RESET_EXPLICITNESS=NOT_APPLICABLE: this goal has no bulk apply or reset action.
ADVANCED_WITHOUT_DOMINATING=PASS: provenance is project detail; setup shows concise narration source and next work.
DISABLED_STATE_EXPLANATION=PASS: Render only is disabled with the exact accepted-visuals prerequisite message.
BULK_DESTRUCTIVE_SAFETY=NOT_APPLICABLE.
VISIBLE_HIERARCHY=PASS: format, execution intent, contextual Full Image settings, then narration source are ordered in the setup flow.
CONTROL_DENSITY=PASS: four mutually exclusive execution choices are grouped as one native radio fieldset.
COHERENT_APPLICATION_COMPOSITION=PASS: setup remains a three-step dialog; active-state controls stay on the project surface.
DESTRUCTIVE_DIFFERENTIATION=NOT_APPLICABLE.
EXISTING_WORKFLOW_PRESERVATION=PASS: FULL remains the default and existing formats retain their controls.
INFORMATION_ARCHITECTURE=PASS: source, execution intent, and work state are distinct operator concepts.
NAVIGATION=NOT_APPLICABLE: the existing linear wizard route is preserved.
WORKSPACE_LAYOUT=PASS: choice groups replace rather than append unrelated narrator fields; narrow layout keeps the wizard usable.
VIEWPORT_BUDGET=PASS: desktop and 800px rendered reviews retain readable cards and an internally scrolling dialog.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: Full Image duration is contextual; current intent is persistent on the project.
LAYOUT_ARCHETYPE_FIT=PASS: stacked linear wizard with contextual replacement fits configuration.
RESPONSIVE_WORKSPACE_BEHAVIOR=PASS: rendered at default desktop and 800px widths.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE: Goal49 does not target a sprawl reduction.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE: Goal49 does not target a workspace-layout replacement.
TASK_FLOW_ARCHITECTURE=PASS: Content -> Format, narration & reuse -> Review & Create.
LINEAR_MULTISTEP_REASONING=PASS: dependency validation happens before the next step and Review precedes create.
REVIEW_BEFORE_COMMIT=PASS: Review states narration source, execution intent, format, and next work before Create video.
EXECUTION_STATE_SEPARATION=PASS: project execution appears only after project creation.
RESOURCE_MANAGEMENT_SEPARATION=PASS: existing home/project resource model remains unchanged.
POST_COMPLETION_DESTINATION=PASS: completed project retains the project execution/review surface.
candidate_preview=PASS: local UI rendered at desktop and 800px widths on 2026-08-28; imported-voice canary was created through the normal UI.
owner_ux_gate=NOT_REQUIRED.
