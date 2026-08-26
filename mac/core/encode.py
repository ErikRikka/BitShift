from __future__ import annotations

import collections
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .config import (
    AUDIO_BITRATE,
    AUDIO_COPY_MAX_CHANNELS,
    AUDIO_DOWNMIX_CHANNELS,
    CODECS_WITHOUT_HW_DECODE,
    FFMPEG_DECODE_TROUBLE_HINTS,
    FFMPEG_ERROR_MARKS,
    FFMPEG_HW_DECODE_FAILURE_MARKS,
    FFMPEG_NOISE_MARKS,
    FFMPEG_STDERR_TAIL_LINES,
    PRORES_PROFILE_HQ,
    RESULT_SUFFIX,
)
from .tools import tool_path
from .modes import AUDIO_ORIGINAL, Codec
from .probe import MediaInfo


def hw_decode_possible(codec_name: str) -> bool:
    return codec_name.lower() not in CODECS_WITHOUT_HW_DECODE


def ffmpeg_path() -> str:
    path = tool_path("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg не найден. Установите: brew install ffmpeg")
    return path


def run_with_progress(
    args: Sequence[str],
    *,
    duration: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    on_pid: Callable[[int, bool], None] | None = None,
) -> tuple[int, str]:
    live = on_progress is not None and duration > 0
    proc = subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE if live else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    if on_pid:
        on_pid(proc.pid, True)

    tail: collections.deque[str] = collections.deque(maxlen=FFMPEG_STDERR_TAIL_LINES)

    def drain() -> None:
        if proc.stderr is not None:
            for line in proc.stderr:
                tail.append(line)

    pump = threading.Thread(target=drain, daemon=True)
    pump.start()

    try:
        if live and proc.stdout is not None and on_progress is not None:
            for line in proc.stdout:
                if line.startswith("out_time_us="):
                    raw = line.split("=", 1)[1].strip()
                    if raw.isdigit():
                        done = int(raw) / 1_000_000 / duration
                        on_progress(min(max(done, 0.0), 1.0))
            proc.stdout.close()
        proc.wait()
        pump.join(timeout=10)
    finally:
        if on_pid:
            on_pid(proc.pid, False)

    return proc.returncode, "".join(tail).strip()


def result_path(src: Path, codec: Codec) -> Path:
    ext = ".mov" if codec.key == "prores" else ".mp4"
    return src.with_name(f"{src.stem}{RESULT_SUFFIX}{ext}")


def is_result_name(path: Path) -> bool:
    return path.stem.endswith(RESULT_SUFFIX)


def _pix_fmt_for(info: MediaInfo, codec: Codec) -> str | None:
    wide_or_deep = info.is_10bit_or_422

    if codec.key == "prores":
        return "p210le"
    if codec.key == "av1":
        return "yuv420p10le" if wide_or_deep else "yuv420p"
    return "p010le" if wide_or_deep else "yuv420p"


def audio_args(info: MediaInfo, audio_mode: str) -> list[str]:
    if not info.audio_codec:
        return ["-an"]
    if audio_mode == AUDIO_ORIGINAL:
        return ["-c:a", "copy"]
    if info.audio_codec == "aac" and info.audio_channels <= AUDIO_COPY_MAX_CHANNELS:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ac", AUDIO_DOWNMIX_CHANNELS]


def error_summary(stderr: str, limit: int = 2) -> str:
    lines = [
        line.strip() for line in (stderr or "").splitlines()
        if line.strip() and not any(noise in line for noise in FFMPEG_NOISE_MARKS)
    ]
    if not lines:
        return "без сообщения"

    hits = [ln for ln in lines if any(m in ln.lower() for m in FFMPEG_ERROR_MARKS)]
    picked = hits[:limit] if hits else lines[-limit:]
    return " ".join(picked)


def build_command(
    src: Path,
    dst: Path,
    info: MediaInfo,
    codec: Codec,
    target_bitrate: int,
    *,
    audio_mode: str = AUDIO_ORIGINAL,
    hw_decode: bool = True,
    progress: bool = True,
) -> list[str]:
    args: list[str] = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error"]
    if progress:
        args += ["-progress", "pipe:1", "-nostats"]

    if hw_decode_used(info, hw_decode):
        args += ["-hwaccel", "videotoolbox"]

    args += ["-i", str(src)]

    pix_fmt = _pix_fmt_for(info, codec)
    if pix_fmt:
        args += ["-pix_fmt", pix_fmt]

    args += ["-c:v", codec.encoder]

    if codec.key == "prores":
        args += ["-profile:v", PRORES_PROFILE_HQ]
    elif codec.key == "av1":
        args += ["-preset", codec.preset, "-b:v", str(int(target_bitrate))]
    else:
        args += ["-b:v", str(int(target_bitrate))]
        args += ["-tag:v", "hvc1"]
        if pix_fmt == "p010le":
            args += ["-profile:v", "main10"]

    args += info.color_args()

    args += audio_args(info, audio_mode)

    args += ["-map_metadata", "0", "-movflags", "+faststart" if codec.key != "prores" else "+write_colr"]
    args += [str(dst)]
    return args


def carry_timestamps(src: Path, dst: Path) -> None:
    st = src.stat()
    os.utime(dst, (st.st_atime, st.st_mtime))


@dataclass
class EncodeResult:
    ok: bool
    dst: Path
    stderr: str = ""
    used_cpu_decode: bool = False
    hw_decode_broke: bool = False
    audio_mode: str = AUDIO_ORIGINAL


def hw_decode_used(info: MediaInfo, hw_decode: bool) -> bool:
    return hw_decode and not info.is_10bit_or_422 and hw_decode_possible(info.codec)


def hw_decode_broke(stderr: str) -> bool:
    return any(mark in stderr for mark in FFMPEG_HW_DECODE_FAILURE_MARKS)


def decode_looks_broken(stderr: str) -> bool:
    text = (stderr or "").lower()
    return any(hint in text for hint in FFMPEG_DECODE_TROUBLE_HINTS)


def run_encode(
    src: Path,
    dst: Path,
    info: MediaInfo,
    codec: Codec,
    target_bitrate: int,
    *,
    audio_mode: str = AUDIO_ORIGINAL,
    on_progress: Callable[[float], None] | None = None,
    on_pid: Callable[[int, bool], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_retry: Callable[[str], None] | None = None,
    hw_decode: bool = True,
) -> EncodeResult:
    hw_real = hw_decode_used(info, hw_decode)
    attempts = [True, False] if hw_real else [hw_decode]
    last: EncodeResult | None = None

    for use_hw in attempts:
        cmd = build_command(
            src, dst, info, codec, target_bitrate,
            audio_mode=audio_mode,
            hw_decode=use_hw, progress=on_progress is not None,
        )
        code, stderr_text = run_with_progress(
            cmd,
            duration=info.duration,
            on_progress=on_progress,
            on_pid=on_pid,
        )

        on_hw = use_hw and hw_real
        broke = on_hw and hw_decode_broke(stderr_text)

        last = EncodeResult(
            ok=(code == 0 and not broke
                and dst.exists() and dst.stat().st_size > 0),
            dst=dst,
            stderr=stderr_text,
            used_cpu_decode=hw_real and not on_hw,
            hw_decode_broke=broke,
            audio_mode=audio_mode,
        )
        if last.ok:
            if on_progress:
                on_progress(1.0)
            return last

        if dst.exists():
            dst.unlink()

        if should_stop is not None and should_stop():
            break

        if use_hw and not (broke or decode_looks_broken(stderr_text)):
            break

        if on_hw and on_retry is not None:
            on_retry(
                "аппаратный декодер сломался" if broke
                else f"декодер не справился: {error_summary(stderr_text)}"
            )

    assert last is not None
    return last
