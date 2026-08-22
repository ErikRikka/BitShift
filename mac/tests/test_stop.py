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
from core.modes import CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan

CLIP_SECONDS = 90.0

STOP_DEADLINE = 12.0


def make_long_clip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=3840x2160:rate=30:duration={CLIP_SECONDS:g}",
            "-c:v", "libx264", "-b:v", "60M", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def make_short_clip(path: Path, duration: float = 3.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=1280x720:rate=30:duration={duration:g}",
            "-c:v", "libx264", "-b:v", "15M", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def settings_for(folder: Path, **kwargs) -> Settings:
    base = dict(
        mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=folder,
        jobs=1, use_staging=False, trash_originals=False,
    )
    base.update(kwargs)
    return Settings(**base)


def run_until(pipeline: Pipeline, jobs, ready, timeout: float = 180.0):
    worker = threading.Thread(target=pipeline.run, daemon=True)
    worker.start()
    deadline = time.time() + timeout
    while time.time() < deadline and not ready():
        if not worker.is_alive():
            break
        time.sleep(0.1)
    return worker


def case_stop_while_encoding(work: Path) -> list[str]:
    src = work / "C0001.MP4"
    make_long_clip(src)
    before = src.stat().st_size

    settings = settings_for(work)
    todo, _ = scan(settings)
    pipeline = Pipeline(settings, todo)

    worker = run_until(pipeline, todo, lambda: todo[0].progress > 0.05)
    if not worker.is_alive():
        return ["конвейер закончил раньше, чем успели нажать «Стоп»"]

    pressed = time.time()
    pipeline.stop()
    worker.join(timeout=STOP_DEADLINE)
    elapsed = time.time() - pressed

    problems: list[str] = []
    if worker.is_alive():
        problems.append(f"НЕ ОСТАНОВИЛСЯ за {STOP_DEADLINE:.0f}с — кнопка не работает")
        return problems

    if elapsed > STOP_DEADLINE:
        problems.append(f"остановка заняла {elapsed:.1f}с")
    if not src.exists() or src.stat().st_size != before:
        problems.append("ОРИГИНАЛ ПОСТРАДАЛ")
    if (work / "C0001_v2.mp4").exists():
        problems.append("недописанный результат остался на диске")
    if todo[0].state is State.FAILED:
        problems.append("прерванный файл помечен «браком», хотя это не брак")
    if todo[0].state is not State.STOPPED:
        problems.append(f"состояние {todo[0].state.value}, ожидали «остановлено»")
    return problems


def case_stop_while_paused(work: Path) -> list[str]:
    src = work / "C0001.MP4"
    make_long_clip(src)

    settings = settings_for(work)
    todo, _ = scan(settings)
    pipeline = Pipeline(settings, todo)

    worker = run_until(pipeline, todo, lambda: todo[0].progress > 0.05)
    if not worker.is_alive():
        return ["конвейер закончил раньше, чем успели нажать «Пауза»"]

    pipeline.pause()
    time.sleep(1.0)

    pressed = time.time()
    pipeline.stop()
    worker.join(timeout=STOP_DEADLINE)
    elapsed = time.time() - pressed

    problems: list[str] = []
    if worker.is_alive():
        problems.append(f"после «Паузы» не остановился за {STOP_DEADLINE:.0f}с")
    elif elapsed > STOP_DEADLINE:
        problems.append(f"остановка заняла {elapsed:.1f}с")
    if not src.exists():
        problems.append("ОРИГИНАЛ ПРОПАЛ")
    return problems


def case_stop_while_verifying(work: Path) -> list[str]:
    src = work / "C0001.MP4"
    make_long_clip(src)

    settings = settings_for(work)
    todo, _ = scan(settings)
    pipeline = Pipeline(settings, todo)

    worker = run_until(
        pipeline, todo,
        lambda: todo[0].state is State.VERIFYING and todo[0].progress > 0.2,
    )
    problems: list[str] = []
    if not worker.is_alive():
        return ["конвейер закончил раньше, чем дошло до проверки"]
    if todo[0].state is not State.VERIFYING:
        return [f"до проверки не дошли, состояние {todo[0].state.value}"]

    pressed = time.time()
    pipeline.stop()
    worker.join(timeout=STOP_DEADLINE)
    elapsed = time.time() - pressed

    if worker.is_alive():
        problems.append(f"на проверке не остановился за {STOP_DEADLINE:.0f}с")
    elif elapsed > STOP_DEADLINE:
        problems.append(f"остановка на проверке заняла {elapsed:.1f}с")
    if not src.exists():
        problems.append("ОРИГИНАЛ ПРОПАЛ")
    if todo[0].state is State.FAILED:
        problems.append("прерванная проверка помечена «браком»")
    return problems


def case_stop_does_not_trash(work: Path) -> list[str]:
    make_short_clip(work / "C0001.MP4")
    make_short_clip(work / "C0002.MP4", duration=4.0)
    make_long_clip(work / "C0003.MP4")

    trashed: list[tuple[float, Path]] = []
    real_trash = pipeline_module.move_to_trash

    def record_trash(path):
        trashed.append((time.time(), Path(path)))
        return real_trash(path)

    pipeline_module.move_to_trash = record_trash
    try:
        settings = settings_for(work, trash_originals=True)
        todo, _ = scan(settings)
        pipeline = Pipeline(settings, todo)

        worker = run_until(
            pipeline, todo,
            lambda: any(j.state is State.ENCODING and j.progress > 0.05
                        for j in todo),
        )
        if not worker.is_alive():
            return ["конвейер закончил раньше, чем успели нажать «Стоп»"]

        pressed = time.time()
        pipeline.stop()
        worker.join(timeout=STOP_DEADLINE)
    finally:
        pipeline_module.move_to_trash = real_trash

    problems: list[str] = []
    после = [p.name for when, p in trashed if when > pressed]
    if после:
        problems.append(f"ПОСЛЕ «Стопа» в Корзину ушло: {после}")

    удалённые = {p.name for _, p in trashed}
    for name in ("C0001.MP4", "C0002.MP4", "C0003.MP4"):
        if name not in удалённые and not (work / name).exists():
            problems.append(f"ОРИГИНАЛ {name} ПРОПАЛ, хотя его не удаляли")

    for _, path in trashed:
        job = next((j for j in todo if j.src == path), None)
        if job is None or job.report is None or not job.report.ok:
            problems.append(f"{path.name} удалён без успешной проверки")
        elif not job.final_dst.exists():
            problems.append(f"{path.name} удалён, а результата нет на месте")
    return problems


def case_verified_result_survives_stop(work: Path) -> list[str]:
    make_short_clip(work / "C0001.MP4")
    make_long_clip(work / "C0002.MP4")

    settings = settings_for(work, use_staging=True)
    todo, _ = scan(settings)
    by_name = {j.name: j for j in todo}
    pipeline = Pipeline(settings, todo)

    first = by_name["C0001.MP4"]

    worker = run_until(
        pipeline, todo,
        lambda: first.state in (State.VERIFIED, State.MOVING, State.DONE),
    )
    problems: list[str] = []
    if first.state not in (State.VERIFIED, State.MOVING, State.DONE):
        return [f"первый файл не дошёл до переноса: {first.state.value}"]

    pipeline.stop()
    worker.join(timeout=60)

    if worker.is_alive():
        problems.append("не остановился за 60с")
    if not (work / "C0001_v2.mp4").exists():
        problems.append("ПРОВЕРЕННЫЙ РЕЗУЛЬТАТ ПРОПАЛ вместе с кэшем")
    elif (work / "C0001_v2.mp4").stat().st_size == 0:
        problems.append("проверенный результат пустой")
    if first.report is None or not first.report.ok:
        problems.append("отчёт проверки потерян")
    for name in ("C0001.MP4", "C0002.MP4"):
        if not (work / name).exists():
            problems.append(f"ОРИГИНАЛ {name} ПРОПАЛ")
    return problems


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-стопа-"))
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
        ("стоп во время кодирования", case_stop_while_encoding),
        ("стоп после паузы", case_stop_while_paused),
        ("стоп во время проверки", case_stop_while_verifying),
        ("стоп не удаляет оригиналы", case_stop_does_not_trash),
        ("проверенный результат переживает стоп", case_verified_result_survives_stop),
    ]
    print("Кнопка «Стоп»\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
