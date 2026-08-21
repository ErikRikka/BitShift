# BitShift

Video archive converter for Windows. Re-encodes footage to HEVC, AV1 or DNxHR on an
NVIDIA GPU — verifying every file and never putting your originals at risk.

A real example: a folder of concert footage went from **155 GB to 27 GB** (4K H.264 → HEVC)
with no visible loss.

Interface is available in **English and Russian** — it follows your Windows language and
can be switched at the bottom of the sidebar.

*Читаете по-русски? [README.ru.md](README.ru.md)*

---

## Requirements

The constraints are strict, so check them first:

- **An NVIDIA graphics card** (GTX 16xx or newer) — all encoding runs on NVENC.
  The app will not start on AMD or Intel Arc.
- **Windows 10 or 11.**
- **ffmpeg** on your system (`ffmpeg` and `ffprobe` available in PATH).

Install ffmpeg with a single command:

```
winget install Gyan.FFmpeg
```

Close the terminal window afterwards so PATH refreshes.

## Running it

Download `BitShift.exe` from [Releases](../../releases/latest) and double-click it —
no installation, it is a single file.

On first launch Windows SmartScreen may warn about an unknown publisher (the app is not
code-signed): **More info** → **Run anyway**.

If you would rather not trust the exe, run the source directly:

```
powershell -STA -ExecutionPolicy Bypass -File HEVC-Converter-WPF.ps1
```

## What it does

**Three codecs:**

| Codec | When to use it |
|---|---|
| **HEVC** | Default. Plays everywhere: Resolve, Premiere, phones, TVs |
| **AV1** | Roughly 20% smaller at the same quality, but not decoded everywhere |
| **DNxHR HQX** | Grading master: 4:2:2, 10-bit, intra. Encoded on the CPU |

**Three modes** based on where the footage came from: *Old video* (AVI, WMV, MTS),
*Camera footage* (Log/RAW, compressed gently), *Regular video* (maximum savings).

The bitrate is computed **per file** — from its resolution, frame rate and source bitrate.
If the gain would be under 10%, the file is left alone.

**Size estimate before you start.** You see "155 GB → ~27 GB, −82%" before pressing Start.

**You choose what happens to audio.** Multi-track production sound can be kept intact
(every channel, original bit depth) or downmixed to stereo AAC. On a 16-channel recording
that is an eightfold difference in size.

**Built for slow drives.** If footage sits on an external HDD, files are moved to the
internal SSD one at a time, encoded there and moved back — otherwise the drive chokes on
parallel reads. Anything already on a fast disk is processed in place.

Plus: several folders in one run, pausing (which frees the GPU), time remaining estimated
by data volume, per-file progress, and shutdown when finished.

## Data safety

This is the whole reason the tool exists.

- **Originals are never overwritten** — results are separate files with a `_v2` suffix.
- **Deletion goes to the Recycle Bin only.** There is no permanent delete anywhere in the app.
- An original is removed only after the result passes **all four checks**:
  1. the result really is in the expected codec;
  2. duration matches within 2%;
  3. frame count matches within ±2;
  4. the file decodes completely without errors.

Fail any of them and the original stays where it is.

That verification matters more than it sounds: a hardware decoder can **silently** drop the
first frames of a GOP on 10-bit 4:2:2 footage. The file opens, looks fine, and the beginning
is gone — the frame count check is what catches it.

**On your first run, untick the auto-delete box**: look at the results yourself, then let
the tool handle the Recycle Bin.

## Limitations

- NVIDIA only, Windows only.
- No macOS build yet (porting notes live in `docs-mac-port.md`).
- The app is unsigned, so SmartScreen will warn about it.
- This is a personal tool rather than a polished product: it was built for one specific job
  and tested on one machine.

## Files

| File | What it is |
|---|---|
| `BitShift.exe` | The application, built from `HEVC-Converter-WPF.ps1` with ps2exe |
| `HEVC-Converter-WPF.ps1` | Source (PowerShell + WPF). The filename is historical |
| `bitshift.ico`, `bitshift-source.png` | Icon and its master image |
| `CLAUDE.md` | Engineering notes: architecture, measurements, hard-won pitfalls (in Russian) |
| `docs-mac-port.md` | What needs porting to macOS (in Russian) |

## Building the exe

Requires the ps2exe module (`Install-Module ps2exe -Scope CurrentUser`):

```
Invoke-ps2exe -inputFile HEVC-Converter-WPF.ps1 -outputFile BitShift.exe -iconFile bitshift.ico -noConsole -STA -title BitShift -product BitShift -version 3.5.0.0
```

The source must be saved as **UTF-8 with BOM**, otherwise PowerShell 5.1 misreads Cyrillic
characters in the interface strings.

## Licence

MIT — see [LICENSE](LICENSE).
