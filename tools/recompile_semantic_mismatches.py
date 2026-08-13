"""Replace only failed semantic shot requests with text-grounded identities."""
from __future__ import annotations
import argparse, hashlib
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.planning.service import validate_generation_requests
from story_auto.core.visual import compile_image_prompt, compile_video_prompt

def digest(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument("project_root",type=Path);ap.add_argument("decisions",type=Path);args=ap.parse_args();root=args.project_root.resolve()
document=read_json(root/"output/generation_requests.json");decisions=read_json(args.decisions)["decisions"];shots={x["shot_id"]:x for x in read_json(root/"output/shot_plan.json")["shots"]};continuity=read_json(root/"output/continuity_bible.json");entities={x["entity_id"]:x for section in ("characters","locations","props") for x in continuity.get(section,[])}
replacements={}
for request in document["requests"]:
    if decisions.get(request["request_id"],{}).get("classification")!="MISMATCH": continue
    shot=shots[request["shot_id"]];chars=[entities[x] for x in shot.get("character_ids",[])];props=[entities[x] for x in shot.get("prop_ids",[])];location=entities.get(shot.get("location_id"),{})
    char_text="; ".join(f"{x['name']}: {x.get('visual_design',{})}" for x in chars);prop_text="; ".join(f"{x['name']}: {x.get('visual_design',{})}" for x in props)
    detail=f"Exact story shot. Active subject: {shot['subject']}. Visible action: {shot['action']}. Location: {location.get('name')}, {location.get('visual_design',{})}. Critical props: {prop_text or 'none'}. Character designs: {char_text or 'no featured character'}. Composition: {shot['composition_intent']}. Do not substitute a portrait, an empty room, a prop-only still life, or an unrelated musician. Single coherent cinematic frame, no collage or split panels"
    if request["media_type"]=="IMAGE": prompt=compile_image_prompt(detail,request["visual_policy"])
    else: prompt=detail+". "+compile_video_prompt(subject_motion=shot["action"],environmental_motion="only subtle physically plausible movement in the described academy location",camera_motion=shot.get("camera_intent","STATIC"),timing=f"part {request.get('part_index',1)} of {request.get('part_count',1)}, {float(request['target_duration']):.3f} seconds")
    identity=digest(request["fingerprint"]+"|semantic-correction-v3|"+prompt);new=dict(request);new.update({"request_id":"req_"+identity[:20],"fingerprint":identity,"prompt":prompt,"depends_on":[],"reference_asset_ids":[],"supersedes_request_id":request["request_id"],"semantic_correction":"TEXT_GROUNDED_V3"});replacements[request["request_id"]]=new
document["requests"]=[replacements.get(x["request_id"],x) for x in document["requests"]];document["prompt_version"]="story-auto-generation-prompt/3.0.0-semantic-correction";media=read_json(root/"output/media_plan.json");validate_generation_requests(document,media,continuity);atomic_write_json(root/"output/generation_requests.json",document)
print({"replaced_requests":len(replacements),"preserved_requests":len(document["requests"])-len(replacements)})
