# Hybrid Visual Provider Setup — Pexels credential UX

Date: 2026-09-16
Status: PRODUCT_CONFIGURATION_ACCEPTED / LIVE_OWNER_KEY_NOT_EXERCISED

## Scope

This slice closes the missing user journey around Pexels configuration for Hybrid Visual. It does not change visual-quality policy and does not make Pexels a hard dependency.

## Credential contract

- Pexels API keys use Story Auto's existing provider credential boundary.
- `PEXELS_API_KEY` environment configuration remains supported and has priority.
- Keys saved from Settings are stored in `%LOCALAPPDATA%/StoryAuto/credentials.v1.json` using Windows DPAPI for the current user.
- Key text is never returned by Settings APIs, written into project JSON, committed source, evidence, diagnostics, or browser-visible text after save.
- Environment-provided credentials are reported as non-removable from Story Auto Settings.

## Product journey

Settings -> Hybrid stock video / Pexels:

1. paste a key;
2. Save key;
3. status becomes `Configured`;
4. optional `Test connection` performs one bounded search request and no media download;
5. live response projects `Connected` plus non-secret rate-limit remaining when available;
6. `Remove saved key` clears only the DPAPI-stored key.

The New Video Hybrid surface projects provider readiness before project creation.

- Pexels configured -> stock path is available.
- Pexels not configured -> user is explicitly told generated-image fallback will be used.
- Missing Pexels never blocks project creation or canonical Run-to-Final.

## Execution behavior

The H4 acquisition path remains unchanged:

`semantic narration query -> cached Pexels search -> deterministic compatible candidate -> bounded HTTPS download -> FFmpeg silent normalize -> SHA-bound local asset`

Failure or missing key falls back to generated body imagery.

## Verification

Targeted setup tests: 3/3 PASS.

- Windows DPAPI round-trip proves plaintext is absent from the credential store.
- Live-test projection is non-secret and exposes only readiness/rate-limit metadata.
- Real browser journey proves Save -> Configured -> Test -> Connected -> Remove and Hybrid wizard fallback visibility.

Existing H4 Pexels suite: 7/7 PASS.

No real Pexels network request was made during qualification. The browser test uses a fake provider transport while exercising the real HTTP/UI/DPAPI path.

## Deferred

A real owner-key Pexels smoke is useful but is not required for flow acceptance because Pexels is an optional enhancement with deterministic image fallback.
