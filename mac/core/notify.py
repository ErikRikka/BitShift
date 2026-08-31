from __future__ import annotations

import subprocess

from .config import COMPLETION_SOUND


def send(title: str, text: str) -> bool:
    script = f'display notification {_quote(text)} with title {_quote(title)}'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def play_completion_sound() -> bool:
    try:
        proc = subprocess.run(
            ["afplay", str(COMPLETION_SOUND)],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
