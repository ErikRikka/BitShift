# BitShift for macOS

Video archive converter for macOS. Squeezes footage into HEVC, AV1 or ProRes on Apple's
hardware encoder, runs four checks on every result, and only then moves the original
to the Trash.

The window is HTML/CSS in a native Mac frame; the core is Python 3 driving `ffmpeg`.

*По-русски → [README.ru.md](README.ru.md)* · *Project overview → [../README.md](../README.md)*

---

## ⚠️ Before you run it on your own files

Defaults: **HEVC** codec, **stereo AAC** audio, subfolders included.
Interface language follows your system and can be switched with the gear button.

**Moving originals to the Trash is on by default.** Only files that passed every check
are moved, and only to the Trash — nothing is ever deleted permanently, anywhere. But if
you just want to poke around, **untick "Move originals to Trash after verifying"** before
your first run.

The command line is the opposite way round: without the `--to-trash` flag nothing is
removed at all.

The safest way to see what the tool intends to do:

```
.venv/bin/python cli.py ~/Movies/test --mode arc --dry-run
```

`--dry-run` prints the plan and exits without touching a thing.

> Every flag has both an English and a Russian name — `--mode` and `--режим` do the same
> thing — so older scripts keep working. The messages the CLI prints are still Russian;
> the graphical interface is the fully bilingual one.

---

## The packaged app

Download `BitShift-macOS.zip` from [Releases](../../../releases/latest) — everything is
inside: its own Python, pywebview, PyObjC and its own `ffmpeg`. No Homebrew, no virtual
environment, nothing to install. All you need is a Mac on Apple Silicon.

Because everything ships inside, so do other people's licences: the bundled FFmpeg is a
GPL v2+ build. What that means for BitShift's own MIT licence — and the full list of what
travels in the archive — is in [THIRD-PARTY.md](../THIRD-PARTY.md).

**macOS will block the first launch** — the app is signed locally, without Apple
notarisation (which requires a paid developer account). Two ways past it:

- right-click the app → **Open** → **Open** again in the dialog; or
- once in Terminal:

```
xattr -dr com.apple.quarantine /path/to/BitShift.app
```

After that it opens with a normal double-click.

## Building that app yourself

```
.venv/bin/python build.py
```

The script downloads static arm64 builds of `ffmpeg` and `ffprobe` (into `build/`, and
skips the download if they are already there), **verifies them against pinned SHA-256
hashes**, checks that the encoders it needs are present, builds the icon and runs py2app.
The result is `dist/BitShift.app`, around 128 MB.

Everything below is about running from source, if you want to dig into the code.

## Requirements

- **a Mac on Apple Silicon** — this uses VideoToolbox and will not run anywhere else;
- `ffmpeg` and `ffprobe`: `brew install ffmpeg`;
- Python 3.

Hardware ProRes exists only on M1 Pro/Max and newer. Apple has no hardware AV1 encoder at
all, so that codec runs on the CPU — slow, but very compact.

## Setup

```
cd mac
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.venv` is not in the repository — it is about 50 MB and belongs to each machine anyway.

## Running it

```
open BitShift.app                          # the window
./run.command                              # same thing, if the .app misbehaves
.venv/bin/python app.py                    # same thing from a terminal

.venv/bin/python cli.py <folder> --mode arc --dry-run   # plan only, changes nothing
.venv/bin/python cli.py <folder1> <folder2>            # several folders
.venv/bin/python cli.py <folder> --audio original      # keep every audio channel
.venv/bin/python cli.py <folder> --no-subfolders       # do not descend into subfolders
.venv/bin/python cli.py <folder> --to-trash            # move verified originals to Trash
```

## Tests

They run real `ffmpeg` against real files, which they generate themselves in a temporary
directory. They are not fast: a full round is about twenty minutes, with `test_stop.py`
(roughly eight minutes) and `test_parallel.py` taking the longest.

```
.venv/bin/python tests/test_safety.py      # a bad result never costs you the original
.venv/bin/python tests/test_verify.py      # the four checks, and the lying hardware decoder
.venv/bin/python tests/test_collision.py   # same-named files in different folders stay apart
.venv/bin/python tests/test_audio.py       # 16-channel audio, parsing ffmpeg's complaints
.venv/bin/python tests/test_progress.py    # time estimate, stages, several folders
.venv/bin/python tests/test_stop.py        # Stop actually stops
.venv/bin/python tests/test_deadlock.py    # hanging on an unread stderr pipe
.venv/bin/python tests/test_parallel.py    # stages really do overlap
.venv/bin/python tests/test_picker.py      # source selection and the size forecast
.venv/bin/python tests/test_bundle.py      # the built .app is complete
```

You can iterate on the window design without encoding anything:

```
.venv/bin/python -m http.server 8765
# open http://localhost:8765/tests/ui_preview.html
```

## Layout

```
app.py         the window: a bridge between interface and core
cli.py         the same thing from the command line
build.py       builds the self-contained .app
icon.py        rebuilds the icon from ../bitshift-source.png
run.command    double-click launcher for Finder
core/          the engine: all the logic, knows nothing about the interface
  config.py      every tunable number, path and string — in one place
  pipeline.py    the pipeline: stages run concurrently
  encode.py      assembling and running ffmpeg, parsing its complaints
  verify.py      the four checks on a result
  modes.py       modes, bitrate maths, skip rules
  estimate.py    size forecast before you start
  staging.py     cache on the fast disk
  probe.py       ffprobe: what kind of file is this
  eta.py         time remaining — by bytes, not by file count
  lang.py        interface strings in both languages
  trash.py       the Trash, through the system API
ui/            the interface: plain HTML, CSS and JS
tests/         the checks
BitShift.app   thin wrapper: no Python of its own, calls the app.py next to it
```

**The `BitShift.app` in this folder cannot be moved away from the project** — it points at
the `.venv` and `app.py` beside it. Putting it in the Dock is fine, but the bundle itself
has to stay where it is. The self-contained build is the one in `dist/`.

## Tuning it

Everything adjustable lives in `core/config.py`: verification tolerances, progress
weights, the disk headroom, thread counts, the shutdown delay, window dimensions. The
modules themselves hold no literals — that one file is the only place to edit.

The code has no comments, deliberately. The reasoning behind every decision is in
`CLAUDE.md`.

## Further reading

`CLAUDE.md` holds the engineering notes: which traps were hit on real footage, what must
not be "optimised" back, and why. It also carries the measurements — codec speeds,
hardware decoder behaviour, the parallelism numbers. **It is written in Russian**, as
working notes rather than user documentation.
