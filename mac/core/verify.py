from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .encode import ffmpeg_path, hw_decode_possible, run_with_progress
from .modes import Codec
from .config import (
    DURATION_TOLERANCE_MIN,
    DURATION_TOLERANCE_RATIO,
    FRAME_TOLERANCE,
    FRAME_TOLERANCE_RATIO,
    VERIFY_WEIGHT_DECODE,
    VERIFY_WEIGHT_FRAMES,
    VERIFY_WEIGHT_PROBE,
)
from .probe import MediaInfo, ProbeError, count_frames, frames_countable, probe


@dataclass
class VerifyReport:
    ok: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    decoded_on_cpu: bool = False
    vmaf: float | None = None

    def fail(self, name: str, message: str) -> "VerifyReport":
        self.checks[name] = False
        self.problems.append(message)
        return self

    def passed(self, name: str) -> "VerifyReport":
        self.checks[name] = True
        return self


def duration_tolerance(duration: float) -> float:
    return max(duration * DURATION_TOLERANCE_RATIO, DURATION_TOLERANCE_MIN)


def frame_tolerance(count: int) -> int:
    return max(round(count * FRAME_TOLERANCE_RATIO), FRAME_TOLERANCE)


def full_decode(
    path: Path,
    *,
    hw: bool,
    duration: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    on_pid: Callable[[int, bool], None] | None = None,
) -> tuple[bool, str]:
    args = [ffmpeg_path(), "-hide_banner", "-v", "error"]
    if on_progress is not None and duration > 0:
        args += ["-progress", "pipe:1", "-nostats"]
    if hw:
        args += ["-hwaccel", "videotoolbox"]
    args += ["-i", str(path), "-f", "null", "-"]

    code, err = run_with_progress(
        args, duration=duration, on_progress=on_progress, on_pid=on_pid,
    )
    ok = code == 0 and not err
    if ok and on_progress is not None:
        on_progress(1.0)
    return ok, err


def measure_vmaf(
    src: Path,
    dst: Path,
    *,
    on_pid: Callable[[int, bool], None] | None = None,
) -> float | None:
    log_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    log_path = Path(log_file.name)
    log_file.close()
    try:
        filt = (
            "[0:v]scale=iw:ih:flags=bicubic,format=yuv420p[dist];"
            "[1:v]scale=iw:ih:flags=bicubic,format=yuv420p[ref];"
            f"[dist][ref]libvmaf=log_path={log_path}:log_fmt=json"
        )
        args = [
            ffmpeg_path(), "-hide_banner", "-v", "error",
            "-i", str(dst), "-i", str(src),
            "-lavfi", filt, "-f", "null", "-",
        ]
        code, _ = run_with_progress(args, on_pid=on_pid)
        if code != 0:
            return None
        data = json.loads(log_path.read_text())
        return round(float(data["pooled_metrics"]["vmaf"]["mean"]), 1)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    finally:
        log_path.unlink(missing_ok=True)


def verify_pair(
    src_info: MediaInfo,
    dst: Path,
    codec: Codec,
    *,
    src_frames: int | None = None,
    measure_quality: bool = False,
    on_progress: Callable[[float], None] | None = None,
    on_pid: Callable[[int, bool], None] | None = None,
) -> VerifyReport:
    report = VerifyReport()

    def step(done: float) -> None:
        if on_progress is not None:
            on_progress(min(max(done, 0.0), 1.0))

    if not dst.exists() or dst.stat().st_size == 0:
        return report.fail("файл", "результата нет или он пустой")

    try:
        dst_info = probe(dst)
    except ProbeError as exc:
        return report.fail("файл", f"результат не читается: {exc}")

    step(VERIFY_WEIGHT_PROBE)

    if dst_info.codec != codec.probe_name:
        report.fail(
            "кодек",
            f"кодек результата {dst_info.codec or '?'}, ожидался {codec.probe_name}",
        )
    else:
        report.passed("кодек")

    tol = duration_tolerance(src_info.duration)
    delta = abs(dst_info.duration - src_info.duration)
    if src_info.duration <= 0:
        report.fail("длительность", "у оригинала неизвестна длительность")
    elif delta > tol:
        report.fail(
            "длительность",
            f"длительность разошлась на {delta:.2f}с "
            f"({src_info.duration:.2f} → {dst_info.duration:.2f}, допуск {tol:.2f}с)",
        )
    else:
        report.passed("длительность")

    if frames_countable(src_info.path) and frames_countable(dst):
        try:
            if src_frames is not None:
                a = src_frames
                step(VERIFY_WEIGHT_PROBE + VERIFY_WEIGHT_FRAMES / 2)
            else:
                a = count_frames(src_info.path, on_pid=on_pid)
                step(VERIFY_WEIGHT_PROBE + VERIFY_WEIGHT_FRAMES / 2)
            b = count_frames(dst, on_pid=on_pid)
        except ProbeError as exc:
            report.fail("кадры", f"не удалось посчитать кадры: {exc}")
        else:
            frame_tol = frame_tolerance(a)
            if abs(a - b) > frame_tol:
                report.fail(
                    "кадры",
                    f"кадров {a} → {b}, разница {abs(a - b)} (допуск {frame_tol})",
                )
            else:
                report.passed("кадры")
    else:
        report.checks["кадры"] = True

    step(VERIFY_WEIGHT_PROBE + VERIFY_WEIGHT_FRAMES)

    decode_seconds = dst_info.duration or src_info.duration
    base = VERIFY_WEIGHT_PROBE + VERIFY_WEIGHT_FRAMES

    def decode_progress(done: float) -> None:
        step(base + done * VERIFY_WEIGHT_DECODE)

    hw = hw_decode_possible(dst_info.codec)

    ok, err = full_decode(
        dst, hw=hw, duration=decode_seconds,
        on_progress=decode_progress, on_pid=on_pid,
    )
    if not ok and hw:
        ok_cpu, err_cpu = full_decode(
            dst, hw=False, duration=decode_seconds,
            on_progress=decode_progress, on_pid=on_pid,
        )
        report.decoded_on_cpu = True
        if ok_cpu:
            report.passed("декод")
        else:
            report.fail("декод", f"результат не декодируется: {err_cpu[:300] or err[:300]}")
    elif not ok:
        report.fail("декод", f"результат не декодируется: {err[:300]}")
    else:
        report.passed("декод")

    report.ok = all(report.checks.values())

    if report.ok and measure_quality:
        report.vmaf = measure_vmaf(src_info.path, dst, on_pid=on_pid)

    return report
