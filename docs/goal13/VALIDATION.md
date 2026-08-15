# Goal 13 Validation

Goal: `STORY-AUTO-GOAL-13-AMBIENT-STORY-FOUNDATION`

## Automated gates

- `python -m unittest discover -s tests -v`: PASS, 148 tests.
- `python tools/quality_gate.py`: `QUALITY_GATE=PASS`.
- `python tools/security_gate.py`: `SECURITY_GATE=PASS`; `YOUTUBE_AUTO_RUNTIME_IMPORTS=0`.
- `python -m unittest tests.test_ambient_story -v`: PASS, 7 tests.
- `python -m unittest tests.test_ui -v`: PASS, 3 tests.
- `node --check story_auto/ui/static/app.js`: PASS.
- `git diff --check`: PASS (line-ending notices only).

## Offline demo evidence

The demos are fully local fixtures and report `external_provider_calls: 0` in
`runtime/goal13_ambient_demos/ambient-demo-summary.json`.

| Demo | Style | Chapters | Duration | Final | Contact sheet | Black frames |
|---|---|---:|---:|---|---|---|
| `ambient_quiet_verdict_demo` | Quiet Verdict | 3 | 36.0 s | `runtime/goal13_ambient_demos/projects/prj_ambient_quiet_verdict_demo/output/final.mp4` | `runtime/goal13_ambient_demos/projects/prj_ambient_quiet_verdict_demo/output/ambient_contact_sheet.jpg` | none |
| `ambient_hidden_mastery_demo` | Hidden Mastery | 4 | 40.0 s | `runtime/goal13_ambient_demos/projects/prj_ambient_hidden_mastery_demo/output/final.mp4` | `runtime/goal13_ambient_demos/projects/prj_ambient_hidden_mastery_demo/output/ambient_contact_sheet.jpg` | none |

Both render plans resolve exact clean-derivative paths and hashes. Presentation
plans show bounded 1–3% scale change, at most 3% translation, fine-grain
overlays, and 0.35 s crossfades. The compiler regression test streams a 15 s
image segment to the exact requested duration.

## UX review

The creation wizard was inspected in the in-app browser at desktop and narrow
viewport sizes. Ambient Story exposes exactly Quiet Verdict and Hidden Mastery,
the style choice is contextual, the review step reports Format and Ambient
Style, the narrow layout remains reachable, keyboard focus is visible, and the
browser console has no warnings or errors. See `UX_IMPLEMENTATION_REVIEW.md`.

## Compatibility anchors

- Historical release and frozen-design files have no diff; `VERSION` remains
  `1.0.0`.
- Video 001 master SHA-256 remains
  `9b5d794fdf16575616a57a0eb91a437da232a9c59313eaa88b7a39daa6c71e81`.
- Video 002 master SHA-256 remains
  `69c4d2abf7232e4e5ff9cfb9e6b2e6302539cd56ecc8cecc50072f8c10bf495b`.

## Result

Local candidate acceptance: PASS. Trials A and B remain the next explicit
scope; no production-video trial or accepted baseline promotion is claimed.
