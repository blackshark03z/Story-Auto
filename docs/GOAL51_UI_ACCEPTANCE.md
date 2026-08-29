# Goal 51 — Operator UI acceptance

## Browser acceptance

Acceptance used a cold local browser session at `Home -> + New video` with the
short audible fixture and matching SRT from `D:\Story Auto\goal50-ui-canary`.
The disposable acceptance runtime is `D:\Story Auto\goal51-ui-canary`.

| Evidence state | Result |
| --- | --- |
| Initial input source selector | PASS — `STORY / CONTENT`, `EXISTING AUDIO`, and `AUDIO + SRT` were simultaneously visible. |
| Audio + SRT controls | PASS — both file controls were visible; after selection the UI showed `Audio: PASS · SRT: PASS · TIMING: SRT · TTS: SKIPPED`. |
| Full Image controls | PASS — `FULL IMAGE`, 10/15/20/30/60/custom duration, Fixed/Semantic Adaptive cadence, waveform state, and `AUTO CONTINUOUS ZOOM` were visible. |
| Audio + SRT review | PASS — 15 seconds, Fixed cadence, waveform OFF; summary showed import, `TTS: SKIP`, `Timing: SRT`, visual planning/image generation RUN, video generation SKIP, QC RUN, and Compose RUN. |
| Audio + SRT project | PASS — project `prj_013b5dbe69b34e299704507deea5e748` showed `Audio=IMPORTED`, `SRT=IMPORTED`, `TIMING SOURCE=SRT`, `TTS=SKIPPED`, Full Image 15 sec, waveform OFF, and reached the plan-review boundary through the normal UI. |
| Existing Audio project | PASS — project `prj_38d84bd6748f46408b8461f358c11554` was created from imported audio plus canonical narration text, showed `TTS=SKIPPED`, deterministic alignment, and Full Image 10 sec. |
| Existing project controls | PASS — `Generate / Continue visuals`, Full Image/timing facts, and `Render Again` were visible. With no accepted assets, Render Again was disabled with the exact reason. |

No image-generation submission was needed for acceptance; visual planning was
reached and stopped at the normal review boundary.

## Fail-closed checks

- Missing audio: `NARRATION_AUDIO_REQUIRED` / disabled explanatory state.
- Missing SRT: `SRT_REQUIRED` / disabled explanatory state.
- Malformed SRT: parser failure is returned without project creation.
- Audio/SRT mismatch: `AUDIO_SRT_DURATION_MISMATCH`.
- No accepted visual assets: Render Again remains disabled with its reason.

## UX implementation review

```text
UX_IMPLEMENTATION_REVIEW
PRIMARY_SURFACE_DISCOVERABILITY=PASS: cold Home -> New video begins with the three source choices.
SCOPE_CLARITY=PASS: each source card names imports, TTS behavior, and timing ownership.
APPLY_REAPPLY_RESET_EXPLICITNESS=NOT_APPLICABLE: no bulk action.
ADVANCED_WITHOUT_DOMINATING=PASS: fixed motion is exposed as a fact, not a setup burden.
DISABLED_STATE_EXPLANATION=PASS: missing source files and unavailable Render Again name exact reasons.
BULK_DESTRUCTIVE_SAFETY=NOT_APPLICABLE.
VISIBLE_HIERARCHY=PASS: source -> format -> review is explicit in the stepper.
CONTROL_DENSITY=PASS: only source-relevant inputs are rendered at each step.
COHERENT_APPLICATION_COMPOSITION=PASS: creation flow remains in the existing modal and project controls in project view.
DESTRUCTIVE_DIFFERENTIATION=NOT_APPLICABLE.
EXISTING_WORKFLOW_PRESERVATION=PASS: Story / Content retains its prior narration path.
INFORMATION_ARCHITECTURE=PASS: source is the primary entry decision.
NAVIGATION=PASS: Back preserves in-dialog selections and review has Change controls.
WORKSPACE_LAYOUT=NOT_APPLICABLE: bounded dialog flow, not a workspace redesign.
VIEWPORT_BUDGET=PASS: Full Image settings replace unrelated contextual settings.
PERSISTENT_CONTEXTUAL_CONTROLS=PASS: source and format are setup-only; persisted controls appear on project view.
LAYOUT_ARCHETYPE_FIT=PASS: linear three-step creation flow.
RESPONSIVE_WORKSPACE_BEHAVIOR=NOT_APPLICABLE: no responsive-layout scope change.
VERTICAL_SPRAWL_REDUCED=NOT_APPLICABLE.
WORKSPACE_LAYOUT_SOLUTION=NOT_APPLICABLE.
TASK_FLOW_ARCHITECTURE=PASS: explicit source, configuration, review, and commit progression.
LINEAR_MULTISTEP_REASONING=PASS: dependency-aware Next and Back behavior.
REVIEW_BEFORE_COMMIT=PASS: execution summary appears immediately before Create video.
EXECUTION_STATE_SEPARATION=PASS: creation transitions to the existing project execution surface.
RESOURCE_MANAGEMENT_SEPARATION=PASS: persisted controls remain on the project resource view.
POST_COMPLETION_DESTINATION=PASS: created project opens directly after Create video.
```
