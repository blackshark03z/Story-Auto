# Cookie-owned Flow reference-video qualification

Status: bounded transport PASS; PRODUCT_ACCEPTED is NOT claimed.

## Verified scope

CookieBrowserRpcSession owns a fresh plain Playwright headless Chromium process,
imports the explicit local Google export, validates the exact project/RPC metadata,
and closes only its own browser. No external CDP attachment is used. Production
operator/UI routing is unchanged; cookie setup/product account binding is pending.

The prior absent-WIZ finding was execution-context dependent: the same page
exposed WIZ metadata to Playwright but not Patchright evaluate. No RPC metadata
requirement was removed. Empty-project drift was separately corrected by parsing
one explicit catalog envelope and validating auxiliary schemas and every row,
rather than recursively searching any frame and fingerprinting row population.
Observed empty and populated shapes are saved as sanitized type-only evidence.
Auxiliary records are schema guards, not media identity/ownership evidence.

## Live result, 2026-09-21 local time

Evidence root: `D:\Story Auto\evidence\cookie-video-canary-20260921`.
Provider project: d838fe6b-9c2c-4fa6-8ed6-39af07333bd2.

- One PNG reference upload; readback pixel similarity verified by existing adapter.
- One generation submit. Durable journal before writes; unique prompt marker,
  exact reference/model/project/output linkage validated by existing strict matcher.
- H.264/AAC MP4, 1280x720, 8.000 seconds; full FFmpeg decode exit0.
- SHA256: 81e47db64ed4e0b59fa66cc231e969ee0415772d574759a7c81b593123b628ba.
- Fresh-process recovery acquired the identical output; upload/submit counters
  remained 1/1. No replacement request or blind retry.

## Engineering checks

- Independent cookie parser review: three findings fixed and regression tested.
- Independent catalog review: auxiliary envelope checks tightened with observed
  shapes; metadata placeholders/unknown structures rejected before provider writes.
- Final current Flow group: 309 tests PASS in 44.289s.
- Canonical session-factory injection plus focused group: 34 tests PASS.
  Existing default external-CDP route remains the default; explicit factory is
  reused on dispatch and reconciliation, tested with lost-response recovery.

Canonical service live canary SUCCEEDED at
`D:\Story Auto\evidence\cookie-canonical-service-20260921`.
One attempt/provider submission and canonical selected asset. Reinvocation returned
new_submissions=0, preserving the same asset and one attempt. H.264/AAC 1280x720,
8.000s, full FFmpeg decode PASS; SHA256:
fa79cac9975ef0be6868105b16956a66bdb7a6917185a8436f318bbec1f2a965.
QC is explicitly ENGINEERING_FIXTURE, not owner quality approval. Total this
milestone: two real videos, one submit each; no duplicate generation on recovery.
An initial invalid local config was rejected before initialization/provider entry;
the corrected canary preserves the schema-valid legacy config and injects the
cookie-owned session explicitly. Config cdp_url is unused by this factory.

## Remaining acceptance

Encrypted named account/session-mode
binding and supported UI configuration; sequential and interrupted real runs;
product QC/render journey and explicit owner quality acceptance. Source-Chrome
closure and long-duration session survival are not established by these runs.
No Dola qualification or production promotion is implied by Flow evidence.

## Candidate provenance (dirty HEAD 5464cbb, no commit/push)

SHA256 at qualification:

- cookie_session.py: 0061288088aa46a0375d18a395d51b165d7497bf953073a3e02eb7acb614a784
- rpc_contract.py: fbd1f69a5b955435a66e6bf2c4f10520b0185a5a321925fe7424d8aea5463877
- rpc_transport.py: 45a4bc78990532dca06d19db061a6d9cec31088bd96662aac32db43436f2b016
- live.py: 3d905c89ad18a21e28d82970b66e3e16daeafa26021eff6831ad28e3943bb44d
- tools/flow_rpc_service_canary.py: cc3fe8c743984b0d0067657af2e8d317ab2d42728c10b88d8f746f9d1f7ae49d
