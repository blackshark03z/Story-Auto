# Goal48 FULL_IMAGE UX contract

UX_CONTRACT
PRIMARY_USER=Story Auto operator creating reliable long-form story videos.
PRIMARY_JOURNEY=New video -> choose Full Image settings -> review -> create project.
PRIMARY_SURFACE=New video Format and Voice step.
INFORMATION_HIERARCHY=Format is primary; Full Image controls replace unrelated style controls when selected.
SCOPE_MODEL=Controls apply to the new project only and persist as seconds-based project settings.
PRIMARY_CONTROLS=Format, image duration, cadence, audio visualizer, narrator, Create video.
ADVANCED_CONTROLS=NONE.
STATES=Invalid duration stays in the wizard with a direct correction message; settings are retained on Back.
BULK_DESTRUCTIVE=NOT_APPLICABLE.
DISCOVERABILITY=Full Image appears alongside existing visual formats in the normal creation selector.
ACCESSIBILITY=Native labelled controls, keyboard radio/select/input interaction, and wizard alert feedback.
OWNER_PREFERENCE=NONE.

CREATE_FLOW_CONTRACT
TASK_GOAL=Create a Full Image story-video project with predictable visual coverage.
LINEAR_OR_NONLINEAR=linear.
STEPS=Content -> Format and voice -> Review and create.
STEP_DEPENDENCIES=Valid narration before configuration; valid Full Image settings and installed narrator before review.
BACK_BEHAVIOR=Preserves entered content and settings.
NEXT_VALIDATION=Duration/cadence are checked before review and errors return to the current setup step.
FINAL_REVIEW_STEP=Shows format, duration, cadence, visualizer state, and narrator before project creation.
PRIMARY_COMMIT_ACTION=Create video; creates the local project only.
CANCEL_EXIT_BEHAVIOR=Closes the wizard without creating a project.
DRAFT_PERSISTENCE=Wizard values remain in the open dialog; browser defaults remain local.
POST_SUBMIT_DESTINATION=Project execution state.
