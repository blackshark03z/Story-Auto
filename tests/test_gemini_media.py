from __future__ import annotations

import base64
import io
from pathlib import Path
import tempfile
import unittest
import urllib.error

from PIL import Image

from story_auto.providers.gemini_media import GeminiMediaClient, GeminiMediaError, MediaResult, execute_media_request


def png_bytes(color: str = "navy") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (128, 72), color).save(stream, "PNG")
    return stream.getvalue()


class GeminiMediaClientTests(unittest.TestCase):
    def test_discovers_exact_current_candidate_models(self):
        def transport(url, method, body, key, timeout):
            return ({"models": [
                {"name": "models/gemini-3.1-flash-image", "displayName": "NB2", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3-pro-image", "displayName": "NBP", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-omni-flash-preview", "displayName": "Omni", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/veo-3.1-generate-preview", "displayName": "Veo", "supportedGenerationMethods": ["predictLongRunning"]},
                {"name": "models/imagen-4.0-generate-001", "displayName": "deprecated", "supportedGenerationMethods": ["predict"]},
            ]}, 200)
        models = GeminiMediaClient(transport=transport, keys=["secret"]).discover_models()
        self.assertEqual([item.model for item in models], ["gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-omni-flash-preview", "veo-3.1-generate-preview"])

    def test_image_generation_is_x1_atomic_validated_and_reference_aware(self):
        calls = []
        encoded = base64.b64encode(png_bytes()).decode("ascii")
        def transport(url, method, body, key, timeout):
            calls.append(body)
            return ({"id": "interaction-safe", "output_image": {"mime_type": "image/png", "data": encoded}}, 200)
        with tempfile.TemporaryDirectory() as root:
            reference = Path(root, "ref.png"); reference.write_bytes(png_bytes("olive"))
            output = Path(root, "out.png")
            result = GeminiMediaClient(transport=transport, keys=["secret"]).generate_image(
                model="gemini-3.1-flash-image", prompt="natural", references=[reference], destination=output)
            self.assertEqual((result.output_count, result.metadata["width"], result.request_id), (1, 128, "interaction-safe"))
            self.assertEqual(calls[0]["response_format"]["type"], "image")
            self.assertEqual([item["type"] for item in calls[0]["input"]], ["text", "image"])
            self.assertFalse(output.with_suffix(".png.candidate").exists())

    def test_veo_persists_job_before_poll_and_resumes_without_resubmit(self):
        calls = []
        def transport(url, method, body, key, timeout):
            calls.append((url.rsplit("/", 1)[-1], method))
            if method == "POST": return ({"name": "operations/job-safe"}, 200)
            return ({"done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://result.invalid/video"}}]}}}, 200)
        with tempfile.TemporaryDirectory() as root:
            reference = Path(root, "ref.png"); reference.write_bytes(png_bytes())
            destination = Path(root, "out.mp4")
            client = GeminiMediaClient(transport=transport, binary_transport=lambda u,k,t: b"not-video", keys=["secret"], poll_interval=0)
            saved = []
            with self.assertRaises(Exception):
                client.generate_veo_video(prompt="motion", references=[reference], destination=destination,
                                          mode="FIRST_FRAME", on_submitted=saved.append)
            self.assertEqual(saved, ["operations/job-safe"])
            self.assertEqual(sum(method == "POST" for _, method in calls), 1)

    def test_veo_uses_prediction_media_shape_and_x1(self):
        bodies = []
        def transport(url, method, body, key, timeout):
            bodies.append(body); return ({"name": "operations/job"}, 200)
        with tempfile.TemporaryDirectory() as root:
            reference = Path(root, "ref.png"); reference.write_bytes(png_bytes())
            client = GeminiMediaClient(transport=transport, keys=["secret"])
            self.assertEqual(client.submit_veo(prompt="motion", references=[reference], mode="REFERENCE_IMAGES"), "operations/job")
        image = bodies[0]["instances"][0]["referenceImages"][0]["image"]
        self.assertEqual((set(image), bodies[0]["parameters"]["sampleCount"]), ({"bytesBase64Encoded", "mimeType"}, 1))

    def test_post_timeout_is_ambiguous_and_never_blindly_rotated(self):
        count = 0
        def transport(url, method, body, key, timeout):
            nonlocal count; count += 1
            raise GeminiMediaError("AMBIGUOUS_POST_DISPATCH", dispatch_confirmed=True)
        client = GeminiMediaClient(transport=transport, keys=["one", "two"])
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(GeminiMediaError) as caught:
                client.generate_image(model="gemini-3.1-flash-image", prompt="x", references=[], destination=Path(root, "x.png"))
        self.assertEqual((caught.exception.failure_class, count), ("AMBIGUOUS_POST_DISPATCH", 1))

    def test_invalid_key_and_rejected_quota_rotate_but_request_error_does_not(self):
        attempts = []
        def transport(url, method, body, key, timeout):
            attempts.append(key)
            if key == "invalid": raise GeminiMediaError("CREDENTIAL_OR_ACCESS_DENIED")
            if key == "limited": raise GeminiMediaError("RATE_LIMITED")
            raise GeminiMediaError("CAPABILITY_OR_REQUEST_INVALID")
        client = GeminiMediaClient(transport=transport, keys=["invalid", "limited", "request-bad"])
        with tempfile.TemporaryDirectory() as root, self.assertRaises(GeminiMediaError) as caught:
            client.generate_image(model="gemini-3.1-flash-image", prompt="x", references=[], destination=Path(root, "x.png"))
        self.assertEqual((caught.exception.failure_class, attempts), ("CAPABILITY_OR_REQUEST_INVALID", ["invalid", "limited", "request-bad"]))

    def test_post_transient_or_unidentified_generating_attempt_never_resubmits(self):
        calls=[]
        def transport(url,method,body,key,timeout):
            calls.append(key); raise GeminiMediaError("AMBIGUOUS_POST_DISPATCH",dispatch_confirmed=True)
        with tempfile.TemporaryDirectory() as root:
            client=GeminiMediaClient(transport=transport,keys=["one","two"])
            with self.assertRaises(GeminiMediaError):
                client.generate_image(model="gemini-3.1-flash-image",prompt="x",references=[],destination=Path(root,"x.png"))
            self.assertEqual(calls,["one"])
            import json
            base=Path(root); manifest=base/"manifest.json"
            request={"request_id":"req","request_identity_sha256":"identity","media_type":"VIDEO","model":"veo-3.1-generate-preview","endpoint_identity":"predictLongRunning","prompt":"motion"}
            manifest.write_text(json.dumps({"requests":[{"request_id":"req","request_identity_sha256":"identity","media_type":"VIDEO","model":"veo-3.1-generate-preview","attempts":[{"attempt":1,"status":"GENERATING"}],"status":"GENERATING"}]}))
            with self.assertRaises(GeminiMediaError) as caught:
                execute_media_request(manifest_path=manifest,artifact_root=base,request=request,references=[],destination=base/"x.mp4",client=client)
            self.assertEqual(caught.exception.failure_class,"AMBIGUOUS_RECONCILIATION_REQUIRED")

    def test_manifest_execution_is_append_only_and_skips_valid_selection(self):
        class Fake:
            calls = 0
            def generate_image(self, **kwargs):
                self.calls += 1; kwargs["destination"].parent.mkdir(parents=True, exist_ok=True); kwargs["destination"].write_bytes(png_bytes())
                from story_auto.providers.flow.validation import validate_image
                return MediaResult(kwargs["destination"], "google_gemini_api", kwargs["model"], "interactions", "safe", None, "TEXT_TO_IMAGE", 1, validate_image(kwargs["destination"]))
        with tempfile.TemporaryDirectory() as root:
            base=Path(root); manifest=base/"manifest.json"; output=base/"assets/out.png"; fake=Fake()
            request={"request_id":"req","request_identity_sha256":"identity","media_type":"IMAGE","model":"gemini-3.1-flash-image","endpoint_identity":"interactions","prompt":"natural"}
            first=execute_media_request(manifest_path=manifest,artifact_root=base,request=request,references=[],destination=output,client=fake)
            second=execute_media_request(manifest_path=manifest,artifact_root=base,request=request,references=[],destination=output,client=fake)
            self.assertEqual((first,second,fake.calls),("RUN","SKIP",1))
            import json
            self.assertEqual(len(json.loads(manifest.read_text())["requests"][0]["attempts"]),1)


if __name__ == "__main__":
    unittest.main()
