from pathlib import Path

from setuptools import setup

from core.config import APP_NAME, APP_VERSION, BUNDLED_TOOLS_SUBDIR, NOTICE_NAMES

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"

def ui_data_files() -> list[tuple[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    for path in (ROOT / "ui").rglob("*"):
        if path.is_file():
            rel_dir = str(path.relative_to(ROOT).parent)
            groups.setdefault(rel_dir, []).append(str(path))
    return [(rel_dir, sorted(files)) for rel_dir, files in sorted(groups.items())]


TOOL_FILES = sorted(str(p) for p in (BUILD / BUNDLED_TOOLS_SUBDIR).iterdir()
                    if p.is_file())
NOTICE_FILES = [str(ROOT.parent / name) for name in NOTICE_NAMES]

PLIST = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": "local.bitshift",
    "CFBundleVersion": APP_VERSION,
    "CFBundleShortVersionString": APP_VERSION,
    "LSMinimumSystemVersion": "12.0",
    "NSHighResolutionCapable": True,
    "NSRequiresAquaSystemAppearance": False,
}

setup(
    name=APP_NAME,
    app=["app.py"],
    data_files=[*ui_data_files(), (BUNDLED_TOOLS_SUBDIR, TOOL_FILES),
                ("", NOTICE_FILES)],
    options={
        "py2app": {
            "iconfile": str(BUILD / "icon.icns"),
            "plist": PLIST,
            "packages": ["core", "webview", "objc"],
            "includes": [
                "AppKit", "Foundation", "WebKit", "Quartz",
                "PyObjCTools.AppHelper",
            ],
            "excludes": ["tkinter", "setuptools", "pip", "py2app"],
            "argv_emulation": False,
            "arch": "arm64",
        }
    },
)
