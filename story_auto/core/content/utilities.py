"""Deterministic narration helpers that never rewrite source narration."""

from __future__ import annotations

import hashlib
import unicodedata
import re


def narration_hash(narration: str) -> str:
    if not isinstance(narration, str):
        raise TypeError("narration must be text")
    return hashlib.sha256(narration.encode("utf-8")).hexdigest()


def normalize_for_comparison(narration: str) -> str:
    """Normalize only for equality comparisons, never for durable source output."""

    if not isinstance(narration, str):
        raise TypeError("narration must be text")
    return unicodedata.normalize("NFC", narration.replace("\r\n", "\n").replace("\r", "\n"))


def narrations_equivalent(left: str, right: str) -> bool:
    return normalize_for_comparison(left) == normalize_for_comparison(right)


def plan_chunks(narration: str, *, max_characters: int) -> tuple[str, ...]:
    """Plan deterministic source slices whose concatenation is exactly *narration*."""

    if not isinstance(narration, str) or not narration:
        raise ValueError("narration must be non-empty text")
    if not isinstance(max_characters, int) or max_characters < 1:
        raise ValueError("max_characters must be a positive integer")
    chunks: list[str] = []
    position = 0
    while position < len(narration):
        limit = min(len(narration), position + max_characters)
        if limit < len(narration):
            split = narration.rfind("\n\n", position + 1, limit + 1)
            if split > position:
                limit = split + 2
        chunks.append(narration[position:limit])
        position = limit
    result = tuple(chunks)
    if "".join(result) != narration:
        raise AssertionError("chunk plan did not reconstruct narration exactly")
    return result


def validate_reconstruction(source: str, chunks: tuple[str, ...] | list[str]) -> bool:
    return "".join(chunks) == source


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Deterministic sentence ranges, retaining all source characters across spans."""
    spans, cursor = [], 0
    for match in re.finditer(r".+?(?:[.!?]+(?:[\"')\]]+)?)(?=\s+|$)", text, re.DOTALL):
        start, end = match.span()
        if text[start:end].strip(): spans.append((start, end)); cursor = end
    if cursor < len(text) and text[cursor:].strip(): spans.append((cursor, len(text)))
    return spans or [(0, len(text))]
