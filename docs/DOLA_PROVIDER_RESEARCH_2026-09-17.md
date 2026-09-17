# Dola provider research — 2026-09-17

Status: **RESEARCH_ACCEPTED / OFFICIAL_API_REQUIRED / COOKIE-INTERNAL-API_ROUTE_BLOCKED**

## Product reality

Dola currently exposes browser-based AI video generation with Seedance 2.5, text-to-video and image-to-video, 480p/720p output, and short-form duration controls in the 4–15 second range. Its public site also advertises free daily credits plus paid credit plans.

## External-contract finding

Dola's public Terms of Service say the service may expose API endpoints, but the same Terms prohibit reverse engineering/extracting/copying the platform and prohibit attempts to bypass quotas/rate limits. The public materials reviewed in this research did not provide a stable developer API reference sufficient to implement and qualify a production adapter.

An unofficial GitHub client exists that explicitly describes itself as reverse-engineering the Android app API and supports browser cookies as an alternative session source. That implementation demonstrates technical feasibility, but it is not an acceptable stable-product contract for Story Auto because it depends on reverse-engineered private behavior rather than a provider-supported developer boundary.

## Decision

1. Do **not** implement a `DolaSessionAdapter` that calls reverse-engineered/internal Dola endpoints with browser/app cookies.
2. Keep Dola in the Provider Registry as `dola_official`, experimental and not production-routed.
3. Promote Dola only after a provider-supported official API contract can be verified for authentication, task identity, polling/recovery, result acquisition, cost/quota semantics, and permitted automation.
4. Until then, Dola remains usable through Hybrid Opening's existing **Manual external generation → Import clip** path.
5. Dola's free daily credits remain a useful owner workflow, but Story Auto must not treat free access as authority to automate an unsupported/private interface.

## Promotion checklist for a future official Dola adapter

- provider-authored API reference or documented supported endpoint contract;
- explicit authentication/session mechanism intended for API automation;
- stable create-task identity returned before polling;
- retry/idempotency semantics or a fail-closed ambiguity strategy;
- model/capability discovery or a documented Seedance model id;
- duration/resolution/aspect-ratio constraints;
- quota/credit observability and no-dispatch proof on preflight failure;
- deterministic result download and local SHA binding;
- provider terms permit the intended automated integration;
- mocked contract tests, then bounded live read-only preflight, then one explicit-spend UAT before routing promotion.

## Sources reviewed

- Dola public product page and pricing/FAQ.
- Dola Terms of Service, effective 2026-08-20.
- Unofficial `Linkmail16/DolaAI-API` repository, which describes reverse-engineered Android API usage and optional browser-cookie session input.

No Dola credential, cookie, generation request, or live account action was used in this research.
