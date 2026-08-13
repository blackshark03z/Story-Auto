"""Promote validated corrective drafts into a separate project identity."""
from __future__ import annotations
import argparse, copy, os, shutil
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json, read_json

def relink(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists(): return
    try: os.link(source, target)
    except OSError: shutil.copy2(source, target)

def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("source",type=Path); ap.add_argument("destination",type=Path); args=ap.parse_args()
    src,dst=args.source.resolve(),args.destination.resolve()
    if dst.exists(): raise SystemExit("destination already exists; promotion fails closed")
    (dst/"output").mkdir(parents=True); shutil.copy2(src/"content.md",dst/"content.md")
    project=read_json(src/"project.json"); project["project_id"]=dst.name; atomic_write_json(dst/"project.json",project)
    for name in ("alignment","audio_manifest","content_manifest","story_timeline","continuity_bible"):
        value=read_json(src/"output"/f"{name}.json"); value["project_id"]=dst.name; atomic_write_json(dst/"output"/f"{name}.json",value)
    for name in ("shot_plan","media_plan","generation_requests"):
        value=read_json(src/"output"/f"{name}_corrective_draft.json"); value["project_id"]=dst.name; atomic_write_json(dst/"output"/f"{name}.json",value)
    shutil.copy2(src/"output"/"corrective_visual_intents.json",dst/"output"/"corrective_visual_intents.json")
    alignment=read_json(dst/"output"/"alignment.json"); relink(src/alignment["audio_path"],dst/alignment["audio_path"])
    requests=read_json(dst/"output"/"generation_requests.json")["requests"]; ids={r["request_id"] for r in requests if r.get("purpose")=="REFERENCE"}
    old=read_json(src/"output"/"generation_manifest.json"); entries=[]
    for entry in old.get("requests",[]):
        if entry.get("request_id") not in ids or entry.get("status")!="SUCCEEDED" or not isinstance(entry.get("selected_asset"),dict): continue
        selected=entry["selected_asset"]; relink(src/selected["path"],dst/selected["path"]); entries.append(copy.deepcopy(entry))
    atomic_write_json(dst/"output"/"generation_manifest.json",{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":dst.name,"requests":entries})
    atomic_write_json(dst/"output"/"review_state.json",{"schema_version":"story-auto-review-state/1.0.0","project_id":dst.name,"plan_approval":{"status":"APPROVED","basis":"CORRECTIVE_SUPERSESSION"},"references":{},"assets":{},"batch_confirmations":[]})
    atomic_write_json(dst/"output"/"release_supersession.json",{"status":"CORRECTIVE_IN_PROGRESS","supersedes_project_id":src.name,"rejected_final":"output/final.mp4","corrected_output_identity":"output/final_corrected_v2.mp4"})
    print({"project_id":dst.name,"preserved_reference_assets":len(entries),"generation_requests":len(requests)})
if __name__=="__main__": main()
