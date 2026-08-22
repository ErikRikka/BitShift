from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import FFMPEG_STDERR_TAIL_LINES
from core.encode import (
    build_command, ffmpeg_path, hw_decode_possible, run_with_progress,
)
from core.modes import CODEC_AV1, CODEC_HEVC
from core.probe import MediaInfo, probe
from core.verify import full_decode

DEADLINE = 90.0

CLIP_SECONDS = 20.0


def make_av1_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=640x480:rate=24:duration={CLIP_SECONDS:g}",
            "-c:v", "libsvtav1", "-preset", "10", "-b:v", "1M", str(path),
        ],
        check=True,
    )


def with_deadline(fn, seconds: float = DEADLINE):
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=seconds)
    if worker.is_alive():
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("value")


def case_noisy_stderr_does_not_hang(work: Path) -> list[str]:
    clip = work / "av1.mp4"
    make_av1_clip(clip)

    done, result = with_deadline(
        lambda: full_decode(clip, hw=True, duration=CLIP_SECONDS,
                            on_progress=lambda _: None)
    )

    problems: list[str] = []
    if not done:
        problems.append(
            f"ЗАВИС: декод не завершился за {DEADLINE:.0f}с — stderr не вычерпывается"
        )
        return problems

    ok, err = result
    if ok:
        problems.append("декод с невозможным аппаратным ускорением отчитался успехом")
    if "hardware accelerated AV1" not in err and "videotoolbox" not in err:
        problems.append(f"в stderr не та ошибка: {err[:120]!r}")
    return problems


def case_stderr_is_capped(work: Path) -> list[str]:
    clip = work / "av1.mp4"
    make_av1_clip(clip)

    args = [
        ffmpeg_path(), "-hide_banner", "-v", "error",
        "-hwaccel", "videotoolbox", "-i", str(clip), "-f", "null", "-",
    ]
    done, result = with_deadline(lambda: run_with_progress(args))
    if not done:
        return [f"ЗАВИС на {DEADLINE:.0f}с"]

    _, err = result
    lines = err.splitlines()
    problems: list[str] = []
    if len(lines) > FFMPEG_STDERR_TAIL_LINES:
        problems.append(f"stderr не ограничен: {len(lines)} строк")
    if not lines:
        problems.append("stderr потерялся целиком")
    return problems


def case_av1_never_asks_for_hw(work: Path) -> list[str]:
    clip = work / "av1.mp4"
    make_av1_clip(clip)
    info = probe(clip)

    problems: list[str] = []
    if info.codec != "av1":
        return [f"клип получился не av1, а {info.codec}"]

    if hw_decode_possible("av1"):
        problems.append("av1 считается пригодным для аппаратного декода")
    if not hw_decode_possible("h264"):
        problems.append("h264 объявлен непригодным для аппаратного декода")

    cmd = build_command(clip, work / "out.mp4", info, CODEC_HEVC, 2_000_000,
                        hw_decode=True, progress=False)
    if "-hwaccel" in cmd:
        problems.append(f"для AV1-исходника просят -hwaccel: {' '.join(cmd)}")

    h264 = MediaInfo(path=clip, codec="h264", duration=10, width=1920,
                     height=1080, fps=25, pix_fmt="yuv420p")
    cmd_h264 = build_command(clip, work / "out2.mp4", h264, CODEC_AV1, 2_000_000,
                             hw_decode=True, progress=False)
    if "-hwaccel" not in cmd_h264:
        problems.append("для h264 аппаратный декод перестали просить")
    return problems


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-дедлока-"))
    try:
        problems = fn(work)
    except Exception as exc:
        problems = [f"исключение: {exc!r}"]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if problems:
        print(f"✗ {name}")
        for p in problems:
            print(f"    {p}")
        return False
    print(f"✓ {name}")
    return True


def main() -> int:
    cases = [
        ("болтливый stderr не вешает проверку", case_noisy_stderr_does_not_hang),
        ("stderr ограничен по объёму", case_stderr_is_capped),
        ("у AV1 аппаратный декод не запрашивается", case_av1_never_asks_for_hw),
    ]
    print("Дедлок на непрочитанном stderr\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
