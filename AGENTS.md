# Story Auto operating map

Start from the repository as it is now. Read `TASK.md`, `ARCHITECTURE.md`,
the relevant README and product documentation, Git status and history, and the
source, tests, and runtime artifacts relevant to the requested work before
changing anything.

## Sources of authority

- Git owns product history and the current source baseline.
- Tests and CI own verification truth.
- The Owner and Tech Lead own product intent and approvals.
- A Worker owns ordinary reversible implementation decisions within the
  approved task scope.
- Preserve owner work. Do not reset, clean, overwrite, or silently stage it.

## Normal development

Normal development uses native Git, an editor, and the applicable tests.
`TASK.md` supplies active working context; it is not lifecycle state. Use
Simplified Build OS only when it is available, explicitly requested, and the
work crosses a consequential boundary. It does not replace normal development
or become repository-wide execution authority.

The legacy `.buildos` records and historical authority files are provenance,
not active authority. Do not reconstruct or migrate their lifecycle state.

## Provider and runtime safety

Never blindly retry a Flow or other provider request. Before a dispatch or
recovery decision, reread the relevant runtime provider evidence and preserve
ambiguous attempts and completed assets. Product-level generation-manifest
reconciliation remains Story Auto behavior; it is separate from any
consequential-effect guard.
