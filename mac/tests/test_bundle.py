from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.tools as tools
from core.config import APP_NAME, BUNDLED_TOOLS_SUBDIR

BUNDLE = Path(__file__).resolve().parent.parent / "dist" / f"{APP_NAME}.app"

REQUIRED_ENCODERS = (
    "hevc_videotoolbox",
    "prores_videotoolbox",
    "h264_videotoolbox",
    "libsvtav1",
)


def case_frozen_prefers_bundled_tools(work: Path) -> list[str]:
    fake = work / f"{APP_NAME}.app"
    binaries = fake / "Contents" / "Resources" / BUNDLED_TOOLS_SUBDIR
    binaries.mkdir(parents=True)
    (binaries / "ffmpeg").write_text("", encoding="utf-8")
    launcher = fake / "Contents" / "MacOS" / APP_NAME
    launcher.parent.mkdir(parents=True)
    launcher.write_text("", encoding="utf-8")

    real_executable = sys.executable
    problems: list[str] = []
    sys.frozen = "macosx_app"
    sys.executable = str(launcher)
    try:
        found = tools.tool_path("ffmpeg")
        if Path(found).resolve() != (binaries / "ffmpeg").resolve():
            problems.append(f"в бандле взят не встроенный ffmpeg: {found}")
        if tools.resources_dir() != (fake / "Contents" / "Resources").resolve():
            problems.append(f"неверный корень ресурсов: {tools.resources_dir()}")
        missing = tools.tool_path("ffprobe")
        if missing is not None and str(fake) in str(missing):
            problems.append("несуществующий инструмент выдан как встроенный")
    finally:
        del sys.frozen
        sys.executable = real_executable

    if tools.is_frozen():
        problems.append("режим бандла не сбросился")
    return problems


def case_source_run_uses_system_tools(_work: Path) -> list[str]:
    problems: list[str] = []
    found = tools.tool_path("ffmpeg")
    if not found:
        problems.append("ffmpeg не найден в системе")
    elif "dist/" in found:
        problems.append(f"при запуске из исходников взят бандл: {found}")
    return problems


def case_built_bundle_is_complete(_work: Path) -> list[str]:
    if not BUNDLE.is_dir():
        print("    бандл не собран, пропускаю (собрать: python3 build.py)")
        return []

    resources = BUNDLE / "Contents" / "Resources"
    problems: list[str] = []

    for relative in (f"{BUNDLED_TOOLS_SUBDIR}/ffmpeg", f"{BUNDLED_TOOLS_SUBDIR}/ffprobe",
                     "ui/index.html", "ui/style.css", "ui/app.js"):
        if not (resources / relative).exists():
            problems.append(f"в бандле нет {relative}")
    if problems:
        return problems

    ffmpeg = resources / BUNDLED_TOOLS_SUBDIR / "ffmpeg"
    for encoder in REQUIRED_ENCODERS:
        check = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-h", f"encoder={encoder}"],
            capture_output=True, text=True,
        )
        if check.returncode != 0 or "Encoder " not in check.stdout:
            problems.append(f"во встроенном ffmpeg нет {encoder}")

    core_dir = resources / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "core"
    if not (core_dir / "pipeline.py").exists() and not (core_dir / "pipeline.pyc").exists():
        problems.append("ядро не попало в бандл")

    signature = subprocess.run(["codesign", "-dv", str(BUNDLE)],
                               capture_output=True, text=True)
    if "adhoc" not in signature.stderr and "Signature" not in signature.stderr:
        problems.append("бандл не подписан даже локально")
    return problems


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-бандла-"))
    try:
        problems = fn(work)
    except Exception as exc:
        problems = [f"исключение: {exc!r}"]
    finally:
        import shutil
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
        ("в бандле берутся встроенные инструменты", case_frozen_prefers_bundled_tools),
        ("из исходников берутся системные", case_source_run_uses_system_tools),
        ("собранный бандл укомплектован", case_built_bundle_is_complete),
    ]
    print("Самодостаточный бандл\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
