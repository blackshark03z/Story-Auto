"""One real village reference via existing IMAGE adapter, never auto-retry."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.live import LiveFlowGenerator
from story_auto.providers.flow.session import FlowRuntime

root = Path(r'D:\Story Auto\evidence\flow-real-product-journey-20260921\reference-acquisition-handshake-fixed')
root.mkdir(parents=True, exist_ok=True)
if '--execute' not in sys.argv or (root / 'intent.json').exists():
    raise SystemExit('Explicit execute required; existing attempts must not be resubmitted.')
project = 'a94d36d0-5f95-420d-97b4-dc7cf0c87453'
request = {'request_id': 'village-reference-20260922', 'media_type': 'IMAGE',
           'aspect_ratio': '16:9', 'output_count': 1, 'depends_on': [],
           'prompt': 'Cinematic photorealistic wide establishing shot at sunrise. A quiet river reflects soft golden light beside a small rural village. A simple wooden footbridge crosses the river. Tall green trees, a narrow riverbank path, wild flowers and an old stone cottage, rolling green hills in the distance. Natural proportions, calm believable countryside, no people, no text, no logos. Landscape 16:9.'}
atomic_write_json(root / 'intent.json', {'request': request, 'max_submits': 1,
    'route': 'existing CDP IMAGE adapter; not cookie IMAGE qualification'})
runtime = FlowRuntime(Path(r'C:\Users\ADMIN\AppData\Local\FlowCookieTest\owner-login-20260921'),
    'http://127.0.0.1:9333', 'https://flow.google.com/project/' + project, project)
generator = LiveFlowGenerator(runtime, timeout_seconds=120)
generator.set_before_provider_boundary(lambda: atomic_write_json(root / 'boundary.json', {'entered': True}))
result = {}
try:
    output = generator(request, [], root / 'reference.png')
    result.update(status='ACQUIRED', output=str(output))
except Exception as error:
    result.update(status='NOT_ACQUIRED', reason_code=getattr(error, 'failure_class', type(error).__name__))
result['dispatch_state'] = generator.dispatch_confirmation_state
result['dispatch_confirmed'] = generator.dispatch_confirmed
atomic_write_json(root / 'result.json', result)
print(json.dumps(result))
