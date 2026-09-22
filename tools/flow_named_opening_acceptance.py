"""Bounded real Opening acceptance; existing attempts only resume, never resend."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_auto.core.artifacts import atomic_write_json
from story_auto.core.project import RuntimeLayout, ProjectConfig, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder
from story_auto.providers.flow.opening import generate_flow_cookie_opening
from story_auto.application.operator import OperatorService

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = Path(r'D:\Story Auto\evidence\flow-named-opening-acceptance-20260921')
    project = 'prj_flow_named_acceptance'
    provider_project = 'a94d36d0-5f95-420d-97b4-dc7cf0c87453'
    runtime = RuntimeLayout.from_root(root).ensure()
    if not (runtime.projects/project/'project.json').exists():
        if not args.execute: raise SystemExit('EXPLICIT_EXECUTE_REQUIRED')
        create_project(runtime, ProjectConfig(project, render_mode='hybrid_hook', settings={
            'render': {'width':1280,'height':720,'fps':24,'pixel_format':'yuv420p'},
            'hybrid_visual': {'cuj_enabled':True,'opening_provider_policy':'AUTO'}}),
            '# Flow named-session acceptance\n\n## Narration\n\nA study of colour and motion. Three simple shapes share a single frame.\n')
        configure_opening_builder(root,project,shared_context='Preserve the reference geometry and colours.',slot_specs=[
            {'duration_seconds':6,'purpose':purpose,'prompt':prompt} for purpose,prompt in [
                ('Hook','Very slow camera orbit around the exact reference composition. Preserve the red circle, green triangle, blue rectangle and yellow frame. No additional objects. Smooth cinematic motion.'),
                ('Develop','Slow push toward the same reference shapes, preserving colours and geometry.'),
                ('End','Slow pull away from the same reference shapes, preserving colours and geometry.')]])
    service = OperatorService(root)
    slot = service.opening_builder(project)['slots'][0]
    existing = slot.get('api_generation')
    if not existing and not args.execute: raise SystemExit('EXPLICIT_EXECUTE_REQUIRED')
    os.environ['STORY_AUTO_FLOW_RPC_EXPERIMENTAL']='1'
    os.environ['STORY_AUTO_FLOW_RPC_PROJECT']=provider_project
    options = {} if existing else {
        'account_id':'flow-owner','project_url':'https://flow.google.com/project/'+provider_project,
        'reference_path':Path(r'D:\Story Auto\evidence\transport_probe_20260920\stability-qualification-09\stable-reference.png')}
    print(json.dumps({'project':project,'slot':'OPENING_O1','recovery_only':bool(existing)}),flush=True)
    result=generate_flow_cookie_opening(root,project,'OPENING_O1',timeout_seconds=120,**options)
    selected=result['slots'][0]
    summary={'project':project,'slot':'OPENING_O1','asset_ready':selected.get('asset_ready'),
             'generation':selected.get('api_generation'),'normalized_asset':selected.get('normalized_asset'),
             'scope':'one real Opening slot; full composition and owner acceptance pending'}
    atomic_write_json(root/'slot-result.json',summary)
    print(json.dumps(summary),flush=True)

if __name__ == '__main__': main()
