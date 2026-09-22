"""Read-only current product session check; never prints credential material."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.cookie_session import CookieBrowserRpcSession
from story_auto.providers.flow.session import FlowRuntime

root = Path(r'D:\Story Auto\evidence\flow-real-product-journey-20260921')
project = 'a94d36d0-5f95-420d-97b4-dc7cf0c87453'
runtime = FlowRuntime(root, 'cookie-owned://read', 'https://flow.google.com/project/' + project, project)
result = {'generations': 0, 'uploads': 0}
try:
    with CookieBrowserRpcSession(runtime, cookie_file=Path(r'D:\Story Auto\cookie\flow_profile_export_20260921T153746199592Z.json')) as session:
        result.update(status='READ_VERIFIED', catalog_count=len(session.catalog()))
except Exception as error:
    result.update(status='UNAVAILABLE', reason_code=getattr(error, 'code', type(error).__name__))
atomic_write_json(root / 'current-export-read.json', result)
print(json.dumps(result))
