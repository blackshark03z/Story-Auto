# Hybrid Visual / Opening Builder Research V1

Date: 2026-09-15
Status: RESEARCH_BASELINE / PRODUCT_DIRECTION_ACCEPTED
Related decision: `docs/decisions/0004-hybrid-visual-opening-builder.md`

## Research question

How should Story Auto evolve the still-image workflow so a long-form narrated video can use a 15–20 second manually/API-generated opening, animated still-image blocks, and relevant stock-video inserts while keeping narration, subtitles and waveform unchanged?

## Product conclusion

Use a mixed visual timeline over the existing master narration timeline. Do not create separate audio/subtitle pipelines per visual source.

The core abstraction should be a durable `Visual Slot` scheduled on the canonical timeline. `IMAGE`, `STOCK_VIDEO`, `AI_VIDEO` and `USER_VIDEO` are acquisition/render types behind the same slot contract.

V1 narrows the generic model to:

- Opening Builder: `USER_VIDEO` and optionally `AI_VIDEO`;
- body: `IMAGE` + `STOCK_VIDEO`;
- continuous existing narration/subtitle/waveform/audio layers.

This gives most of the perceived-motion/retention benefit of mixed media without making every body segment depend on AI-video credits and provider lifecycle complexity.

## Opening Builder findings

### Why 15–20 seconds

A short opening is long enough to provide a stronger visual hook while remaining bounded enough for manual generation and review. It also maps naturally to common external generation durations (roughly 5–10 seconds per clip) without requiring one provider to produce a single exact 20-second shot.

### Why slot-based manual round-trip is required

External/manual generation is not an edge case. It is a cost-control and provider-independence strategy.

A user must be able to:

- obtain exact prompts from Story Auto;
- generate clips outside the app using free credits, a web UI, or another provider;
- import those clips into explicit planned slots;
- let Story Auto normalize and compose them without losing timing/provenance.

The slot ID rather than filename is canonical. Slot-specific import is therefore the safest default interaction.

### Prompt-pack requirements

The exported opening package should include:

- opening-level shared continuity/style context;
- slot ID;
- intended duration/time range;
- shot purpose/acting beat;
- exact provider-neutral prompt;
- optional provider-specific hints kept separate from the canonical prompt;
- prompt SHA-256/version.

This lets manual and API generation share the same evidence model and supports exact replacement later.

## Duration adaptation research

Do not make external clip duration equal canonical slot identity.

Instead, treat imported duration as an observation and reconcile it against an allowed timeline envelope.

Recommended order:

1. accept exact/near-exact duration;
2. trim a longer clip to the slot;
3. rebalance neighboring opening slots while total opening stays within 15–20 s;
4. permit only tiny bounded speed/hold/transition compensation;
5. fail closed for material mismatch.

This avoids obvious slow-motion/time-stretch artifacts while allowing practical 5/6/8/10-second generator outputs.

## Mixed-media recipe research

A rigid `N images -> one stock clip -> repeat every X seconds` pattern will look automated. Use bounded variation instead.

Recommended starting envelope:

- image block 14–24 s;
- 2–5 images per image block;
- 4–7 s per image;
- stock clip 5–10 s;
- deterministic jitter from a stored run seed;
- forbid adjacent stock blocks by default;
- avoid reusing the same source asset inside the same final video.

Recommended still-image motion:

- slow zoom in;
- slow zoom out;
- pan left/right/up/down when composition allows;
- restrained push/pull;
- crop drift;
- dissolve/crossfade.

The purpose is to prevent visual stasis, not to turn the story video into an effects reel.

## Pexels API verification

Verified against official Pexels documentation on 2026-09-15:

- current video search endpoint: `GET https://api.pexels.com/v1/videos/search`;
- Pexels notes that video endpoints under `/v1/videos/` are the current path and the older `/videos/` path is to be deprecated;
- search requires a `query` and supports optional `orientation`, `size`, `locale`, `page`, and `per_page` parameters;
- supported orientation values include `landscape`, `portrait`, `square`;
- size filtering supports `large` (4K), `medium` (Full HD), `small` (HD);
- `vi-VN` is a supported locale, although production search may still choose normalized English semantic queries when retrieval quality is better;
- API authentication uses the `Authorization` header;
- default documented API limits are 200 requests/hour and 20,000 requests/month; Pexels provides response rate-limit headers and documents a process for requesting higher limits;
- API guidance requires a prominent Pexels link and asks applications to credit photographers/creators when possible;
- Pexels terms apply to API use and should be rechecked before release/promotion.

Official references:

- https://www.pexels.com/api/documentation/
- https://www.pexels.com/api/
- https://help.pexels.com/hc/en-us/articles/900005880463-What-are-the-Terms-and-Conditions
- https://help.pexels.com/hc/en-us/articles/900005852323-How-do-I-get-unlimited-requests

## Pexels production implications

### Search

Do not sample from global/popular stock at random for ordinary body slots.

Pipeline:

`narration segment -> semantic concepts -> bounded query set -> Pexels video search -> technical/relevance filtering -> deterministic selection -> local cache -> slot binding`

Store at least:

- provider = Pexels;
- Pexels video ID;
- creator name/ID when available;
- source/page URL;
- search query/locale;
- selected video-file URL metadata needed for acquisition;
- local asset SHA-256;
- project slot ID;
- attribution fields;
- rate-limit observations when useful for diagnostics.

### Candidate filtering

Before selection, prefer candidates that satisfy:

- project orientation/aspect needs;
- sufficient resolution for target output;
- duration compatible with the slot or safely trimmable;
- no obvious unusable/watermarked/text-heavy composition when detectable;
- semantic relevance to the narration segment;
- no duplicate/recently reused provider asset in the same project.

### Determinism and caching

Once selected, provider asset identity becomes durable run state. A rerender must not silently re-search and select a different clip.

Download/cache the chosen asset locally and bind by hash before render. Network/Pexels failures during rerender should use the cached copy when valid.

### Failure policy

Pexels is an enhancement layer, not a whole-project blocker.

For an unresolved ordinary stock slot, the preferred fallback is a compatible image slot generated from the same semantic segment, or an explicit recoverable state if the owner configured stock as required.

Do not substitute an unrelated stock video solely to keep rendering moving.

## Master-track contract

Hybrid Visual must preserve current Story Auto ownership:

- narration/audio duration is canonical;
- subtitle timestamps remain tied to narration, not visual asset boundaries;
- waveform is generated/composited from the same master audio;
- BGM/mix remains independent of visual source;
- imported/generated visual clip audio is ignored by default.

This is the key reason Hybrid Visual can be added without rebuilding the audio/subtitle pipeline.

## Suggested canonical data shape

A future schema can model slots approximately as:

- `slot_id`
- `start`, `end`, `target_duration`
- `visual_type`
- `purpose`
- `semantic_context`
- `source_policy`
- `prompt_snapshot` / `prompt_sha256` when applicable
- `provider_query` / provider asset identity when applicable
- `source_asset`
- `normalized_asset`
- `effect`
- `transition`
- `fallback_policy`
- `status`
- `replacement_history`

Exact schema remains an implementation task; these fields are design requirements, not frozen serialization names.

## Recommended implementation slices

### Slice H1 — contract + planner

- new Hybrid Visual mode without changing Full Image behavior;
- visual-slot schema;
- 15–20 s opening planner;
- prompt-pack export;
- no provider calls.

### Slice H2 — manual Opening Builder

- slot cards;
- per-slot import/replace;
- media probe/normalize/hash;
- duration reconciliation;
- opening-only render proof;
- master audio/subtitle/waveform continuity proof.

This slice should be Product Acceptance-capable without any AI-video API.

### Slice H3 — optional opening API acquisition

- provider adapter behind the same opening-slot contract;
- manual fallback remains first-class;
- provider consequence/retry semantics reuse CADS lessons from Goal 54 where applicable.

### Slice H4 — Pexels stock body blocks

- semantic query planner;
- API client and rate-limit observability;
- deterministic candidate selection;
- cache/provenance/attribution;
- image fallback.

### Slice H5 — mixed compositor + UI polish

- full timeline recipe;
- image motion/effects;
- stock-video insertion;
- preview recipe;
- final E2E product acceptance.

## Open questions to resolve before implementation freeze

These are not blockers to recording the product direction, but must be settled before Slice H1/H2 is considered accepted:

- default opening target: 15 s, 18 s, or adaptive 15–20 s;
- exact safe tolerance for short imported clips;
- whether user-imported opening clips may optionally preserve their own audio for special cases;
- default image/stock mix presets and stock frequency;
- whether the UI exposes attribution in-project or only stores it for an export/description package;
- whether Pexels semantic query generation is deterministic template/LLM-based or hybrid.

## Recommendation

Start with H1 + H2 and prove the entire manual round-trip first. That yields immediate value and lets the owner use any external/free video generator without waiting for one API provider. Add Pexels only after the slot/timeline/import contract is stable.
