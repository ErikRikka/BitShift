from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import AppKit
import Quartz

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "bitshift-source.png"
DEFAULT_ICNS = ROOT / "BitShift.app" / "Contents" / "Resources" / "icon.icns"

MASTER = 1024
ARTWORK_SHARE = 0.805
CORNER_SHARE = 0.2237
EDGE_JUMP = 0.08
SIZES = (16, 32, 128, 256, 512)


def load_rep(path: Path) -> AppKit.NSBitmapImageRep:
    image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        raise SystemExit(f"не читается: {path}")
    return AppKit.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())


def luminance(rep, x: int, y: int) -> float:
    c = rep.colorAtX_y_(x, y)
    return (0.299 * c.redComponent()
            + 0.587 * c.greenComponent()
            + 0.114 * c.blueComponent())


def outer_edges(values: list[float]) -> tuple[int, int]:
    n = len(values)
    low = next((i for i in range(n - 1) if abs(values[i + 1] - values[i]) > EDGE_JUMP), 0)
    high = next((i for i in range(n - 2, 0, -1) if abs(values[i + 1] - values[i]) > EDGE_JUMP), n - 1)
    return low, high + 1


def tile_bounds(rep) -> tuple[int, int, int, int]:
    w, h = rep.pixelsWide(), rep.pixelsHigh()
    left, right = outer_edges([luminance(rep, x, h // 2) for x in range(w)])
    top, bottom = outer_edges([luminance(rep, w // 2, y) for y in range(h)])
    return left, top, right - left, bottom - top


def render(rep, bounds: tuple[int, int, int, int]) -> AppKit.NSBitmapImageRep:
    x, y, w, h = bounds
    cropped = Quartz.CGImageCreateWithImageInRect(
        rep.CGImage(), Quartz.CGRectMake(x, y, w, h)
    )

    canvas = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, MASTER, MASTER, 8, 4, True, False,
        AppKit.NSCalibratedRGBColorSpace, 0, 0,
    )

    context = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(canvas)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(context)

    side = MASTER * ARTWORK_SHARE
    inset = (MASTER - side) / 2
    rect = AppKit.NSMakeRect(inset, inset, side, side)
    radius = side * CORNER_SHARE

    AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        rect, radius, radius
    ).addClip()
    Quartz.CGContextDrawImage(context.CGContext(), rect, cropped)

    AppKit.NSGraphicsContext.restoreGraphicsState()
    return canvas


def write_png(rep, path: Path) -> None:
    data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    path.write_bytes(bytes(data))


def build_iconset(master: Path, iconset: Path) -> None:
    iconset.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        for scale, name in ((1, f"icon_{size}x{size}.png"),
                            (2, f"icon_{size}x{size}@2x.png")):
            px = size * scale
            subprocess.run(
                ["sips", "-z", str(px), str(px), str(master), "--out", str(iconset / name)],
                check=True, capture_output=True,
            )


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ICNS
    if not SOURCE.exists():
        raise SystemExit(f"нет исходника {SOURCE}")

    rep = load_rep(SOURCE)
    bounds = tile_bounds(rep)
    print(f"плитка найдена: x={bounds[0]} y={bounds[1]} {bounds[2]}×{bounds[3]}")

    canvas = render(rep, bounds)
    work = ROOT / "build" / "icon"
    work.mkdir(parents=True, exist_ok=True)
    master = work / "master.png"
    write_png(canvas, master)

    iconset = work / "icon.iconset"
    build_iconset(master, iconset)

    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    print(f"готово: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
