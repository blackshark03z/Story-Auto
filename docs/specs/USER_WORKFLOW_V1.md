# User Workflow V1

## Create

1. Create/import project from `content.md`.
2. Select `hybrid_hook` or `full_video_ai`.
3. Select ElevenLabs/Typecast voice and settings.
4. Optional: select local/licensed BGM.
5. Validate provider credentials/session capability without spending large credits.

## Plan

1. Generate narration.
2. Normalize alignment.
3. Generate story timeline.
4. Generate continuity bible.
5. Generate shot plan.
6. Generate media plan according to render mode.
7. Operator reviews continuity + shot plan and edits/approves.

## Reference pass

1. Compile reference-image requests for recurring characters, locations, and important props.
2. Show planned request count.
3. Generate bounded reference set with Flow.
4. Operator approves/rejects/regenerates references.

## Main generation

1. Compile shot generation requests from approved plans + approved references.
2. Show request counts and estimated cost/credits when provider capability exposes them.
3. Require explicit batch confirmation according to guardrail policy.
4. Generate with per-request state/resume.
5. Operator reviews assets and resolves rejects/regenerates/overrides.

## Render

1. Resolve exact selected sources to `render_plan.json`.
2. Block if required media is unresolved.
3. Normalize sources to silent MP4 clips.
4. Generate subtitles.
5. Mix narration + optional BGM.
6. Compose `final.mp4`.
7. Validate duration, streams, dimensions, and representative visual output.

## Publishing package

1. Gemini creates title candidates + description.
2. Operator can edit/select.
3. Generate thumbnail brief/request and Flow image.
4. Operator approves/selects thumbnail.
5. Persist `publishing_package.json`.

## Resume

`status` reports the next blocked/runnable action. Resume never means re-run everything. Valid unchanged artifacts/assets are reused; only invalidated or unresolved work proceeds.

## Regenerate one shot

1. Select shot.
2. Optional prompt edit or request revision.
3. New generation request/attempt; old attempt retained.
4. Review/select candidate.
5. Only dependent render segment/final output becomes stale.
