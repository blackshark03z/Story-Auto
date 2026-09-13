# Goal 54 — X3 Preview Evidence

Date: 2026-09-13
Status: TECHNICAL_VERIFIED / ASSISTANT_VISUAL_PASS_WITH_MINOR_DRIFT / OWNER_DECISION_PENDING

## Locked baseline

- pre-dispatch evidence commit: `2ecfd47` (`Goal54-bind-X3-pre-dispatch-evidence`)
- plan: `docs/GOAL54_X3_PLAN.md`
- pre-dispatch evidence: `docs/GOAL54_X3_PRE_DISPATCH_EVIDENCE.md`
- X2 continuity baseline: `g_d59e88f0244b0717a1b29da6` (`KEPT`)
- X3 source-frame SHA-256: `5edaecf148914b1230ecf4d3bc0a7f1f80b513cdda9cd71a835471c3e15480ef`
- X3 prompt SHA-256: `8e062a316c0bf5aa329f9baa1cb17f89b892a88d5c72f349c542645011c7f68c`

## Provider identity

Exactly one X3 generation was dispatched.

- recipe: `X3`
- provider: `elyum_seedance`
- model: `seedance-2-fast-i2v`
- duration: `4 s`
- resolution: `480p`
- aspect ratio: `16:9`
- audio: off
- client_ref: `story-auto-g54-a37bc6258d2bd96a732f2f9de8a3302c84e5bb1a9905c39a`
- experiment identity SHA-256: `a37bc6258d2bd96a732f2f9de8a3302c84e5bb1a9905c39a7cdf8f39826b6c01`
- job_id: `cos_leYmn4yuIWZosURXvTRbUo:90981d0a-4963-45f6-8547-22cded994c38`
- gen_id: `g_a18de93d00316ba4dbbe32ba`
- provider execution state: `done`
- preview state: `PREVIEW_READY`
- balance before dispatch: `50` credits
- generation estimate: `44` credits
- provider Keep/unlock quote: `20` credits

## Recovery proof

The dispatch returned a durable `job_id` and then `WAIT_UNAVAILABLE / PROVIDER_TRANSIENT`. Recovery never called make-video again.

1. first dispatch created the one durable job above;
2. two same-job `resume` observations returned the same transient wait classification;
3. read-only `elyum_job_status` then confirmed that the same job was `done` with generation `g_a18de93d00316ba4dbbe32ba`;
4. one final same-job `resume` reconciled the durable ledger to `PREVIEW_READY`.

There was no X3 redispatch, no Keep, and no Kill.

## Locked preview evidence

- local preview: `D:\Story Auto\evidence\goal54\xianxia\x3_locked_preview.mp4`
- SHA-256: `8c916375cf3ab76b22dbf69da1e1749a9425396632c0c6696ade185be3ca518b`
- bytes: `125040`
- codec: H.264
- dimensions: `836x480`
- frame rate: `24 fps`
- frame count: `97`
- duration: `4.041667 s`
- contact sheet: `D:\Story Auto\evidence\goal54\xianxia\x3_contact_sheet.png`
- contact-sheet SHA-256: `718a2a167f540d46e9b92866112ee7757fe69817223cf361ace4d9353655aeee`

## Acceptance boundary

Technical/provenance acceptance is complete. Visual acceptance is intentionally still pending Owner review of the actual locked preview/contact sheet against `docs/GOAL54_X3_PLAN.md`:

- face/identity continuity with X2;
- matte skin and low-gloss material response retained;
- pavilion/mountain/waterfall/dawn continuity retained;
- camera almost locked;
- small coherent hand raise;
- faint localized translucent pale-blue glow only;
- no scene change, extra character, anatomy break, large spell effect, or style shift.

Do not Keep or Kill X3 automatically. No later experiment is authorized by this evidence alone.
## Assistant visual review of Owner-uploaded locked preview

The Owner uploaded a copy of the X3 locked preview for review. The uploaded bytes were independently verified as the exact locked preview above: SHA-256 `8c916375cf3ab76b22dbf69da1e1749a9425396632c0c6696ade185be3ca518b`, 97 frames, 4.041667 s.

Verdict: `PASS_WITH_MINOR_DRIFT` for the bounded X3 research objective.

- identity/face remains stable across the clip with no obvious age/face reshape drift;
- matte/subdued skin, fabric, wood and environment response remains consistent enough with the accepted continuity direction;
- pavilion, mountains, mist, waterfall/dawn composition remain stable and there is no scene replacement;
- camera is effectively locked for the shot objective;
- the single hand raise is readable and anatomically coherent enough across the motion;
- the pale-blue spiritual effect stays localized to the raised hand and does not expand into a scene-wide aura;
- no extra character, hard cut, combat action, large spell effect or material/style collapse is visible.

Minor drift: the blue glow becomes somewhat stronger than the word `faint` near the end, and the raised-hand/finger rendering is slightly simplified in the final phase, but neither crosses the current X3 rejection threshold.

This assistant review is not Owner approval and does not authorize Keep/Kill. X3 remains locked until the Owner explicitly approves or rejects it.
