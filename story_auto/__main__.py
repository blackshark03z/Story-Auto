"""Minimal CLI for the Story Auto foundation."""

from __future__ import annotations
import argparse
import uuid
from pathlib import Path

from .core.project import ProjectConfig, RuntimeLayout, create_project
from .pipeline import run_content_stage

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
    args = parser.parse_args()
    try:
        if args.command == "new":
            project_id = args.project_id or f"prj_{uuid.uuid4().hex}"
            create_project(RuntimeLayout.from_root(args.runtime_root), ProjectConfig(project_id=project_id, render_mode=args.render_mode))
            print(f"CREATED {project_id}")
            return 0
        result = run_content_stage(Path(args.runtime_root), args.project_id)
        print(f"content stage = {result}")
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")

if __name__ == "__main__":
    raise SystemExit(main())
