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
mode. For durable recovery, configure `model_cache` as the canonical
`models--hexgrad--Kokoro-82M` cache directory and pin `model_snapshot` to the
required 40-character revision. New-project defaults preserve these two fields;
`STORY_AUTO_KOKORO_MODEL_CACHE` and `STORY_AUTO_KOKORO_MODEL_SNAPSHOT` provide
the same defaults when no project has established them.

Kokoro is `Ready` only after a local, load-only probe initializes the configured
model and selected voice through Kokoro's own Python interpreter. The probe does
not synthesize narration or use a network and caches a successful result against
the runtime/model/voice file identities. Missing runtime, model, voice, invalid
configuration, and runtime-load failures are reported separately. Production
uses this same readiness authority before TTS checkpoint mutation, Gemini
planning, or Flow work; no ElevenLabs/Typecast balance or credential is
consulted. Existing projects retain their configured provider.

## Local operator UI

Start with `python -m story_auto --runtime-root <root> ui`. The server is
loopback-only by design. Generation can be paused between provider requests;
resume reuses successful and QC-pending attempts. Asset replacement accepts an
explicit local file path and retains prior attempts in the manifest.

## Ambient Story

Create an Ambient project through the normal New video **Format** control or:

```text
python -m story_auto --runtime-root runtime new --project-id prj_ambient_example --render-mode ambient_story --ambient-style quiet_verdict
```

Valid styles are `quiet_verdict` and `hidden_mastery`. Ambient planning must
produce only required image requests; a video request or video media override
is a policy failure. Temporal video QC is not run. Semantic/naturalness/visible-
mark QC, exact selected-asset mapping, Flow image cleanup, subtitles, narration,
BGM, rendering, resume, and publishing continue through their existing paths.

Quiet Verdict prefers 2–5 images with a hard maximum of 8; Hidden Mastery
prefers 4–7 with a hard maximum of 10. Preferred counts are not permission to
merge incompatible narrative states. A preferred-budget overflow records
`SEMANTIC_STATE_INCOMPATIBILITY`; a hard-limit overflow stops at visual
planning.

Ambient Flow IMAGE prompts use the centralized 1,200-character provider limit
and a 1,100-character internal target. If a required structured visual brief
cannot fit, no Flow call occurs. The normal project state says **Visual planning
needs to be regenerated**; expand Technical details for the exact failure code.
Resume from visual planning. Existing content, TTS audio, and canonical
alignment remain valid unless their own inputs changed.

Rebuild the two provider-free engineering demos with:

```text
python tools/ambient_demo.py
```

The command writes ignored runtime evidence under
`runtime/goal13_ambient_demos/`, including both MP4s, contact sheets, resolved
render/presentation plans, black-frame results, and an explicit provider-call
counter. It must remain zero. Real long-form trials are separate operator work.

## Provider calls

Large batches are operator-confirmed. Full-video batch generation is always confirmation-gated. A bounded live smoke test is not permission for a large batch.

## Crash/restart

- Planning/checkpoint state is project-local and atomic.
- Provider attempts are manifest-backed and not overwritten.
- Resume reconciles the earliest unresolved Flow dispatch/output attribution
  before any new activation. If provider-visible evidence remains ambiguous,
  the entire serial project queue stays halted; do not click Generate again.
- A Flow activation requires a stable pre-dispatch tile/asset baseline.
  Dispatch confirmation does not confirm an asset. Only one stable,
  request-specific provider delta may be downloaded and selected; multiple
  unseen candidates require reconciliation, never newest-card or timestamp
  selection. Stale/foreign provider output is excluded; postprocessing and
  `selected_asset` require confirmed attribution.
- Composition writes to temporary outputs and atomically publishes only validated final artifacts where practical.

Render recovery expectations are executable behavior:

- missing `final.mp4` -> reuse provider/audio/planning/scene artifacts and compose only;
- missing normalized scene -> rebuild that scene and final render;
- invalid selected provider asset -> mark only that request retryable, preserve all
  attempts, reconcile/regenerate it, then rebuild render descendants;
- unchanged complete project -> no provider submissions and all stages SKIP.

### Preserved Trial A resume gate

The preserved Quiet Verdict Trial A project is
`prj_4f895eb1436c42c4ba5b908381b14fd1`. Its earliest unresolved Flow request is
`req_28728acbcab5522b8685` (`FLOW_DISPATCH_UNCERTAIN`); a later request also
remains dispatch-uncertain and a separate request is
`OUTPUT_ATTRIBUTION_INVALID`. The first request's initial attempt is already
recorded `NOT_DISPATCHED`, but its second reconciliation remains ambiguous; the
invalidated request has no selected asset. These records and their raw/clean
evidence remain append-only. Resume only through the normal
reconciliation/barrier path, which must reconcile the earliest unresolved
attempt before any activation. If it remains unresolved or ambiguous, stop
with the queue halted. Do not re-submit, adopt a gallery output, or start Trial
B.

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
A remaining visible mark on a production image is a QC failure. The supported
Flow IMAGE profiles are `1280x720 v1` and `1376x768 v1`; any other geometry
fails closed locally. Flow video is
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
