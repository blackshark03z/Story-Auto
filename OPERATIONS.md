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

## Kokoro Local TTS

Select `kokoro_local` explicitly in the project TTS settings and configure its
installed runtime path, voice, language, speed, device, and chunk size. The
adapter uses the installation's direct Python environment in offline model-cache
mode. Readiness is `LOCAL_RUNTIME_AVAILABLE`; no ElevenLabs/Typecast balance or
credential is consulted. Existing projects retain their configured provider.

## Local operator UI

Start with `python -m story_auto --runtime-root <root> ui`. The server is
loopback-only by design. Generation can be paused between provider requests;
resume reuses successful and QC-pending attempts. Asset replacement accepts an
explicit local file path and retains prior attempts in the manifest.

## Provider calls

Large batches are operator-confirmed. Full-video batch generation is always confirmation-gated. A bounded live smoke test is not permission for a large batch.

## Crash/restart

- Planning/checkpoint state is project-local and atomic.
- Provider attempts are manifest-backed and not overwritten.
- Resume reconciles ambiguous provider outcomes before re-submit.
- Composition writes to temporary outputs and atomically publishes only validated final artifacts where practical.

Render recovery expectations are executable behavior:

- missing `final.mp4` -> reuse provider/audio/planning/scene artifacts and compose only;
- missing normalized scene -> rebuild that scene and final render;
- invalid selected provider asset -> mark only that request retryable, preserve all
  attempts, reconcile/regenerate it, then rebuild render descendants;
- unchanged complete project -> no provider submissions and all stages SKIP.

## Hybrid production evidence

- Real prototype: `runtime/goal07_hybrid/projects/prj_goal07hybrid/output/final.mp4`
  (71.067 s, 1920x1080 H.264/AAC).
- Technical representative: `runtime/goal07_representative/projects/prj_goal07representative/output/final.mp4`
  (5.867 s, largest approved local content fixture).
- Representative publishing thumbnail:
  `runtime/goal07_representative/projects/prj_goal07representative/assets/image/req_thumbnail_884edd3158597839/manual_recovery_002.png`.
- Runtime roots are excluded from Git and contain no browser-profile copies in
  product artifacts. Evidence records hashes/metadata, never cookies or signed URLs.

Goal 08 release evidence distinguishes technical fixtures from production
acceptance. Run `python tools/goal08_production.py` after local reviews to rebuild
the sanitized inventory. Story Auto uses `GOOGLE_FLOW_WEB` for both images and
videos. Production Flow images are postprocessed locally inside the provider
adapter: preserve the raw provider file, verify its recorded hash, create the
clean derivative, and verify the derivative lineage before review or rendering.
A remaining visible mark on a production image is a QC failure. Flow video is
unchanged; its visible sparkle mark remains an `ACCEPTED_KNOWN_LIMITATION` and
must not be removed, covered, or cropped specifically to hide it.

Flow-bound prompts use a soft `BOTTOM_RIGHT` provider-mark safe area. Keep faces,
eyes, critical hand actions, important props/text, and focal details out of that
region where practical without making the shot unnatural. Subtitles remain a
centered lower-third with extra right-side clearance; subtitle boxes must not
cover the mark. Naturalness, anatomy, identity, continuity, material, and motion
defects remain normal QC failures. Every Flow image request must resolve and
verify `output_count=1` before dispatch. If local image cleanup fails or a clean
derivative is missing/corrupt, resume retries cleanup from the valid raw attempt
first. Do not requeue or resubmit Flow solely to repair a local derivative.

## Provider quality benchmark (closed)

Provider-selection research is `CLOSED_BY_OWNER_DECISION`. Do not run unfinished
Gemini API or Gemini Web cases. Preserve the API 429 attempts, partial Web
outputs, completed Flow baseline, ledger, mapping, and review artifacts as
provenance. Rebuild only the closure record with
`python tools/goal08_benchmark.py --close-by-owner-decision`.

## Disk preflight

Before generation/render, check writable paths and free disk. Rendering/generation must stop before predictable disk exhaustion; temporary/partial files are isolated from selected assets.

The application now enforces `settings.storage.minimum_free_bytes` (64 MiB by
default) before provider acquisition and rendering. Normalized clips and the
final video publish through validated sibling candidates, so an interruption or
failed replace preserves the prior selected output and removes partial candidates.

## Release/deployment

V1 is a local operator tool. There is no cloud deployment or YouTube publication pipeline. A release is an accepted Git baseline plus a locally runnable package/environment and verified representative runtime evidence.
