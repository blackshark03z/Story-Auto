# Quality and Acceptance V1

## Evidence hierarchy

```text
real runtime artifact
> integration/E2E
> focused unit/contract test
> static check
> written claim
```

A visibly wrong production artifact overrides a passing automated suite.

## Foundation gates

- strict narration parsing;
- atomic I/O;
- deterministic fingerprints;
- project lock;
- stage cache/resume;
- bounded retry;
- no provider/network calls.

## Audio gates

For each TTS provider:

- narration reconstruction preserved;
- output audio valid;
- canonical alignment covers narration in order;
- provider-specific error classification tested;
- no silent cross-provider fallback.

## Planning gates

- Gemini structured output validates;
- scene/shot timing ordered and within narration duration;
- continuity IDs resolve;
- media mode semantic validation passes;
- review approvals bind to artifact hashes;
- same inputs/settings produce deterministic stage fingerprints.

## Renderer local vertical slice

Synthetic/local fixture:

```text
image + video + hold + short narration + subtitles + optional BGM
→ normalized clips
→ render plan
→ final.mp4
```

Validate with FFprobe and inspect representative frames/output.

## Flow image live gate

Exactly one or a very small bounded request set:

- session/auth detection;
- prompt readback;
- result detection;
- local extraction/download;
- manifest provenance;
- resume does not duplicate a successful identical request.

## Flow video live gate

Exactly one bounded video request before any batch:

- capability discovery;
- safe submission;
- completion detection;
- download;
- FFprobe validation;
- source audio muted downstream;
- ambiguous timeout path tested or safely simulated.

## Hybrid production gate

First live production proof is 60–90 seconds:

- required video hook;
- image body;
- at least one representative transition;
- narration/subtitles;
- optional BGM;
- per-shot provenance/resume;
- human continuity/visual review.

Only after this passes may a full-length hybrid generation batch be proposed to the operator.

## UI gate

UI is not accepted merely because pages render. It must drive the exact same application services/artifacts as CLI for project setup, review, generation status, per-shot regenerate/approve, and render.

## Full-video gate

Before 18–24 minutes:

1. all-video 2–3 minute prototype;
2. every final visual segment resolves to video;
3. continuity review passes;
4. failed/missing shot blocks render;
5. resume/regenerate one shot does not invalidate unrelated successful generations;
6. explicit cost/batch confirmation.

Only then attempt one representative long-form run.

## Publishing gate

- title/description editable;
- thumbnail asset validated/approved;
- publishing package references the correct project/final content;
- no automatic YouTube upload.
