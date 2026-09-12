# Decision 0003 — Goal 54 3D Xianxia research branch

Status: **ACCEPTED**

Date: 2026-09-13

## Context

Goal 54 has already proven a recoverable Elyum Fast-I2V provider path with one
bounded R1 fixture. R1 demonstrated durable `clientRef`/`jobId` recovery and a
usable cinematic result, but it used a deliberately simple flat illustrated
fixture. The Owner now wants to test a materially different production-relevant
visual domain: high-quality 3D Chinese xianxia/donghua.

This introduces a new visual-style/continuity question, not a provider-routing
question. Mixing it into R1 or immediately replacing the production provider
would destroy comparison clarity.

## Decision

Create a separate research branch named `XIANXIA_3D_V1` under Goal 54.

- Production Full Video routing remains BytePlus ModelArk; Elyum remains a
  research-only provider candidate.
- R1 remains preserved as historical provider/recovery evidence and is not
  rewritten into a xianxia test.
- Use GPT Image exactly once to create the canonical xianxia anchor for the first
  experiment. Earlier ad-hoc/generated xianxia images are exploratory only and
  are not canonical anchors.
- Use Seedance 2 Fast I2V at 4 s / 480p / 16:9 as the first video screening path.
- Run one controlled shot at a time. X1 must complete QA before X2 is authorized;
  X2 must complete QA before X3 is authorized.
- Keep and Kill remain explicit consequence decisions. No experiment runner may
  automatically Keep, Kill, or start the next shot.
- Seedance 2.5 Reference is an optional later A/B only after the Fast-I2V recipe
  is already understood; it must not be used to rescue an unproven prompt/style.

## Why

The design follows the existing Goal 54 methodology:

`controlled visual anchor -> one-variable shot recipe -> low-cost preview -> evidence-backed QA -> explicit consequence -> next continuity shot`.

This preserves causal learning, minimizes scarce Credit use, and prevents a
beautiful one-off generation from being mistaken for a production method.

## Consequences

- A new research contract is canonical at
  `docs/GOAL54_XIANXIA_3D_RESEARCH_PLAN_V1.md`.
- Xianxia evidence uses a separate ledger/artifact namespace from R1.
- No Story Auto planner abstraction or UI mode is added from this decision alone.
- Combat choreography, multiple characters, dialogue/lip-sync, strong VFX,
  720p/1080p and multi-camera shots stay out of the first branch.

## Revisit triggers

Revisit this decision only when one of these is true:

1. X1/X2 show the style or identity is not viable with Fast I2V;
2. current Elyum Credit balance/pricing makes the bounded sequence infeasible;
3. Seedance 2.5 Reference provides a concrete capability required by a proven
   Fast-I2V limitation;
4. at least one xianxia recipe is repeatable enough to justify planner-level
   integration work.
