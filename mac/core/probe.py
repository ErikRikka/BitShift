from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from .config import (
    COUNTABLE_EXTS,
    EMPTY_COLOR_VALUES,
    PROBE_CACHE_MAX,
    PROBE_TIMEOUT,
)
from .tools import tool_path


class ProbeError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    path: Path
    duration: float = 0.0
    bit_rate: int = 0
    codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    pix_fmt: str = ""
    color_primaries: str = ""
    color_trc: str = ""
    colorspace: str = ""
    audio_codec: str = ""
    audio_channels: int = 0
    audio_bit_rate: int = 0

    @property
    def pixel_rate(self) -> float:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            return 0.0
        return float(self.width) * float(self.height) * float(self.fps)

    @property
    def is_10bit_or_422(self) -> bool:
        pf = self.pix_fmt
        return bool(pf) and ("422" in pf or "444" in pf or "10le" in pf or "10be" in pf or "12le" in pf)

    def color_args(self) -> list[str]:
        args: list[str] = []
        if self.color_primaries not in EMPTY_COLOR_VALUES:
            args += ["-color_primaries", self.color_primaries]
        if self.color_trc not in EMPTY_COLOR_VALUES:
            args += ["-color_trc", self.color_trc]
        if self.colorspace not in EMPTY_COLOR_VALUES:
            args += ["-colorspace", self.colorspace]
        return args


def _tool(name: str) -> str:
    path = tool_path(name)
    if not path:
        raise ProbeError(
            f"{name} не найден. Установите ffmpeg: brew install ffmpeg"
        )
    return path


def _run(args: list[str], timeout: float | None = None) -> str:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise ProbeError(proc.stderr.strip() or f"код возврата {proc.returncode}")
    return proc.stdout


def _to_float(value: object) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and f not in (float("inf"), float("-inf")) else 0.0


def _to_int(value: object) -> int:
    return int(_to_float(value))


def _parse_fps(raw: object) -> float:
    if not isinstance(raw, str) or "/" not in raw:
        return _to_float(raw)
    try:
        frac = Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(frac) if frac.denominator else 0.0


def _probe_now(path: Path) -> MediaInfo:
    out = _run(
        [
            _tool("ffprobe"),
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=PROBE_TIMEOUT,
    )
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe вернул неразбираемый JSON: {exc}") from exc

    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ProbeError("в файле нет видеодорожки")

    info = MediaInfo(path=path)
    info.codec = str(video.get("codec_name") or "")
    info.width = _to_int(video.get("width"))
    info.height = _to_int(video.get("height"))
    info.pix_fmt = str(video.get("pix_fmt") or "")
    info.color_primaries = str(video.get("color_primaries") or "")
    info.color_trc = str(video.get("color_transfer") or "")
    info.colorspace = str(video.get("color_space") or "")
    info.audio_codec = str(audio.get("codec_name") or "") if audio else ""
    info.audio_channels = _to_int(audio.get("channels")) if audio else 0
    info.audio_bit_rate = _to_int(audio.get("bit_rate")) if audio else 0

    info.fps = _parse_fps(video.get("r_frame_rate")) or _parse_fps(
        video.get("avg_frame_rate")
    )

    info.duration = _to_float(video.get("duration")) or _to_float(
        fmt.get("duration")
    )

    info.bit_rate = _to_int(video.get("bit_rate")) or _to_int(fmt.get("bit_rate"))

    return info


_CACHE: dict[tuple[str, int, int], MediaInfo] = {}


def reset_probe_cache() -> None:
    _CACHE.clear()


def probe(path: Path | str) -> MediaInfo:
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return _probe_now(path)

    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        return replace(hit)

    info = _probe_now(path)
    if len(_CACHE) >= PROBE_CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = replace(info)
    return info


def count_frames(path: Path | str, timeout: float | None = None) -> int:
    path = Path(path)
    out = _run(
        [
            _tool("ffprobe"),
            "-v", "error",
            "-select_streams", "v:0",
            "-count_packets",
            "-show_entries", "stream=nb_read_packets",
            "-of", "csv=p=0",
            str(path),
        ],
        timeout=timeout,
    )
    return _to_int(out.strip().rstrip(","))


def frames_countable(path: Path | str) -> bool:
    return Path(path).suffix.lower() in COUNTABLE_EXTS
