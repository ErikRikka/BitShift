from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.encode import build_command, quality_overshot, run_encode
from core.modes import CODEC_AV1, CODEC_HEVC, MODES_BY_KEY, quality_value
from core.probe import MediaInfo, probe


def info_with(width: int, height: int, pix_fmt: str = "yuv420p") -> MediaInfo:
    return MediaInfo(path=Path("x.mp4"), pix_fmt=pix_fmt, codec="h264",
                      width=width, height=height, fps=25.0, bit_rate=10_000_000)


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-качества-"))
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


def case_quality_value_picks_by_resolution_and_mode(_work: Path) -> list[str]:
    problems: list[str] = []
    arc = MODES_BY_KEY["arc"]
    slog = MODES_BY_KEY["slog"]
    old = MODES_BY_KEY["old"]

    if quality_value(arc, 3840, 2160) != 58:
        problems.append(f"arc 4K: {quality_value(arc, 3840, 2160)}, ждали 58")
    if quality_value(arc, 1920, 1080) != 70:
        problems.append(f"arc 1080p: {quality_value(arc, 1920, 1080)}, ждали 70")
    if quality_value(slog, 3840, 2160) != 66:
        problems.append(f"slog 4K: {quality_value(slog, 3840, 2160)}, ждали 66")
    if quality_value(slog, 1920, 1080) != 66:
        problems.append(f"slog 1080p: {quality_value(slog, 1920, 1080)}, ждали 66")
    if quality_value(old, 3840, 2160) is not None:
        problems.append("«старое видео» не откалибровано — должно оставаться None")
    if quality_value(arc, 2160, 3840) != 58:
        problems.append("вертикальный 4K (2160×3840) должен определяться по длинной стороне")
    return problems


def case_build_command_quality_beats_bitrate(_work: Path) -> list[str]:
    cmd = build_command(
        Path("src.mp4"), Path("dst.mp4"), info_with(3840, 2160), CODEC_HEVC,
        20_000_000, quality=58, progress=False,
    )
    problems: list[str] = []
    if "-q:v" not in cmd or cmd[cmd.index("-q:v") + 1] != "58":
        problems.append(f"нет -q:v 58 в команде: {cmd}")
    if "-b:v" in cmd:
        problems.append(f"-b:v не должно быть рядом с -q:v: {cmd}")
    return problems


def case_av1_ignores_quality(_work: Path) -> list[str]:
    cmd = build_command(
        Path("src.mp4"), Path("dst.mp4"), info_with(3840, 2160), CODEC_AV1,
        20_000_000, quality=58, progress=False,
    )
    if "-q:v" in cmd:
        return [f"AV1 не должен получать -q:v: {cmd}"]
    if "-b:v" not in cmd:
        return [f"AV1 должен остаться на -b:v: {cmd}"]
    return []


def case_quality_overshot_detects_big_file(work: Path) -> list[str]:
    small = work / "мал.mp4"
    big = work / "велик.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x240:rate=25:duration=1",
         "-c:v", "libx264", "-b:v", "200k", str(small)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x240:rate=25:duration=1",
         "-c:v", "libx264", "-b:v", "5000k", str(big)],
        check=True,
    )
    problems: list[str] = []
    if quality_overshot(small, 300_000):
        problems.append("маленький файл ошибочно признан перебором")
    if not quality_overshot(big, 300_000):
        problems.append("большой файл (в разы больше цели) не пойман")
    return problems


def case_real_overshoot_falls_back_to_bitrate(work: Path) -> list[str]:
    # намеренно шумный источник + завышенное q — должно перебрать и откатиться
    src = work / "шум.mov"
    dst = work / "результат.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "mandelbrot=size=960x540:rate=25", "-t", "2",
         "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )
    info = probe(src)
    target = 1_500_000
    calls: list[str] = []

    result = run_encode(
        src, dst, info, CODEC_HEVC, target,
        quality=90,  # заведомо высокое, чтобы гарантированно перебрать
        on_quality_retry=lambda: calls.append("retry"),
    )

    problems: list[str] = []
    if not result.ok:
        return [f"кодирование не удалось: {result.stderr[:200]}"]
    if not calls:
        problems.append("откат на битрейт не сработал, хотя должен был")
    result_info = probe(dst)
    if result_info.bit_rate > target * 1.3:
        problems.append(
            f"после отката всё равно перебор: {result_info.bit_rate} > {target * 1.3}"
        )
    return problems


def main() -> int:
    cases = [
        ("quality_value подбирает по режиму и разрешению", case_quality_value_picks_by_resolution_and_mode),
        ("команда берёт -q:v вместо -b:v", case_build_command_quality_beats_bitrate),
        ("AV1 не получает -q:v — не поддерживает", case_av1_ignores_quality),
        ("quality_overshot ловит перебор", case_quality_overshot_detects_big_file),
        ("реальный перебор откатывается на битрейт", case_real_overshoot_falls_back_to_bitrate),
    ]
    print("Кодирование по качеству (CLAUDE.md §23)\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
