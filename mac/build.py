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

from core.config import APP_NAME, BUNDLE_REQUIRED, BUNDLED_TOOLS_SUBDIR
from core.modes import CODECS

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
TOOLS = BUILD / BUNDLED_TOOLS_SUBDIR
DIST = ROOT / "dist"

TOOL_SOURCES = {
    "ffmpeg": "https://www.osxexperts.net/ffmpeg9arm.zip",
    "ffprobe": "https://www.osxexperts.net/ffprobe9arm.zip",
}

TOOL_HASHES = {
    "ffmpeg": "591260c945d0eef150e3bf82b0ef988bd36a9cecc18ff05d6679617159f0a95e",
    "ffprobe": "e11c17e8200b3ee4c4c186d245e2b4053f01d56957336c1817fca0b997469106",
}

REQUIRED_ENCODERS = tuple(sorted({codec.encoder for codec in CODECS.values()}))


def say(text: str) -> None:
    print(text, flush=True)


def fetch_tools() -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    for name, url in TOOL_SOURCES.items():
        target = TOOLS / name
        if target.is_file():
            if hashlib.sha256(target.read_bytes()).hexdigest() == TOOL_HASHES[name]:
                say(f"  {name}: уже скачан")
                continue
            say(f"  {name}: отпечаток не сошёлся, качаю заново…")
            target.unlink()
        else:
            say(f"  {name}: качаю…")
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


def check_tools() -> None:
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
        say(f"  {name}: arm64, {version.stdout.splitlines()[0][:40]}")

    for encoder in REQUIRED_ENCODERS:
        check = subprocess.run([str(TOOLS / "ffmpeg"), "-hide_banner",
                                "-h", f"encoder={encoder}"],
                               capture_output=True, text=True)
        if check.returncode != 0 or "Encoder " not in check.stdout:
            sys.exit(f"во встроенном ffmpeg нет энкодера {encoder}")
    say(f"  энкодеры на месте: {', '.join(REQUIRED_ENCODERS)}")


def make_icon() -> None:
    icns = BUILD / "icon.icns"
    subprocess.run([sys.executable, str(ROOT / "icon.py"), str(icns)],
                   check=True, capture_output=True)
    say("  иконка: собрана из bitshift-source.png")


def make_bundle() -> Path:
    shutil.rmtree(DIST, ignore_errors=True)
    for stale in BUILD.glob("bdist.macosx*"):
        shutil.rmtree(stale, ignore_errors=True)
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


def check_bundle(app: Path) -> None:
    resources = app / "Contents" / "Resources"
    ffmpeg = resources / BUNDLED_TOOLS_SUBDIR / "ffmpeg"
    launcher = app / "Contents" / "MacOS" / APP_NAME

    missing = [rel for rel in BUNDLE_REQUIRED if not (resources / rel).exists()]
    if not launcher.exists():
        missing.append(f"MacOS/{APP_NAME}")
    if missing:
        sys.exit("в бандле нет: " + ", ".join(missing))

    version = subprocess.run([str(ffmpeg), "-version"],
                             capture_output=True, text=True)
    if version.returncode != 0:
        sys.exit("встроенный ffmpeg не запускается")

    size = subprocess.run(["du", "-sh", str(app)], capture_output=True,
                          text=True).stdout.split()[0]
    say(f"  всё на месте, размер {size}")


def main() -> int:
    BUILD.mkdir(exist_ok=True)

    say("Инструменты:")
    fetch_tools()
    check_tools()

    say("Иконка:")
    make_icon()

    say("Сборка:")
    app = make_bundle()

    say("Проверка:")
    check_bundle(app)

    say(f"\nГотово: {app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
