from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.estimate import forecast_bytes
from core.modes import CODECS, DEFAULT_MODE, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan


def main(source: Path, mode_key: str = DEFAULT_MODE, codec_key: str = "hevc") -> int:
    clips = sorted(
        p for p in source.rglob("*")
        if p.is_file() and p.suffix.lower() in MODES_BY_KEY[mode_key].exts
        and not p.stem.endswith("_v2")
    )
    if not clips:
        print(f"Нет подходящих файлов в {source}")
        return 1

    work = Path(tempfile.mkdtemp(prefix="замер-прогноза-"))
    try:
        for clip in clips:
            shutil.copy2(clip, work / clip.name)

        settings = Settings(
            mode=MODES_BY_KEY[mode_key], codec=CODECS[codec_key], folder=work,
            use_staging=False, trash_originals=False,
        )
        todo, skipped = scan(settings)
        if not todo:
            print("Все файлы отсеяны — прогноз мерить не на чем")
            return 1

        raw = {
            job.src.name: forecast_bytes(
                job.info, job.target, settings.codec, settings.audio,
                src_bytes=job.src_bytes, skipped=False,
            ) / settings.codec.estimate_overhead
            for job in todo
        }

        done = Pipeline(settings, todo).run()

        print(f"{'файл':<28}{'прогноз':>12}{'факт':>12}{'факт/прогноз':>15}")
        total_raw = total_real = 0.0
        for job in done:
            if job.state is not State.DONE or not job.final_dst.exists():
                print(f"{job.src.name:<28}  не сконвертировался: {job.message[:40]}")
                continue
            predicted = raw[job.src.name]
            actual = job.final_dst.stat().st_size
            total_raw += predicted
            total_real += actual
            print(f"{job.src.name:<28}{predicted / 1e6:>11.1f}М{actual / 1e6:>11.1f}М"
                  f"{actual / predicted:>14.3f}")

        if total_raw <= 0:
            print("Нечего сравнивать")
            return 1

        print()
        print(f"Итого прогноз без поправки: {total_raw / 1e6:.1f} МБ")
        print(f"Итого факт:                 {total_real / 1e6:.1f} МБ")
        print(f"КОЭФФИЦИЕНТ (факт/прогноз): {total_real / total_raw:.3f}")
        print(f"Сейчас у кодека:            {settings.codec.estimate_overhead}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__ or "Использование: bench_estimate.py <папка> [режим] [кодек]")
        raise SystemExit(2)
    raise SystemExit(main(
        Path(sys.argv[1]),
        sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODE,
        sys.argv[3] if len(sys.argv) > 3 else "hevc",
    ))
