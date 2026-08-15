# Goal 10 UX design rationale

Status: implementation contract for `STORY-AUTO-GOAL-10-UX-UI-SIMPLIFICATION`

## Bounded research synthesis

- Microsoft Windows progress guidance distinguishes determinate work from unknown-duration work and recommends explanatory text alongside progress. Story Auto will show a six-stage production path, exact completed/total visual counts when canonical state provides them, and plain-language current activity rather than an unexplained spinner. Source: <https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/progress-controls>
- Microsoft navigation and command guidance treats app navigation as a small set of top-level destinations and keeps the most important commands visible first. Story Auto will keep Home and Settings as the persistent destinations, put one dominant project action in the project header, and place Diagnostics under Settings/Show details. Sources: <https://learn.microsoft.com/en-us/windows/apps/design/controls/navigationview> and <https://learn.microsoft.com/en-us/windows/apps/design/controls/command-bar>
- Material Design 3 progress, button, and interaction-state guidance was inspected at the official component pages. The site requires JavaScript in the research reader, so it was used as corroborating component guidance rather than as the only authority. Sources: <https://m3.material.io/components/progress-indicators/guidelines>, <https://m3.material.io/components/buttons/guidelines>, and <https://m3.material.io/foundations/interaction/states/overview>
- WCAG 2.2 requires visible keyboard focus, programmatically exposed status messages, and targets of at least 24 by 24 CSS pixels or sufficient spacing. Story Auto will use a strong `:focus-visible` ring, semantic status/progress regions, dialog focus behavior, persistent text labels, and primary controls at least 40 pixels high. Sources: <https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html>, <https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html>, and <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html>
- GOV.UK guidance says errors should state what happened and how to fix it, preserve entered answers, and provide a check-answers step immediately before consequential submission. Story Auto will retain wizard input after errors, associate content errors with the input, and show a Review & Create summary with Change actions before project creation. Sources: <https://design-system.service.gov.uk/components/error-message/> and <https://design-system.service.gov.uk/patterns/check-answers/>

## Existing running UI audit

The stable application was launched against the real Video 001 runtime and a separate empty audit runtime. The rendered audit found:

- A CSS rule overrides the native `hidden` attribute, leaving the first-run empty state visibly layered over a loaded project.
- Project navigation leads with opaque `prj_*` identities and render-mode codes rather than story titles, attention, progress, or next actions.
- The default project view displays eight low-level status tiles, raw manifest counts, `MEDIA_QC_REQUIRED`, and the full canonical narration editor.
- Planning exposes continuity JSON, shot IDs, media requirement codes, and three equal-weight actions.
- Production exposes one card per request with request/shot IDs, prompts, attempt history, and six equal-weight actions.
- Render exposes exact runtime paths and raw media-plan JSON as primary content; completion is not a distinct success experience.
- New project creation depends on sequential browser `prompt()` calls rather than a labeled, recoverable form; the in-app browser reports that `prompt()` is unsupported.
- There is no first-class Settings surface, provider-health summary, dedicated review experience, user-oriented progress screen, or diagnostics boundary.

Baseline evidence is under `docs/evidence/goal10/before/` and was captured from the actual running application. Missing baseline surfaces (Settings and first-class Review) are audit findings, not omitted screenshots.

## Skill discovery record

| Skill discovered | Path | Relevance | Influence |
| --- | --- | --- | --- |
| UX/UI Product Design v1.2.1 | `C:/Users/ADMIN/.codex/skills/ux-ui-product-design-v1.2.1/SKILL.md` | Primary | Required the UX, create-flow, execution, resource-library, and workspace contracts; separates technical validation from owner acceptance. |
| UX/UI Product Design v1.2.0 | `C:/Users/ADMIN/.codex/skills/ux-ui-product-design/SKILL.md` | Superseded relevant version | Inspected; v1.2.1 is the active implementation authority. |
| Browser | `C:/Users/ADMIN/.codex/plugins/cache/openai-bundled/browser/26.803.81509/skills/control-in-app-browser/SKILL.md` | Primary validation | Required real localhost walkthroughs, rendered screenshots, representative viewports, and browser cleanup. |
| Project lifecycle bootstrap | `D:/Youtube/_packages/build-os-v1.22-lifecycle-v1.1.2/skills/project-lifecycle-bootstrap/SKILL.md` | Required project authority | Established the adopted lifecycle, bounded authority reads, clean baseline, and current Goal 10 task. |
| Documentation handoff continuity | `D:/Youtube/_packages/build-os-v1.22-lifecycle-v1.1.2/skills/documentation-handoff-continuity/SKILL.md` | Required project authority | Established the bounded working-state sidecar and documentation-impact gate. |
| Git validation v1.22 | `D:/Youtube/_packages/build-os-v1.22-lifecycle-v1.1.2/skills/git-validation-v122/SKILL.md` | Closeout | Will govern focused commits, validation binding, and closeout inspection. |
| Python change v1.22 | `D:/Youtube/_packages/build-os-v1.22-lifecycle-v1.1.2/skills/python-change-v122/SKILL.md` | Application adapter/tests | Requires focused application-service seams, negative tests, integrated tests, and representative visual output. |
| Archived Build OS copies | `D:/Story Auto/story_auto_implementation_kit_v1.0.0/archives/.../skills/*/SKILL.md` | Provenance only | Discovered and intentionally not applied; the repository authority names the installed lifecycle v1.1.2 package as the only executor. |
| Visualize, Sites, artifact templates, documents, PDFs, presentations, spreadsheets, plugin management, and local memory skills | `C:/Users/ADMIN/.codex/plugins/cache/**/skills/**/SKILL.md` and `C:/Users/ADMIN/.codex/memories/skills/**/SKILL.md` | Not relevant | Discovered but not applied: this is an existing vanilla HTML/CSS/JS desktop UI, not a generated visualization, hosted Site, office artifact, plugin task, or storage-cleanup task. |

Repository-local `.agents`, `.codex`, `.claude`, and `skills` locations were searched recursively (including case variants of `SKILL.md`). No repository-local frontend, React, TypeScript, Playwright, CSS, or accessibility skill exists. The actual frontend is dependency-free HTML/CSS/JavaScript served by the Python loopback server, so no React/TypeScript skill applies and adding a large framework would conflict with the goal.

## UX contract

```text
UX_CONTRACT
PRIMARY_USER=A creator turning an approved story package into a finished long-form video.
PRIMARY_JOURNEY=Home -> New video -> Content -> Style & Voice -> Review & Create -> production -> review -> final video.
PRIMARY_SURFACE=Home, with New video as the dominant action and recent/attention projects below it.
INFORMATION_HIERARCHY=Next action and human status first; progress and useful project facts second; technical identifiers and raw evidence under details.
SCOPE_MODEL=One local Story Auto project at a time; Home manages the persisted project library.
PRIMARY_CONTROLS=New video, Continue/Back, Create video, Start/Resume, Review video, Open final video.
ADVANCED_CONTROLS=Wizard Advanced options, project Show details, and Settings Advanced/Diagnostics disclosures.
STATES=Purposeful empty Home; loading status; disabled controls with nearby reasons; actionable attention/error cards; complete success state.
BULK_DESTRUCTIVE=No new bulk/destructive behavior in Goal 10.
DISCOVERABILITY=Home answers what to do, what changed, and what needs attention without knowledge of pipeline internals.
ACCESSIBILITY=Semantic headings/landmarks, native dialog, labeled fields, keyboard order, visible focus, 40px controls, text status, live regions, accessible progress.
OWNER_PREFERENCE=Final visual/experiential quality remains the Goal's REVIEW_REQUIRED boundary.
```

## Create-flow contract

```text
CREATE_FLOW_CONTRACT
TASK_GOAL=Create a video project from approved content with a suitable default voice and production style.
LINEAR_OR_NONLINEAR=Linear; each decision depends on valid content and culminates in an expensive production-ready commit.
STEPS=1 Content; 2 Style & Voice; 3 Review & Create.
STEP_DEPENDENCIES=Content must contain one non-empty Narration section; style/voice use safe defaults; Review summarizes all outcome-affecting choices.
BACK_BEHAVIOR=Preserves entered content and selected settings.
NEXT_VALIDATION=Inline on Continue; errors remain associated with Content and entered text is retained.
FINAL_REVIEW_STEP=Story title, word count, estimated duration, narrator, production style, and advanced choices with Change actions.
PRIMARY_COMMIT_ACTION=Create video; creates the canonical project and lands on its production-ready surface.
CANCEL_EXIT_BEHAVIOR=Close returns to Home without creating a project; entered draft remains for the current app session.
DRAFT_PERSISTENCE=In-memory until project creation; browser default choices persist locally and contain no secrets.
POST_SUBMIT_DESTINATION=Project execution surface with Start production as the next action.
```

## Execution and resource-library contracts

```text
EXECUTION_CONTRACT
TRIGGER=Start production or Resume.
RUNNING_STATE=Six human stages with current activity; exact completed/total visual counts when available, otherwise indeterminate progress.
STATUS_SURFACE=The Project overview, also summarized on its Home card.
LOGS_DETAIL=Lazy Show details disclosure; never the default workspace.
CANCEL_OR_STOP=Pause safely where the canonical generation control supports it.
COMPLETED_STATE=Video preview, title, duration, output readiness, publishing status, and Open final video.
FAILED_STATE=Plain-language explanation, next action, retry availability, completed-work reassurance, expandable technical details.
RETURN_PATH=Home for project library; Review/Open final for results.

RESOURCE_LIBRARY_CONTRACT
RESOURCE_SCOPE=All existing projects, grouped by attention and recent work.
ROW_OR_ITEM_ACTIONS=One contextual primary action: Start, Resume, Review video, or Open final video.
STATUS_AND_OUTPUT=Human status, progress, updated time, duration/word count, and title; no opaque ID by default.
EMPTY_STATE=What Story Auto does plus the New video CTA.
SEARCH_FILTER=Not added; current local project scale does not justify it.
```

## Workspace contract

```text
WORKSPACE_CONTRACT
PRIMARY_TASK=Advance one video from ready content to reviewed final output.
PRIMARY_WORKSPACE=The current Home, wizard step, project state, review, or settings view replaces the previous view.
PERSISTENT_REGIONS=Compact adaptive navigation for Home and Settings plus application identity.
CONTEXTUAL_REGIONS=Project action/status, attention card, review media, and technical detail appear only for the relevant project state.
NAVIGATION_MODEL=Two top-level destinations; project cards open a project and Back to Home returns to the library.
LAYOUT_ARCHETYPE=Side navigation plus focused workspace; linear stacked content only inside each short wizard step; disclosure for diagnostics.
VIEWPORT_BUDGET=Primary action/header first, project status/progress second, supporting cards below; maximum readable content width on large desktops.
CONTENT_REPLACEMENT_STRATEGY=Home, wizard steps, execution, review/complete, settings, and diagnostics replace one another instead of stacking pipeline modules.
ADVANCED_CONTROL_STRATEGY=Native details disclosures and a Settings Advanced section; heavy diagnostic payloads lazy-load on demand.
EXPECTED_SCROLL_BEHAVIOR=Normal page scroll for project cards/review issues; no full narration or attempt ledger in the default project view.
ARCHETYPE_RATIONALE=The creator alternates between managing persisted projects and focusing on one lifecycle state; simultaneous pipeline-module comparison is not required.
```

## Implementation boundary

The canonical technical state remains unchanged. A small `OperatorService` presentation mapper will translate artifacts and manifest status into title, user status, current stage, progress, attention copy, review summary, and next action. The browser continues to call the loopback HTTP layer, which calls `OperatorService`, which calls the accepted core services. No frontend component writes provider or artifact internals directly.
