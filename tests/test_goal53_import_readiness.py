from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch

from story_auto.application.operator import OperatorService, OperatorServiceError
from story_auto.core.audio import SrtError, parse_srt_bytes
from story_auto.ui import create_server


def _wav(seconds: int = 2) -> bytes:
    value = BytesIO()
    with wave.open(value, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\x11\x11" * 8000 * seconds)
    return value.getvalue()


def _upload(filename: str, payload: bytes) -> dict[str, str]:
    return {"filename": filename, "base64": base64.b64encode(payload).decode("ascii")}


def _owner_shape_srt() -> bytes:
    """The audited 606 text / 605 empty-cue pattern, with intentionally mixed EOLs."""
    lines: list[str] = []
    total = 1211
    for index in range(1, total + 1):
        start_ms = round((index - 1) * 1_246_350 / total)
        end_ms = 1_246_360 if index == total else round(index * 1_246_350 / total)
        def stamp(value: int) -> str:
            hours, remainder = divmod(value, 3_600_000); minutes, remainder = divmod(remainder, 60_000)
            seconds, milliseconds = divmod(remainder, 1000)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
        lines.extend([str(index), f"{stamp(start_ms)} --> {stamp(end_ms)}"])
        if index % 2:
            lines.append(f"Narration cue {index}.")
        lines.append("")
    # Odd cue IDs contain all 606 text-bearing cues.  Deliberately serialize the
    # file with mixed newlines and repeated physical separators around empty cues.
    return "\n".join(lines).replace("\n\n", "\r\n\n").encode("utf-8")


class Goal53ImportReadinessTests(unittest.TestCase):
    def test_parser_normalizes_lf_crlf_mixed_and_empty_micro_cues(self):
        fixture = _owner_shape_srt()
        cues, _, stats = parse_srt_bytes(fixture)
        self.assertEqual(stats["raw_cue_count"], 1211)
        self.assertEqual(stats["text_cue_count"], 606)
        self.assertEqual(stats["ignored_empty_cues"], 605)
        self.assertEqual(len(cues), 606)
        self.assertEqual(cues[0].text, "Narration cue 1.")

    def test_parser_rejects_genuine_malformed_and_timestamp_cues(self):
        with self.assertRaisesRegex(SrtError, "SRT_CUE_MALFORMED"):
            parse_srt_bytes(b"not a cue number\nsubtitle\n")
        with self.assertRaisesRegex(SrtError, "SRT_TIMESTAMP_INVALID"):
            parse_srt_bytes(b"1\n00:99:00,000 --> 00:00:02,000\nsubtitle\n")

    def test_owner_shape_is_parsed_then_truthfully_blocked_for_timeline_only(self):
        with tempfile.TemporaryDirectory() as root, patch("story_auto.application.import_readiness.inspect_audio", return_value={"duration_seconds": 1245.053968, "container": "m4a", "codec": "aac"}):
            app = OperatorService(root)
            readiness = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=_upload("owner.m4a", _wav()),
                                            imported_srt=_upload("owner.srt", _owner_shape_srt()))
        self.assertEqual((readiness["status"], readiness["code"]), ("BLOCKED", "TIMELINE_MISMATCH"))
        self.assertEqual((readiness["audio"]["status"], readiness["srt"]["status"]), ("READY", "READY"))
        self.assertEqual(readiness["srt"]["text_cue_count"], 606)
        self.assertEqual(readiness["srt"]["ignored_empty_cues"], 605)
        self.assertAlmostEqual(readiness["timeline"]["delta_ms"], 1306.032, places=3)
        self.assertEqual(readiness["timeline"]["tolerance_ms"], 500.0)

    def test_valid_wav_srt_is_ready_and_create_rechecks_the_same_gate(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            audio = _upload("voice.wav", _wav())
            srt = _upload("voice.srt", b"1\r\n00:00:00,000 --> 00:00:01,800\r\nReadable narration.\r\n")
            readiness = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=audio, imported_srt=srt)
            self.assertEqual(readiness["status"], "READY")
            created = app.create_project(project_id="prj_goal53_ready", settings={"execution": {"mode": "EXISTING_VOICE"}, "ui": {"input_source": "AUDIO_SRT"}}, imported_audio=audio, imported_srt=srt)
            self.assertEqual(created["input_source"], "AUDIO_SRT")
            bad = _upload("late.srt", b"1\n00:00:00,000 --> 00:00:00,200\nlate\n")
            with self.assertRaisesRegex(OperatorServiceError, "TIMELINE_MISMATCH") as blocked:
                app.create_project(project_id="prj_goal53_blocked", settings={"execution": {"mode": "EXISTING_VOICE"}, "ui": {"input_source": "AUDIO_SRT"}}, imported_audio=audio, imported_srt=bad)
            self.assertEqual(blocked.exception.readiness["timeline"]["code"], "TIMELINE_MISMATCH")

    def test_timeline_mismatch_messages_preserve_direction_and_magnitude(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); audio = _upload("voice.wav", _wav())
            after = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=audio,
                                        imported_srt=_upload("after.srt", b"1\n00:00:00,000 --> 00:00:03,000\nToo late.\n"))
            before = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=audio,
                                         imported_srt=_upload("before.srt", b"1\n00:00:00,000 --> 00:00:00,200\nToo early.\n"))
        self.assertEqual((after["status"], after["timeline"]["code"], after["timeline"]["direction"]),
                         ("BLOCKED", "TIMELINE_MISMATCH", "SRT_AFTER_AUDIO"))
        self.assertIn("after", after["timeline"]["message"]); self.assertNotIn("before", after["timeline"]["message"])
        self.assertEqual((before["status"], before["timeline"]["code"], before["timeline"]["direction"]),
                         ("BLOCKED", "TIMELINE_MISMATCH", "SRT_BEFORE_AUDIO"))
        self.assertIn("before", before["timeline"]["message"]); self.assertNotIn("after", before["timeline"]["message"])
        self.assertAlmostEqual(before["timeline"]["signed_offset_ms"], -1800.0)
        self.assertEqual(before["timeline"]["delta_ms"], 1800.0)

    def test_existing_audio_semantics_remain_alignment_when_blocked_or_ready(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            missing = app.inspect_imports(source_mode="EXISTING_AUDIO", imported_audio=None, imported_srt=None)
            invalid = app.inspect_imports(source_mode="EXISTING_AUDIO", imported_audio=_upload("bad.wav", b"not audio"), imported_srt=None)
            ready = app.inspect_imports(source_mode="EXISTING_AUDIO", imported_audio=_upload("voice.wav", _wav()), imported_srt=None)
        for readiness in (missing, invalid):
            self.assertEqual((readiness["status"], readiness["tts"], readiness["timing"]), ("BLOCKED", "SKIPPED", "ALIGNMENT"))
        self.assertEqual((ready["status"], ready["tts"], ready["timing"]), ("READY", "SKIPPED", "ALIGNMENT"))

    def test_valid_m4a_srt_is_ready(self):
        ffmpeg = shutil.which("ffmpeg")
        self.assertIsNotNone(ffmpeg, "ffmpeg is required by the M4A import contract")
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "tone.m4a"
            result = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(source)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            app = OperatorService(root)
            readiness = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=_upload("tone.m4a", source.read_bytes()),
                                            imported_srt=_upload("tone.srt", b"1\n00:00:00,000 --> 00:00:01,900\nA real audible tone.\n"))
            self.assertEqual(readiness["status"], "READY")
            self.assertEqual((readiness["audio"]["format"], readiness["audio"]["codec"]), ("m4a", "aac"))

    def test_invalid_audio_and_srt_are_structured_not_generic_exceptions(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            invalid_audio = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=_upload("bad.wav", b"not audio"),
                                                imported_srt=_upload("timing.srt", b"1\n00:00:00,000 --> 00:00:01,000\nText\n"))
            invalid_srt = app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=_upload("ok.wav", _wav()),
                                              imported_srt=_upload("bad.srt", b"1\nnot-a-time\nText\n"))
        self.assertEqual((invalid_audio["status"], invalid_audio["code"]), ("BLOCKED", "AUDIO_INVALID"))
        self.assertEqual((invalid_srt["status"], invalid_srt["code"], invalid_srt["srt"]["code"]), ("BLOCKED", "SRT_INVALID", "SRT_TIMESTAMP_INVALID"))

    def test_browser_shows_actionable_readiness_and_gates_continue(self):
        chrome = Path(__import__("os").environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe"
        if not chrome.is_file(): self.skipTest("Google Chrome is not installed for the browser acceptance test")
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as root:
            server = create_server(root, port=0); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                    page = browser.new_page(); page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                    page.get_by_role("button", name="＋ New video", exact=True).first.click()
                    page.get_by_role("radio", name="AUDIO + SRT Import matching audio and SRT. TTS is skipped; SRT is timing.", exact=True).check()
                    page.locator("#existingAudio").set_input_files({"name": "voice.wav", "mimeType": "audio/wav", "buffer": _wav()})
                    page.locator("#existingSrt").set_input_files({"name": "ready.srt", "mimeType": "text/plain", "buffer": b"1\n00:00:00,000 --> 00:00:01,800\nReady subtitle.\n"})
                    page.locator("#sourceReadiness").get_by_text("Import readiness: READY", exact=False).wait_for(timeout=5000)
                    self.assertTrue(page.get_by_role("button", name="Continue", exact=True).is_enabled())
                    page.locator("#existingSrt").set_input_files({"name": "late.srt", "mimeType": "text/plain", "buffer": b"1\n00:00:00,000 --> 00:00:00,200\nLate subtitle.\n"})
                    page.locator("#sourceReadiness").get_by_text("Subtitle timing ends", exact=False).first.wait_for(timeout=5000)
                    readiness_text = page.locator("#sourceReadiness").inner_text()
                    self.assertIn("before the narration audio", readiness_text)
                    self.assertNotIn("after the narration audio", readiness_text)
                    self.assertIn("Allowed: 0.500 s", readiness_text)
                    self.assertFalse(page.get_by_role("button", name="Continue", exact=True).is_enabled())
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(5)
