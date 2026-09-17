# Decision 0008 — Gemini 3.8 reasoning baseline

Date: 2026-09-17
Status: Accepted

## Context

Google lists `gemini-3.8-flash` as a GA stable Gemini API model and the current most capable Flash generation. Story Auto's reasoning router still preferred Gemini 3.6 Flash and new-project defaults still referenced Gemini 3.5 Flash.

Google also documents that sampling parameters such as `temperature` and `top_p` are deprecated starting with Gemini 3.6 Flash and future generations may reject them.

## Decision

- Promote `gemini-3.8-flash` to the first HARD reasoning model.
- Keep deterministic fallback order: 3.8 -> 3.7 -> 3.6 -> 3.5 -> established 2.5 fallbacks.
- Preserve the Flash-Lite BULK tier until a newer stable Lite target is qualified.
- Make `gemini-3.8-flash` the default model for new/current-default project configuration without rewriting historical project JSON.
- For Gemini 3.6+ request shapes, do not send deprecated `temperature` or `topP`; continue sending bounded output-token settings.
- Keep schema validation, credential pooling, cache identity, and fallback safety unchanged.

## Evidence boundary

This decision establishes code/config defaults. Production promotion still requires regression/security gates and a bounded live capability probe using an authorized Gemini credential before claiming runtime model activation.
