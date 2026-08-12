# Gemini Model Verification — 2026-08-12

Official Google AI for Developers documentation was checked during design freeze.

Verified model IDs:

- `gemini-3.5-flash` — GA; Story Auto V1 baseline.
- `gemini-3.6-flash` — available; first benchmark candidate.

Google's current latest-model guidance describes 3.6 Flash as stronger on complex agentic/multimodal tasks with reduced token usage and lower price than 3.5 Flash. Story Auto intentionally keeps 3.5 Flash as the baseline until a representative planning benchmark proves 3.6 equal or better on schema validity, continuity quality, retry rate, latency, and cost.

Runtime must capability-probe the configured model rather than relying solely on this dated note.

Official references:

- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash
- https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash
- https://ai.google.dev/gemini-api/docs/latest-model
- https://ai.google.dev/gemini-api/docs/changelog
