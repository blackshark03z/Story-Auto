# Experimental Flow reference-video transport

## Supported scope

One PNG reference (at most 20 MB), one video per request, 8 seconds, 16:9,
`abra_r2v_8s`. Other intentions stop; this route never silently falls back to
compositor clicks or another provider. Image generation retains its existing route.
Google's private contract can change. A schema/session mismatch stops the attempt;
do not loosen validation just to get past a failure.

## Activation and rollback

Only for the qualified candidate after acceptance: set both environment variables
in the same process that starts Story Auto:

- `STORY_AUTO_FLOW_RPC_EXPERIMENTAL=1`
- `STORY_AUTO_FLOW_RPC_PROJECT=<exact bound Google Flow project UUID>`

No environment change is made globally by the canary scripts. They set the gate
inside their own process only. To disable new RPC dispatches, unset the first
variable and restart the application. Preserve attempt journals: recovery of an
existing RPC attempt must stay RPC/read-only even when its generation gate is off.
Rollback does not mean redispatching unresolved shots with the UI adapter.

## Browser/session

Use the existing dedicated Flow profile, not another Chrome profile or exported
cookies. The normal application launcher supplies remote debugging and the exact
localhost allowed origin required by the legacy UI capability inspector. CDP
health alone does not prove that this inspector can attach. Never restart Chrome
in the middle of an unresolved write merely to rerun Generate.

## Recovery

`flow_rpc_attempt.json` is under the canonical attempt directory. It records the
request/ref hashes, profile/project, write-boundary counters, output identity and
acquired hash. After `submit_attempts=1`, acquisition/reconciliation is read-only.
No output yet is not permission to retry. A corrupt or mismatched journal stops.
Checksums protect against accidental corruption, not a malicious local operator.

An upload with uncertain response is preserved and does not automatically repeat
inside that attempt. Never delete journals or clone them into a new attempt.

## Verification tools

- `python -m tools.flow_rpc_readiness --help`: no upload/generation/token minting;
  compare with the saved baseline and write a new evidence filename.
- `python -m tools.flow_rpc_canary --help`: one explicitly scoped wrapper shot;
  existing journal means recovery-only. `--crash-after-submit` deliberately exits
  after the POST response, before local acknowledgement. This is a test, not a
  normal launch option.
- `python -m tools.flow_rpc_service_canary --help`: canonical service in an isolated
  runtime, local reference fixture plus at most one live video. This exercises
  manifest/selection but deliberately does not claim production visual QC or UI
  owner acceptance.

Evidence, actual source identity and outstanding gates are in
`FLOW_RPC_INTEGRATION_STATUS.md`. Do not advertise stable production while that
record still says HOLD.
