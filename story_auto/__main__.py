"""Minimal CLI for the Story Auto foundation."""

from __future__ import annotations
import argparse
import uuid
from pathlib import Path

from .core.project import ProjectConfig, RuntimeLayout, create_project
from .pipeline import run_audio_stages, run_content_stage
from .core.planning import approve_plan, run_planning_stages

def main() -> int:
    parser = argparse.ArgumentParser(prog="story-auto")
    parser.add_argument("--runtime-root", default="runtime", help="Story Auto runtime root")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an isolated project")
    new.add_argument("--project-id")
    new.add_argument("--render-mode", default="hybrid_hook")
    for name in ("run", "resume"):
        command = commands.add_parser(name, help="Run the foundation pipeline" if name == "run" else "Resume the foundation pipeline")
        command.add_argument("project_id")
    approve = commands.add_parser("approve-plan", help="Approve validated story timeline and continuity")
    approve.add_argument("project_id")
    args = parser.parse_args()
    try:
        if args.command == "new":
            project_id = args.project_id or f"prj_{uuid.uuid4().hex}"
            create_project(RuntimeLayout.from_root(args.runtime_root), ProjectConfig(project_id=project_id, render_mode=args.render_mode))
            print(f"CREATED {project_id}")
            return 0
        if args.command == "approve-plan":
            approve_plan(Path(args.runtime_root), args.project_id)
            print("review_state: APPROVED")
            return 0
        result = run_content_stage(Path(args.runtime_root), args.project_id)
        print(f"content: {result}")
        # Projects created before audio configuration remain valid content-only projects.
        from .core.project import load_project
        _, config = load_project(RuntimeLayout.from_root(args.runtime_root), args.project_id)
        if "tts" in config.settings:
            tts, alignment = run_audio_stages(Path(args.runtime_root), args.project_id)
            print(f"tts: {tts}\nalignment: {alignment}")
        if "llm" in config.settings:
            if "tts" not in config.settings:
                raise ValueError("planning requires canonical alignment; configure and run tts first")
            timeline, continuity = run_planning_stages(Path(args.runtime_root), args.project_id)
            print(f"story_timeline: {timeline}\ncontinuity: {continuity}")
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")

if __name__ == "__main__":
    raise SystemExit(main())
