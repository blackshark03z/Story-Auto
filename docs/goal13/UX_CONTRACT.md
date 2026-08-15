# Goal 13 UX Contract

```text
UX_CONTRACT
PRIMARY_USER=The single local operator creating a long-form story video from approved narration.
PRIMARY_JOURNEY=Home -> New video -> Content -> Format, style & voice -> Review -> Create video -> Project.
PRIMARY_SURFACE=The second New video step, where production intent is chosen before project creation.
INFORMATION_HIERARCHY=Format is primary; Ambient Style is contextual; narrator is supporting; technical policy stays in diagnostics.
SCOPE_MODEL=Format and style apply to the new project and persist when it is reopened or resumed.
PRIMARY_CONTROLS=Format, contextual Style, and Narrator; Review shows the resolved user-facing choices.
ADVANCED_CONTROLS=No motion, overlay, FFmpeg, budget, or QC tuning is exposed in the normal flow.
STATES=Ambient Style appears only for Ambient Story; invalid or missing choices return focus to the affected field with an actionable error.
BULK_DESTRUCTIVE=NOT_APPLICABLE; project creation is additive and Cancel safely exits without creating a project.
DISCOVERABILITY=All three formats are visible on the normal setup step without opening Advanced.
ACCESSIBILITY=Semantic fieldsets/legends, labelled controls, keyboard order, visible focus, live error/status text, and responsive card reflow.
OWNER_PREFERENCE=NONE; format names, two styles, progressive disclosure, and the existing flow are fixed by Goal 13.

CREATE_FLOW_CONTRACT
TASK_GOAL=Create a durable project with the chosen production format, Ambient style when applicable, and narrator.
LINEAR_OR_NONLINEAR=linear; content validity is required before production choices and final review.
STEPS=Content -> Format, style & voice -> Review & Create.
STEP_DEPENDENCIES=Valid Narration unlocks setup; a valid format and required Ambient style unlock review.
BACK_BEHAVIOR=Back preserves entered content and setup choices; Change links return to the relevant step.
NEXT_VALIDATION=Content validates on step 1; format/style validate on step 2 and return focus to the invalid control.
FINAL_REVIEW_STEP=Review summarizes story, narration length, narrator, format, and Ambient style when selected.
PRIMARY_COMMIT_ACTION=Create video creates one local project with the reviewed settings.
CANCEL_EXIT_BEHAVIOR=Cancel closes the dialog without creating a project; in-progress choices remain until reset by successful creation.
DRAFT_PERSISTENCE=The open wizard retains choices while moving Back/Continue; created settings persist in project.json.
POST_SUBMIT_DESTINATION=The newly created Project workspace, ready to start production.

WORKSPACE_CONTRACT
PRIMARY_TASK=Choose a production format and narrator for a new story project.
PRIMARY_WORKSPACE=The focused New video dialog step content.
PERSISTENT_REGIONS=Dialog title, three-step progress indicator, error summary, and Back/Continue actions preserve orientation.
CONTEXTUAL_REGIONS=Ambient Style replaces irrelevant style choices only when Ambient Story is selected.
NAVIGATION_MODEL=Linear stepper with Back, Continue, Change, Cancel, and Create video.
LAYOUT_ARCHETYPE=Stacked single page inside a short linear modal workflow.
VIEWPORT_BUDGET=One setup step at a time; format cards lead, contextual style follows, narrator remains compact.
CONTENT_REPLACEMENT_STRATEGY=Each step replaces the prior step; Ambient-specific choices render only for Ambient Story.
ADVANCED_CONTROL_STRATEGY=Technical policy is omitted from normal creation and remains inspectable through diagnostics artifacts.
EXPECTED_SCROLL_BEHAVIOR=Dialog content scrolls only at constrained heights; cards reflow to one column at narrow widths.
ARCHETYPE_RATIONALE=The existing three-step Goal 10 journey is short, ordered, and already owner-accepted.
```
