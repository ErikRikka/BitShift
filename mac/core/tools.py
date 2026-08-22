from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .config import APP_NAME, BUNDLED_TOOLS_SUBDIR, ICON_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resources_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent.parent / "Resources"
    return Path(__file__).resolve().parent.parent


def tool_path(name: str) -> str | None:
    bundled = resources_dir() / BUNDLED_TOOLS_SUBDIR / name
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)


def icon_path() -> Path | None:
    places = [resources_dir() / ICON_NAME]
    if not is_frozen():
        places.append(
            resources_dir() / f"{APP_NAME}.app" / "Contents" / "Resources" / ICON_NAME
        )
    for place in places:
        if place.is_file():
            return place
    return None
