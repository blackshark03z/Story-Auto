# Goal 33 — Flow dispatch requires causal acceptance evidence

## Product case study

- Title: Temporal provider-surface activity is not request acceptance proof.
- Classification: `PRODUCT / INTEGRATION / DESIGN-ASSURANCE`.
- Confirmed source defect: `BLOCK_SOURCE_DEFECT_PROVIDER_CARD_DELTA_NOT_CAUSALLY_BOUND_TO_CURRENT_ACTIVATION`.

The prior Flow adapter could treat one stable post-baseline card or asset delta
as `dispatch=CONFIRMED` even where the exact Generate transport recorded
`input_dispatched=true`, `trusted_click_seen=false`, no provider job ID, no
provider acknowledgement, and no composer transition.  A later card is
evidence that the provider surface changed; it does not causally prove that the
current request was accepted.

Goal 33 separates the evidence ladder:

```text
INTENT
-> INPUT ATTEMPT
-> INPUT VERIFIED
-> EXTERNAL ACCEPTANCE
-> OUTPUT OBSERVED
-> OUTPUT ATTRIBUTED
```

`DispatchEvidenceTracker` now confirms only either:

1. a serialized, request-bound direct provider acknowledgement such as a job
   ID; or
2. a compound UI proof: verified exact Generate activation, a provider-UI
   acceptance transition attributable to that activation, and a durable
   request-local provider tile/output identity.

A card/output delta without verified activation remains `UNCERTAIN`, has no
authoritative dispatch binding, blocks same-request retry through the existing
canonical no-dispatch authority, and is retained as append-only provider-surface
evidence.  Attribution remains independent: a confirmed dispatch does not
select an output, and an unverified activation cannot promote a later candidate
into attribution authority.

## Activation transport decision

The Goal32 runtime receipt showed that raw CDP coordinate input was not a
reliable proof of delivery to the exact control.  Goal 33 attaches Playwright
over CDP to Story Auto's already-selected dedicated Chrome/project page and
uses one uniquely resolved Locator click.  The control is re-resolved just
before the attempt, actionability is enforced by Playwright, a trusted event
audit is attached to that exact control, and no coordinate fallback is allowed
after activation begins.

Youtube Auto was used only as the narrow positive control for the transport
pattern: Playwright `Locator.click()` followed by observed media.  Story Auto
does not adopt Youtube Auto's first-new-media ownership policy.  It retains its
request-local baselines, provider tile/asset lineage, strict attribution, and
append-only recovery evidence.

## Runtime compatibility

The preserved historical request `req_1757ad26a03ff73774b1` is never rewritten
to `NOT_DISPATCHED`.  Its existing canonical unresolved replay child is
`req_4b8dba2869afe1e12a52`. Revision 2 captures a deterministic sanitized
projection of the actual pair (`runtime_projection_sha256=
65fc2e7fb7174b8b3c8caa1490a193c96d786d41029e78c6447d55e2d277bbc8`) and
uses its exact persisted lineage shape: confirmed dispatch,
`OUTPUT_ATTRIBUTION_UNCERTAIN`, unresolved attribution, and a pre-created
receipt-backed replay. The primary regression never invokes replay creation.
It proves the historical parent remains retry-denied, the child has zero
attempts/zero submissions/no selected asset, and only that current child can
reach a fake provider boundary. Corrupted genesis, altered links or identity,
mutated parent history, a competing child, a non-pristine child, and cycles all
fail closed without reopening the parent.

Compatibility tests for state-machine fixes must reproduce the exact persisted
historical state shape from which production resumes. A generic reconstruction
using another failure state is not equivalent evidence.

## Production dependency contract

Goal 33 changed Generate activation to Python Playwright. Revision 2 makes it
explicit in Story Auto's `requirements.txt` and adds an offline import smoke
test. The supported installation command is `python -m pip install -r
requirements.txt`. This needs no Playwright-managed browser download: Story
Auto connects to its existing dedicated Chrome CDP session rather than
launching a Playwright browser. The dependency is owned by Story Auto and is
not inherited from Youtube Auto or an incidental developer site-package.

## Deferred Build OS finding

Plan/design assurance for external effects should require explicit evidence
ladders from input attempt through output attribution.  This is a documented
post-shipping synthesis item only; no Build OS source was modified.

`unpersisted_os_findings=0`

`unpersisted_orchestration_findings=0`
