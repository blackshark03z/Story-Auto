"""Sequential real product Opening journey; existing slots are recovery-only."""
import argparse
import base64
import json
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_auto.application.operator import OperatorService
from story_auto.core.artifacts import atomic_write_json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit('EXPLICIT_EXECUTE_REQUIRED')
    from PIL import Image
    with Image.open(args.reference) as image:
        image.load()
        normalized = io.BytesIO()
        image.convert('RGB').save(normalized, format='PNG')
    root = Path(r'D:\Story Auto\evidence\flow-real-product-journey-20260921')
    project = 'prj_flow_real_product'
    provider = 'a94d36d0-5f95-420d-97b4-dc7cf0c87453'
    os.environ['STORY_AUTO_FLOW_RPC_EXPERIMENTAL'] = '1'
    os.environ['STORY_AUTO_FLOW_RPC_PROJECT'] = provider
    service = OperatorService(root)
    reference = {'filename': 'reference.png',
                 'base64': base64.b64encode(normalized.getvalue()).decode('ascii')}
    import hashlib
    provenance = {
        'source':str(args.reference.resolve()),
        'source_sha256':hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        'png_sha256':hashlib.sha256(normalized.getvalue()).hexdigest(),
        'conversion':'Pillow RGB PNG encoding; no spatial or semantic edits'}
    for slot_id in ('OPENING_O1', 'OPENING_O2', 'OPENING_O3'):
        slot = next(s for s in service.opening_builder(project)['slots'] if s['slot_id'] == slot_id)
        if slot.get('asset_ready'):
            continue
        recovery = bool(slot.get('api_generation'))
        if not recovery:
            provenance_path = root / (slot_id + '-reference-provenance.json')
            if provenance_path.exists():
                if json.loads(provenance_path.read_text(encoding='utf-8')) != provenance:
                    raise SystemExit('REFERENCE_PROVENANCE_CHANGED')
            else:
                atomic_write_json(provenance_path, provenance)
        print(json.dumps({'slot':slot_id, 'recovery_only':recovery}), flush=True)
        result = service.generate_flow_cookie_opening(project, slot_id=slot_id,
            account_id='flow-product-20260922', project_url='https://flow.google.com/project/'+provider,
            imported_reference=reference, confirm_generate=True, recovery_only=recovery)
        selected = next(s for s in result['slots'] if s['slot_id'] == slot_id)
        summary = {'slot':slot_id, 'asset_ready':bool(selected.get('asset_ready')),
                   'generation':selected.get('api_generation')}
        atomic_write_json(root / (slot_id + '-result.json'), summary)
        print(json.dumps(summary), flush=True)
        if not summary['asset_ready']:
            raise SystemExit('STOPPED_FOR_RECONCILIATION_NO_NEXT_SLOT_DISPATCH')

if __name__ == '__main__':
    main()
