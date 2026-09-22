# Cookie Flow Opening delivery checkpoint

Status: IMPLEMENTED_EXPERIMENTAL / PRODUCT_ACCEPTANCE_PENDING.
Source: dirty HEAD5464cbb1d1c11a550b5e096647b9f94587de5bfe; owner changes preserved.
No commit, push, default provider promotion or new real generation this milestone.

## Product entry and scope

Hybrid Opening, Auto provider policy, each unbound slot has an optional Flow
reference-video disclosure. Named encrypted session, exact gated Flow project,
PNG reference and explicit confirmation authorize one8-second source, normalized
to a4–8-second slot. Existing image/body/thumbnail and Full Video API routes stay
unchanged. Existing RPC environment gate remains default OFF and project-specific.
Settings exposes configured separately from read-verified and generation-enabled.

## Durable provider safety

- Before provider effects, copy PNG into the attempt directory and persist
  slot prompt/duration, reference hash, account revision, project and request.
- Existing attempts re-enter RPC recovery-only; changed identity fails closed.
- Canonical importer checks sealed acquired receipt, output bytes, request hash,
  reference hash, project/account/revision and exact attempt directory.
- Explicit reset preserves history and only accepts an exact sealed PREPARING
  journal with zero upload/submit attempts and no reference/output IDs.
- Cookie generator cannot fall back to CDP on unsupported IMAGE or gate OFF.
- Structured and string cookie input share the1MiB limit; invalid input is safe
  and never written. No raw credentials in UI, journals or error messages.

## Evidence and limits

Current combined refresh:363 Flow/Dola tests PASS in70.228s on dirty HEAD5464cbb.
Real metadata now Flow1 (flow-owner revision1), Dola0. The saved Flow export fails
authentication as recorded in cookie-settings-live-20260921; no new generation.
Older snapshots below are retained as history, not current account/readiness state.

Latest refresh: Flow discovery339 PASS (60.801s); Settings8 PASS (1.310s).
The Settings HTTP regression verifies only literal true authorizes removal and
the displayed revision is forwarded unchanged. Actual stores were re-read:
Flow0/Dola0. No live provider effect or credential change in this refresh.

- Flow suite332 PASS,52.123s (before final added regression/copy changes).
- Final focused cookie-opening/settings/RPC-service19 PASS,8.422s.
- Opening/Dola/cookie/RPC regression87 PASS,31.149s (before final added tests).
- Node syntax PASS; tracked scoped diff whitespace PASS (CRLF warnings only).
- Independent review exposed structured-size bypass and pre-effect recovery
  wedge; both fixed and regression-tested. Gate metadata now uses the exact
  backend predicate; configured credentials do not imply live readiness.
- Three offline slots have distinct provider lineage; repeat is idle. Ambiguous
  submit recovers with generation gate OFF and one upload/one submit total.
- Wrong output bytes rejected by canonical importer despite matching identity.
- Rendered Settings empty/error at1280x900 and760x900. Rendered Opening disclosure
  with no account, and enabled fixture with account/project/reference controls.
  Actual desktop preview caught inherited absolute-position inputs; scoped CSS
  fixed them and desktop was rechecked. Narrow enabled-form recheck remains due.
- UI fixture at `D:\Story Auto\evidence\cookie-opening-enabled-ui-20260921`
  has fake metadata only; Flow dispatch is explicitly disabled server-side.
  Confirmation click timed out in browser-control focus/dispatch. No definitive
  dialog cancel result; this UI step is UNVERIFIED, not a passed generation.
  Filesystem reread confirmed3 slots and0 provider attempts afterward.

Relevant tested-source SHA256:

- providers/flow/opening.py: A588603A93C39981BDA73D98FDB80C1241D6BA9A07954B3A1EC929E2ACB68043
- core/visual/opening_builder.py: E21F2FE6709114C8B8767AE6D1DBD234AD7218F45916CC7C977E427B5C37226B
- ui/static/app.js: 09157C016FFF8C5C294FF65433C8ACA71B957CC2BA4D0136DF073C9DF632F576
- ui/static/styles.css: DE90E448D7595EA5B511423F3ACB9436DEEEAF965B977563289D0AA898270D31

## Next required work (not waived)

Lifecycle follow-up2026-09-21: item1 below is now implemented and independently
reviewed. Local remove uses expected revision and increments a secret-free
tombstone; reimport increments again. Old account bindings cannot revive.
Legacy1.0 migration and failed-write preservation have explicit regressions.
Final focused65 PASS (8.711s), JS syntax PASS. Real-store read returned Flow0,
Dola0; no real credentials were removed or saved and no provider call was made.
The prior native-confirmation timeout was addressed with scoped in-page Flow
dialogs: exact generation scope rendered, Escape returned focus to Generate;
removal dialog rendered desktop/narrow, Cancel retained the session selection.
Final post-focus-fix rendered pass and full live journey remain outstanding.

1. DONE: local alias removal with revision tombstones. This does not remotely
   revoke a Google session or stop work already using in-memory cookies.
2. Owner-approved service save DONE: flow-owner revision1, Windows DPAPI,
   fresh-process decryption verified. Read check FAILED: exact project redirects
   to /about, no authenticated session metadata. Need fresh login/export; do not
   treat configured state as live proof. Safe evidence: cookie-settings-live-20260921.
3. Enabled-form760px and post-fix Cancel focus-return DONE in fresh fixture51189;
   exact source hashes and rendered observations in FLOW_COOKIE_SETTINGS_UX.md.
   Real completed-result reload/recovery UI evidence remains pending.
4. Bounded live product slot generation and canonical full composition/format
   acceptance using approved existing allowance; reuse canaries where legitimate.
5. Dola still needs a valid saved account and live protocol/result qualification.
6. Full goal remains active; no product/owner acceptance inferred from tests.
