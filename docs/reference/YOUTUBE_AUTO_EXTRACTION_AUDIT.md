# YouTube Auto Extraction Audit — Source Reference

Inspected preview commit: `d0c86c8e0258b7c2f3d59469e2b00a951025207e` (2026-07-27). The supplied preview had no source test files and no live provider rendering evidence.

## Port/adapt candidates

- strict `core/content.py` parsing (do not retain permissive whole-document fallback);
- narration compare/chunk utilities;
- atomic file helpers, adding Story Auto durability policy;
- ElevenLabs TTS/alignment/error classification, removing old paths/manifests;
- Typecast TTS/timestamps, replacing plaintext credential assumptions;
- secure config / provider key fallback / LLM errors under Story Auto namespace;
- timeline LLM grouping/reconstruction logic only, targeting new Story timeline contract;
- SRT/ASS timing/wrapping;
- bounded retry primitive;
- ProjectLock pattern;
- Google Flow image browser mechanics, isolated under provider boundary;
- low-level FFmpeg/FFprobe helpers.

## Reference only / do not port contracts

- current character/prompt/style contracts: insufficient continuity state;
- current StageCache: useful concept but too coupled to old stages/styles;
- old Flow launch profile: recreate dedicated Story Auto profile;
- legacy composer: image-only/sequential and coupled to old timeline/motion behavior;
- old metadata/thumbnail pipeline: patterns only;
- old project/run_pipeline/UI/runtime layout: do not port.

## Flow mechanics worth adapting

- CDP health check and dedicated debug profile pattern;
- explicit project URL + login detection;
- fail-closed prompt-editor discovery;
- prompt insertion + readback verification;
- generate-control resolution scoped to active composer;
- cross-process single-flight lock/cooldown/bounded attempts;
- completion by pre/post media candidate comparison;
- image extraction/decodability/placeholder rejection + atomic publication.

## New Story Auto work still required

- Flow video workflow;
- capability discovery;
- video download/validation;
- manifest idempotency;
- ambiguous-timeout reconciliation;
- new checkpoint store;
- continuity/shot/media contracts;
- normalized media compositor;
- replacement test suite.
