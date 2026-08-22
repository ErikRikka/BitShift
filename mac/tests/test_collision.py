from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.modes import CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan
from core.probe import probe

TREE: dict[str, float] = {
    "08 Съёмка A/C0008.MP4": 5.0,
    "09 Съёмка B/C0008.MP4": 8.0,
    "09 Съёмка B/День 2/C0008.MP4": 11.0,
    "08 Съёмка A/C0009.MP4": 14.0,
    "09 Съёмка B/C0009.MP4": 17.0,
}


def make_clip(path: Path, duration: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi",
            "-i", f"testsrc2=size=1920x1080:rate=30:duration={duration}",
            "-c:v", "libx264", "-b:v", "20M", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
    )


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="злое-дерево-"))
    print(f"Дерево: {root}")
    try:
        for rel, duration in TREE.items():
            make_clip(root / rel, duration)
        print(f"Создано файлов: {len(TREE)}")

        settings = Settings(
            mode=MODES_BY_KEY["arc"],
            codec=CODEC_HEVC,
            folder=root,
            recursive=True,
            jobs=2,
            use_staging=True,
            trash_originals=False,
        )

        before = set(Path(tempfile.gettempdir()).glob("конвертер-кэш-*"))

        todo, skipped = scan(settings)
        print(f"В работу: {len(todo)}, отсеяно: {len(skipped)}")
        for job in skipped:
            print(f"  пропуск {job.src.relative_to(root)}: {job.message}")

        if len(todo) != len(TREE):
            print("ПРОВАЛ: в работу взяты не все файлы")
            return 1

        pipeline = Pipeline(settings, todo, on_log=lambda t: print(f"  лог: {t}"))
        done = pipeline.run()

        failures: list[str] = []
        for job in done:
            rel = job.src.relative_to(root)
            expected = TREE[str(rel)]

            if job.state not in (State.DONE, State.TRASHED):
                failures.append(f"{rel}: состояние {job.state.value} — {job.message}")
                continue
            if not job.final_dst.exists():
                failures.append(f"{rel}: результата нет на месте")
                continue

            actual = probe(job.final_dst).duration
            if abs(actual - expected) > 1.0:
                failures.append(
                    f"{rel}: ПОДМЕНА — ожидали {expected:.1f}с, получили {actual:.1f}с"
                )
                continue

            src_size = job.src.stat().st_size
            dst_size = job.final_dst.stat().st_size
            print(
                f"  ✓ {rel}: {expected:.0f}с, "
                f"{src_size / 1e6:.1f} → {dst_size / 1e6:.1f} МБ "
                f"(−{100 - dst_size * 100 / src_size:.0f}%)"
            )

        for rel in TREE:
            if not (root / rel).exists():
                failures.append(f"{rel}: ОРИГИНАЛ ПРОПАЛ при выключенном удалении")

        leftovers = sorted(
            set(Path(tempfile.gettempdir()).glob("конвертер-кэш-*")) - before
        )
        if leftovers:
            failures.append(f"кэш не прибран: {leftovers}")

        if failures:
            print("\nПРОВАЛ:")
            for f in failures:
                print(f"  ✗ {f}")
            return 1

        print("\nВсё сошлось: каждый результат совпал со своим оригиналом.")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
