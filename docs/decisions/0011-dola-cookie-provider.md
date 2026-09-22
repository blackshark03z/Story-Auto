# Decision 0011 — Owner-directed Dola cookie integration

Date: 2026-09-20. Status: ACCEPTED FOR IMPLEMENTATION; live qualification pending.

The Owner requested stopping Flow reliability research and implementing Dola AI
with a bulk cookie list. The extra `9` was explicitly a typo. This supersedes the
official-only restriction in Decision 0006 item 7 for the new `dola_cookie`
adapter. It does not rename that adapter to `dola_official` or establish provider
support for the private protocol.

## Design and milestones

1. Named account pool in Settings: preview bulk additions/updates, encrypt cookie
   headers with Windows DPAPI, and replace a cookie under the same account alias.
   Account names, counts and local configuration state are the only public data.
2. Direct HTTP T2V adapter: incremental SSE receipt capture, bounded response
   parsing, same-conversation polling and validated video acquisition. Upstream
   protocol evidence requests `seedance_v2.0`; observed model remains unknown.
   The upstream direct-cookie method has no reference-image contract. I2V is
   unavailable until separately implemented and qualified.
3. Explicit Dola generation in the existing Hybrid Opening builder: persist
   intent/account before submit, persist receipt immediately, resume the same
   account/conversation, then reuse canonical clip import/normalization/render.
   Existing Full Video routing is not silently replaced.
4. Verify fake-provider composed journey, interruption/restart and credential
   replacement; inspect Settings/Opening candidate; independent review. Live
   canary requires an available owner-supplied Dola session and records actual
   output/latency/accounting. Configuration is not authenticated readiness.

## Runtime invariants

- One request binds to a stable account alias. Daily cookie refresh retains it.
- Pool size does not imply parallel generation; first implementation is serial
  per account. No arbitrary retry or account rotation after uncertain dispatch.
- Unknown acceptance remains AMBIGUOUS. A receipt resumes polling/acquisition.
- Persist prompt hash, account, submission count and conversation identity;
  exclude cookies, raw provider bodies and signed URLs from project artifacts.
- Check output validity and preserve source/hash/provider lineage through the
  existing opening manifest. Requested duration/model are not observed facts.
- No new scheduler, browser pool, CAPTCHA automation or upstream code vendoring.
- The canonical importer additionally requires the persisted local request ID
  to be echoed in history and linked to the video-bearing message (same local
  ID or an explicit parent/reply link). These link fields are a conservative
  candidate contract, not observed live Dola evidence. Missing linkage returns
  DOLA_RESULT_IDENTITY_UNVERIFIED and preserves the conversation for diagnosis.
  Real response qualification is still required before claiming usable output.

## Acceptance record

Implementation and evidence are tracked in TASK.md. At creation: no Dola cookie
loaded, no Dola provider request made, no live stability claim.
