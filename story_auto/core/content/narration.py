"""Strict parsing for Story Auto's ``content.md`` input."""

from __future__ import annotations

from dataclasses import dataclass
import re


_ATX_HEADING = re.compile(r"^ {0,3}(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$")


class ContentValidationError(ValueError):
    """Raised when a source document cannot supply canonical narration."""

    failure_class = "INPUT_INVALID"


@dataclass(frozen=True)
class NarrationDocument:
    """The narration text extracted from a valid ``content.md`` document."""

    narration: str


def _heading_at(line: str) -> tuple[int, str] | None:
    match = _ATX_HEADING.match(line)
    if match is None:
        return None
    return len(match.group("marks")), match.group("title").strip()


def parse_content_markdown(markdown: str) -> NarrationDocument:
    """Return the one required non-empty ``## Narration`` section.

    The parser intentionally does not infer narration from the document body.
    Only an H2 whose title is exactly ``Narration`` is accepted.  Its text ends
    at the next heading of equal or higher rank, while lower-rank headings are
    preserved as narration content.
    """

    if not isinstance(markdown, str):
        raise ContentValidationError("content.md must be UTF-8 text")

    lines = markdown.splitlines()
    narration_starts: list[int] = []
    for index, line in enumerate(lines):
        heading = _heading_at(line)
        if heading == (2, "Narration"):
            narration_starts.append(index)

    if not narration_starts:
        raise ContentValidationError("content.md requires exactly one ## Narration section")
    if len(narration_starts) > 1:
        raise ContentValidationError("content.md contains duplicate ## Narration sections")

    start = narration_starts[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        heading = _heading_at(lines[index])
        if heading is not None and heading[0] <= 2:
            end = index
            break

    narration = "\n".join(lines[start:end]).strip()
    if not narration:
        raise ContentValidationError("## Narration must contain non-whitespace text")
    return NarrationDocument(narration=narration)
