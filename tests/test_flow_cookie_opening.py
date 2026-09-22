import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image
from story_auto.core.artifacts import read_json, atomic_write_json
from story_auto.core.project import RuntimeLayout, ProjectConfig, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder, import_opening_clip, OpeningBuilderError
from story_auto.providers.flow.opening import generate_flow_cookie_opening, reset_unused_flow_cookie_opening
from story_auto.providers.flow.rpc_transport import RpcError
from tests.test_flow_rpc_transport import Session, PROJECT


class CookieOpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        runtime = RuntimeLayout.from_root(self.root).ensure()
        self.paths = create_project(runtime, ProjectConfig('prj_cookie', render_mode='hybrid_hook', settings={
            'render':{'width':320,'height':180,'fps':24,'pixel_format':'yuv420p'},
            'hybrid_visual':{'opening_provider_policy':'AUTO'}}))
        configure_opening_builder(self.root, 'prj_cookie', shared_context='A dawn journey', slot_specs=[
            {'duration_seconds':6,'purpose':purpose,'prompt':prompt} for purpose,prompt in
            [('Hook','The dawn'),('Develop','The traveller'),('End','The valley')]])
        self.reference = self.root/'reference.png'
        Image.new('RGB',(320,180),'navy').save(self.reference)
        video = self.root/'fixture.mp4'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i',
                        'color=c=navy:s=320x180:r=24:d=8','-c:v','libx264','-pix_fmt','yuv420p','-an',str(video)],check=True)
        payload = video.read_bytes()
        class VideoSession(Session):
            def media(self, identity, kind):
                return payload
        self.session = VideoSession()
        self.factory = MagicMock(return_value=self.session)
        self.factory.binding = {'mode':'cookie_owned','account_id':'daily','revision':1}
        self.store = MagicMock()
        self.store.get_account.return_value = {'account_id':'daily','revision':1}
        self.gate = patch.dict('os.environ',{'STORY_AUTO_FLOW_RPC_EXPERIMENTAL':'1','STORY_AUTO_FLOW_RPC_PROJECT':PROJECT})
        self.gate.start(); self.addCleanup(self.gate.stop)

    def run_slot(self, *, resume=False, **kwargs):
        options = {} if resume else {'account_id':'daily','project_url':f'https://flow.google.com/project/{PROJECT}', 'reference_path':self.reference}
        options.update(kwargs)
        return generate_flow_cookie_opening(self.root,'prj_cookie','OPENING_O1',store=self.store,
                                            session_factory=self.factory,timeout_seconds=0,**options)

    def test_generate_normalize_and_repeat_is_idle(self):
        slot = self.run_slot()['slots'][0]
        self.assertTrue(slot['asset_ready'])
        self.assertEqual(slot['source_asset']['provider'],'flow_cookie')
        self.assertAlmostEqual(slot['normalized_asset']['duration_seconds'],6,places=1)
        self.assertEqual(slot['api_generation']['status'],'SUCCEEDED')
        self.run_slot(resume=True)
        self.assertEqual((self.session.uploads,self.session.submits),(1,1))

    def test_ambiguous_submit_recovers_with_gate_off_without_retry(self):
        self.session.fail_submit = True
        first = self.run_slot()['slots'][0]
        self.assertEqual(first['api_generation']['status'],'RECOVERY_REQUIRED')
        with patch.dict('os.environ',{'STORY_AUTO_FLOW_RPC_EXPERIMENTAL':'0'}):
            final = self.run_slot(resume=True)['slots'][0]
        self.assertTrue(final['asset_ready'])
        self.assertEqual((self.session.uploads,self.session.submits),(1,1))

    def test_revision_or_new_inputs_cannot_switch_pending_attempt(self):
        self.session.fail_submit = True
        self.run_slot()
        for options in ({'account_id':'other'}, {'project_url':'https://evil.test'}, {'reference_path':self.reference}):
            with self.assertRaisesRegex(RpcError,'IDENTITY_MISMATCH'):
                self.run_slot(resume=True,**options)
        self.store.get_account.return_value['revision']=2
        with self.assertRaisesRegex(RpcError,'IDENTITY_MISMATCH'):
            self.run_slot(resume=True)
        self.assertEqual(self.session.submits,1)

    def test_disabled_gate_and_long_slot_never_submit(self):
        with patch.dict('os.environ',{'STORY_AUTO_FLOW_RPC_EXPERIMENTAL':'0'}):
            with self.assertRaisesRegex(RpcError,'FLOW_RPC_DISABLED'): self.run_slot()
        path = self.paths.artifact_path('output/opening_manifest.json')
        doc = read_json(path); doc['slots'][0]['duration_seconds']=9
        atomic_write_json(path,doc)
        with self.assertRaisesRegex(RpcError,'DURATION_UNSUPPORTED'): self.run_slot()
        self.assertEqual(self.session.submits,0)

    def test_zero_effect_setup_can_reset_after_cookie_refresh(self):
        self.factory.side_effect = RuntimeError('browser unavailable')
        first = self.run_slot()['slots'][0]
        self.assertEqual(first['api_generation']['status'],'RECOVERY_REQUIRED')
        self.assertEqual((self.session.uploads,self.session.submits),(0,0))
        self.store.get_account.return_value['revision']=2
        reset = reset_unused_flow_cookie_opening(self.root,'prj_cookie','OPENING_O1')['slots'][0]
        self.assertNotIn('api_generation',reset)
        self.assertEqual(reset['provider_attempt_history'][0]['revision'],1)
        self.factory.side_effect = None
        self.factory.binding['revision']=2
        final = self.run_slot()['slots'][0]
        self.assertTrue(final['asset_ready'])
        self.assertEqual((self.session.uploads,self.session.submits),(1,1))

    def test_no_reset_after_upload_or_submit_boundary(self):
        self.session.fail_submit = True
        self.run_slot()
        with self.assertRaisesRegex(RpcError,'NO_EFFECT_PROOF_REQUIRED'):
            reset_unused_flow_cookie_opening(self.root,'prj_cookie','OPENING_O1')
        self.assertEqual(self.session.submits,1)

    def test_recovery_action_cannot_create_new_attempt(self):
        from story_auto.application.operator import OperatorService, OperatorServiceError
        with self.assertRaisesRegex(OperatorServiceError,'RECOVERY_NOT_AVAILABLE'):
            OperatorService(self.root).generate_flow_cookie_opening('prj_cookie',slot_id='OPENING_O1',recovery_only=True)

    def test_three_slots_keep_distinct_lineage_and_resume_without_submit(self):
        from uuid import UUID, uuid5
        from tests.test_flow_rpc_contract import record
        self.session.catalog = lambda: ([record(identity=str(uuid5(UUID(PROJECT),self.session.prompt)),
                                                   prompt=self.session.prompt)] if self.session.prompt else [])
        for index in range(1,4):
            result=generate_flow_cookie_opening(self.root,'prj_cookie',f'OPENING_O{index}',
                account_id='daily',project_url=f'https://flow.google.com/project/{PROJECT}',
                reference_path=self.reference,store=self.store,session_factory=self.factory,timeout_seconds=0)
        self.assertTrue(result['ready'])
        self.assertEqual(len({s['api_generation']['provider_task_id'] for s in result['slots']}),3)
        for index in range(1,4):
            generate_flow_cookie_opening(self.root,'prj_cookie',f'OPENING_O{index}',store=self.store,session_factory=self.factory)
        self.assertEqual((self.session.uploads,self.session.submits),(3,3))

    def test_wrong_output_bytes_not_authorized_by_provider_identity(self):
        slot = self.run_slot()['slots'][0]
        generation = slot['api_generation']
        other = self.root/'other.mp4'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i',
                        'color=c=red:s=320x180:r=24:d=8','-c:v','libx264','-pix_fmt','yuv420p','-an',str(other)],check=True)
        identity = {key:generation[key] for key in ('provider','provider_task_id','account_id','revision','project_identity')}
        with self.assertRaisesRegex(OpeningBuilderError,'EFFECT_UNRESOLVED'):
            import_opening_clip(self.root,'prj_cookie','OPENING_O1',other,_provider_identity=identity)


if __name__ == '__main__': unittest.main()
