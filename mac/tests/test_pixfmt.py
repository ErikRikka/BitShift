from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.encode import _pix_fmt_for, build_command
from core.modes import CODEC_AV1, CODEC_HEVC, CODEC_PRORES
from core.probe import MediaInfo, probe


def info_with(pix_fmt: str) -> MediaInfo:
    return MediaInfo(path=Path("x.mp4"), pix_fmt=pix_fmt, codec="h264",
                      width=1920, height=1080, fps=25.0, bit_rate=10_000_000)


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-формата-"))
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


def case_hevc_keeps_422_chroma(_work: Path) -> list[str]:
    problems: list[str] = []
    cases = [
        ("yuv420p", "yuv420p"),
        ("yuv420p10le", "p010le"),
        ("yuv422p", "p210le"),
        ("yuv422p10le", "p210le"),
        ("yuv444p10le", "p210le"),
    ]
    for src_fmt, expected in cases:
        got = _pix_fmt_for(info_with(src_fmt), CODEC_HEVC)
        if got != expected:
            problems.append(f"{src_fmt} -> {got}, ждали {expected}")
    return problems


def case_av1_still_never_gets_422(_work: Path) -> list[str]:
    problems: list[str] = []
    if _pix_fmt_for(info_with("yuv422p10le"), CODEC_AV1) != "yuv420p10le":
        problems.append("AV1 не должен получать 4:2:2 — libsvtav1 его не умеет")
    if _pix_fmt_for(info_with("yuv420p"), CODEC_AV1) != "yuv420p":
        problems.append("обычный 8-битный источник для AV1 сломался")
    return problems


def case_prores_unaffected(_work: Path) -> list[str]:
    if _pix_fmt_for(info_with("yuv420p"), CODEC_PRORES) != "p210le":
        return ["ProRes должен всегда просить p210le, независимо от источника"]
    return []


def case_hevc_command_gets_matching_profile(_work: Path) -> list[str]:
    problems: list[str] = []
    for src_fmt, expected_profile in (
        ("yuv422p10le", "main42210"),
        ("yuv420p10le", "main10"),
        ("yuv420p", None),
    ):
        cmd = build_command(
            Path("src.mp4"), Path("dst.mp4"), info_with(src_fmt), CODEC_HEVC,
            10_000_000, progress=False,
        )
        if expected_profile is None:
            if "-profile:v" in cmd:
                problems.append(f"{src_fmt}: лишний -profile:v в команде: {cmd}")
            continue
        if "-profile:v" not in cmd:
            problems.append(f"{src_fmt}: нет -profile:v в команде")
            continue
        got = cmd[cmd.index("-profile:v") + 1]
        if got != expected_profile:
            problems.append(f"{src_fmt}: профиль {got}, ждали {expected_profile}")
    return problems


def case_real_hevc_422_encode_stays_422(work: Path) -> list[str]:
    src = work / "источник.mov"
    dst = work / "результат.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "testsrc2=size=960x540:rate=25:duration=2",
            "-pix_fmt", "yuv422p10le", "-c:v", "libx264", "-profile:v", "high422",
            "-b:v", "15M", str(src),
        ],
        check=True,
    )

    info = probe(src)
    if not info.is_wide_chroma:
        return [f"подготовка не удалась: исходник не распознан как 4:2:2 ({info.pix_fmt})"]

    cmd = build_command(src, dst, info, CODEC_HEVC, 8_000_000, progress=False)
    subprocess.run(cmd, check=True)

    result = probe(dst)
    problems: list[str] = []
    if "422" not in (result.pix_fmt or ""):
        problems.append(f"результат потерял 4:2:2: pix_fmt={result.pix_fmt}")
    return problems


def main() -> int:
    cases = [
        ("HEVC сохраняет 4:2:2, если он есть в источнике", case_hevc_keeps_422_chroma),
        ("AV1 всё равно не получает 4:2:2 — не умеет", case_av1_still_never_gets_422),
        ("ProRes не задет правкой", case_prores_unaffected),
        ("команда ffmpeg берёт нужный профиль", case_hevc_command_gets_matching_profile),
        ("реальное кодирование 4:2:2 остаётся 4:2:2", case_real_hevc_422_encode_stays_422),
    ]
    print("Автовыбор 4:2:2 (CLAUDE.md §7, §22)\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
