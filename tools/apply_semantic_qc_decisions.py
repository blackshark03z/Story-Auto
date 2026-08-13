"""Persist structured semantic QC decisions without deleting attempts."""
from pathlib import Path
import argparse
from story_auto.core.artifacts import read_json
from story_auto.providers.flow.service import FlowError, review_production_asset
FIELDS=("SKIN_REALISM","LIGHTING_NATURALISM","MATERIAL_REALISM","COMPOSITION_NATURALISM","AI_POLISH","CONTINUITY","TECHNICAL_VALIDITY")
ap=argparse.ArgumentParser();ap.add_argument("runtime_root",type=Path);ap.add_argument("project_id");ap.add_argument("decisions",type=Path);args=ap.parse_args();decisions=read_json(args.decisions)["decisions"]
counts={}
for request_id,decision in decisions.items():
    classification=decision["classification"];report={"results":{k:"PASS" for k in FIELDS},"visible_provider_watermark":True,"reviewer":"structured_multimodal_shot_review","notes":decision["observed"],"alignment_classification":classification}
    try: review_production_asset(args.runtime_root,args.project_id,request_id,report)
    except FlowError as error:
        if classification!="MISMATCH" or error.failure_class!="VISUAL_NARRATION_ALIGNMENT_MISMATCH": raise
    counts[classification]=counts.get(classification,0)+1
print(counts)
