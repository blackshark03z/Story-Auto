# Story Auto operating map

Start from the repository as it is now. Read `TASK.md`, `ARCHITECTURE.md`,
the relevant README and product documentation, Git status and history, and the
source, tests, and runtime artifacts relevant to the requested work before
changing anything.

## Sources of authority

- Identified Git/source owns implementation reality and product history.
- Identified runtime evidence owns observed behavior for the source,
  configuration, and environment actually exercised.
- Tests and CI provide verification evidence; they do not by themselves prove
  Product Goal acceptance.
- The Owner owns desired product outcome, material product trade-offs,
  consequential authorization, and subjective real-use acceptance where human
  experience is the oracle.
- The AI Tech Lead/Worker owns ordinary reversible engineering judgment within
  established intent and authority.
- Preserve owner work. Do not reset, clean, overwrite, or silently stage it.

## CADS working model

Normal development uses native Git, an editor, and the applicable tests.
`TASK.md` supplies active working context; it is not lifecycle state. Use five
reasoning controls rather than a persisted lifecycle: **Reality -> Intent / Design
-> Change -> Acceptance -> Consequence**. Make the minimum sufficient change and
prefer `REUSE -> WIRE -> FIX -> REPLACE_AND_DELETE -> ADD`; abstract demonstrated
volatility rather than hypothetical possibility.

For multi-step user-facing work, define a representative Critical User Journey
and prove the composed journey on the supported surface. Isolated feature or
subsystem PASS does not establish Product Goal acceptance. When durable
system/provider/runtime/data/deployment/trust shape is material, apply CADS
Architecture Description conditionally: `ARCHITECTURE.md` describes current
durable truth and concern-driven views, while accepted rationale that could
change a later session's approach belongs in `docs/decisions/`. Architecture
prose never outranks identified Git/runtime reality. Chat memory and agent
reports are not authority.

The legacy `.buildos` records and historical authority files are provenance,
not active authority. Do not reconstruct or migrate their lifecycle state.

## Provider and runtime safety

Never blindly retry a Flow or other provider request. Before a dispatch or
recovery decision, reread the relevant runtime provider evidence and preserve
ambiguous attempts and completed assets. Product-level generation-manifest
reconciliation remains Story Auto behavior; it is separate from any
consequential-effect guard.
