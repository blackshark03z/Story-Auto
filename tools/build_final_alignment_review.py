"""Build a timestamped human visual-alignment review package from final bytes."""
from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file


def stamp(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
args = parser.parse_args()
root = args.project_root.resolve()
output = root / "output"
video = output / "final.mp4"
audit = read_json(output / "visual_narration_alignment.json")
review = output / "review"
frames = review / "frames"
frames.mkdir(parents=True, exist_ok=True)
try:
    font = ImageFont.truetype("arial.ttf", 20)
except OSError:
    font = ImageFont.load_default()
rows = []
for index, row in enumerate(audit["rows"], 1):
    start, end = float(row["final_timeline_start"]), float(row["final_timeline_end"])
    at = (start + end) / 2
    target = frames / f"{index:03d}_{row['shot_id']}_{at:010.3f}.jpg"
    subprocess.run(["ffmpeg", "-y", "-ss", f"{at:.3f}", "-i", str(video),
                    "-frames:v", "1", "-q:v", "2", str(target)],
                   check=True, capture_output=True)
    rows.append({"index": index, "timestamp": at, "timestamp_label": stamp(at),
                 "shot_id": row["shot_id"], "request_id": row["generation_request_id"],
                 "classification": row["alignment_classification"],
                 "narration_excerpt": row["narration_excerpt"],
                 "observation": row.get("alignment_observation"),
                 "frame": target.relative_to(output).as_posix()})

sheets = []
for page, offset in enumerate(range(0, len(rows), 6), 1):
    canvas = Image.new("RGB", (1600, 1500), "white")
    draw = ImageDraw.Draw(canvas)
    for slot, row in enumerate(rows[offset:offset + 6]):
        col, line = slot % 2, slot // 2
        x, y = 20 + col * 790, 20 + line * 490
        frame = Image.open(output / row["frame"]).convert("RGB")
        frame.thumbnail((750, 360))
        canvas.paste(frame, (x, y))
        label = f"{row['timestamp_label']}  {row['shot_id']}  {row['classification']}\n{row['request_id']}"
        draw.multiline_text((x, y + 370), label, fill="black", font=font, spacing=6)
    path = review / f"contact_sheet_{page:02d}.jpg"
    canvas.save(path, quality=92)
    sheets.append(path.relative_to(output).as_posix())

metrics = audit["metrics"]
body = []
for row in rows:
    body.append("<tr>" +
        f"<td>{html.escape(row['timestamp_label'])}</td><td>{html.escape(row['shot_id'])}</td>" +
        f"<td>{html.escape(row['classification'])}</td>" +
        f"<td><img src='{html.escape(row['frame'])}' loading='lazy'></td>" +
        f"<td>{html.escape(row['narration_excerpt'])}<br><em>{html.escape(row['observation'] or '')}</em></td></tr>")
page = """<!doctype html><meta charset='utf-8'><title>Corrected visual alignment review</title>
<style>body{font:15px Arial;margin:24px;background:#eee;color:#181818}h1{margin-bottom:4px}.gate{padding:14px;background:#fff4c2;border:2px solid #9a7000}table{border-collapse:collapse;background:white;width:100%%}th,td{border:1px solid #bbb;padding:9px;vertical-align:top}img{width:420px}em{color:#555}</style>
<h1>Corrected long-form visual alignment review</h1>
<p class='gate'><b>REVIEW_REQUIRED — CORRECTED_LONG_FORM_VISUAL_ALIGNMENT</b><br>Operator decision: approve or reject the corrected output. This package does not self-approve release.</p>
<p><b>Audit:</b> %d final parts · %d unique assets · DIRECT %d · SUPPORTIVE %d · ATMOSPHERIC %d · MISMATCH %d · longest still %.3fs.</p>
<p>Every final shot part is sampled at its midpoint. The first 55 seconds contain six separate hook samples. Review narration meaning, entity continuity, visible action, and provider watermark limitations.</p>
<table><thead><tr><th>Time</th><th>Shot</th><th>Class</th><th>Frame</th><th>Narration / semantic observation</th></tr></thead><tbody>""" % (
    metrics["total_final_shots"], metrics["unique_selected_asset_hashes"],
    metrics["classification_counts"]["DIRECT"], metrics["classification_counts"]["SUPPORTIVE"],
    metrics["classification_counts"]["ATMOSPHERIC"], metrics["classification_counts"]["MISMATCH"],
    metrics["maximum_single_still_screen_duration_seconds"],
) + "".join(body) + "</tbody></table>"
(review / "visual_alignment_review.html").write_text(page, encoding="utf-8")
manifest = {"schema_version": "story-auto-human-alignment-review/1.0.0",
            "decision": "REVIEW_REQUIRED — CORRECTED_LONG_FORM_VISUAL_ALIGNMENT",
            "video": "output/final.mp4", "video_sha256": sha256_file(video),
            "first_55_second_sample_count": sum(r["timestamp"] <= 55 for r in rows),
            "rows": rows, "contact_sheets": sheets,
            "visual_alignment_metrics": audit["metrics"]}
atomic_write_json(review / "review_manifest.json", manifest)
print(json.dumps({"review_rows": len(rows), "contact_sheets": len(sheets),
                  "decision": manifest["decision"]}))
