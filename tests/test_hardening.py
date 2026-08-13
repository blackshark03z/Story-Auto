from __future__ import annotations

import subprocess
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.planning import run_planning_stages
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render.service import _atomic_media_publish
from story_auto.core.resources import ResourceError, ensure_free_space
from story_auto.providers.flow.service import FlowError, FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities
from story_auto.providers.llm.gemini import LLMResponse


class InterruptingPlanner:
    def __init__(self, fail_continuity: bool): self.fail_continuity=fail_continuity; self.calls=[]
    def generate_structured(self, request):
        self.calls.append(request.stage)
        if request.stage=="story_timeline": value={"groups":[{"segment_ids":["seg_0001"],"story_role":"setup","summary":"A traveler waits.","entity_ids":[]}]}
        elif self.fail_continuity: raise RuntimeError("simulated process interruption")
        else: value={"style":{},"characters":[],"locations":[],"props":[]}
        return LLMResponse(value,request.model,request.request_id,1,1,{})


class ReleaseHardeningTests(unittest.TestCase):
    def _flow_project(self, root):
        runtime=RuntimeLayout.from_root(root); config=ProjectConfig("prj_hardflow01"); paths=create_project(runtime,config)
        atomic_write_json(paths.artifact_path("output/review_state.json"),{"plan_approval":{"status":"APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[{"request_id":"req_image","fingerprint":"identity","purpose":"SHOT","shot_id":"sh_0001","media_type":"IMAGE","prompt":"natural","depends_on":[],"provider":"google_flow","output_count":1}]})
        return runtime,config,paths

    def test_zero_byte_acquisition_is_retryable_and_never_selected(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,config,paths=self._flow_project(root); capabilities=FlowCapabilities(True,True,True,True,True,True)
            def zero(_request,_refs,path): path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"");return path
            first=execute_generation(runtime.root,config.project_id,executor=FlowExecutor(capabilities,zero),execute=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((first["new_submissions"],entry["status"],entry.get("selected_asset")),(0,"FAILED_RETRYABLE",None))
            def valid(_request,_refs,path): Image.new("RGB",(32,32),"navy").save(path,"PNG");return path
            second=execute_generation(runtime.root,config.project_id,executor=FlowExecutor(capabilities,valid),execute=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((second["new_submissions"],entry["status"],len(entry["attempts"])),(1,"SUCCEEDED",2))

    def test_partial_download_failure_remains_isolated_from_selection(self):
        with tempfile.TemporaryDirectory() as root:
            runtime,config,paths=self._flow_project(root); capabilities=FlowCapabilities(True,True,True,True,True,True)
            def partial(_request,_refs,path): path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"partial");raise FlowError("ASSET_ACQUISITION_FAILED")
            execute_generation(runtime.root,config.project_id,executor=FlowExecutor(capabilities,partial),execute=True)
            entry=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(entry["failure_class"],"ASSET_ACQUISITION_FAILED");self.assertNotIn("selected_asset",entry)

    def test_planning_restart_reuses_completed_timeline_after_interruption(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root); config=ProjectConfig("prj_hardplan01",settings={"llm":{"provider":"gemini","model":"gemini-3.5-flash"}}); paths=create_project(runtime,config,"# Story\n\n## Narration\n\nA traveler waits.\n")
            atomic_write_json(paths.artifact_path("output/alignment.json"),{"duration_seconds":1.0,"segments":[{"segment_id":"seg_0001","start":0.0,"end":1.0,"text":"A traveler waits."}]})
            first=InterruptingPlanner(True)
            with self.assertRaises(RuntimeError): run_planning_stages(runtime.root,config.project_id,provider=first)
            self.assertTrue(paths.artifact_path("output/story_timeline.json").is_file())
            second=InterruptingPlanner(False); actions=run_planning_stages(runtime.root,config.project_id,provider=second)
            self.assertEqual(actions,("SKIP","RUN"));self.assertEqual(second.calls,["continuity"])

    def test_atomic_media_publish_preserves_prior_output_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/"scene.mp4";target.write_bytes(b"known-good")
            def interrupted(candidate): candidate.write_bytes(b"partial");raise OSError("simulated publish interruption")
            with self.assertRaises(OSError): _atomic_media_publish(target,interrupted)
            self.assertEqual(target.read_bytes(),b"known-good")
            self.assertFalse(any(Path(root).glob("*.candidate*")))

    def test_insufficient_workspace_is_rejected_before_stage_work(self):
        Usage=namedtuple("Usage","total used free")
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ResourceError) as caught: ensure_free_space(root,minimum_free_bytes=100,disk_usage=lambda _:Usage(100,99,1))
            self.assertEqual(caught.exception.failure_class,"INSUFFICIENT_DISK_SPACE")

    def test_repository_security_gate(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(["python","tools/security_gate.py"],cwd=root,capture_output=True,text=True,check=True)
        self.assertIn("SECURITY_GATE=PASS",result.stdout);self.assertIn("YOUTUBE_AUTO_RUNTIME_IMPORTS=0",result.stdout)


if __name__=="__main__": unittest.main()
