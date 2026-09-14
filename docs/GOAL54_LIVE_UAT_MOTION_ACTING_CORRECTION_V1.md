# Goal 54 — Live UAT Motion / Acting Correction V1

Date: 2026-09-14
Status: OWNER_REJECTED_V1 / PROVIDER_FREE_CORRECTION_READY / NO_KILL_YET

## Owner visual verdict

The exact live production locked preview at SHA-256 `a8c72a65008492638863ccfa31e0e59267e756c6d1d68a538883c0149e92a0f8` is rejected for product quality: **motion and facial expression are too stiff**.

The canonical production manifest records the decision as `PREVIEW_REJECTED`. No Keep/unlock has occurred. No Kill has occurred.

## Root cause

The V1 provider prompt over-constrained movement. It explicitly asked for:

- camera almost locked;
- torso and head mostly steady;
- one hand moving only a small distance;
- one subtle blink;
- faint/minimal secondary motion.

Those instructions strongly bias a reference-I2V model toward a near-static mannequin-like performance. The prompt also named an historical `kept X2` result while the live production attempt was actually bound to the canonical supplied X3 continuity frame. The next prompt must refer only to the supplied continuity reference, never a stale research-step name.

## Prompt correction policy

For human-centered story shots, continuity constraints must preserve identity and scene without suppressing performance. A four-second shot should contain a small number of readable acting beats with connected whole-body mechanics:

1. posture/breath/weight shift establishes life;
2. eyes, head, shoulder, elbow, wrist and fingers participate in the intended gesture;
3. facial micro-expression changes with the beat rather than remaining frozen;
4. fabric/hair follow-through responds to body movement;
5. camera may use one restrained cinematic move when it improves life and readability.

Avoid vague constraints such as `mostly steady`, `small distance`, `subtle motion everywhere`, or a long stack of `no movement` clauses when the acceptance target is natural human acting.

## Replacement prompt V2

Use the supplied reference image as the exact continuity reference. Preserve the same adult Chinese female cultivator, face identity, long black half-up hair, silver-blue floral hairpin, restrained earrings, white and pale-blue layered xianxia hanfu, teal waist sash, jade pendant, wooden mountain pavilion, misty mountains, waterfall, distant pavilion, and subdued blue-white-gold dawn palette.

Preserve the accepted soft matte material response: natural fair skin with visible texture and restrained highlights, low-gloss soft-satin fabric, diffuse weathered wood, muted rocks and architecture, and only small localized reflections on jade and metal. Do not beautify, polish, whiten, or re-style the scene.

Create a continuous natural four-second performance with readable but restrained acting. At the start she takes a calm visible breath and shifts her weight slightly through the torso and shoulders while her eyes focus toward the hand she is about to raise. She then raises one hand smoothly from a relaxed position toward chest/shoulder height using connected shoulder, elbow, wrist and finger motion; the wrist turns naturally and the fingers uncurl with soft asymmetry instead of moving as one rigid piece. Her head turns about 8–12 degrees and her gaze follows the hand. As a faint pale-blue spiritual glow gathers close to the palm, her expression changes from calm neutrality to quiet focused wonder: a slight brow lift, subtle eyelid response and a small natural parting of the lips, then settling into composed concentration. Breathing remains visible, and the sleeve edge plus a few loose hair strands show gentle follow-through from the movement and breeze.

Use a very gentle cinematic push-in over the shot, only enough to add life and draw attention to the face and raised hand. Keep motion smooth and physically connected with natural acceleration/deceleration. One character only. Keep identity, facial proportions, costume, lighting and environment stable.

Avoid frozen pose, mannequin stiffness, isolated hand-only animation, rigid torso, fixed stare, expressionless face, synchronized finger motion, abrupt gesture, overacting, face reshaping, younger-looking face, style shift, glossy/waxy/plastic skin, bright aura, sparks, explosion, large spell effect, scene change, cut, orbit, handheld shake, flying sword, combat, or extra characters.

## V2 visual acceptance

A replacement preview may pass only when all are true:

- gesture uses connected shoulder/elbow/wrist/finger mechanics rather than an isolated moving hand;
- torso/head/gaze participate naturally but identity remains stable;
- expression visibly evolves with the action while remaining restrained and character-consistent;
- breathing plus hair/fabric follow-through prevent a frozen mannequin impression;
- camera movement is smooth and secondary to the acting;
- no critical identity, anatomy, continuity, material/style or scene drift occurs.

## Provenance / replacement boundary

The Elyum replacement lifecycle now supports a full `replacement_prompt` snapshot. The new attempt persists the exact prompt text and SHA-256 and derives a distinct clientRef before provider mutation. The rejected attempt remains immutable.

Kill is still a separate explicit provider consequence because it consumes the account's kill allowance. No replacement provider generation is authorized by this document alone.
