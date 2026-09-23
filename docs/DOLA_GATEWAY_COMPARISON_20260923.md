# Dola gateway comparison — 2026-09-23

Status: READ-ONLY COMPARISON / NO NEW GENERATION. The Owner reports no new
Dola job or credit deduction for Story Auto's one approved canary. This is
Owner-observed account evidence, not a provider dispatch ledger or a receipt.

Source identity: https://github.com/coll3879xx-cyber/dola-render-gateway main
`57518aac4e0a150fa54386654ba8738a15d2a2b3`, independently checked against
the prior read-only checkout at `D:\Story Auto\evidence\dola-audit-6d99c8f7`.
Gateway is a third-party implementation, not Dola's official API contract.
Historical security/architecture audit remains in
`docs/dola-gateway-audit-2026-09-19.md`.

## Actual active paths

| Boundary | Gateway | Story Auto candidate |
|---|---|---|
| Session | Patchright `launch_persistent_context` per account, populated by a full browser OAuth/login flow (`browser.py`, `add_account.py`) | DPAPI named account contains a seven-cookie HTTP header; fresh Chromium contexts are seeded from these pairs |
| Submit | Active `server -> browser_pool -> video_worker_ui.generate_video` clicks the video mode and sends the prompt via UI | `DolaCookieClient.submit` sends one Python HTTP POST to `/chat/completion` |
| Receipt | UI worker waits for a numeric conversation ID in the page URL, then calls `on_conversation_id` | SSE parser requires `SSE_ACK.ack_client_meta.conversation_id` and persists it immediately |
| Poll | Browser-page fetch of `/im/chain/single` using the full current `uplink_body` envelope (`video_worker.py`) | Python HTTP POST to `/im/chain/single`; requires exact input/output linkage before import |
| Recovery | Same account/profile and conversation when ID exists; pool may rotate on several failure classes | Same named account and conversation only; no retry/rotation after uncertain submit |

The gateway also contains a direct `dola_client.py` SSE submission method, but
its active video route imports `video_worker_ui.generate_video`. Thus its
operation is **not evidence that a copied cookie header alone works**. Its
direct request has more `option` fields than Story Auto's, but there is no
live evidence identifying any omitted field as the cause of our HTTP-200/no-ACK
result. Do not cargo-cult the unverified payload.

## New read-only controls

The saved `dola-main` record yields seven cookie names, including
`sessionid_ss` but not `sessionid`. A fresh Chrome context seeded with those
seven pairs loaded `/chat` with HTTP 200, as did a cookie-free control. Both
rendered a login button and login-required prompt. The prior conclusion that
HTTP 200 proved authentication is withdrawn; cookie-only fresh-context auth
is **NOT PASS**. A separate read-only Japanese-locale view rendered the video
entry, but that public UI affordance is not proof that generation is available
to the saved session. No prompt was submitted by these checks.

An additional read-only `/im/chain/recent_conv` query, using the gateway's
query shape with zero requested messages, returned HTTP 200 and one cell in
both the cookie-free and seven-cookie contexts. That response is therefore
not a distinguishing authentication check either. No conversation IDs or
response bodies were recorded.

Story Auto's approved canary `9a849c09107a4ee4b5c019ea14424917` remains
AMBIGUOUS: one POST, HTTP 200, no SSE receipt, no task ID, no asset. Neither
the Owner's no-job/no-credit report nor negative UI search proves that the
provider received no request. Preserve the journal and do not redispatch it.

## Adoption decision and next gate

Prefer an **isolated dedicated browser profile** with Owner-completed Dola
login as the next authentication candidate, without attaching to an already
running Chrome CDP session. First qualify it read-only with a real signed-in
account marker and a negative control, then across a browser restart. Only
after that should a separate feature-gated UI transport be considered. It
must retain Story Auto's durable one-attempt journal, account lock, exact
conversation/output identity, no automatic POST retry or account rotation,
and fail-closed manual handling for CAPTCHA/verification. Do not copy the
gateway's automated CAPTCHA solver, default extension/interception, silent
ratio/duration fallbacks, or unauthenticated server defaults.

No new generation is authorized by this comparison. The sole newly approved
canary was consumed. A future live canary requires a fresh, explicitly bounded
Owner decision after auth/profile qualification and offline failure tests.
