# Hybrid Visual H3 — Opening API acquisition

Date: 2026-09-16
Status: ENGINEERING_COMPLETE / NO_LIVE_SPEND_IN_QUALIFICATION / QUALITY_DEFERRED

## Product intent

H3 adds an optional API path to the existing Opening Builder. Manual external generation/import remains first-class and is never removed. Run/Continue does not automatically spend provider credits: the owner explicitly chooses `Generate with API` for an exact `OPENING_O*` slot or imports a clip manually.

## Provider and credential boundary

- provider: BytePlus ModelArk Seedance;
- T2V request: text prompt only, 16:9, 4–30 s provider envelope, 480p/720p, provider audio disabled;
- Story Auto credential source: environment first, otherwise Windows DPAPI current-user Story Auto credential store;
- Settings supports Save key, read-only Test connection, and Remove saved key;
- credentials never enter project manifests, API responses, UI text, logs, or repository evidence.

## Exact-slot acquisition contract

Each Opening Builder slot keeps stable identity, exact prompt hash, duration and target timing. API state is persisted on that same slot.

`Generate with API` executes:

`persist PRE_DISPATCH intent -> one BytePlus POST -> persist task id -> poll/resume same task -> acquire provider video -> existing import/normalize path -> silent SHA-bound opening asset`

Safety invariants:

- intent is persisted before provider mutation;
- a known task id is always resumed, never replaced by a blind second POST;
- ambiguous POST becomes `AMBIGUOUS` and is not automatically redispatched;
- terminal provider failure does not automatically create a replacement task;
- manual import remains available after ambiguity/failure;
- successful API output goes through the same `import_opening_clip()` normalization contract as manual video;
- embedded provider audio cannot override narration/BGM master audio.

## UI behavior

Settings exposes `Opening API video · BytePlus` with Save/Test/Remove.

Each missing Opening slot shows:

- Copy prompt;
- Generate with API when BytePlus is ready;
- Resume API generation when a durable task exists;
- Import clip at all times.

If BytePlus is missing, the slot explains that API generation is not configured and manual import remains available. Ambiguous/terminal states also guide the user back to manual import instead of silently submitting again.

## Verification

Targeted H3 suite: 5/5 PASS.

It covers:

- persisted intent before POST;
- successful T2V acquisition and exact-slot normalization/binding;
- ambiguous POST no-redispatch;
- known-task same-id resume with zero new POSTs;
- BytePlus key DPAPI round-trip without plaintext persistence;
- browser Settings Save -> Configured -> Test -> Connected -> Remove;
- browser Opening Builder displays API and manual paths together;
- browser `Generate with API` routes to the exact project/slot action.

Qualification uses fake provider transport. No live BytePlus generation/spend occurs.

## Acceptance boundary

This closes Provider Configuration / Opening acquisition flow completeness. It does not claim visual-quality acceptance. Motion, acting, prompt quality, pacing, model choice and provider cost optimization remain Quality V2 work.
