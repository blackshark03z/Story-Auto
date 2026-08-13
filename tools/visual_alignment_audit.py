"""Build the durable visual/narration shot mapping audit for a project."""
from __future__ import annotations
import argparse
import html
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.visual_alignment import build_shot_mapping_audit

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    root = args.project_root
    load = lambda n: read_json(root / "output" / f"{n}.json")
    audit = build_shot_mapping_audit(alignment=load("alignment"), shot_plan=load("shot_plan"),
        media_plan=load("media_plan"), generation_requests=load("generation_requests"),
        generation_manifest=load("generation_manifest"), render_plan=load("render_plan"))
    atomic_write_json(root / "output" / "visual_narration_alignment.json", audit)
    rows = audit["rows"]
    body = "".join(f"<tr><td>{html.escape(str(r['shot_id']))}</td><td>{float(r['final_timeline_start'] or 0):.3f}–{float(r['final_timeline_end'] or 0):.3f}</td><td>{html.escape(r['alignment_classification'])}</td><td>{html.escape(str(r['selected_asset_sha'] or ''))}</td><td>{html.escape(str(r['narration_excerpt'] or '')[:320])}</td><td>{html.escape(str((r['intended'] or {}).get('subject', '')))} — {html.escape(str((r['intended'] or {}).get('action', '')))}</td></tr>" for r in rows)
    (root / "output" / "visual_alignment_review.html").write_text("<!doctype html><meta charset='utf-8'><title>Visual/narration alignment audit</title><style>body{font:14px sans-serif}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px;vertical-align:top}.MISMATCH{background:#ffd7d7}</style><h1>Visual/narration alignment audit</h1><p>RELEASE_CANDIDATE_VISUAL_ALIGNMENT_REJECTED — diagnostic sample; not a corrected release.</p><table><thead><tr><th>Shot</th><th>Timeline</th><th>Class</th><th>Asset SHA</th><th>Narration</th><th>Intent</th></tr></thead><tbody>" + body + "</tbody></table>", encoding="utf-8")
    print(audit["metrics"])

if __name__ == "__main__": main()
