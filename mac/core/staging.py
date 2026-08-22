from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import STAGING_COPY_CHUNK, STAGING_PREFIX


@dataclass
class VolumeInfo:
    mount_point: Path
    protocol: str = ""
    solid_state: bool | None = None
    free_bytes: int = 0

    @property
    def is_external_usb(self) -> bool:
        return self.protocol.upper() in {"USB", "FIREWIRE", "THUNDERBOLT"}

    @property
    def looks_slow(self) -> bool:
        if self.solid_state is False:
            return True
        return self.is_external_usb


_VOLUME_CACHE: dict[Path, "VolumeInfo"] = {}
_VOLUME_LOCK = threading.Lock()


def reset_volume_cache() -> None:
    with _VOLUME_LOCK:
        _VOLUME_CACHE.clear()


def volume_info(path: Path | str) -> VolumeInfo:
    mount = _mount_point(Path(path))
    with _VOLUME_LOCK:
        cached = _VOLUME_CACHE.get(mount)
    if cached is not None:
        fresh = VolumeInfo(
            mount_point=cached.mount_point,
            protocol=cached.protocol,
            solid_state=cached.solid_state,
        )
        try:
            fresh.free_bytes = shutil.disk_usage(mount).free
        except OSError:
            fresh.free_bytes = cached.free_bytes
        return fresh

    info = _read_volume_info(mount)
    with _VOLUME_LOCK:
        _VOLUME_CACHE[mount] = info
    return info


def _read_volume_info(mount: Path) -> VolumeInfo:
    info = VolumeInfo(mount_point=mount)

    try:
        usage = shutil.disk_usage(mount)
        info.free_bytes = usage.free
    except OSError:
        pass

    try:
        out = subprocess.run(
            ["diskutil", "info", "-plist", str(mount)],
            capture_output=True, timeout=20,
        )
        if out.returncode == 0 and out.stdout:
            data = plistlib.loads(out.stdout)
            info.protocol = str(data.get("BusProtocol") or data.get("Protocol") or "")
            ss = data.get("SolidState")
            info.solid_state = bool(ss) if ss is not None else None
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        pass

    return info


def _mount_point(path: Path) -> Path:
    path = path.resolve()
    while not path.is_mount() and path != path.parent:
        path = path.parent
    return path


@dataclass
class Slot:
    directory: Path
    src_copy: Path
    dst: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


class StagingArea:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))

    def slot(self, src: Path, dst_name: str) -> Slot:
        directory = Path(tempfile.mkdtemp(dir=self.root))
        return Slot(
            directory=directory,
            src_copy=directory / src.name,
            dst=directory / dst_name,
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _copy_bytes(
    src: Path, dst: Path, on_progress: Callable[[float], None] | None
) -> None:
    total = src.stat().st_size
    copied = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            chunk = fin.read(STAGING_COPY_CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            copied += len(chunk)
            if on_progress and total > 0:
                on_progress(min(copied / total, 1.0))
    shutil.copystat(src, dst)
    if on_progress:
        on_progress(1.0)


def copy_in(
    src: Path, slot: Slot, on_progress: Callable[[float], None] | None = None
) -> Path:
    if on_progress is None:
        shutil.copy2(src, slot.src_copy)
    else:
        _copy_bytes(src, slot.src_copy, on_progress)
    return slot.src_copy


def move_out(
    slot_dst: Path,
    final_dst: Path,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    final_dst.parent.mkdir(parents=True, exist_ok=True)
    staging_name = final_dst.with_name(final_dst.name + ".частичный")
    if staging_name.exists():
        staging_name.unlink()

    try:
        os.rename(slot_dst, staging_name)
        if on_progress:
            on_progress(1.0)
    except OSError:
        _copy_bytes(slot_dst, staging_name, on_progress)
        slot_dst.unlink()

    staging_name.replace(final_dst)
    return final_dst
