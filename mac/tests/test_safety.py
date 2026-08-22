from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.pipeline as pipeline_module
from core.modes import CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan
from core.verify import VerifyReport

CLIP_SECONDS = 4.0


def make_clip(path: Path, duration: float = CLIP_SECONDS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=1280x720:rate=30:duration={duration}",
            "-c:v", "libx264", "-b:v", "15M", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def make_settings(folder: Path, **kwargs) -> Settings:
    base = dict(
        mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=folder,
        jobs=1, use_staging=False, trash_originals=False,
    )
    base.update(kwargs)
    return Settings(**base)


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-безопасности-"))
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


def case_failed_verification(work: Path) -> list[str]:
    src = work / "C0001.MP4"
    make_clip(src)
    original_size = src.stat().st_size

    trashed: list[Path] = []
    real_verify = pipeline_module.verify_pair
    real_trash = pipeline_module.move_to_trash

    def always_fails(*args, **kwargs):
        report = VerifyReport()
        report.fail("кадры", "подстроенный провал проверки")
        report.ok = False
        return report

    def record_trash(path):
        trashed.append(Path(path))
        return real_trash(path)

    pipeline_module.verify_pair = always_fails
    pipeline_module.move_to_trash = record_trash
    try:
        settings = make_settings(work, trash_originals=True)
        todo, _ = scan(settings)
        done = Pipeline(settings, todo).run()
    finally:
        pipeline_module.verify_pair = real_verify
        pipeline_module.move_to_trash = real_trash

    problems: list[str] = []
    if not src.exists():
        problems.append("ОРИГИНАЛ ПРОПАЛ после провала проверки")
    elif src.stat().st_size != original_size:
        problems.append("оригинал изменился в размере")
    if trashed:
        problems.append(f"в Корзину ушло при браке: {trashed}")
    result = work / "C0001_v2.mp4"
    if result.exists():
        problems.append("бракованный результат остался на диске")
    if done and done[0].state is not State.FAILED:
        problems.append(f"состояние {done[0].state.value}, ожидали «брак»")
    return problems


def case_trash_off_by_default(work: Path) -> list[str]:
    src = work / "C0002.MP4"
    make_clip(src)

    settings = make_settings(work)
    problems: list[str] = []
    if settings.trash_originals:
        problems.append("trash_originals по умолчанию включён — так нельзя")

    todo, _ = scan(settings)
    done = Pipeline(settings, todo).run()

    if not src.exists():
        problems.append("ОРИГИНАЛ ПРОПАЛ при выключенном удалении")
    if done and done[0].state is not State.DONE:
        problems.append(f"состояние {done[0].state.value}, ожидали «готово»")
    return problems


def case_original_never_overwritten(work: Path) -> list[str]:
    src = work / "C0003.MP4"
    make_clip(src)
    before = src.read_bytes()

    settings = make_settings(work)
    todo, _ = scan(settings)
    done = Pipeline(settings, todo).run()

    problems: list[str] = []
    if src.read_bytes() != before:
        problems.append("ОРИГИНАЛ ПЕРЕЗАПИСАН")
    result = work / "C0003_v2.mp4"
    if not result.exists():
        problems.append("результата нет")
    elif result.resolve() == src.resolve():
        problems.append("результат и оригинал — один файл")
    if done and done[0].state is not State.DONE:
        problems.append(f"состояние {done[0].state.value}")
    return problems


def case_rerun_is_safe(work: Path) -> list[str]:
    src = work / "C0004.MP4"
    make_clip(src)

    settings = make_settings(work)
    todo, _ = scan(settings)
    Pipeline(settings, todo).run()

    result = work / "C0004_v2.mp4"
    stamp = result.stat().st_mtime_ns
    body = result.read_bytes()

    todo2, skipped2 = scan(settings)

    problems: list[str] = []
    if todo2:
        problems.append(f"повторный запуск снова взял в работу: {[j.name for j in todo2]}")
    if not any("результат уже есть" in j.message for j in skipped2):
        problems.append(f"причина пропуска не та: {[j.message for j in skipped2]}")
    if result.stat().st_mtime_ns != stamp or result.read_bytes() != body:
        problems.append("готовый результат изменился при повторном запуске")
    if any(j.name.endswith("_v2.mp4") for j in todo2):
        problems.append("_v2 попал в кандидаты")
    return problems


def case_one_name_two_extensions(work: Path) -> list[str]:
    mp4 = work / "C0008.mp4"
    mov = work / "C0008.mov"
    make_clip(mp4, duration=CLIP_SECONDS)
    make_clip(mov, duration=CLIP_SECONDS * 2)

    settings = make_settings(work)
    todo, skipped = scan(settings)

    problems: list[str] = []
    destinations = [str(job.final_dst) for job in todo]
    if len(set(destinations)) != len(destinations):
        problems.append(f"два исходника метят в один файл: {destinations}")
    if len(todo) != 1:
        problems.append(f"в работу взято {len(todo)} файлов вместо одного")
    if not any("совпал бы" in job.message for job in skipped):
        problems.append(f"причина пропуска не та: {[j.message for j in skipped]}")

    if not problems:
        pipeline = Pipeline(settings, todo)
        pipeline.run()
        if not mp4.exists() or not mov.exists():
            problems.append("оригинал пропал")

    return problems


def main() -> int:
    cases = [
        ("брак проверки не стоит оригинала", case_failed_verification),
        ("удаление выключено по умолчанию", case_trash_off_by_default),
        ("оригинал не перезаписывается", case_original_never_overwritten),
        ("повторный запуск безопасен", case_rerun_is_safe),
        ("одно имя с двумя расширениями не сталкивается", case_one_name_two_extensions),
    ]
    print("Гарантии безопасности (CLAUDE.md §2)\n")
    results = [run_case(name, fn) for name, fn in cases]
    failed = results.count(False)
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
