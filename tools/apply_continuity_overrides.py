"""Apply explicit visual-design overrides and recompile request identities."""
from __future__ import annotations
import argparse
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.planning.service import compile_generation_requests, _media_settings, validate_continuity, validate_generation_requests
from story_auto.core.project import RuntimeLayout, load_project

ap=argparse.ArgumentParser(); ap.add_argument("project_root",type=Path); ap.add_argument("overrides",type=Path); args=ap.parse_args()
root=args.project_root.resolve(); overrides=read_json(args.overrides); continuity=read_json(root/'output/continuity_bible.json')
for section in ("characters","locations","props"):
    for entity in continuity.get(section,[]):
        if entity.get("entity_id") in overrides: entity["visual_design"]=overrides[entity["entity_id"]]
timeline=read_json(root/'output/story_timeline.json'); validate_continuity(continuity,timeline); atomic_write_json(root/'output/continuity_bible.json',continuity)
runtime=RuntimeLayout.from_root(root.parent.parent); paths,config=load_project(runtime,root.name); shots=read_json(root/'output/shot_plan.json'); media=read_json(root/'output/media_plan.json'); settings=_media_settings(config)
requests=compile_generation_requests(config.project_id,shots,media,continuity,settings); validate_generation_requests(requests,media,continuity); atomic_write_json(root/'output/generation_requests.json',requests)
print({"continuity_entities":len(overrides),"generation_requests":len(requests["requests"])})
