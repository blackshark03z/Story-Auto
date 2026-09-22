# Flow exported-cookie diagnostic

Read-only HTTP probe using the owner-specified export, located at
`D:\Story Auto\cookie\flow_cookie.txt` (the originally typed nested path did not
exist). Cookie values remain outside repository/evidence output.

Observed: Cookie Editor JSON, 16 scoped cookies, domains .google.com and
flow.google.com, zero expired by exported expiry, zero empty values, path /.
Preserved exported SameSite classification in the second probe.

Three authenticated-cookie page reads returned HTTP200 but no SNlM0e field and
contained a Google login link. A separate no-cookie control had the same three
properties. This supports failed authentication for this direct HTTP route, not
a regex miss of an existing SNlM0e field. No catalog/generation/upload was sent.
SID/HSID/APISID are absent; SSID/SAPISID and Secure-1PSID/3PSID are present. Presence
alone does not establish completeness or validity; missing names do not prove
the root cause. Unexpired cookies may still be rejected or require browser context.

Evidence: D:\Story Auto\evidence\flow-cookie-diagnostic-20260921.json.
Conclusion: this export does not qualify cookie-only HTTP. No stability advantage
has been demonstrated. Browser import was not exercised; do not present it as
tested. Do not alter the working Chrome profile or bypass an authentication challenge.
Next useful input: a fresh Cookie Editor JSON export made after confirming the
same target project opens in the exporting browser. No cookies should be pasted
into chat. Current profile-based RPC remains unchanged/default OFF.

Owner confirmed export refresh. Reread the same file and repeated the bounded
probe: again 16 scoped/unexpired cookies, three HTTP200 responses without the at
field and with a login link; no-cookie control agrees on these properties.
Evidence: D:\Story Auto\evidence\flow-cookie-refreshed-20260921.json.
No uploads/generations. This repeats failure of this HTTP route, not proof that
all cookie-based techniques fail. Do not request repeated exports without a new
diagnostic reason; browser-context dependence remains untested.

## Browser-seeded verification, 2026-09-21

Owner requested continuing through product acceptance, stopping only for a genuine
blocker or required data. Tested isolated ephemeral browsers, no persistent profile
modification, no upload, no generation, no CAPTCHA execution:

- Current Story Auto export (17 scoped cookies) + installed Chrome: login link,
  redirected away from project, at length0, no captcha API.
- Same export + installed Patchright Chromium: same result.
- AutoVideoPipeline's configured cookie file (18 scoped cookies) + Patchright:
  same result against Story Auto research project.
- Same AutoVideoPipeline file + its own configured project
  7a6d66d6-96ae-468a-b59c-d3bdd2dd21db: same result. This removes wrong-project
  selection as an explanation for that control.

Evidence files under D:\Story Auto\evidence:
flow-cookie-browser-20260921.json, flow-cookie-patchright-20260921.json,
flow-cookie-antigravity-control-20260921.json,
flow-cookie-antigravity-exact-20260921.json.

Probe reuses Cookie Editor metadata and preserves expiry rather than deleting it;
it does not copy raw cookie values, execute third-party generation scripts, or
declare historical MP4 files proof of today's session validity. Browser instances
were closed after each test. Production adapters and existing profiles unchanged.

BLOCKED_AUTHENTICATION: current exports do not reproduce an authenticated browser
session with the tested launches. Root cause (cookie invalidation/incomplete export
or additional account/browser verification) remains unknown. Requires a currently
working authenticated session or a new export demonstrably usable in a fresh
browser. Product acceptance cannot be claimed; no further Generate attempts until
authentication is established. Do not ask for credentials in chat.
