"""Write a non-destructive corrective shot-plan draft."""
from pathlib import Path
import argparse
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.planning.correction import replan_visual_beats
from story_auto.core.planning.service import compile_media_plan, compile_generation_requests, _media_settings
from story_auto.core.project import RuntimeLayout, load_project

parser = argparse.ArgumentParser(); parser.add_argument("project_root", type=Path); parser.add_argument("--max-seconds", type=float, default=45.0); parser.add_argument("--intents", type=Path); args = parser.parse_args()
root = args.project_root; plan = replan_visual_beats(read_json(root/'output/shot_plan.json'), read_json(root/'output/alignment.json'), max_seconds=args.max_seconds)
if args.intents:
    overrides = read_json(args.intents).get("shots", {})
    for shot in plan["shots"]:
        intent = overrides.get(shot["shot_id"])
        if intent:
            for key in ("subject", "action", "location_id", "character_ids", "prop_ids", "composition_intent", "camera_intent", "visual_emotional_purpose", "atmospheric"):
                if key in intent: shot[key] = intent[key]
            shot["resolved_continuity"] = {"characters": shot.get("character_ids", []), "location": shot.get("location_id"), "props": shot.get("prop_ids", []), "time_of_day": shot.get("time_of_day"), "wardrobe_state_refs": shot.get("wardrobe_state_refs", [])}
atomic_write_json(root/'output/shot_plan_corrective_draft.json', plan)
paths, config = load_project(RuntimeLayout.from_root(root.parent.parent), root.name)
settings = _media_settings(config)
media = compile_media_plan(config.project_id, plan, config.render_mode, settings)
requests = compile_generation_requests(config.project_id, plan, media, read_json(root/'output/continuity_bible.json'), settings)
atomic_write_json(root/'output/media_plan_corrective_draft.json', media)
atomic_write_json(root/'output/generation_requests_corrective_draft.json', requests)
print({"shots": len(plan["shots"]), "requests": len(requests["requests"]), "max_seconds": args.max_seconds})
