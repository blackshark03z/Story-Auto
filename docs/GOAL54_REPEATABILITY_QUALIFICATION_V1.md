# Goal 54 — Xianxia Repeatability Qualification V1

Date: 2026-09-13
Status: COMPLETE / REPEATABILITY_QUALIFIED

## Baseline
- Completed kept chain: X1C -> X2 -> X3.
- Current state: RESEARCH_CANDIDATE.
- Accepted X3 reference frame SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`.
- Accepted X3 prompt SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`.
- X3 kept clean SHA-256: `8da1d34734f83d8131812f619490b6c0a358948d7e9a9cbc8518883fac24976f`.
- One passing chain is insufficient for product promotion.

## Qualification question
When the exact accepted X3 input contract is repeated as independent provider generations, does the method continue to satisfy the same identity/material/camera/motion/VFX rubric without rescue tuning?

This phase measures stochastic repeatability, not robustness/generalization. Therefore the visual input, prompt, model and settings stay exactly frozen.

## Bounded experiment
Create exactly two independent repeats: `RQ1` and `RQ2`.

Frozen inputs for both:
- exact same X3 continuity frame bytes (SHA above);
- exact same X3 prompt bytes (SHA above);
- model `seedance-2-fast-i2v`;
- duration `4s`;
- resolution `480p`;
- aspect ratio `16:9`;
- audio off.

Independence comes only from separate provider generations. Each repeat must use its own durable recipe/clientRef/job identity. Do not reuse X3 clientRef because provider idempotency would replay X3 instead of creating an independent sample.

Rules:
1. no prompt or source-image edits between X3, RQ1 and RQ2;
2. no prompt tuning after seeing RQ1;
3. no visual-quality redispatch after a failed repeat;
4. provider transport recovery may only resume/reconcile the same durable job/clientRef;
5. run one generation at a time;
6. stop after RQ2; there is no RQ3 rescue run.

## Acceptance per repeat
Use the exact X3 acceptance rubric:
- same adult Chinese female identity; no face replacement or younger-face drift;
- matte natural skin and low-gloss soft-satin material response retained;
- pavilion/mountains/waterfall/subdued dawn continuity retained;
- camera remains almost locked;
- hand raise is small and anatomically coherent;
- pale-blue spiritual glow stays faint/localized/translucent;
- no scene change, extra character, severe anatomy break, large spell effect or style shift;
- durable request/job/gen provenance and exact local preview hash.

`PASS_WITH_MINOR_DRIFT` is acceptable only when no critical gate is crossed.

## Aggregate promotion gate
Promote `RESEARCH_CANDIDATE` -> `REPEATABILITY_QUALIFIED` only when:
- baseline X3 is already accepted/kept;
- RQ1 is PASS or PASS_WITH_MINOR_DRIFT;
- RQ2 is PASS or PASS_WITH_MINOR_DRIFT;
- zero critical failures across the two repeats;
- zero visual-quality redispatches;
- all provenance/budget gates complete.

If either repeat has a critical visual failure, stop as `NOT_REPEATABLE` for the frozen X3 method. Do not create a third sample to rescue the score. If only one repeat can run because of budget, record `PARTIAL_REPEATABILITY_EVIDENCE` and do not promote.

## RQ1 outcome

RQ1 is `OWNER_APPROVED / PASS` on the exact locked preview SHA-256 `3cdd424427c1cbf1042c7160e74529023cf90ceb5ebdab74a6a1577c9b772cd9`. Exactly one RQ1 generation was created, with no quality redispatch and no Keep/Kill. RQ2 is therefore authorized as the second and final independent sample under this frozen contract.

## RQ2 outcome

RQ2 is `OWNER_APPROVED / PASS` on the exact locked preview SHA-256 `56aee3514dcccca429c918f4d92e0a6768d0b09f889f29dc59fd481b58575598`. It preserved the frozen X3/RQ1 input contract, created one durable provider job after idempotent same-clientRef reconciliation, used same-job recovery after a transient wait, and required zero visual-quality redispatches. No Keep/Kill was executed.

## Aggregate verdict

All promotion gates are satisfied: X3 is accepted/kept, RQ1 PASS, RQ2 PASS, zero critical failures, zero visual-quality redispatches, and complete provenance/budget evidence. The frozen X3 continuity method is therefore `REPEATABILITY_QUALIFIED`. No RQ3 exists or is authorized.

## Budget / consequence gate
Before each repeat:
- live Elyum account + estimate read-only preflight must PASS;
- estimate must be `<=44` credits;
- available balance must cover the estimate;
- no dispatch when balance is insufficient;
- Keep/Kill remains explicit Owner consequence only;
- locked-preview review is sufficient for repeatability verdict; do not Keep merely to obtain a clean asset unless a later phase actually needs that repeat as a promoted artifact;
- no 720p/1080p work during repeatability qualification.

The last verified balance before X3 Keep was 50 and X3 Keep quote was 20. A fresh live balance read is mandatory; do not infer authorization from arithmetic.

### Credential-pool rule
The Elyum key file may contain multiple non-empty credentials, one per line. Qualification tooling must preflight each slot independently without printing credentials, select only a slot whose live balance covers the current quote, and persist the non-secret `credential_slot` with the durable experiment entry. Same-job resume/status/Keep/Kill must reuse that persisted slot. Never merge credential text, log it, or infer that one slot's balance applies to another.

## Separation from robustness
After repeatability passes, robustness/generalization may be tested separately with changed continuity frames, motion classes or scene conditions. Do not mix that question into this qualification.

## After qualification
If `REPEATABILITY_QUALIFIED`, the next phase is production-integration planning: feature flag/provider routing, workflow state, failure recovery, cost policy, observability and UAT. Qualification is not automatic production promotion.
