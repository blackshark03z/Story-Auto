UX_CONTRACT
PRIMARY_USER=An operator importing narration audio and matching SRT timing for a new video.
PRIMARY_JOURNEY=New Video -> Audio + SRT -> choose files -> understand readiness -> Continue -> review -> Create video.
PRIMARY_SURFACE=New Video, Input source step.
INFORMATION_HIERARCHY=Overall readiness is primary; audio, SRT, and timeline measurements explain it.
SCOPE_MODEL=Readiness applies only to the current draft, selected source mode, audio file, and SRT file.
PRIMARY_CONTROLS=Audio picker, SRT picker, Continue, Back, Create video.
ADVANCED_CONTROLS=NONE.
STATES=No files | validating | ready | blocked with measured reason and remedy.
BULK_DESTRUCTIVE=NOT_APPLICABLE.
DISCOVERABILITY=Audio + SRT is a first-step input-source choice in New Video.
ACCESSIBILITY=Field labels, live/readable status text, disabled Continue reason, and preserved keyboard wizard flow.
OWNER_PREFERENCE=NONE.

CREATE_FLOW_CONTRACT
TASK_GOAL=Create a video project from a validated narration import.
LINEAR_OR_NONLINEAR=linear; imported files must be ready before format and review.
STEPS=Input source -> Format & output -> Review & Create.
STEP_DEPENDENCIES=Audio + SRT requires canonical ImportReadiness READY before continuing from Input source.
BACK_BEHAVIOR=Back preserves the draft and its current readiness until an input changes.
NEXT_VALIDATION=Validation occurs after selection; stale responses never replace newer file identities.
FINAL_REVIEW_STEP=Review & Create summarizes source and output before project creation.
PRIMARY_COMMIT_ACTION=Create video creates one local project only after server-side readiness revalidation.
CANCEL_EXIT_BEHAVIOR=Cancel discards the in-memory draft.
DRAFT_PERSISTENCE=The current in-memory wizard draft remains while the dialog stays open.
POST_SUBMIT_DESTINATION=Created project view.
