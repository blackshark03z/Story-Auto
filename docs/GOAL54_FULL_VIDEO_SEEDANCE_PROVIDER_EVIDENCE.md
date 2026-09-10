# Goal 54 — Full Video Seedance Provider Evidence Plan

This document is the durable research/evidence plan for Goal 54. Provider web
pages, chat research, and community reports are discovery inputs only. A provider
moves from candidate to qualified only through direct evidence tied to date,
account context, model identity, request/result identity, and the Story Auto
source/configuration used for the probe.

## Candidate queue

Initial candidates: Dola, Dreamina, Elyum, Pollo, DeeVid, AdSkull, plus any other
Seedance-access provider discovered during research. Inclusion here means only
"worth checking"; it is not a recommendation or acceptance result.

## Evidence matrix

For every candidate record:

| Dimension | Required evidence |
| --- | --- |
| Provider/model identity | Exact provider surface and exposed Seedance model/version |
| Access surface | Public API, supported integration, browser-only, or other |
| Free/trial | Credits/quota, reset behavior, account restrictions, expiration |
| Input contract | T2V/I2V/reference/video-edit inputs actually accepted |
| Output contract | Duration, resolution, aspect ratio, audio, watermark |
| Usage rights | Relevant personal/commercial restrictions found in provider terms |
| Job identity | Request/job/result identifiers available to bind attempts |
| Acquisition | Stable downloadable result or deterministic local acquisition path |
| Failure semantics | Timeout/error/queued/ambiguous states and safe reconciliation |
| Cost consequence | Observable credit/cost before or after dispatch where available |
| Automation fit | Can Story Auto integrate without fragile undocumented UI assumptions? |
| Runtime result | PASS/BLOCK/FAIL with evidence pointer and date |

Unknown must remain UNKNOWN. Do not infer unsupported capability from marketing
copy or another provider's Seedance implementation.

## Benchmark order

### Stage A — read-only qualification

1. Verify current model availability and access surface.
2. Verify documented/free quota and usage restrictions.
3. Identify job/result identity and output-acquisition contract.
4. Identify ambiguity/retry semantics before spending provider quota.
5. Rank candidates for the first vertical slice.

No generation is required to complete Stage A.

### Stage B — single-scene vertical slice

Use one fixed approved Story Auto scene with one REQUIRED VIDEO request. For the
selected candidate:

1. compile the provider request from existing Story Auto generation-request data;
2. record provider/model/request identity before dispatch;
3. dispatch one bounded generation;
4. preserve attempt state and any observable quota/cost consequence;
5. acquire the result once ownership is sufficiently attributable;
6. validate local media and hash it;
7. feed the asset through existing media/render contracts;
8. exercise unchanged resume and one realistic failure/recovery path without
   duplicate generation.

A provider is QUALIFIED_FOR_E2E only after Stage B passes.

### Stage C — Full Video E2E

Expand only the best qualified provider to a representative multi-scene fixture.
Acceptance requires complete REQUIRED VIDEO coverage, final render through the
existing compositor, provenance continuity, regression evidence for Full Image,
and one identified Product HEAD.

## Selection rule

Prefer the provider that satisfies Goal 54 with the smallest reliable system
change. Free access is valuable but does not outrank identity/recovery safety or
output usability. A slightly paid provider can beat a free provider if the free
path requires fragile UI scraping, cannot bind result ownership, or cannot be
recovered safely.

## Abstraction trigger

Do not create a generic provider router now. Reconsider only after a second
provider is directly characterized and there is concrete repeated logic or
provider volatility worth isolating. Until then, one narrow adapter is the
preferred implementation shape.

## Evidence record template

For each direct probe append a dated section containing:

- provider + exact model;
- source HEAD/configuration;
- access/account tier (without secrets);
- request fixture/fingerprint;
- request/job/result identities;
- observable credits/cost before and after;
- output properties + local SHA-256;
- failure/retry observations;
- verdict: `CANDIDATE`, `BLOCKED`, `QUALIFIED_FOR_E2E`, or `REJECTED`;
- evidence paths/screenshots/log references retained outside source when large.

Do not mark Goal 54 complete from this document alone. `TASK.md` acceptance and
identified runtime evidence remain the completion oracle.
