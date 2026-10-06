"""Find the JSON array in a model's raw reply (spec 4.8: "extract the JSON array").

Tolerated, because real models do it and it says nothing about the content: a code fence around the
array, and prose before or after it. NOT tolerated: anything that is not valid JSON inside the array
(trailing commas, comments, single quotes, a truncated reply). Content is validated later, per
company, by `gauge.schemas.CompanyJudgment`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*\n(.*?)```", re.DOTALL)
_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class Extraction:
    items: list[Any] | None  # the array's elements, or None when no array was found
    method: str  # plain | fenced | embedded | none
    error: str | None = None


def _as_list(text: str) -> list[Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, list) else None


def extract_json_array(text: str) -> Extraction:
    """The most plausible JSON array of objects in `text`, and how it was found."""
    stripped = text.strip()
    if not stripped:
        return Extraction(None, "none", "the reply is empty")

    if (items := _as_list(stripped)) is not None:
        return Extraction(items, "plain")

    for block in FENCE_RE.findall(text):
        if (items := _as_list(block.strip())) is not None:
            return Extraction(items, "fenced")

    best: list[Any] | None = None
    for match in re.finditer(r"\[", text):
        try:
            value, _end = _DECODER.raw_decode(text, match.start())
        except ValueError:
            continue
        is_objects = isinstance(value, list) and value and all(isinstance(v, dict) for v in value)
        if is_objects and (best is None or len(value) > len(best)):
            best = value
    if best is not None:
        return Extraction(best, "embedded")

    if "[" in text and "]" not in text[text.rfind("[") :]:
        return Extraction(None, "none", "no complete JSON array found (the reply looks truncated)")
    return Extraction(None, "none", "no valid JSON array of objects found in the reply")
