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

### Stability gate — 2026-09-12

Production candidates must satisfy all of the following before implementation:

- documented programmatic API; no browser/session/CDP dependency;
- durable provider task/job identity returned by submission;
- queryable non-terminal and terminal states;
- deterministic result acquisition from the identified task;
- explicit failure/timeout semantics sufficient to avoid blind duplicate POSTs;
- server-side credentials with no account/session scraping.

Dola and Dreamina browser surfaces fail this production gate even if their free
quota is attractive. Google Flow remains the accepted Full Image provider but is
not reused for the new Full Video production transport.

The first implementation candidate is BytePlus ModelArk first-party Seedance
2.5 using model `dreamina-seedance-2-5-260628` and the official asynchronous
`/api/v3/contents/generations/tasks` contract. The provider returns a durable task
ID, supports direct task polling, and returns the completed video URL from the
same task record. This choice is provisional until direct runtime credential and
single-scene evidence passes.

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

## Stage A research snapshot — 2026-09-12

This is discovery evidence only. No provider below is `QUALIFIED_FOR_E2E` yet;
no Story Auto generation has been dispatched in this stage.

| Provider | Current evidence | Free/trial evidence | Automation evidence | Stage A status |
| --- | --- | --- | --- | --- |
| Elyum | Provider page exposes Seedance 2.5, 4–30s, 480p/720p/1080p, native audio, T2V/I2V/reference/edit | 150 starter credits; no card; keep/kill billing advertised | Provider states Web Studio + REST + MCP | `CANDIDATE_HIGH` |
| AdSkull | Provider page exposes Seedance 2.5, 4–30s, 480p/720p | 50 signup credits; enough for one 4s/480p generation | Provider states public API + MCP | `CANDIDATE_HIGH` |
| Pollo AI | Provider states Seedance 2.5 is available through Pollo API | Free/API trial wording exists, exact reusable quota still needs account verification | Public asynchronous API family uses task identity; 2.5-specific runtime contract still needs direct probe | `CANDIDATE_HIGH` |
| Dreamina | Official CapCut/Dreamina surface exposes Seedance 2.5, up to 30s and multimodal references | Official page states free daily/trial credits; allowance varies by account/region | Creator web surface verified; public automation contract not yet established here | `CANDIDATE_MEDIUM` |
| Dola | Recent third-party walkthrough shows Seedance 2.5 available at dola.com | Walkthrough reports free-account credits sufficient for one video and next-day refill | No public API/job identity contract verified yet | `CANDIDATE_MEDIUM_UNVERIFIED_AUTOMATION` |
| DeeVid | Provider page exposes Seedance 2.5 and multimodal reference inputs | Provider advertises free creation; exact quota/cost not yet verified | Public API/job identity contract not yet verified | `CANDIDATE_MEDIUM` |

### Discovery sources

- Elyum Seedance 2.5: https://elyum.ai/models/seedance-2-5
- AdSkull Seedance 2.5: https://adskull.io/en/free/seedance-2-5
- Pollo Seedance 2.5 API guide: https://pollo.ai/hub/seedance-2-5-api
- Pollo existing Seedance async API family: https://docs.pollo.ai/m/seedance/seedance
- Dreamina official Seedance 2.5: https://dreamina.capcut.com/seedance/seedance-2-5
- CapCut newsroom Seedance 2.5 announcement: https://www.capcut.com/newsroom/giving-creators-more-control-with-dreamina-seedance-2-5-and-dola-seedream-5-0-pro
- Dola walkthrough used only as non-authoritative discovery evidence: https://quantrimang.com/tao-video-ai-bang-seedance-2-5-tren-dola-ai-217032
- DeeVid Seedance 2.5: https://deevid.ai/model/seedance-2

### Stage A supersession — stability first

The provisional aggregator ranking above is retained only as historical discovery
context. Owner direction on 2026-09-12 makes connection stability the dominant
selection criterion. Story Auto therefore stops production-path research on
browser/UI routes and does not spend implementation effort qualifying third-party
aggregators while the first-party BytePlus contract remains viable.

### BytePlus implementation evidence — 2026-09-12

- Selected transport: first-party BytePlus ModelArk REST async task API.
- Model: `dreamina-seedance-2-5-260628`.
- Production adapter: `story_auto/providers/byteplus_seedance/`.
- Full Video planning emits only `byteplus_seedance` VIDEO requests for the
  initial path; no Flow reference-image requests are introduced.
- Submission state is persisted before and immediately after the provider
  boundary. A returned task ID becomes the sole polling/ownership key.
- Known task IDs resume with GET only. POST timeout/5xx ambiguity is persisted as
  `AMBIGUOUS` and cannot trigger blind resubmission.
- Terminal failed/expired/cancelled tasks require an explicit replacement
  decision rather than automatic redispatch.
- Completed results are downloaded to Story Auto-owned storage, validated with
  FFprobe, hashed, and enter the existing manifest as `QC_PENDING`.
- Full Video quality remains manual until automated video QC is accepted.
- Implementation checkpoint: `d2c32745ef1f551f1ef924378b83628464bbde79`
  (`Goal54-stable-api-first-Seedance-path`).
- First-party contract cross-check:
  - BytePlus ModelArk integration guide uses
    `https://ark.ap-southeast.bytepluses.com/api/v3` as the default ModelArk
    base URL and `BYTEPLUS_MODELARK_API_KEY` for image/video auth.
  - BytePlus' official ModelArk MCP API reference exposes Seedance create-task,
    get-task and list-task operations, with create treated as non-idempotent and
    get/list as read-only/idempotent operations.
  - BytePlus LAS documentation independently lists
    `dreamina-seedance-2-5-260628`, async task identity, 4–30 second output and
    480p/720p support. Story Auto uses the ModelArk `/api/v3` contract, not the
    separate LAS operator `/api/v1` endpoint.
- Focused post-implementation gate: 41/41 `unittest` tests PASS, `node --check`
  PASS, and `git diff --check` PASS.
- Full hermetic regression (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`) completed at
  100% with 714 tests PASS and 283 subtests PASS. The ChatCode command wrapper
  reached its timeout only after pytest emitted the complete PASS summary.
- Credential-safe no-generation probe:
  `python tools/goal54_seedance_preflight.py`.
- Live probe result on 2026-09-12: `BLOCKED / CREDENTIAL_MISSING`. No generation
  task was submitted and no provider credit was spent.

First-party references retained for future verification:

- https://github.com/byteplus-sa/modelark-mcp/blob/main/docs/integration-guide.md
- https://github.com/byteplus-sa/modelark-mcp/blob/main/docs/api-reference.md
- https://docs.byteplus.com/en/docs/Byteplus_LAS/video_gen_enhanced

### Next safe action

Configure a ModelArk API key in the Story Auto process, rerun the zero-generation
list-tasks preflight, and only if it passes submit one 4-second 480p Stage B
fixture through Story Auto. Do not substitute a browser provider for this direct
credential blocker.
