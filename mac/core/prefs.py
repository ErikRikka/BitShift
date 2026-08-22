from __future__ import annotations

import json
from typing import Any

from .config import PREFS_PATH


def load() -> dict[str, Any]:
    try:
        raw = PREFS_PATH.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save(values: dict[str, Any]) -> bool:
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(
            json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return False
    return True


def remember(**values: Any) -> None:
    current = load()
    current.update(values)
    save(current)
