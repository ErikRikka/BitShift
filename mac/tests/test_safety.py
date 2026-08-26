from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.pipeline as pipeline_module
from core.modes import CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan
from core.trash import TrashResult, TrashUnavailable
from core.trash import move_to_trash as real_move_to_trash
from core.verify import VerifyReport

CLIP_SECONDS = 4.0
REQUIRED_CHECKS = {"кодек", "длительность", "кадры", "декод"}


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
    if not done:
        problems.append("конвейер не взял в работу ни одного файла — кейс ничего не проверил")
    elif done[0].state is not State.FAILED:
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
    if not done:
        problems.append("конвейер не взял в работу ни одного файла")
    elif done[0].state is not State.DONE:
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
    if not done:
        problems.append("конвейер не взял в работу ни одного файла")
    elif done[0].state is not State.DONE:
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


def case_trash_only_after_clean_report(work: Path) -> list[str]:
    src = work / "C0009.MP4"
    make_clip(src)
    trashcan = work / "подставная-корзина"
    trashcan.mkdir()

    settings = make_settings(work, trash_originals=True)
    todo, _ = scan(settings)
    if not todo:
        return ["конвейер не взял в работу ни одного файла — кейс ничего не проверил"]

    moment: list[tuple] = []
    forbidden: list[str] = []
    real_trash = pipeline_module.move_to_trash
    real_unlink = Path.unlink
    real_remove = os.remove

    def fake_trash(path):
        target = Path(path)
        job = next((j for j in todo if j.src == target), None)
        report = job.report if job is not None else None
        moment.append((
            target,
            dict(report.checks) if report is not None else None,
            bool(report is not None and report.ok),
            target.exists(),
        ))
        destination = trashcan / target.name
        shutil.move(str(target), str(destination))
        return TrashResult(True, target, trashed_to=destination)

    def guarded_unlink(self, *args, **kwargs):
        if Path(self) == src:
            forbidden.append("Path.unlink")
            raise AssertionError("оригинал удаляли напрямую")
        return real_unlink(self, *args, **kwargs)

    def guarded_remove(path, *args, **kwargs):
        if Path(path) == src:
            forbidden.append("os.remove")
            raise AssertionError("оригинал удаляли напрямую")
        return real_remove(path, *args, **kwargs)

    pipeline_module.move_to_trash = fake_trash
    Path.unlink = guarded_unlink
    os.remove = guarded_remove
    try:
        done = Pipeline(settings, todo).run()
    finally:
        pipeline_module.move_to_trash = real_trash
        Path.unlink = real_unlink
        os.remove = real_remove

    problems: list[str] = []
    if forbidden:
        problems.append(f"ОРИГИНАЛ УДАЛЯЛИ БЕЗВОЗВРАТНО через {', '.join(forbidden)}")
    if len(moment) != 1:
        problems.append(f"в Корзину отправляли {len(moment)} раз, ожидали один")
        return problems

    path, checks, ok, existed = moment[0]
    if path != src:
        problems.append(f"в Корзину отправили не оригинал, а {path}")
    if not existed:
        problems.append("на момент переноса оригинала уже не было на месте")
    if checks is None:
        problems.append("ОРИГИНАЛ УШЁЛ В КОРЗИНУ БЕЗ ОТЧЁТА О ПРОВЕРКЕ")
    else:
        missing = REQUIRED_CHECKS - set(checks)
        if missing:
            problems.append(f"на момент переноса не было проверок: {sorted(missing)}")
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            problems.append(f"ОРИГИНАЛ УШЁЛ В КОРЗИНУ С ПРОВАЛЕННЫМИ ПРОВЕРКАМИ: {failed}")
    if not ok:
        problems.append("ОРИГИНАЛ УШЁЛ В КОРЗИНУ ПРИ НЕУСПЕШНОМ ОТЧЁТЕ")

    job = done[0]
    if job.state is not State.TRASHED:
        problems.append(f"состояние {job.state.value}, ожидали «оригинал в Корзине»")
    if src.exists():
        problems.append("оригинал остался на месте, хотя помечен как отправленный в Корзину")
    if not (trashcan / src.name).exists():
        problems.append("оригинала нет и в Корзине — файл потерян")
    if job.final_dst is None or not job.final_dst.exists():
        problems.append("оригинал убрали, а результата нет на месте")
    elif job.final_dst.stat().st_size == 0:
        problems.append("оригинал убрали, а результат пустой")
    return problems


def case_trash_is_the_real_trash(work: Path) -> list[str]:
    marker = work / "BitShift-проверка-Корзины.txt"
    marker.write_text(
        "Этот файл создал тест BitShift, чтобы убедиться, "
        "что оригиналы уезжают в системную Корзину, а не удаляются.\n",
        encoding="utf-8",
    )

    try:
        result = real_move_to_trash(marker)
    except TrashUnavailable as exc:
        return [f"Корзина недоступна: {exc}"]

    problems: list[str] = []
    if not result.ok:
        return [f"система отказалась класть файл в Корзину: {result.error}"]
    if marker.exists():
        problems.append("файл остался на месте, хотя Корзина отчиталась об успехе")
    if result.trashed_to is None:
        problems.append("Корзина не сказала, куда положила файл")
    elif not result.trashed_to.exists():
        problems.append(f"по адресу {result.trashed_to} файла нет — он не в Корзине")
    elif ".Trash" not in str(result.trashed_to):
        problems.append(f"файл уехал не в Корзину, а в {result.trashed_to}")
    else:
        print(f"    оставлен в Корзине: {result.trashed_to}")
    return problems


def main() -> int:
    cases = [
        ("брак проверки не стоит оригинала", case_failed_verification),
        ("удаление выключено по умолчанию", case_trash_off_by_default),
        ("оригинал не перезаписывается", case_original_never_overwritten),
        ("повторный запуск безопасен", case_rerun_is_safe),
        ("одно имя с двумя расширениями не сталкивается", case_one_name_two_extensions),
        ("в Корзину только после четырёх сошедшихся проверок", case_trash_only_after_clean_report),
        ("Корзина — настоящая, а не удаление", case_trash_is_the_real_trash),
    ]
    print("Гарантии безопасности (CLAUDE.md §2)\n")
    results = [run_case(name, fn) for name, fn in cases]
    failed = results.count(False)
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
