"""One owner-authorized diagnostic; no retry of old or new submissions."""
import json
import sys
from pathlib import Path
from functools import partial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.cookie_session import CookieBrowserRpcSession
from story_auto.providers.flow.rpc_transport import FlowRpcGenerator, JOURNAL_NAME, submission_diagnostic
from story_auto.providers.flow.session import FlowRuntime
from story_auto.providers.flow import rpc_contract

ROOT = Path(r'D:\Story Auto\evidence\flow-authorized-diagnostic-20260921')
COOKIE = Path(r'D:\Story Auto\cookie\flow_profile_export_20260921T153746199592Z.json')
PROJECT = 'a94d36d0-5f95-420d-97b4-dc7cf0c87453'

class DiagnosticSession(CookieBrowserRpcSession):
    def rpc(self, rpcid, body):
        text = super().rpc(rpcid, body)
        if rpcid == rpc_contract.RPC_VIDEO:
            summary = submission_diagnostic(text)
            payload = rpc_contract.parse_rpc(text, rpcid)
            # Only fixed tokens and booleans escape memory, never provider prose.
            lowered = json.dumps(payload).lower()
            summary['signals'] = {key:key in lowered for key in (
                'captcha', 'permission_denied', 'unauthenticated', 'resource_exhausted',
                'invalid_argument', 'quota', 'credits', 'error', 'failed')}
            summary['null_payload'] = payload is None
            atomic_write_json(ROOT/'submission-response-summary.json', summary)
        return text

def main():
    if '--execute' not in sys.argv:
        raise SystemExit('EXPLICIT_EXECUTE_REQUIRED')
    ROOT.mkdir(parents=True, exist_ok=True)
    if (ROOT/JOURNAL_NAME).exists():
        raise SystemExit('EXISTING_ATTEMPT_READ_ONLY_RECONCILIATION_REQUIRED')
    atomic_write_json(ROOT/'intent.json', {'scope':'one separate authorized diagnostic',
        'max_submits':1,'project':PROJECT,'old_attempt_untouched':True})
    runtime=FlowRuntime(COOKIE.parent,'cookie-owned://diagnostic',
                        'https://flow.google.com/project/'+PROJECT,PROJECT)
    generator=FlowRpcGenerator(runtime,session_factory=partial(DiagnosticSession,cookie_file=COOKIE),timeout_seconds=60)
    request={'request_id':'authorized-diagnostic-20260921','media_type':'VIDEO',
             'target_duration':8,'aspect_ratio':'16:9','output_count':1,
             'prompt':'A slow gentle zoom toward the reference geometric shapes. Keep the red circle, green triangle, blue rectangle and yellow frame unchanged. No new objects.'}
    def boundary(): atomic_write_json(ROOT/'boundary.json',{'entered':True})
    result={'status':'UNRESOLVED'}
    try:
        output=generator.run(request,[Path(r'D:\Story Auto\evidence\transport_probe_20260920\stability-qualification-09\stable-reference.png')],ROOT/'output.mp4',before_boundary=boundary)
        result.update(status='ACQUIRED',output=str(output))
    except Exception as error:
        result['failure_class']=getattr(error,'failure_class',type(error).__name__)
        result['safe_code']=str(error) if result['failure_class']=='FLOW_DISPATCH_UNCERTAIN' else 'LOCAL_ERROR'
    atomic_write_json(ROOT/'result.json',result)
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()
