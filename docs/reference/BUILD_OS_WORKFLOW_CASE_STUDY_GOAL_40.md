# Goal 40 case study: motion evidence at the producer boundary

## Defect

The Flow executor already rejected every VIDEO request without
`motion_risk_analysis`, and Story Auto already had canonical motion planning,
validation, decomposition, and prompt-compilation primitives. The normal visual
planning path nevertheless published and approved base generation requests
immediately after `compile_generation_requests`. It never performed the
transition through those motion primitives.

Trial B exposed the asymmetric contract: the producer persisted eight
STANDARD_PRODUCTION VIDEO requests without motion evidence, while the consumer
correctly refused to execute them. The stop occurred before manifest creation,
Flow activation, or provider submission.

## Repair

The generation-request producer now constructs a canonical intent for every
base VIDEO request from the authoritative shot and request, routes it through
the existing Gemini motion planner, validates the returned plan, compiles it
through `apply_motion_plans`, and validates the final rewritten artifact before
publishing it.

Atomic decomposition preserves exact request timing, renumbers all parts per
shot, regenerates stable identities and fingerprints, and carries canonical
motion-risk evidence on every resulting VIDEO request. IMAGE requests bypass
motion planning, including every ambient_story request.

The generation-request checkpoint identity now includes both the updated
generation prompt version and `MOTION_PLAN_VERSION`. Final artifact validation
also rejects missing or malformed canonical motion evidence, so a stale
pre-repair artifact cannot remain reusable merely because a checkpoint exists.

## Compatibility proof

The offline sanitized Trial B fixture begins with the persisted pre-repair
shape: hybrid_hook, 16 logical visuals, eight VIDEO requests, no motion
evidence, no generation manifest, and zero provider submissions. Running the
normal post-repair visual-planning path keeps the shot and media checkpoints,
reruns generation-request planning, and publishes eight valid motion-aware
VIDEO requests with no external provider or Flow calls.

## Lesson

Producer and consumer invariants must be symmetric. If execution requires
motion-risk evidence, the canonical generation-request producer must guarantee
that evidence before it publishes an executable artifact; the executor check
remains defense in depth.
