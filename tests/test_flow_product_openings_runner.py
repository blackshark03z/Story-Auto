import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from tools import flow_product_openings as runner


class ProductRunnerTests(unittest.TestCase):
    def test_recovery_does_not_rewrite_reference_provenance(self):
        slots = [{'slot_id':f'OPENING_O{i}', 'asset_ready':False,
                  'api_generation':{'provider':'flow_cookie'}} for i in range(1,4)]
        service = Mock()
        service.opening_builder.return_value = {'slots':slots}
        service.generate_flow_cookie_opening.return_value = {
            'slots':[{**slot, 'asset_ready':True} for slot in slots]}
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / 'different.png'
            Image.new('RGB', (16, 16), 'green').save(reference)
            with patch.object(runner.sys, 'argv', ['runner','--execute','--reference',str(reference)]), \
                 patch.object(runner, 'OperatorService', return_value=service), \
                 patch.object(runner, 'atomic_write_json') as write, \
                 patch.dict(runner.os.environ, {}), patch('builtins.print'):
                runner.main()
            self.assertEqual(service.generate_flow_cookie_opening.call_count,3)
            self.assertTrue(all(call.kwargs['recovery_only'] for call in service.generate_flow_cookie_opening.call_args_list))
            self.assertTrue(all('reference-provenance' not in str(call.args[0]) for call in write.call_args_list))
