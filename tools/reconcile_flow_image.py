"""Reconcile one ambiguous Flow image request without a new submission."""
from pathlib import Path
import argparse
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.artifacts import read_json
from story_auto.providers.flow.session import FlowRuntime
from story_auto.providers.flow.live import download_provider_asset_candidate
from story_auto.providers.flow.service import adopt_manual_recovery
ap=argparse.ArgumentParser();ap.add_argument("runtime_root",type=Path);ap.add_argument("project_id");ap.add_argument("request_id");ap.add_argument("--provider-asset-id",required=True);ap.add_argument("--attribution",required=True);args=ap.parse_args()
rt=RuntimeLayout.from_root(args.runtime_root);paths,cfg=load_project(rt,args.project_id);manifest=read_json(paths.artifact_path("output/generation_manifest.json"));entry=next(x for x in manifest["requests"] if x.get("request_id")==args.request_id)
if entry.get("status")!="AMBIGUOUS": raise SystemExit("request is not ambiguous")
target=paths.artifact_path(f"assets/reconciliation/{args.request_id}_{args.provider_asset_id}.png");download_provider_asset_candidate(FlowRuntime.from_settings(rt,cfg.settings),target,provider_asset_id=args.provider_asset_id)
settings=dict(entry["attempts"][-1].get("provider_settings") or {});settings["provider_asset_id"]=args.provider_asset_id
selected=adopt_manual_recovery(rt.root,cfg.project_id,args.request_id,target,settings=settings,attribution=args.attribution);print(selected)
