from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from story_auto.core.artifacts import ArtifactWriteError, atomic_write_json, atomic_write_text, read_json, sha256_file
from story_auto.core.checkpoint import CheckpointStore, FingerprintError, canonical_json, fingerprint
from story_auto.core.content import ContentValidationError, narrations_equivalent, narration_hash, parse_content_markdown, plan_chunks, validate_reconstruction
from story_auto.core.project import ProjectConfig, ProjectPathError, ProjectPaths, ProjectValidationError, RuntimeLayout, create_project, load_project
from story_auto.core.project import lock as lock_module
from story_auto.core.project.lock import ProjectLock, ProjectLockedError, _process_is_alive, _windows_process_is_alive
from story_auto.core.retry import retry
from story_auto.pipeline import run_content_stage


class NarrationParsingTests(unittest.TestCase):
    def test_extracts_only_required_narration_section(self) -> None:
        document = parse_content_markdown(
            "# Title\n\n## Narration\n\nFirst line.\n\n### Preserved subheading\nSecond line.\n\n## Notes\nHidden.\n"
        )
        self.assertEqual(document.narration, "First line.\n\n### Preserved subheading\nSecond line.")

    def test_rejects_missing_empty_and_duplicate_sections(self) -> None:
        for source in (
            "# Title\n\nNarration without a heading.",
            "## Narration\n\n ## Other\n",
            "## Narration\nOne\n\n## Narration\nTwo\n",
        ):
            with self.subTest(source=source), self.assertRaises(ContentValidationError):
                parse_content_markdown(source)

    def test_preserves_paragraphs_and_chunk_plans_reconstruct_exactly(self) -> None:
        narration = "First paragraph.\n\nSecond paragraph is longer.\n\nThird."
        chunks = plan_chunks(narration, max_characters=22)
        self.assertTrue(validate_reconstruction(narration, chunks))
        self.assertEqual(chunks, plan_chunks(narration, max_characters=22))
        self.assertTrue(narrations_equivalent("A\r\nB", "A\nB"))
        self.assertEqual(narration_hash(narration), narration_hash(narration))


class AtomicArtifactTests(unittest.TestCase):
    def test_writes_utf8_json_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "artifact.json"
            atomic_write_json(target, {"z": "Tiếng Việt", "a": [1, 2]})
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{\n  "a": [\n    1,\n    2\n  ],\n  "z": "Tiếng Việt"\n}\n',
            )
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["z"], "Tiếng Việt")

    def test_failed_replace_preserves_prior_file_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "artifact.txt"
            target.write_text("previous", encoding="utf-8")
            with patch("story_auto.core.artifacts.atomic.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(ArtifactWriteError):
                    atomic_write_text(target, "replacement")
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(Path(directory).glob(".artifact.txt.*.tmp")), [])

    def test_json_roundtrip_and_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a.json"
            atomic_write_json(path, {"a": 1})
            self.assertEqual(read_json(path), {"a": 1})
            self.assertEqual(sha256_file(path), sha256_file(path))


class FingerprintTests(unittest.TestCase):
    def test_canonical_inputs_have_stable_identity(self) -> None:
        first = fingerprint(namespace="story_auto.content.v1", direct_inputs={"b": 2, "a": {"y": 1, "x": 0}})
        second = fingerprint(namespace="story_auto.content.v1", direct_inputs={"a": {"x": 0, "y": 1}, "b": 2})
        changed = fingerprint(namespace="story_auto.content.v1", direct_inputs={"a": {"x": 0, "y": 2}, "b": 2})
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_rejects_invalid_namespace_and_nonfinite_json(self) -> None:
        with self.assertRaises(FingerprintError):
            fingerprint(namespace="", direct_inputs={})
        with self.assertRaises(FingerprintError):
            canonical_json({"not_finite": float("nan")})

    def test_semantic_fields_and_settings_are_order_independent(self) -> None:
        first = fingerprint(stage_name="content", producer_version="v1", artifact_schema_version="a1", direct_inputs={"content": "one"}, settings={"b": 2, "a": 1})
        second = fingerprint(stage_name="content", producer_version="v1", artifact_schema_version="a1", direct_inputs={"content": "one"}, settings={"a": 1, "b": 2})
        changed = fingerprint(stage_name="content", producer_version="v1", artifact_schema_version="a1", direct_inputs={"content": "two"}, settings={"a": 1, "b": 2})
        setting_changed = fingerprint(stage_name="content", producer_version="v1", artifact_schema_version="a1", direct_inputs={"content": "one"}, settings={"a": 2, "b": 2})
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertNotEqual(first, setting_changed)


class RuntimePathTests(unittest.TestCase):
    def test_creates_only_story_auto_runtime_layout_under_temporary_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layout = RuntimeLayout.from_root(Path(directory) / "story-auto-runtime").ensure()
            expected = {
                layout.projects,
                layout.flow_profile,
                layout.cache,
                layout.temp,
                layout.logs,
                layout.evidence,
                layout.locks,
            }
            self.assertTrue(all(path.is_dir() for path in expected))
            self.assertTrue(all("youtube" not in str(path).casefold() for path in expected))

    def test_project_artifacts_require_opaque_id_and_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = ProjectPaths(RuntimeLayout.from_root(directory), "prj_story001")
            self.assertEqual(project.project_file, project.root / "project.json")
            self.assertEqual(project.content_file, project.root / "content.md")
            self.assertEqual(
                project.artifact_path("artifacts/plans/timeline.json"),
                project.root / "artifacts" / "plans" / "timeline.json",
            )
            for unsafe in ("../outside.json", "C:\\outside.json", "/outside.json", ""):
                with self.subTest(unsafe=unsafe), self.assertRaises(ProjectPathError):
                    project.artifact_path(unsafe)
            with self.assertRaises(ProjectPathError):
                ProjectPaths(RuntimeLayout.from_root(directory), "story-001")


class ProjectContractTests(unittest.TestCase):
    def test_create_and_load_small_project_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory)
            created = create_project(runtime, ProjectConfig(project_id="prj_story001"))
            loaded_paths, config = load_project(runtime, "prj_story001")
            self.assertEqual(created.root, loaded_paths.root)
            self.assertEqual(config.render_mode, "hybrid_hook")
            self.assertTrue((created.root / "output").is_dir())
            self.assertTrue((created.root / "logs").is_dir())

    def test_rejects_invalid_project_configuration(self) -> None:
        with self.assertRaises(ProjectValidationError):
            ProjectConfig(project_id="prj_story001", render_mode="invalid")


class LockTests(unittest.TestCase):
    class _WindowsProbe:
        def __init__(self, *, handle=1, error=0, exit_code=259, raises: Exception | None = None) -> None:
            self.handle, self.error, self.code, self.raises = handle, error, exit_code, raises
            self.closed: list[int] = []

        def open_process(self, pid: int):
            if self.raises:
                raise self.raises
            return self.handle

        def last_error(self) -> int:
            return self.error

        def exit_code(self, handle: int) -> int | None:
            if self.raises:
                raise self.raises
            return self.code

        def close_handle(self, handle: int) -> None:
            self.closed.append(handle)

    def test_process_probe_keeps_posix_semantics(self) -> None:
        self.assertFalse(_process_is_alive(-1))
        with patch.object(lock_module.os, "name", "posix"), patch.object(lock_module.os, "kill") as kill:
            self.assertTrue(_process_is_alive(42))
            kill.assert_called_once_with(42, 0)
        with patch.object(lock_module.os, "name", "posix"), patch.object(lock_module.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(_process_is_alive(42))
        with patch.object(lock_module.os, "name", "posix"), patch.object(lock_module.os, "kill", side_effect=PermissionError):
            self.assertTrue(_process_is_alive(42))

    def test_windows_native_probe_classifies_liveness_and_closes_handles(self) -> None:
        missing = self._WindowsProbe(handle=0, error=87)
        self.assertFalse(_windows_process_is_alive(21136, probe=missing))
        self.assertEqual(missing.closed, [])
        self.assertTrue(_windows_process_is_alive(21136, probe=self._WindowsProbe(handle=0, error=5)))
        self.assertTrue(_windows_process_is_alive(21136, probe=self._WindowsProbe(raises=RuntimeError("unknown"))))
        live = self._WindowsProbe(handle=7, exit_code=259)
        self.assertTrue(_windows_process_is_alive(21136, probe=live))
        self.assertEqual(live.closed, [7])
        exited = self._WindowsProbe(handle=9, exit_code=0)
        self.assertFalse(_windows_process_is_alive(21136, probe=exited))
        self.assertEqual(exited.closed, [9])

    def test_windows_path_never_invokes_os_kill(self) -> None:
        with patch.object(lock_module.os, "name", "nt"), patch.object(lock_module, "_windows_process_is_alive", return_value=False) as native, patch.object(lock_module.os, "kill") as kill:
            self.assertFalse(_process_is_alive(21136))
        native.assert_called_once_with(21136)
        kill.assert_not_called()

    def test_windows_stale_positive_pid_recovers_without_runtime_lock_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory).ensure()
            stale = runtime.locks / "prj_21136.lock"
            atomic_write_json(stale, {"project_id": "prj_21136", "pid": 21136, "hostname": __import__("socket").gethostname(), "created_at": 0})
            with patch.object(lock_module, "_process_is_alive", return_value=False) as alive:
                lock = ProjectLock(runtime, "prj_21136", stale_after_seconds=1, clock=lambda: 2)
                self.assertTrue(lock._stale())
                lock.acquire().release()
            alive.assert_called_with(21136)

    def test_lock_keeps_live_nonstale_and_foreign_owners(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory).ensure()
            host = __import__("socket").gethostname()
            cases = [
                ("prj_live", {"project_id": "prj_live", "pid": 21136, "hostname": host, "created_at": 0}, True, 2),
                ("prj_fresh", {"project_id": "prj_fresh", "pid": -1, "hostname": host, "created_at": 1.5}, False, 2),
                ("prj_foreign", {"project_id": "prj_foreign", "pid": -1, "hostname": "another-host", "created_at": 0}, False, 2),
            ]
            for project_id, metadata, owner_live, now in cases:
                atomic_write_json(runtime.locks / f"{project_id}.lock", metadata)
                with patch.object(lock_module, "_process_is_alive", return_value=owner_live):
                    with self.assertRaises(ProjectLockedError):
                        ProjectLock(runtime, project_id, stale_after_seconds=1, clock=lambda now=now: now).acquire()

    def test_one_writer_release_and_stale_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory)
            first = ProjectLock(runtime, "prj_story001")
            first.acquire()
            with self.assertRaises(ProjectLockedError):
                ProjectLock(runtime, "prj_story001").acquire()
            ProjectLock(runtime, "prj_other").acquire().release()
            first.release()
            ProjectLock(runtime, "prj_story001").acquire().release()
            stale = runtime.ensure().locks / "prj_stale.lock"
            atomic_write_json(stale, {"project_id": "prj_stale", "pid": -1, "hostname": __import__("socket").gethostname(), "created_at": 0})
            ProjectLock(runtime, "prj_stale", stale_after_seconds=1, clock=lambda: 2).acquire().release()


class CheckpointAndPipelineTests(unittest.TestCase):
    def _project(self, directory: str) -> tuple[RuntimeLayout, ProjectPaths]:
        runtime = RuntimeLayout.from_root(directory)
        paths = create_project(runtime, ProjectConfig(project_id="prj_story001"), "# Title\n\n## Narration\n\nFirst paragraph.\n\nSecond paragraph.\n")
        return runtime, paths

    def test_checkpoint_hit_misses_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._project(directory)
            store = CheckpointStore(paths)
            self.assertEqual(store.decide("content", "one").action, "RUN")
            atomic_write_json(paths.artifact_path("output/manifest.json"), {"ok": True})
            store.record("content", fingerprint="one", status="SUCCESS", outputs=["output/manifest.json"], producer_version="v1")
            self.assertEqual(store.decide("content", "one").action, "SKIP")
            self.assertEqual(store.decide("content", "two").action, "RUN")
            paths.artifact_path("output/manifest.json").unlink()
            self.assertEqual(store.decide("content", "one").action, "RUN")
            store.record("content", fingerprint="one", status="FAILED", outputs=[], producer_version="v1")
            self.assertEqual(store.decide("content", "one").action, "RUN")
            store._path("content").write_text("not json", encoding="utf-8")
            self.assertEqual(store.decide("content", "one").action, "RUN")

    def test_integration_run_skip_changed_content_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._project(directory)
            self.assertEqual(run_content_stage(runtime.root, "prj_story001"), "RUN")
            self.assertEqual(run_content_stage(runtime.root, "prj_story001"), "SKIP")
            atomic_write_text(paths.content_file, "## Narration\n\nChanged narration.\n")
            self.assertEqual(run_content_stage(runtime.root, "prj_story001"), "RUN")

    def test_missing_and_malformed_content_fail_at_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._project(directory)
            paths.content_file.unlink()
            with self.assertRaisesRegex(ContentValidationError, "missing content.md"):
                run_content_stage(runtime.root, "prj_story001")
            atomic_write_text(paths.content_file, "# No narration\n")
            with self.assertRaises(ContentValidationError):
                run_content_stage(runtime.root, "prj_story001")

    def test_cli_new_run_resume_and_content_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            command = [sys.executable, "-m", "story_auto", "--runtime-root", str(root)]
            created = subprocess.run([*command, "new", "--project-id", "prj_cli"], text=True, capture_output=True, check=True)
            self.assertIn("CREATED prj_cli", created.stdout)
            self.assertIn("RUN", subprocess.run([*command, "run", "prj_cli"], text=True, capture_output=True, check=True).stdout)
            self.assertIn("SKIP", subprocess.run([*command, "resume", "prj_cli"], text=True, capture_output=True, check=True).stdout)
            atomic_write_text(root / "projects" / "prj_cli" / "content.md", "## Narration\n\nA changed story.\n")
            self.assertIn("RUN", subprocess.run([*command, "resume", "prj_cli"], text=True, capture_output=True, check=True).stdout)


class RetryTests(unittest.TestCase):
    def test_retry_is_bounded_and_testable_without_real_sleep(self) -> None:
        calls, delays = [], []
        def operation() -> str:
            calls.append(1)
            if len(calls) < 3: raise OSError("temporary")
            return "ok"
        self.assertEqual(retry(operation, attempts=3, base_delay_seconds=2, max_delay_seconds=3, sleep=delays.append), "ok")
        self.assertEqual(delays, [2, 3])


if __name__ == "__main__":
    unittest.main()
