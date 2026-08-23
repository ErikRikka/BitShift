# BitShift

Video archive converter that re-encodes footage on your GPU — verifying every single file,
and never putting your originals at risk.

A real example: a folder of concert footage went from **155 GB to 27 GB**
(4K H.264 → HEVC) with no visible loss.

**Two independent builds live in this repository:** one for Windows on NVIDIA NVENC, one
for macOS on Apple VideoToolbox. They share design decisions and safety rules, but not a
single line of code.

Both interfaces are available in **English and Russian**, following your system language
and switchable inside the app.

*Читаете по-русски? → [README.ru.md](README.ru.md)*

---

## Download

| Platform | File | Requirements |
|---|---|---|
| **Windows** | [`BitShift.exe`](../../releases/latest) | NVIDIA GPU (GTX 16xx or newer), Windows 10/11, ffmpeg |
| **macOS** | [`BitShift-macOS.zip`](../../releases/latest) | Apple Silicon (M1 or newer), macOS 12+. Nothing else — ffmpeg is bundled |

Neither build is code-signed by a paid developer account, so both systems will warn you
on first launch. See the platform sections below for how to get past it.

---

## What it does

You point it at a folder — or several folders, or individual files — and it re-encodes
everything into a modern codec, checks each result, and only then offers to clear the
originals away.

**The bitrate is computed per file** from its resolution, frame rate and source bitrate.
If the expected gain is under 10%, the file is left alone rather than re-encoded for
nothing.

**You see the size estimate before you start** — "155 GB → ~27 GB, −82%" — so there are
no surprises.

**You choose what happens to audio.** Multi-track production sound can be kept intact
(every channel, original bit depth) or downmixed to stereo AAC. On a 16-channel concert
recording that is an eightfold difference in file size.

**It is built for slow drives.** If footage sits on an external HDD, files are copied to
the internal SSD one at a time, encoded there and moved back — otherwise the drive chokes
on parallel reads, which turned out to be the real bottleneck rather than the GPU.
Anything already on a fast disk is processed in place.

Plus: several folders in one run, pause and resume, time remaining estimated by data
volume rather than file count, per-file progress bars, and shutting the machine down when
everything is finished.

---

## Data safety

This is the whole reason the tool exists, and it works the same way on both platforms.

- **Originals are never overwritten.** Results are separate files with a `_v2` suffix.
- **Deletion goes to the Recycle Bin / Trash only.** There is no permanent delete
  anywhere in either app, and there will not be one.
- An original is cleared away only after its result passes **all four checks**:
  1. the result really is in the codec you asked for;
  2. duration matches within 2%;
  3. frame count matches within ±2 frames;
  4. the file decodes from start to finish without a single error.

Fail any one of them and the original stays exactly where it is.

That verification matters more than it sounds. A hardware decoder can **silently** drop
frames and still report success: on one real camera file ffmpeg exited with code 0 having
written a result that was missing a quarter of its frames, with correct duration metadata.
The frame counter is what catches that, which is why it is not "redundant".

**On your first run, untick the auto-delete box.** Look at the results yourself, then let
the tool handle the Recycle Bin.

---

## Windows

Source and binary live at the root of this repository.

**Requirements:** an NVIDIA graphics card (GTX 16xx or newer) — all encoding runs on
NVENC, so the app will not start on AMD or Intel Arc. Windows 10 or 11. ffmpeg available
in PATH:

```
winget install Gyan.FFmpeg
```

Close the terminal window afterwards so PATH refreshes.

**Running it.** Download `BitShift.exe` from [Releases](../../releases/latest) and
double-click — no installation, it is a single file. On first launch SmartScreen will
warn about an unknown publisher: **More info** → **Run anyway**.

If you would rather not trust the exe, run the source directly:

```
powershell -STA -ExecutionPolicy Bypass -File HEVC-Converter-WPF.ps1
```

**Codecs:**

| Codec | When to use it |
|---|---|
| **HEVC** | Default. Plays everywhere: Resolve, Premiere, phones, TVs |
| **AV1** | Roughly 20% smaller at the same quality, but not decoded everywhere |
| **DNxHR HQX** | Grading master: 4:2:2, 10-bit, intra. Encoded on the CPU |

**Building the exe** requires the ps2exe module
(`Install-Module ps2exe -Scope CurrentUser`):

```
Invoke-ps2exe -inputFile HEVC-Converter-WPF.ps1 -outputFile BitShift.exe -iconFile bitshift.ico -noConsole -STA -title BitShift -product BitShift -version 3.6.0.0
```

The source must be saved as **UTF-8 with BOM**, otherwise PowerShell 5.1 misreads the
Cyrillic characters in the interface strings.

---

## macOS

Everything macOS lives in [`mac/`](mac/) and has its own documentation:
**[mac/README.md](mac/README.md)**.

**Requirements:** Apple Silicon (M1 or newer) and macOS 12 or later. The packaged app
carries its own Python and ffmpeg, so there is nothing else to install.

**Running it.** Download `BitShift-macOS.zip` from [Releases](../../releases/latest),
unzip it and move `BitShift.app` wherever you like. macOS will block it on first launch
because the app is signed locally rather than notarised by Apple. Two ways past it:

- right-click the app → **Open** → **Open** again in the dialog; or
- once in Terminal:

```
xattr -dr com.apple.quarantine /path/to/BitShift.app
```

After that it opens with a normal double-click.

**Codecs:** HEVC (default, hardware), ProRes 422 HQ (hardware, M1 Pro/Max and newer) and
AV1 (software — Apple has no hardware AV1 encoder, so it is slow but very compact).

---

## Limitations

- Windows build: NVIDIA only.
- macOS build: Apple Silicon only, and its size forecast has so far been calibrated on
  synthetic clips rather than a large real archive.
- Neither build is notarised or code-signed by a paid account, so both systems warn on
  first launch.
- This is a personal tool rather than a polished product: it was built for one specific
  job, by one person, and tested on two machines.

## What is in the repository

| Path | What it is |
|---|---|
| `BitShift.exe` | Windows application, built from `HEVC-Converter-WPF.ps1` with ps2exe |
| `HEVC-Converter-WPF.ps1` | Windows source (PowerShell + WPF). The filename is historical |
| `mac/` | The macOS version: Python core, HTML/CSS window, VideoToolbox |
| `bitshift.ico`, `bitshift-source.png` | Icon and the master image both versions are cut from |
| `CLAUDE.md`, `mac/CLAUDE.md` | Engineering notes: architecture, measurements, hard-won pitfalls. **Written in Russian** — these are working notes rather than user documentation |
| `docs-mac-port.md` | What still needs porting between the two versions (in Russian) |
| `THIRD-PARTY.md` | What ships inside the downloads and under which licences |

## Licence

MIT — see [LICENSE](LICENSE).

**The macOS download bundles FFmpeg, and that build is GPL v2+.** It does not change the
licence of BitShift itself — the app runs `ffmpeg` as a separate process rather than
linking against it — but the notice and a pointer to the sources belong with the binary.
Both are in [THIRD-PARTY.md](THIRD-PARTY.md), along with everything else that ships inside
the app. The Windows exe bundles nothing: you install FFmpeg yourself.
