# Hybrid Visual H4 — semantic Pexels stock-video foundation

Date: 2026-09-16
Status: ENGINEERING_COMPLETE / LIVE_KEY_NOT_EXERCISED / RELEASE_DISABLED

## Scope

H4 adds the body-level image/stock recipe and a production-safe Pexels adapter without release-enabling `hybrid_hook` and without making a live Pexels API request during qualification.

H1/H2 Opening Builder remains the canonical opening contract. H4 starts at the durable opening end and follows the narration/alignment master clock to the final audio duration.

## Current Pexels verification

Official Pexels docs were rechecked on 2026-09-16 before implementation:

- video search: `GET https://api.pexels.com/v1/videos/search`;
- API key is sent through the `Authorization` header;
- search supports `query`, `orientation`, `size`, `locale`, `page`, and `per_page`;
- default documented limits remain 200 requests/hour and 20,000 requests/month;
- rate-limit diagnostics are projected from `X-Ratelimit-Limit`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset`;
- Pexels recommends query normalization and response caching; approximately 24 hours is explicitly suggested as a useful cache duration;
- product surface must link prominently to Pexels and should retain creator/source attribution.

References remain recorded in `docs/HYBRID_VISUAL_RESEARCH_V1.md`.

## Body recipe contract

Canonical artifact: `output/hybrid_body_plan.json` (`story-auto-hybrid-body-plan/1.0.0`).

Default recipe after the opening:

- image slot: 6 seconds;
- 3 image slots per image block;
- stock slot: 7 seconds;
- stock duration is constrained to 5–10 seconds;
- image motion rotates through restrained zoom/pan/push effects;
- exact timing is contiguous and non-overlapping until master narration duration;
- semantic context comes only from narration segments overlapping the slot;
- stock query is deterministic from that semantic context;
- every stock slot has `fallback_policy=IMAGE`.

The body planner is provider-free. It does not search Pexels while planning.

## Pexels search / selection contract

The client:

- never persists the API key;
- normalizes video/creator/source/file metadata and attribution;
- observes rate-limit headers;
- uses a deterministic cache identity from normalized query + search options;
- caches successful search results locally for 24 hours by default;
- parses only HTTPS downloadable video files;
- deterministically selects within the top relevant compatible candidates;
- excludes already-selected Pexels asset IDs in the same project;
- requires sufficient clip duration and selects the most compatible available MP4 for the render target.

Search failure/no compatible candidate is a body-slot fallback boundary, not a whole-project failure.

## Acquisition / local asset contract

`resolve_pexels_stock_slot(...)` performs one bounded slot journey:

`cached search -> deterministic candidate -> persisted provider selection -> bounded Pexels-domain download -> FFmpeg normalize -> silent SHA-bound local asset`

Important invariants:

- provider selection is durable before acquisition;
- once a valid normalized asset exists, resolving that slot is idempotent and does not search/download again;
- downloads are HTTPS and restricted to `pexels.com` subdomains;
- download size is bounded;
- source bytes and normalized bytes are project-owned and hash-bound;
- embedded stock audio is stripped so narration/BGM/subtitles/waveform remain master tracks;
- rerender can use the local normalized asset without Pexels availability.

## Product observability

For development/existing `hybrid_hook` projects, the workspace exposes:

- provider-free `Plan body recipe` action;
- stock slot timing/query/status;
- explicit one-slot Pexels resolution action;
- Pexels source/creator attribution when selected;
- prominent `Stock videos provided by Pexels` link.

`hybrid_hook` still resolves to `FEATURE_NOT_AVAILABLE`; H4 does not bypass activation/promotion gates.

## Verification

Targeted H4 suite: `7 tests` PASS.

Coverage includes:

- mocked Pexels API authorization/search normalization;
- rate-limit projection and no key leakage into persisted result;
- 24-hour cache reuse;
- deterministic top-relevant candidate selection;
- same-project duplicate avoidance;
- exact non-overlapping narration-timeline body recipe;
- semantic stock query and IMAGE fallback contract;
- provider selection/provenance/attribution persistence;
- mocked full `search -> select -> download -> normalize` service path;
- idempotent reuse after a hash-bound READY asset;
- FFmpeg resolution/FPS/duration normalization and stock-audio stripping.

No live Pexels request was made in qualification.

## Remaining before Product Acceptance

H4 is an engineering foundation, not Hybrid Visual Product Acceptance. Remaining work is H5:

- compositor consumes Opening Builder + image slots + stock slots in one visual timeline;
- actual image assets/effects cover IMAGE slots;
- final render proves master narration/subtitle/waveform continuity across source changes;
- UI recipe preview/controls are polished for ordinary users;
- one bounded live Pexels smoke/UAT may be run after an owner-provided API key is configured;
- Hybrid Visual may be release-enabled only after exact E2E Product Acceptance.
