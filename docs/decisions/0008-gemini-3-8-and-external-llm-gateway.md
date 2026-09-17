# Decision 0008 — Gemini 3.8 baseline and external LLM gateway

Date: 2026-09-17
Status: Accepted

## Context

Google released `gemini-3.8-flash` as GA on 2026-09-02 and documents it as its most intelligent Flash model for long-horizon engineering, autonomous agents, and complex workflows. Story Auto's earlier reasoning baseline predated this release.

The Owner also wants Story Auto to support externally purchased/model-routed APIs such as ETFBit without coupling the product to one reseller. The referenced shop page is not itself a stable API contract, so Story Auto must integrate by protocol rather than vendor-specific assumptions.

## Decision

1. Gemini HARD reasoning starts with `gemini-3.8-flash`, then falls back through 3.7, 3.6, 3.5 and the established 2.5 models. New Gemini projects default to 3.8.
2. Add an optional `external_anthropic` brain provider implementing the Anthropic Messages `/v1/messages` wire contract.
3. External configuration is generic: base URL, model alias, authentication mode (`x-api-key` or Bearer), plus an append-only DPAPI key pool.
4. The gateway may use a safe HTTPS path prefix; Story Auto appends `/v1/messages`. Non-loopback HTTP, URL credentials, query strings and fragments fail closed.
5. External model names are gateway aliases. Story Auto records both the configured alias and any gateway-reported model but does not claim this proves upstream vendor/model identity.
6. Brain defaults affect only newly created projects. Existing projects retain their saved provider/model.
7. Secrets never enter project JSON, runtime defaults, repo files, logs, diagnostics, or API responses.
8. A named reseller is not production-qualified until its actual API base URL and model alias pass the product `Test connection` surface.

## Sources

- Google AI Gemini 3.8 Flash model page and September 2026 release notes.
- Anthropic Platform API Overview and Authentication documentation for Messages API and supported authentication headers.
- Cloudflare AI Gateway Claude integration as evidence that Anthropic-compatible gateways can legitimately use non-root path prefixes.
