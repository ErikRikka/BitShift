from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.modes import CODEC_HEVC, MODES_BY_KEY
from core.probe import probe
from core.pipeline import Pipeline, Settings, State, scan


def main(source: Path) -> int:
    clips = sorted(source.glob("*.mp4"))
    if not clips:
        print(f"Нет клипов в {source}")
        return 1

    total_seconds = sum(probe(c).duration for c in clips)
    print(f"Клипов: {len(clips)}, суммарно {total_seconds:.0f}с материала\n")
    print(f"{'JOBS':>5} {'время':>9} {'× реального':>13} {'на клип':>10}")

    results: dict[int, float] = {}
    for jobs in (1, 2, 3, 4):
        work = Path(tempfile.mkdtemp(prefix=f"замер-{jobs}-"))
        try:
            for clip in clips:
                shutil.copy2(clip, work / clip.name)

            settings = Settings(
                mode=MODES_BY_KEY["slog"],
                codec=CODEC_HEVC,
                folder=work,
                jobs=jobs,
                use_staging=False,
                trash_originals=False,
            )
            todo, _ = scan(settings)
            if not todo:
                print(f"{jobs:>5}  все файлы отсеяны — проверь битрейт исходников")
                return 1

            started = time.time()
            done = Pipeline(settings, todo).run()
            elapsed = time.time() - started

            bad = [j for j in done if j.state not in (State.DONE, State.TRASHED)]
            if bad:
                print(f"{jobs:>5}  ПРОВАЛ: {bad[0].message[:80]}")
                return 1

            results[jobs] = elapsed
            print(
                f"{jobs:>5} {elapsed:>8.1f}с {total_seconds / elapsed:>12.1f}× "
                f"{elapsed / len(clips):>9.1f}с"
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    best = min(results, key=lambda k: results[k])
    print(f"\nЛучший JOBS: {best} ({results[best]:.1f}с)")
    base = results.get(1)
    if base:
        for jobs, elapsed in sorted(results.items()):
            print(f"  JOBS={jobs}: выигрыш к одному потоку ×{base / elapsed:.2f}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
