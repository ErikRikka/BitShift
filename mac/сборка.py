#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import APP_NAME, BUNDLED_TOOLS_SUBDIR

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
TOOLS = BUILD / BUNDLED_TOOLS_SUBDIR
DIST = ROOT / "dist"

TOOL_SOURCES = {
    "ffmpeg": "https://www.osxexperts.net/ffmpeg711arm.zip",
    "ffprobe": "https://www.osxexperts.net/ffprobe711arm.zip",
}

TOOL_HASHES = {
    "ffmpeg": "011221d75eae36943b5a6a28f70e25928cfb5602fe616d06da0a3b9b55ff6b75",
    "ffprobe": "ae77d6751f4db81098a11dcc966a8d098925411430169475c8f8a7bfad76188b",
}

REQUIRED_ENCODERS = (
    "hevc_videotoolbox",
    "prores_videotoolbox",
    "h264_videotoolbox",
    "libsvtav1",
)


def сообщить(text: str) -> None:
    print(text, flush=True)


def скачать_инструменты() -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    for name, url in TOOL_SOURCES.items():
        target = TOOLS / name
        if target.is_file():
            сообщить(f"  {name}: уже скачан")
            continue
        сообщить(f"  {name}: качаю…")
        archive = BUILD / f"{name}.zip"
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if Path(member).name == name:
                    with zf.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break
        archive.unlink()
        if not target.is_file():
            sys.exit(f"в архиве {url} нет файла {name}")

        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != TOOL_HASHES[name]:
            target.unlink()
            sys.exit(
                f"{name} с {url} не совпал с ожидаемым отпечатком.\n"
                f"  ожидался: {TOOL_HASHES[name]}\n"
                f"  получен:  {digest}\n"
                "Если версия по ссылке обновилась — сверьте её у издателя "
                "и впишите новый отпечаток в TOOL_HASHES."
            )

        target.chmod(0o755)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target)],
                       capture_output=True)


def проверить_инструменты() -> None:
    for name in TOOL_SOURCES:
        path = TOOLS / name
        arch = subprocess.run(["lipo", "-archs", str(path)],
                              capture_output=True, text=True).stdout.split()
        if "arm64" not in arch:
            sys.exit(f"{name}: не arm64, а {arch}")
        version = subprocess.run([str(path), "-version"],
                                 capture_output=True, text=True)
        if version.returncode != 0:
            sys.exit(f"{name} не запускается: {version.stderr[:200]}")
        сообщить(f"  {name}: arm64, {version.stdout.splitlines()[0][:40]}")

    for encoder in REQUIRED_ENCODERS:
        check = subprocess.run([str(TOOLS / "ffmpeg"), "-hide_banner",
                                "-h", f"encoder={encoder}"],
                               capture_output=True, text=True)
        if check.returncode != 0 or "Encoder " not in check.stdout:
            sys.exit(f"во встроенном ffmpeg нет энкодера {encoder}")
    сообщить(f"  энкодеры на месте: {', '.join(REQUIRED_ENCODERS)}")


def собрать_иконку() -> None:
    icns = BUILD / "icon.icns"
    subprocess.run([sys.executable, str(ROOT / "иконка.py"), str(icns)],
                   check=True, capture_output=True)
    сообщить("  иконка: собрана из bitshift-source.png")


def собрать_бандл() -> Path:
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(ROOT / "build" / "bdist.macosx", ignore_errors=True)
    result = subprocess.run([sys.executable, str(ROOT / "setup.py"), "py2app"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        sys.exit("py2app не собрал бандл")
    app = DIST / f"{APP_NAME}.app"
    if not app.is_dir():
        sys.exit("бандл не появился в dist/")
    return app


def проверить_бандл(app: Path) -> None:
    ffmpeg = app / "Contents" / "Resources" / BUNDLED_TOOLS_SUBDIR / "ffmpeg"
    index = app / "Contents" / "Resources" / "ui" / "index.html"
    launcher = app / "Contents" / "MacOS" / APP_NAME

    for path, что in ((ffmpeg, "встроенный ffmpeg"), (index, "интерфейс"),
                      (launcher, "запускатор")):
        if not path.exists():
            sys.exit(f"в бандле нет: {что} ({path})")

    version = subprocess.run([str(ffmpeg), "-version"],
                             capture_output=True, text=True)
    if version.returncode != 0:
        sys.exit("встроенный ffmpeg не запускается")

    size = subprocess.run(["du", "-sh", str(app)], capture_output=True,
                          text=True).stdout.split()[0]
    сообщить(f"  всё на месте, размер {size}")


def main() -> int:
    BUILD.mkdir(exist_ok=True)

    сообщить("Инструменты:")
    скачать_инструменты()
    проверить_инструменты()

    сообщить("Иконка:")
    собрать_иконку()

    сообщить("Сборка:")
    app = собрать_бандл()

    сообщить("Проверка:")
    проверить_бандл(app)

    сообщить(f"\nГотово: {app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
