import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

from story_auto.providers.flow.rpc_transport import FlowRpcGenerator, JOURNAL_NAME, enabled, verify_attribution
from story_auto.providers.flow.service import FlowError

PROJECT = "11111111-2222-3333-4444-555555555555"
REF = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OUT = "99999999-8888-7777-6666-555555555555"


class Session:
    def __init__(self):
        self.submits = self.uploads = 0
        self.prompt = None
        self.fail_submit = False
        self.available = True

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def catalog(self):
        from tests.test_flow_rpc_contract import record
        return [record(identity=OUT, prompt=self.prompt, reference=REF)] if self.prompt and self.available else []
    def upload(self, path, attempt):
        self.uploads += 1
        return REF
    def submit(self, prompt, reference, attempt):
        self.submits += 1
        self.prompt = prompt
        if self.fail_submit: raise TimeoutError("secret must not leak")
    def media(self, *args): return b"fixture-video"


class RpcTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = self.root / "ref.png"
        Image.new("RGB", (32, 32), "blue").save(self.ref)
        self.runtime = SimpleNamespace(project_identity=PROJECT, project_url=f"https://flow.google.com/project/{PROJECT}", profile=self.root, cdp_url="http://127.0.0.1:9222")
        self.request = {"request_id": "shot-1", "media_type": "VIDEO", "prompt": "A calm scene", "target_duration": 8}
        self.destination = self.root / "attempt_001" / "output.mp4"
        self.session = Session()
        self.validation = patch("story_auto.providers.flow.rpc_transport.validate_video", return_value={"duration_seconds": 8, "width": 1280, "height": 720, "sha256": hashlib.sha256(b"fixture-video").hexdigest()})
        self.validation.start()
        self.addCleanup(self.validation.stop)

    def generator(self):
        return FlowRpcGenerator(self.runtime, session_factory=lambda _: self.session, timeout_seconds=0)

    def run_one(self, **kwargs):
        return self.generator().run(self.request, [self.ref], self.destination, **kwargs)

    def test_default_off_and_project_scoped(self):
        with patch.dict("os.environ", {}, clear=True): self.assertFalse(enabled(self.runtime))
        with patch.dict("os.environ", {"STORY_AUTO_FLOW_RPC_EXPERIMENTAL": "1", "STORY_AUTO_FLOW_RPC_PROJECT": "other"}): self.assertFalse(enabled(self.runtime))

    def test_cookie_account_revision_bound_before_recovery(self):
        factory = lambda runtime:self.session
        factory.binding = {'mode':'cookie_owned','account_id':'daily','revision':1}
        generator = FlowRpcGenerator(self.runtime,session_factory=factory,timeout_seconds=0)
        generator.run(self.request,[self.ref],self.destination,before_boundary=lambda:None)
        journal = json.loads((self.destination.parent/JOURNAL_NAME).read_text())
        self.assertEqual(journal['identity']['session_binding'],factory.binding)
        for binding in ({'mode':'cookie_owned','account_id':'other','revision':1},
                        {'mode':'cookie_owned','account_id':'daily','revision':2}):
            factory.binding=binding
            with self.assertRaisesRegex(FlowError,'FLOW_RPC_REQUEST_MISMATCH'):
                generator.run(self.request,[self.ref],self.destination,recovery_only=True)
        self.assertEqual((self.session.uploads,self.session.submits),(1,1))

    def test_boundary_is_durable_and_success_receipt(self):
        def boundary():
            journal = json.loads((self.destination.parent / JOURNAL_NAME).read_text())
            self.assertEqual(journal["submit_attempts"], 1)
            self.assertEqual(self.session.submits, 0)
        generator = self.generator()
        generator.run(self.request, [self.ref], self.destination, before_boundary=boundary)
        self.assertEqual(verify_attribution(generator.last_settings)["state"], "ACQUIRED")
        self.assertEqual((self.session.uploads, self.session.submits), (1, 1))

    def test_lost_response_recovery_never_resubmits(self):
        self.session.fail_submit = True
        with self.assertRaises(FlowError) as caught:
            self.run_one(before_boundary=lambda: None)
        self.assertNotIn("secret", str(caught.exception))
        self.run_one(recovery_only=True)
        self.assertEqual((self.session.uploads, self.session.submits), (1, 1))

    def test_pending_recovery_never_resubmits(self):
        self.session.available = False
        with self.assertRaises(FlowError): self.run_one(before_boundary=lambda: None)
        with self.assertRaises(FlowError): self.run_one(recovery_only=True)
        self.assertEqual(self.session.submits, 1)

    def test_submission_diagnostic_has_no_values_and_no_acceptance_claim(self):
        from story_auto.providers.flow.rpc_transport import submission_diagnostic
        with patch('story_auto.providers.flow.rpc_transport.contract.parse_rpc',
                   return_value=[None, {'secret-key':'secret-value'}, 403, False]):
            result = submission_diagnostic('wire-secret')
        serialized = json.dumps(result)
        self.assertNotIn('secret', serialized)
        self.assertNotIn('403', serialized)
        self.assertEqual(result['classification'], 'PARSED_NOT_ACCEPTANCE_PROOF')
        self.assertEqual(result['type_counts']['string'], 1)

    def test_diagnostic_persists_but_pending_still_cannot_resubmit(self):
        self.session.available = False
        with self.assertRaises(FlowError): self.run_one(before_boundary=lambda:None)
        journal = json.loads((self.destination.parent/JOURNAL_NAME).read_text())
        self.assertEqual(journal['submission_diagnostic']['classification'], 'NO_WIRE_RESPONSE')
        with self.assertRaises(FlowError): self.run_one(recovery_only=True)
        self.assertEqual(self.session.submits, 1)

    def test_diagnostic_invalid_response_redacted(self):
        from story_auto.providers.flow.rpc_transport import submission_diagnostic
        self.assertEqual(submission_diagnostic('secret'), {'classification':'UNPARSEABLE_RESPONSE'})

    def test_request_change_rejects_without_mutation(self):
        self.run_one(before_boundary=lambda: None)
        self.request["prompt"] = "Changed"
        with self.assertRaisesRegex(FlowError, "REQUEST_MISMATCH"): self.run_one(recovery_only=True)
        self.assertEqual(self.session.submits, 1)

    def test_upload_failure_never_reuploads(self):
        def fail(*args):
            self.session.uploads += 1
            raise TimeoutError()
        self.session.upload = fail
        with self.assertRaises(FlowError): self.run_one(before_boundary=lambda: None)
        with self.assertRaisesRegex(FlowError, "UPLOAD_UNCERTAIN"): self.run_one(recovery_only=True)
        self.assertEqual((self.session.uploads, self.session.submits), (1, 0))

    def test_missing_boundary_blocks_submit(self):
        with self.assertRaisesRegex(FlowError, "CALLBACK_REQUIRED"): self.run_one()
        self.assertEqual(self.session.submits, 0)

    def test_prior_owned_identity_is_not_acquired(self):
        self.request["_flow_provider_identity_history"] = [{"identity": OUT}]
        with self.assertRaisesRegex(FlowError, "OUTPUT_ALREADY_OWNED"):
            self.run_one(before_boundary=lambda: None)
        self.assertFalse(self.destination.exists())

    def test_tampered_journal_blocks_recovery(self):
        self.run_one(before_boundary=lambda: None)
        path = self.destination.parent / JOURNAL_NAME
        journal = json.loads(path.read_text())
        journal["submit_attempts"] = 0
        path.write_text(json.dumps(journal))
        with self.assertRaisesRegex(FlowError, "JOURNAL_INVALID"): self.run_one(recovery_only=True)
        self.assertEqual(self.session.submits, 1)


if __name__ == "__main__": unittest.main()
