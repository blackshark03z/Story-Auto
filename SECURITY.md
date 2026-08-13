# Security

## Secrets

- No API key, browser cookie, token, or provider credential is committed.
- Project JSON stores provider configuration references/settings, never raw secrets.
- Windows secure credential handling may port/adapt YouTube Auto's proven DPAPI pattern under a Story Auto-specific namespace.
- Environment-variable or external secure-store support may be provided as implementation choices.

## Browser profile

The Flow profile is dedicated to Story Auto and stored outside source control. Login is user-managed. The provider adapter must fail closed on unexpected login/UI state and may not attempt credential bypass.

## Network

Offline tests must not accidentally call TTS/Gemini/Flow. Live network/provider tests are explicit, bounded, and recorded as task evidence.

## Generated/content data

Projects may contain private scripts, generated media, and provider responses. Keep runtime outside the source repo by default. Diagnostics must sanitize credentials/tokens and avoid dumping full cookies or authentication storage.

## Release security gate

`python tools/security_gate.py` scans tracked product text plus durable evidence
for private keys, API-key shapes, bearer/cookie material, and signed provider
URLs. It also parses every product Python module and rejects runtime imports
from YouTube Auto. The gate reports file and classification only, never the
matched secret value.
