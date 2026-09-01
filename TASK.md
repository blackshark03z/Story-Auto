# FLOW_GENERATION_RECOVERY_DESIGN_BEFORE_IMPLEMENTATION

## Goal

Design and validate Story Auto's retry and recovery semantics for Google Flow
and partial visual-generation failure before implementation.

## Acceptance

- Distinguish provider terminal failure, provider ambiguity, local failure, and
  QC failure.
- Never redispatch blindly.
- Preserve completed assets.
- Retry only the unresolved logical visual when it is safe.
- Treat policy or content blocks differently from same-prompt transport retry.
- Do not generate new provider work because download or postprocessing failed.
- Make Continue production resume unresolved work rather than restart completed
  work.
- Show Working only while real active work is occurring.
- Freeze a recovery decision matrix before implementation.
- Define a fault-injection acceptance matrix before code.

## Constraints

- DESIGN/RESEARCH ONLY until Tech Lead approval.
- No Flow dispatch during design.
- Preserve unresolved provider evidence.
- Do not reconstruct a Build OS lifecycle.
- Do not build automatic retry architecture into Build OS.

## Currently observed blocker

Prior observation recorded project `prj_07b2054a43dc49429acdbfb6c9fb1140`,
request `req_c25fc3d16b0d3a621267`, provider `google_flow`, in `GENERATING`
with attempt `SUBMITTED` and `dispatch_confirmed=false`. This is an observed
historical working-context note, not a recovery decision: reread the runtime
evidence before relying on it or taking any action.
