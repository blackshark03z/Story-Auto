# Engineering Contract

## Delivery style

- Modular monolith; avoid plugin frameworks and speculative shared libraries.
- One bounded Build OS task at a time.
- One writer per task/worktree.
- CLI/application services first; UI later consumes the same services.
- Port YouTube Auto primitives selectively; never import YouTube Auto at runtime.
- Do not carry historical YouTube Auto schemas/composer/UI merely for compatibility.

## Artifact rules

- Every durable JSON artifact has an explicit schema version.
- Project-relative paths in durable artifacts; avoid machine-specific absolute paths.
- Atomic JSON/text writes.
- Direct-input hashes drive stage fingerprints.
- Generated attempts are never overwritten in place.
- A failed attempt never becomes cache-valid.
- Final manifests bind exact selected asset hashes and plan hashes.

## Checkpoint/invalidation rules

Invalidate only downstream stages that depend on changed inputs. Examples:

- narration text change → TTS/alignment and everything downstream;
- TTS voice/provider/settings change → TTS/alignment and downstream, not source content parsing;
- render mode change → media plan onward, not narration/alignment/story timeline;
- continuity edit → shot/media/prompt generation onward;
- single-shot prompt edit → only that request/asset selection/render segment and final render;
- BGM change → audio plan/final render only;
- title/description settings → publishing package only.

## Error handling

Provider/UI failures must be typed and retain stage/request/attempt context. Do not convert every error to a generic pipeline failure.

Media stages write to isolated candidate files and atomically replace durable
outputs only after validation. Provider destination directories exist before
dispatch. Resource preflights happen before paid acquisition or FFmpeg work.

No infinite retry loops. One initial attempt plus bounded automatic correction/retry is the normal default; further retries are an explicit new operator action or changed request.

## Flow execution and provenance contract

Treat the Flow manifest as a serial project queue, not a gallery-order work
list. A generating, dispatch-uncertain, attribution-uncertain, or
attribution-ambiguous attempt is a barrier across CLI, UI, batch, retry, and
resume. Before any next activation, reconcile the earliest unresolved attempt;
an unresolved result halts the queue.

Dispatch confirmation proves only that the provider accepted/started a request;
it does not prove which asset belongs to it. Record a stable pre-dispatch
provider surface and attribute only the stable request-specific output delta.
Exclude stale/foreign outputs. If more than one unlineaged candidate appears,
retain `OUTPUT_ATTRIBUTION_AMBIGUOUS`; never infer ownership from newest-card
order or timestamp proximity. Only confirmed attribution may enter
postprocessing or create `selected_asset`; attempts and reconciliation evidence
remain append-only.

## Credentials

Never commit secrets. Reuse/adapt the proven secure configuration/key-fallback patterns from YouTube Auto where useful, but give Story Auto its own namespace/store. Browser login is user-managed; do not automate passwords or bypass provider controls.

## Testing strategy

1. Contract/schema and pure-core unit tests.
2. Deterministic stage/checkpoint tests.
3. Provider page-fixture/mock tests with zero network.
4. Tiny FFmpeg/FFprobe integration fixtures created at test time.
5. Bounded live provider smoke tests only with explicit provider-call authorization.
6. 60–90 second hybrid production prototype.
7. 2–3 minute full-video prototype before any 18–24 minute full-video run.
8. Human/vision review can veto a green automated suite when the actual artifact is wrong.

Every production bug becomes the smallest reproducible fixture/test before the root-cause fix is accepted.

## Baseline executable quality gate

```text
python -m unittest discover -s tests -v
python tools/quality_gate.py
```

The offline suite includes tiny FFmpeg/FFprobe integration fixtures. A production
artifact review is still required for accepted runtime evidence and can veto both
commands when frame fit, transitions, subtitle readability, audio, or pacing fail.

## Provider-call policy

Offline tests are the default. Live TTS/Gemini/Flow calls require explicit task scope and a bounded request budget. Never let a long-running Codex Goal start a large Flow batch merely to prove code works.

## Porting provenance

Materially ported logic records source commit/module and adaptations in `docs/reference/YOUTUBE_AUTO_EXTRACTION_AUDIT.md` or a later migration note. Story Auto owns ported code after import.
