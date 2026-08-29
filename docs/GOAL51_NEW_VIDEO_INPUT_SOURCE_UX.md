# Goal 51 — New Video input-source UX

```text
UX_CONTRACT
PRIMARY_USER=An operator who may begin with approved story text, existing narration audio, or matched audio plus SRT.
PRIMARY_JOURNEY=Home -> New video -> choose input source -> configure format -> review execution -> Create video -> project visual planning.
PRIMARY_SURFACE=The first screen of the New Video wizard, opened from Home.
INFORMATION_HIERARCHY=Input source is first; format and Full Image controls are second; the final execution summary is the commitment review.
SCOPE_MODEL=Every choice applies to the new project only; imported audio and SRT become canonical project artifacts after validation.
PRIMARY_CONTROLS=Story / Content, Existing Audio, Audio + SRT, Full Image duration/cadence/waveform, and Create video.
ADVANCED_CONTROLS=NONE; motion remains the fixed canonical AUTO CONTINUOUS ZOOM policy and is shown as a resolved fact.
STATES=Missing files, unreadable audio, malformed SRT, and duration mismatch block Create with the exact reason and remedy.
BULK_DESTRUCTIVE=NOT_APPLICABLE.
DISCOVERABILITY=All three input-source choices are visible immediately after Home -> New video.
ACCESSIBILITY=Native radios, file inputs, labels, status text, focusable errors, and disabled Create reasons.
OWNER_PREFERENCE=NONE.

CREATE_FLOW_CONTRACT
TASK_GOAL=Create a project that can plan and produce visuals from the operator's available source.
LINEAR_OR_NONLINEAR=linear; source validity determines the available next configuration step.
STEPS=Input source -> Format and Full Image settings -> Review and Create.
STEP_DEPENDENCIES=Story needs valid narration; Existing Audio needs readable audio plus canonical narration text; Audio + SRT needs both files and a matching timeline.
BACK_BEHAVIOR=Back preserves selected source, imported files, source text, and format settings.
NEXT_VALIDATION=Source validation occurs after file selection and is repeated server-side on Create; errors remain at their source field.
FINAL_REVIEW_STEP=Review summarizes import/skip/run/reuse behavior immediately before project creation.
PRIMARY_COMMIT_ACTION=Create video; creates the project with the selected source and canonical settings.
CANCEL_EXIT_BEHAVIOR=Cancel closes the dialog without creating a project.
DRAFT_PERSISTENCE=No cross-session draft; in-dialog values survive Back.
POST_SUBMIT_DESTINATION=The created project's execution state, where planning/visual controls remain visible.
```
