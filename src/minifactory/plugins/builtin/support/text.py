"""Small text helpers."""

from __future__ import annotations

import json


def first_json_object(text: str) -> object:
    """Models often wrap JSON in prose or code fences, or add chatter after it:
    take the first complete JSON object and ignore the rest."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    return json.JSONDecoder().raw_decode(text[start:])[0]
