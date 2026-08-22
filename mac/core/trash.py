from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class TrashUnavailable(RuntimeError):
    pass


@dataclass
class TrashResult:
    ok: bool
    path: Path
    trashed_to: Path | None = None
    error: str = ""


def _file_manager():
    try:
        from Foundation import NSFileManager, NSURL
    except ImportError as exc:
        raise TrashUnavailable(
            "Не установлен PyObjC. Выполните: "
            "pip install pyobjc-core pyobjc-framework-Cocoa"
        ) from exc
    return NSFileManager, NSURL


@lru_cache(maxsize=1)
def trash_available() -> bool:
    try:
        _file_manager()
    except TrashUnavailable:
        return False
    return True


def move_to_trash(path: Path | str) -> TrashResult:
    path = Path(path)
    if not path.exists():
        return TrashResult(False, path, error="файла нет")

    NSFileManager, NSURL = _file_manager()
    url = NSURL.fileURLWithPath_(str(path))
    ok, resulting_url, error = (
        NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            url, None, None
        )
    )

    if not ok:
        message = ""
        if error is not None:
            message = str(error.localizedDescription())
        return TrashResult(False, path, error=message or "система отказала без объяснения")

    trashed_to = None
    if resulting_url is not None:
        trashed_to = Path(str(resulting_url.path()))
    return TrashResult(True, path, trashed_to=trashed_to)
