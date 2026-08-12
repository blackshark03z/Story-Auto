# Failure and Recovery Design V1

## Principle

A local long-form generator is successful only when partial failure is cheap to diagnose and cheap to resume.

## Stage failure classes

Minimum semantic classes:

```text
INPUT_INVALID
PROJECT_INVALID
PROJECT_LOCKED
CHECKPOINT_CORRUPT
AUTH_REQUIRED
PROVIDER_CAPABILITY_UNAVAILABLE
PROVIDER_UI_CHANGED
PROVIDER_RATE_LIMIT
PROVIDER_CREDIT_BLOCKED
PROVIDER_TIMEOUT_AMBIGUOUS
PROVIDER_GENERATION_FAILED
ASSET_DOWNLOAD_FAILED
ASSET_INVALID
CREATIVE_REJECTED
DISK_PREFLIGHT_FAILED
FFMPEG_FAILED
SUBTITLE_FAILED
REQUIRED_MEDIA_UNRESOLVED
```

Provider adapters may add internal detail but must map to stable product-facing classes.

## Request states

```text
PENDING
SUBMITTED
GENERATING
SUCCEEDED
FAILED_RETRYABLE
FAILED_PERMANENT
AUTH_REQUIRED
CREDIT_BLOCKED
UI_CHANGED
CANCELLED
```

Asset review is separate (`APPROVED / REJECTED / UNREVIEWED`).

## Ambiguous submit/timeout rule

Never blindly submit again after a timeout that occurred after dispatch.

Resume sequence:

1. inspect manifest request identity and last attempt;
2. query/inspect provider-visible result state where safely possible;
3. search downloaded/provider candidates tied to the request context;
4. if completion is proven, ingest/validate it;
5. only when non-completion is established or reconciliation policy permits, create a new attempt.

## Retry stop-loss

Default maximum automatic attempts per request: 2. No infinite polling. Manual regenerate is a new explicit operator action and remains visible in history/cost accounting.

## Flow UI drift

Selectors/page assumptions are centralized. If the adapter cannot identify exactly one safe composer/action/result boundary, fail closed as `PROVIDER_UI_CHANGED` and capture sanitized diagnostics. Do not broaden selectors or click ambiguous controls as a recovery heuristic.

## Browser/auth failure

Expired login → `AUTH_REQUIRED`. Browser/profile lock → explicit session error. Never silently launch against the YouTube Auto profile.

## Asset validation

Image: decodable, expected dimensions/aspect bounds, non-placeholder checks where practical, hash.  
Video: FFprobe-readable video stream, minimum sensible duration, dimensions/aspect, hash. Generated audio is ignored/muted.

Provider success is not enough; invalid local media is not selectable.

## Project interruption

- JSON/text writes atomic.
- Media downloads use temporary filenames until validated.
- Checkpoints are never valid when required outputs are missing/invalid.
- Generated attempts remain immutable.
- `resume` works at both stage and request level.

## Dependency invalidation examples

| Change | Minimum invalidation |
|---|---|
| `content.md` narration | TTS onward |
| TTS provider/voice/settings | TTS/alignment onward |
| Gemini model/prompt contract for timeline | affected planning stage onward |
| render mode | media plan onward |
| continuity edit | shot/media/request generation onward |
| shot timing/edit | media/request/render for affected downstream dependency |
| one prompt edit | that request/asset/render segment + final render |
| approved reference change | only requests using that reference + render descendants |
| BGM | audio plan + final render |
| title/description generation settings | publishing only |
| Flow browser selector implementation | no planning invalidation; provider requests may need rerun only if unresolved |

## Full-video hard rule

`full_video_ai` cannot resolve a failed required video shot to a still. Render stays blocked until an approved video source exists.

## Hybrid fallback rule

Fallback occurs only when `media_plan` explicitly allows it. Every fallback is recorded in `render_plan` and final provenance.

## Disk

Preflight generation/render. Do not begin a large batch/render when projected free space is below the configured safety margin. Temp files are isolated and cleanup never deletes selected/raw assets without explicit retention policy.

## Final render

Write candidate output to a temporary path. Validate streams/duration/dimensions before publishing as `final.mp4`. A failed final encode must not destroy the previous accepted final output.
