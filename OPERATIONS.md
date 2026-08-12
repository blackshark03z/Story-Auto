# Operations

## Runtime boundary

Story Auto source code is separate from runtime data. Runtime root is configurable through `STORY_AUTO_HOME` or a platform-appropriate default chosen during implementation.

Expected runtime layout:

```text
STORY_AUTO_HOME/
  projects/<project-slug>/
  browser/flow-profile/
  cache/
  temp/
  logs/
  evidence/
  locks/
```

Never reuse YouTube Auto project/runtime/browser roots.

## Provider sessions

- Flow uses a dedicated Story Auto browser profile.
- `story-auto flow-open-session <project_id>` opens that isolated profile with
  its configured CDP endpoint. The operator signs in manually, then runs
  `story-auto flow-preflight <project_id>` before any paid execution.
- Operator logs in manually.
- Session/login expiry is reported as `AUTH_REQUIRED`.
- No automation of credentials/password entry.
- One active production Flow-generation project at a time per profile.

## Provider calls

Large batches are operator-confirmed. Full-video batch generation is always confirmation-gated. A bounded live smoke test is not permission for a large batch.

## Crash/restart

- Planning/checkpoint state is project-local and atomic.
- Provider attempts are manifest-backed and not overwritten.
- Resume reconciles ambiguous provider outcomes before re-submit.
- Composition writes to temporary outputs and atomically publishes only validated final artifacts where practical.

## Disk preflight

Before generation/render, check writable paths and free disk. Rendering/generation must stop before predictable disk exhaustion; temporary/partial files are isolated from selected assets.

## Release/deployment

V1 is a local operator tool. There is no cloud deployment or YouTube publication pipeline. A release is an accepted Git baseline plus a locally runnable package/environment and verified representative runtime evidence.
