# Third-party components

BitShift itself is MIT-licensed — see [LICENSE](LICENSE). This file lists everything else
that ships inside the downloads, and under what terms.

*По-русски → [THIRD-PARTY.ru.md](THIRD-PARTY.ru.md)*

---

## macOS — `BitShift-macOS.zip`

The macOS app is self-contained, so the archive carries third-party binaries with it.

### FFmpeg — **GPL v2 or later**

`ffmpeg` and `ffprobe` **9.0** are bundled inside `BitShift.app/Contents/Resources/bin/`.

The binaries come from the arm64 builds published at
[osxexperts.net](https://www.osxexperts.net/) and are configured with `--enable-gpl`
together with `libx264`, `libx265` and `libvidstab`. **A build with those options is
covered by the GNU General Public License, version 2 or later** — not the LGPL that a
default FFmpeg build carries.

- License text: [COPYING.GPLv2](COPYING.GPLv2) — a copy also ships inside the app,
  next to this file, at `BitShift.app/Contents/Resources/`
- FFmpeg's own licensing notes: <https://ffmpeg.org/legal.html>
- Upstream source for FFmpeg 9.0: <https://ffmpeg.org/releases/ffmpeg-9.0.tar.xz>
  (also <https://github.com/FFmpeg/FFmpeg/tree/n9.0>)

The binaries are not built here — they are the published arm64 builds from osxexperts.net,
statically linked against x264, x265, libaom and SVT-AV1. The upstream tarball above is
FFmpeg's own source, not that packager's exact build tree; if you need the precise
corresponding source for those binaries, ask their author. BitShift neither patches nor
recompiles them.

**This does not make BitShift itself GPL.** The app never links against `libav*`; it runs
`ffmpeg` and `ffprobe` as separate processes, the same way a shell script would. The
application code stays under the MIT license above. What the GPL does require is that the
FFmpeg binaries are distributed with notice of their license and a way to get their
source — which is what this file is for.

Exact copies of the binaries in any release are pinned by SHA-256 in
[`mac/build.py`](mac/build.py) (`TOOL_HASHES`), so you can verify what you downloaded.

### Python and the packages inside the app

The bundle carries its own interpreter and libraries, all under permissive licenses.
The list is read off the bundle itself (`Contents/Resources/lib/python314.zip`) rather
than off `requirements.txt`, because py2app pulls in transitive dependencies too.

| Component | Version | License |
|---|---|---|
| CPython | 3.14.7 | Python Software Foundation License |
| pywebview | 6.2.1 | BSD 3-Clause |
| bottle | 0.13.4 | MIT |
| proxy_tools | 0.1.0 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| pyobjc-core | 12.2.2 | MIT |
| pyobjc-framework-Cocoa | 12.2.2 | MIT |
| pyobjc-framework-Quartz | 12.2.2 | MIT |
| pyobjc-framework-WebKit | 12.2.2 | MIT |
| pyobjc-framework-UniformTypeIdentifiers | 12.2.2 | MIT |

py2app 0.28.10 (MIT) builds the bundle but does not ship inside it.

---

## Windows — `BitShift.exe`

**Nothing third-party is distributed here.** The exe is the application only; FFmpeg is
*not* bundled. You install it yourself:

```
winget install Gyan.FFmpeg
```

Whatever license that build carries is between you and its packager — BitShift neither
ships nor redistributes it.

---

## A note on scope

This is a personal tool published in the open, not a commercial product with a legal
department behind it. The information above is read straight off the build flags of the
binaries being shipped (`ffmpeg -version`), and reflects the ordinary reading of those
licenses. If you spot something wrong or missing, please open an issue — corrections are
welcome.
