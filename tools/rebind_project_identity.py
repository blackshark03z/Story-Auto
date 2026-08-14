"""Rebind copied JSON artifacts to a separately versioned project identity."""
from __future__ import annotations

import argparse
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json

parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
parser.add_argument("project_id")
args = parser.parse_args()
root = args.project_root.resolve()
changed = []
for path in [root / "project.json", *(root / "output").glob("*.json")]:
    try: value = read_json(path)
    except Exception: continue
    if isinstance(value, dict) and "project_id" in value and value["project_id"] != args.project_id:
        value["project_id"] = args.project_id
        atomic_write_json(path, value)
        changed.append(path.relative_to(root).as_posix())
print({"project_id": args.project_id, "changed": changed})
