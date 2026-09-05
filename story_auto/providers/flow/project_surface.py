"""Observed Flow project-list contract (2026-09-05).

Observe responses initiated by the normal provider UI; never replay an RPC.
Absence is usable only when the complete response agrees with the rendered grid.
Unknown response fields, pagination, loading, or partial DOM fail closed.
"""
from __future__ import annotations

import json
import re

PROJECT_ID = re.compile(r"^[A-Za-z0-9-]+$")
CURRENT_PROJECT_PATH = re.compile(r"^/project/([A-Za-z0-9-]+)$")

LIST_DOM = """(()=>({
  ready:document.querySelectorAll('flow-projects-page .projects-grid').length===1 &&
        document.querySelectorAll('flow-loading-page').length===0,
  items:document.querySelectorAll('flow-projects-page .projects-grid-item').length,
  rows:Array.from(document.querySelectorAll('flow-projects-page .project-card')).map(e=>({
    project_url:e.querySelector('a.project-thumbnail-container')?.href,
    project_name:Array.from(e.querySelector('.project-title-label')?.childNodes||[])
      .filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim()
  }))
}))()"""


def observed_project_list(body: str) -> list[dict] | None:
    """Decode only the observed complete UpteDb response; None means no proof."""
    for line in body.splitlines():
        if not line.startswith('[["wrb.fr"'):
            continue
        try:
            envelopes = json.loads(line)
            for envelope in envelopes:
                if envelope[:2] != ["wrb.fr", "UpteDb"]:
                    continue
                payload = json.loads(envelope[2])
                if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], list):
                    return None
                result = []
                for row in payload[0]:
                    if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                            or not PROJECT_ID.fullmatch(row[0]) or not isinstance(row[1], list)
                            or len(row[1]) not in {3, 5} or not isinstance(row[1][0], str)
                            or not row[1][0].strip() or row[1][1] is not None
                            or not isinstance(row[1][2], list) or len(row[1][2]) != 2
                            or not all(type(n) is int for n in row[1][2])):
                        return None
                    result.append({"project_identity":row[0], "project_name":row[1][0],
                                   "project_url":"https://flow.google.com/project/" + row[0],
                                   "created_at_epoch_seconds":row[1][2][0]})
                if len({row["project_identity"] for row in result}) != len(result):
                    return None
                return result
        except (ValueError, IndexError, TypeError):
            return None
    return None


def list_agrees_with_dom(rows: list[dict], dom: dict) -> bool:
    if not isinstance(dom, dict) or dom.get("ready") is not True or dom.get("items") != len(rows):
        return False
    expected = [{"project_name":r["project_name"], "project_url":r["project_url"]} for r in rows]
    rendered = dom.get("rows")
    if not isinstance(rendered, list) or len(rendered) != len(rows):
        return False
    key = lambda r: (r.get("project_url", ""), r.get("project_name", ""))
    return sorted(expected, key=key) == sorted(rendered, key=key)
