from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.pipeline as pipeline_module
from core.modes import CODEC_AV1, CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan

COPY_DELAY = 1.5

MIN_OVERLAP = 0.5


def make_clip(path: Path, seconds: float = 8.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds:g}",
            "-c:v", "libx264", "-b:v", "15M", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


class Timeline:
    def __init__(self) -> None:
        self.spans: dict[State, list[list]] = {}
        self._current: dict[Path, State] = {}
        self._lock = threading.Lock()
        self.started = time.time()

    def note(self, job) -> None:
        with self._lock:
            was = self._current.get(job.src)
            if was == job.state:
                return
            now = time.time() - self.started
            if was is not None and self.spans.get(was) and self.spans[was][-1][1] is None:
                self.spans[was][-1][1] = now
            self._current[job.src] = job.state
            self.spans.setdefault(job.state, []).append([now, None])

    def close(self) -> None:
        end = time.time() - self.started
        for spans in self.spans.values():
            for span in spans:
                if span[1] is None:
                    span[1] = end

    def total(self, state: State) -> float:
        return sum(b - a for a, b in self.spans.get(state, ()))

    def overlap(self, first: State, second: State) -> float:
        result = 0.0
        for a1, b1 in self.spans.get(first, ()):
            for a2, b2 in self.spans.get(second, ()):
                result += max(0.0, min(b1, b2) - max(a1, a2))
        return result


def run_with_slow_disk(work: Path, codec) -> Timeline:
    real_copy = pipeline_module.copy_in

    def slow_copy(src, slot, on_progress=None):
        time.sleep(COPY_DELAY)
        return real_copy(src, slot, on_progress)

    timeline = Timeline()
    pipeline_module.copy_in = slow_copy
    try:
        settings = Settings(
            mode=MODES_BY_KEY["arc"], codec=codec, folder=work,
            jobs=2, use_staging=True, trash_originals=False,
        )
        todo, _ = scan(settings)
        if len(todo) < 3:
            raise AssertionError(f"в работу взято {len(todo)} файлов, нужно 3")
        pipeline = Pipeline(settings, todo, on_update=timeline.note)
        timeline.started = time.time()
        pipeline.run()
    finally:
        pipeline_module.copy_in = real_copy
    timeline.close()
    timeline.jobs = todo
    return timeline


def check(timeline: Timeline, codec_name: str) -> list[str]:
    problems: list[str] = []
    copying = timeline.total(State.COPYING)
    together = timeline.overlap(State.COPYING, State.ENCODING)

    if copying < COPY_DELAY:
        problems.append(f"{codec_name}: копирования почти не было ({copying:.1f}с)")
        return problems
    if together < MIN_OVERLAP:
        problems.append(
            f"{codec_name}: копирование НЕ идёт одновременно с кодированием "
            f"({together:.1f}с из {copying:.1f}с) — стадии выстроились в очередь"
        )

    bad = [j for j in timeline.jobs
           if j.state not in (State.DONE, State.TRASHED)]
    if bad:
        problems.append(f"{codec_name}: не готово {[(j.name, j.state.value) for j in bad]}")
    return problems


def case_software_codec(work: Path) -> list[str]:
    for i in range(3):
        make_clip(work / f"C000{i}.MP4")
    return check(run_with_slow_disk(work, CODEC_AV1), "AV1")


def case_hardware_codec(work: Path) -> list[str]:
    for i in range(3):
        make_clip(work / f"C000{i}.MP4")
    return check(run_with_slow_disk(work, CODEC_HEVC), "HEVC")


def case_cache_does_not_run_away(work: Path) -> list[str]:
    for i in range(6):
        make_clip(work / f"C000{i}.MP4", seconds=4.0)

    peak = 0
    real_copy = pipeline_module.copy_in
    lock = threading.Lock()
    staged: set = set()

    def counting_copy(src, slot, on_progress=None):
        nonlocal peak
        with lock:
            staged.add(src)
            peak = max(peak, len(staged))
        time.sleep(0.4)
        return real_copy(src, slot, on_progress)

    pipeline_module.copy_in = counting_copy
    try:
        settings = Settings(
            mode=MODES_BY_KEY["arc"], codec=CODEC_AV1, folder=work,
            jobs=2, use_staging=True, trash_originals=False,
        )
        todo, _ = scan(settings)
        pipeline = Pipeline(settings, todo)

        held_peak = 0
        stop = threading.Event()

        def watch() -> None:
            nonlocal held_peak
            while not stop.is_set():
                held = sum(1 for j in todo if j.stage_held)
                held_peak = max(held_peak, held)
                time.sleep(0.05)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        pipeline.run()
        stop.set()
        watcher.join(timeout=2)
    finally:
        pipeline_module.copy_in = real_copy

    limit = settings.effective_jobs() + pipeline_module.STAGE_AHEAD
    problems: list[str] = []
    if held_peak > limit:
        problems.append(f"в кэше разом было {held_peak} файлов при пределе {limit}")
    if held_peak == 0:
        problems.append("кэш не использовался вовсе")
    return problems


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-параллели-"))
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


def main() -> int:
    cases = [
        ("копирование идёт вместе с кодированием (AV1)", case_software_codec),
        ("копирование идёт вместе с кодированием (HEVC)", case_hardware_codec),
        ("копировщик не убегает вперёд", case_cache_does_not_run_away),
    ]
    print("Перекрытие стадий\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
