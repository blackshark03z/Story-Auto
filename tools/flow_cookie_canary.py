"""One explicitly authorized cookie-session reference-video canary.

Existing journals are recovery-only; no automatic upload/submit replay.
"""
import argparse
from functools import partial
import json
from pathlib import Path
from datetime import datetime, timezone

from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.cookie_session import CookieBrowserRpcSession
from story_auto.providers.flow.rpc_transport import FlowRpcGenerator, JOURNAL_NAME
from story_auto.providers.flow.session import FlowRuntime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookies',type=Path,required=True)
    parser.add_argument('--provider-project',required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    from uuid import UUID
    project = str(UUID(args.provider_project))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    journal = args.output_dir / JOURNAL_NAME
    recovery = journal.exists()
    if not recovery and not args.execute:
        raise SystemExit('Explicit --execute required for first submission')
    runtime = FlowRuntime(args.cookies.resolve().parent, 'cookie-owned://local-export',
                          'https://flow.google.com/project/'+project, project)
    request = {'request_id':'cookie-reference-video-canary-01','media_type':'VIDEO',
               'target_duration':8,'aspect_ratio':'16:9','output_count':1,
               'prompt':'Very slow camera orbit around the exact reference composition. Preserve the red circle, green triangle, blue rectangle and yellow frame. No additional objects. Smooth cinematic motion.'}
    factory = partial(CookieBrowserRpcSession,cookie_file=args.cookies)
    generator = FlowRpcGenerator(runtime,session_factory=factory,timeout_seconds=180)
    result = {'scope':'isolated cookie reference-video canary, not product acceptance',
              'recovery_only':recovery,'status':'UNRESOLVED'}
    def boundary():
        atomic_write_json(args.output_dir/'provider-boundary.json',{'entered':True,'request_id':request['request_id']})
    try:
        output = generator.run(request,[args.reference],args.output_dir/'output.mp4',before_boundary=boundary,recovery_only=recovery)
        result.update(status='ACQUIRED',output=str(output))
    except Exception as error:
        result['failure_class'] = getattr(error,'failure_class',type(error).__name__)
        # FlowRpcGenerator maps provider messages to known, token-free error codes.
        result['detail'] = str(error) if result['failure_class']=='FLOW_DISPATCH_UNCERTAIN' else 'Unclassified local failure'
    if journal.exists():
        saved = json.loads(journal.read_text(encoding='utf-8'))
        result['journal'] = {k:saved.get(k) for k in ('state','upload_attempts','submit_attempts','output_id','output_sha256')}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    atomic_write_json(args.output_dir/('result-'+stamp+'.json'),result)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='ACQUIRED' else 2


if __name__=='__main__': raise SystemExit(main())
