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
running Chrome CDP session. This gate now has a read-only result: after the
Owner closed the dedicated Chrome window, `tools/dola_profile_read_probe.py`
opened the same profile twice with system Chrome and compared it to a blank
Chrome context. The blank context had a visible Login button and no session
cookie; both profile opens had no Login button and contained cookie *names*
`sessionid` and `sessionid_ss`. All three loaded `www.dola.com/chat` with
HTTP 200. The result is `BROWSER_AUTH_READ_PASS`, not a generation or account
identity proof. Evidence:
`D:\Story Auto\evidence\dola-profile-read-20260923\probe-01.json`.
No cookie values or conversation content were recorded; generation count 0.
The first video-entry matcher missed the current plural label `Create Videos`.
The corrected control (`probe-05.json`) found it in both blank and signed-in
contexts, so the entry alone is not an auth proof. In the signed-in profile,
opening this mode without a prompt displayed Dreamina Seedance 2.0 Fast,
10s and a ratio selector (`video-mode-06.png`). Separate pre-submit menu
inspection found 5s/10s and 16:9 among available options (`probe-07.json`,
`options-07.png`); the model menu displayed Dreamina Seedance 2.5, 2.0 Fast
and 1.0 (`model-08.png`). No model/ratio/duration was changed, no prompt was
entered, and no generation occurred. These controls establish a selectable
UI surface, not request acceptance or video output identity.

An additional pre-submit control selected 5s and 16:9 in the profile UI and
visually confirmed both choices (`probe-11.json`, `selection-11.png`), still
with an empty prompt and zero generation. Full cookies from that profile were
then replayed in a fresh Chrome context **in memory only**: the blank control
showed Login while the replay did not (`probe-12.json`). Unlike the earlier
seven-cookie export, this fresh profile contains exact `sessionid` as well as
`sessionid_ss`.

The fresh cookie set was imported under new DPAPI alias
`dola-profile-20260923` (28 www-applicable cookie pairs), leaving `dola-main`
untouched. A separate read-only browser roundtrip from the saved alias also
distinguished the login control (`saved-alias-01.json`). Cookie-only **browser
UI authentication** is now qualified for this new alias. This still does not
prove private video API acceptance, a charge-free submit, or correct result
identity; it does not authorize replay of either ambiguous Dola attempt.

Authenticated read-only API qualification then distinguished 10 recent
conversations from the saved alias versus one unauthenticated control cell,
without recording IDs or content. A pre-existing video conversation showed a
video creation block and a `bot_reply_message_id` pointing to its text input.
The candidate adapter's old read request returned HTTP 200 but **zero**
messages for that same conversation. A/B requests isolated the cause to
`Content-Type: application/json; charset=utf-8`; Dola's current read path
returns the messages with `application/json; encoding=utf-8`. The adapter now
uses the observed nested `uplink_body` read envelope and accepts the observed
reply linkage, while still requiring the exact input ID. With the corrected
header it read that existing video as `COMPLETED` with one URL and verified
linkage (`conversation-shape-14.json`). This is poll/read qualification only:
it says nothing about a new generation submit.

Independent review caught a shared-header regression: the qualified
`encoding=utf-8` form had also changed the unqualified generation request.
The candidate now uses it only for reads and preserves the prior submit
header. The review also led to top-level-only input matching, fail-closed
handling of mixed valid/unsafe media URLs, and an exact-host/default-port
media-probe boundary. Offline regressions cover these paths. A post-fix
read-only replay (`conversation-shape-15.json`) still identified the same
existing video. None of these checks prove a new submit is accepted.

The existing Dola video URL used `http://v16-dola.dola.com`, outside the old
HTTPS allowlist. A cookie-free HTTPS HEAD to the *same signed path* returned
HTTP 200 video; a bounded GET returned HTTP 206 with `Content-Range` and an
MP4 `ftyp` header (`conversation-shape-13.json`). The adapter therefore
upgrades only this exact Dola host to HTTPS and allows it in the cookie-free
download boundary. It does not permit arbitrary HTTP URLs or lookalike hosts.
Full video download/validation remains untested for this existing artifact.

The next candidate is a separate feature-gated UI transport. It
must retain Story Auto's durable one-attempt journal, account lock, exact
conversation/output identity, no automatic POST retry or account rotation,
and fail-closed manual handling for CAPTCHA/verification. Do not copy the
gateway's automated CAPTCHA solver, default extension/interception, silent
ratio/duration fallbacks, or unauthenticated server defaults.

Before enabling it, bind the profile to an explicit account identity. The
video-mode controls are now observed, but the eventual transport must verify
the requested model, ratio and duration on every new attempt. Persist the
attempt before the single final UI action; on a missing conversation receipt,
leave `AMBIGUOUS` and do not rotate or repeat. Poll only the proven same
conversation and import only a video linked to the submitted input. Test
crash/restart and absent/mismatched receipt cases offline first.

No new generation is authorized by this comparison. The sole newly approved
canary was consumed. A future live canary requires a fresh, explicitly bounded
Owner decision after auth/profile qualification and offline failure tests.
