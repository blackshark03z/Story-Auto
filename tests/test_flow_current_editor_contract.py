from __future__ import annotations

import unittest
import base64
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

from story_auto.providers.flow.live import (
    CURRENT_EDITOR_CONTRACT_VERSION,
    FlowBrowserDom,
    FlowInspector,
    LiveFlowGenerator,
    PROVIDER_SURFACE_EXTRACTOR_VERSION,
    ProviderPollEvidenceTimeline,
    _CURRENT_PROVIDER_SURFACE_JS,
    _EDITOR_JS,
)
from story_auto.providers.flow.service import FlowError
from story_auto.providers.flow.session import FlowCapabilities, FlowRuntime, FlowSessionError


PROJECT_IDENTITY = "11111111-2222-3333-4444-555555555555"
PROJECT_URL = f"https://flow.google.com/project/{PROJECT_IDENTITY}"


class InspectorPage:
    def __init__(self, contract):
        self.contract = contract
        self.closed = False
        self.expressions = []

    def evaluate(self, expression):
        self.expressions.append(expression)
        if "document.querySelector('[role=dialog]')" in expression:
            return False
        if "location.href,text:" in expression:
            return {"url": PROJECT_URL, "text": "", "title": "Google Flow"}
        if '"action": "capabilities"' in expression:
            return dict(self.contract)
        raise AssertionError(expression)

    def command(self, *_args, **_kwargs):
        raise AssertionError("healthy inspection must not reload")

    def close(self):
        self.closed = True


def current_contract(**changes):
    value = {
        "known": True,
        "image": True,
        "video": True,
        "reference_image": True,
        "frame_video": True,
        "prompt_editor": True,
        "generate_control": True,
        "settings_trigger": True,
        "menu_closed": True,
        "contract_version": CURRENT_EDITOR_CONTRACT_VERSION,
    }
    value.update(changes)
    return value


class CurrentFlowEditorContractTests(unittest.TestCase):
    def runtime(self):
        return FlowRuntime(Path("profile"), "http://127.0.0.1:9222",
                           PROJECT_URL, PROJECT_IDENTITY)

    def test_current_settings_trigger_detects_image_video_and_reference_capabilities(self):
        page = InspectorPage(current_contract())
        with patch("story_auto.providers.flow.live.CdpPage.open", return_value=page):
            found = FlowInspector(self.runtime()).inspect(PROJECT_URL)
        self.assertEqual(
            (found["image"], found["video"], found["reference_image"], found["frame_video"]),
            (True, True, True, True),
        )
        script = next(item for item in page.expressions if '"action": "capabilities"' in item)
        self.assertIn("button.settings-trigger-button", script)
        self.assertIn("button.add-menu-trigger", script)
        self.assertIn("mat-icon", script)
        self.assertIn("button[aria-controls]", script)  # intentional legacy fallback
        self.assertTrue(page.closed)

    def test_current_video_only_editor_is_distinguished_without_fake_image_success(self):
        page = InspectorPage(current_contract(image=False, reference_image=False))
        with patch("story_auto.providers.flow.live.CdpPage.open", return_value=page):
            found = FlowInspector(self.runtime()).inspect(PROJECT_URL)
        self.assertFalse(found["image"])
        self.assertTrue(found["video"])
        with self.assertRaises(FlowSessionError) as caught:
            FlowCapabilities(True, True, found["image"], found["video"],
                             found["reference_image"], found["frame_video"]).require("IMAGE", False)
        self.assertEqual(caught.exception.failure_class, "FLOW_CAPABILITY_UNAVAILABLE")

    def test_unknown_editor_contract_fails_closed(self):
        page = InspectorPage(current_contract(known=False, image=False, video=False))
        with patch("story_auto.providers.flow.live.CdpPage.open", return_value=page):
            with self.assertRaises(FlowError) as caught:
                FlowInspector(self.runtime()).inspect(PROJECT_URL)
        self.assertEqual(caught.exception.failure_class, "FLOW_UI_CHANGED")

    def test_current_contract_switches_image_and_reads_back_ratio_and_x1_without_dispatch(self):
        class Page:
            def __init__(self):
                self.expressions = []

            def evaluate(self, expression):
                self.expressions.append(expression)
                if '"action": "choose_mode"' in expression:
                    return {"ok": True, "media": True, "menu_closed": True}
                if '"action": "inspect_count"' in expression:
                    return {"media": True, "count": 1, "menu_closed": True}
                if '"action": "configure_count"' in expression:
                    return {"ok": True, "media": True, "count": 1, "menu_closed": True}
                if '"action": "apply_settings"' in expression:
                    return {"media": True, "ratio": True, "actual_output_count": 1,
                            "model": "Nano Banana Pro", "menu_closed": True}
                raise AssertionError(expression)

        page = Page()
        dom = FlowBrowserDom(page)
        dom.choose_mode("IMAGE")
        self.assertEqual(dom.inspect_generation_count("IMAGE"), 1)
        dom.configure_generation_count("IMAGE", 1)
        actual = dom.apply_request_settings(SimpleNamespace(
            media_type="IMAGE", aspect_ratio="16:9", model_preference="Nano Banana 2",
            workflow_mode="IMAGE_GENERATION", quality_tier="STANDARD_PRODUCTION",
            reference_mode=None, duration_seconds=None))
        self.assertTrue(actual["media"] and actual["ratio"])
        self.assertEqual(actual["actual_output_count"], 1)
        scripts = "\n".join(page.expressions)
        self.assertIn("crop_16_9", scripts)
        self.assertIn("aria-checked", scripts)
        self.assertNotIn("requestAnimationFrame", scripts)
        self.assertFalse(hasattr(page, "locator_click"))

    def test_prosemirror_placeholder_is_excluded_from_empty_editor_readback(self):
        self.assertIn(".ProseMirror-widget", _EDITOR_JS)
        self.assertIn("[contenteditable=\"false\"]", _EDITOR_JS)

    def test_composer_reload_requires_stable_new_document_before_settings(self):
        class Page:
            def __init__(self):
                self.runtime = SimpleNamespace(project_url=PROJECT_URL)
                self.editor_reads = 0
                self.commands = []

            def command(self, method, params):
                self.commands.append((method, params))

            def evaluate(self, expression):
                if "document.readyState" in expression:
                    return {"ready":"complete", "url":PROJECT_URL}
                self.editor_reads += 1
                if self.editor_reads == 1:
                    return [{"i":0, "text":"", "is_empty":True}]
                if self.editor_reads == 2:
                    return []
                return [{"i":0, "text":"", "is_empty":True}]

        page = Page()
        with patch("story_auto.providers.flow.live.time.sleep"):
            FlowBrowserDom(page).reset_composer(timeout_seconds=2)
        self.assertEqual(page.commands, [("Page.reload", {"ignoreCache":False})])
        self.assertEqual(page.editor_reads, 5)

    def test_frontend_has_one_canonical_capability_error_and_exact_project_action(self):
        source = (Path(__file__).parents[1] / "story_auto/ui/static/app.js").read_text(encoding="utf-8")
        self.assertEqual(source.count("FLOW_CAPABILITY_UNAVAILABLE:"), 1)
        self.assertIn("'open_flow_project','Open Flow project'", source)
        self.assertIn("if (action === 'open_flow_project')", source)

    def test_current_angular_surface_is_preferred_when_it_has_a_complete_model(self):
        class Page:
            def __init__(self): self.calls = 0
            def evaluate(self, _expression):
                self.calls += 1
                if self.calls == 1:
                    return {"records":[], "provider_model_complete":False}
                return {"records":[{"card_id":"current:asset", "asset_id":"asset",
                                    "media_type":"IMAGE", "state":"READY"}],
                        "provider_model_complete":True,
                        "provider_model_tiles":[{"card_id":"current:asset"}]}

        surface = FlowBrowserDom(Page()).provider_surface()
        self.assertTrue(surface["provider_model_complete"])
        self.assertEqual(surface["records"][0]["asset_id"], "asset")

    def test_current_surface_contract_uses_complete_top_virtual_viewport(self):
        self.assertEqual(PROVIDER_SURFACE_EXTRACTOR_VERSION, "flow-provider-surface/2.5.0")
        self.assertIn("flow-video-tile", _CURRENT_PROVIDER_SURFACE_JS)
        self.assertIn("classified===tiles.length", _CURRENT_PROVIDER_SURFACE_JS)
        self.assertIn("Math.abs(viewport.scrollTop)<1", _CURRENT_PROVIDER_SURFACE_JS)
        self.assertNotIn("viewport.scrollHeight<=viewport.clientHeight", _CURRENT_PROVIDER_SURFACE_JS)
        self.assertIn("TOP_VIRTUAL_VIEWPORT", _CURRENT_PROVIDER_SURFACE_JS)
        self.assertIn("if(image)", _CURRENT_PROVIDER_SURFACE_JS)

    def test_current_reference_affordance_uses_file_chooser_and_structural_picker_controls(self):
        with tempfile.TemporaryDirectory() as root:
            reference = Path(root) / "reference.png"
            Image.new("RGB", (1280, 720), "navy").save(reference)
            payload = base64.b64encode(reference.read_bytes()).decode("ascii")

            class Page:
                def __init__(self):
                    self.expressions = []
                    self.upload = None

                def evaluate(self, expression):
                    self.expressions.append(expression)
                    if expression == "document.querySelectorAll('input[type=file]').length": return 0
                    if "await fetch" in expression: return payload
                    if "WAITING_FOR_OPTION" in expression: return {"state":"SELECTED"}
                    if "detail-add-to-prompt-btn" in expression: return True
                    if "some(visible)" in expression: return False
                    if "return Array.from(d.querySelectorAll('img'))" in expression:
                        return [{"url":"https://flow-content.google/image/reference", "alt":"reference"}]
                    return True

                def file_chooser_upload(self, selector, files):
                    self.upload = (selector, files)

            page = Page()
            result = FlowBrowserDom(page).add_references([reference])
            self.assertTrue(result["committed"])
            self.assertEqual(page.upload[0], ".cdk-overlay-pane button.sidebar-upload-btn")
            scripts = "\n".join(page.expressions)
            self.assertIn("button.add-menu-trigger", scripts)
            self.assertIn("button.asset-item", scripts)
            self.assertIn("button.detail-add-to-prompt-btn", scripts)

    def test_old_extractor_migration_reconciliation_requires_full_trusted_evidence(self):
        settings = {
            "provider_surface_extractor_version":"flow-provider-surface/2.2.0",
            "pre_dispatch_empty_provider_model_authority":
                "AUTO_MANAGED_BOUND_PROJECT_WITH_NO_PRIOR_DISPATCH",
            "activation":{"input_dispatched":True,"trusted_click_seen":True,
                          "activation_verified":True,"provider_acceptance_transition":True},
        }
        attempt = {"status":"AMBIGUOUS", "failure_class":"OUTPUT_ATTRIBUTION_AMBIGUOUS",
                   "provider_execution_state":"PROVIDER_BOUNDARY_ENTERED",
                   "dispatch_confirmation_state":"UNCERTAIN"}
        evidence = {"observations":[
            {"phase":"PRE_DISPATCH_BASELINE", "current_identity_set":None}
            for _ in range(3)
        ], "decision_bindings":[]}
        eligible = LiveFlowGenerator._eligible_current_editor_migration_reconciliation
        self.assertTrue(eligible(settings, attempt, evidence))
        for key in settings["activation"]:
            altered = {**settings, "activation":{**settings["activation"], key:False}}
            self.assertFalse(eligible(altered, attempt, evidence), key)
        self.assertFalse(eligible(settings, attempt, {**evidence, "observations":evidence["observations"][:2]}))

    def test_23_surface_completeness_gap_allows_read_only_reconciliation_with_exact_baseline(self):
        settings = {
            "provider_surface_extractor_version":"flow-provider-surface/2.3.0",
            "pre_dispatch_provider_model_identity_set":[
                {"card_id":"current:old-image", "media_type":"IMAGE"},
                {"card_id":"current:old-video", "media_type":"VIDEO"},
            ],
            "activation":{"input_dispatched":True,"trusted_click_seen":True,
                          "activation_verified":True,"provider_acceptance_transition":True},
        }
        attempt = {
            "status":"AMBIGUOUS", "failure_class":"OUTPUT_ATTRIBUTION_AMBIGUOUS",
            "provider_execution_state":"PROVIDER_BOUNDARY_ENTERED",
            "dispatch_confirmation_state":"UNCERTAIN",
            "baseline_provider_identities":[{
                "card_id":"current:old-image", "asset_id":"old-image",
                "identity":"asset:old-image", "media_type":"IMAGE", "state":"READY",
            }],
        }
        evidence = {"observations":[
            {"phase":"PRE_DISPATCH_BASELINE", "provider_model_complete":False,
             "provider_surface_fingerprint":"stable-baseline"}
            for _ in range(3)
        ], "decision_bindings":[]}
        eligible = LiveFlowGenerator._eligible_current_surface_completeness_reconciliation
        self.assertTrue(eligible(settings, attempt, evidence))
        self.assertFalse(eligible(settings, {**attempt, "baseline_provider_identities":[]}, evidence))
        altered = {**evidence, "observations":[*evidence["observations"][:2], {
            **evidence["observations"][2], "provider_surface_fingerprint":"different"}]}
        self.assertFalse(eligible(settings, attempt, altered))

    def test_current_poll_schema_keeps_verified_23_evidence_readable_after_24_upgrade(self):
        timeline = ProviderPollEvidenceTimeline(
            max_observations=8,
            parser_extractor_version="flow-provider-surface/2.3.0",
        )
        timeline.append({"phase":"PRE_DISPATCH_BASELINE"})
        timeline.finish("OUTPUT_ATTRIBUTION_AMBIGUOUS")
        verified = ProviderPollEvidenceTimeline.verify_snapshot(timeline.snapshot())
        self.assertEqual(verified["parser_extractor_version"], "flow-provider-surface/2.3.0")

    def test_24_scroll_growth_gap_allows_read_only_reconciliation(self):
        settings = {
            "provider_surface_extractor_version":"flow-provider-surface/2.4.0",
            "pre_dispatch_provider_model_identity_set":[
                {"card_id":"current:old-image", "media_type":"IMAGE"},
            ],
            "activation":{"input_dispatched":True,"trusted_click_seen":True,
                          "activation_verified":True,"provider_acceptance_transition":True},
        }
        attempt = {
            "status":"AMBIGUOUS", "failure_class":"OUTPUT_ATTRIBUTION_AMBIGUOUS",
            "provider_execution_state":"PROVIDER_BOUNDARY_ENTERED",
            "dispatch_confirmation_state":"UNCERTAIN",
            "baseline_provider_identities":[{
                "card_id":"current:old-image", "asset_id":"old-image",
                "identity":"asset:old-image", "media_type":"IMAGE", "state":"READY",
            }],
        }
        evidence = {"observations":[
            {"phase":"PRE_DISPATCH_BASELINE", "provider_model_complete":True,
             "provider_surface_fingerprint":"stable-baseline"}
            for _ in range(3)
        ], "decision_bindings":[]}
        eligible = LiveFlowGenerator._eligible_current_surface_completeness_reconciliation
        self.assertTrue(eligible(settings, attempt, evidence))


if __name__ == "__main__":
    unittest.main()
