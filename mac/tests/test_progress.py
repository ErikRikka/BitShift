from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.pipeline as pipeline_module
import core.staging as staging_module
from core.config import ETA_TAIL_MINIMUM
from core.eta import Estimator, format_left
from core.lang import t as tr
from core.modes import CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Job, Pipeline, Settings, State, progress_bytes, scan
from core.probe import MediaInfo
from core.staging import VolumeInfo, reset_volume_cache, volume_info

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


def fake_job(size: int, state: State, progress: float = 0.0) -> Job:
    job = Job(src=Path("x.mp4"), info=MediaInfo(path=Path("x.mp4")),
              final_dst=Path("x_v2.mp4"), target=0, src_bytes=size)
    job.state = state
    job.progress = progress
    return job


def case_eta_math(_work: Path) -> list[str]:
    problems: list[str] = []

    eta = Estimator()
    eta.reset(0.0)
    calculating = tr("ru", "eta_calculating")
    if eta.update(10, 100, now=10.0) != calculating:
        problems.append("на десятой секунде уже выдаётся оценка, а данных мало")
    if eta.update(0, 100, now=600.0) != calculating:
        problems.append("при нулевом прогрессе выдаётся оценка")

    got = eta.update(10, 100, now=600.0)
    if got != "~1 ч 30 мин":
        problems.append(f"оценка {got}, ожидали «~1 ч 30 мин»")

    if format_left(30) != "меньше минуты":
        problems.append(f"полминуты: {format_left(30)}")
    if format_left(420) != "~7 мин":
        problems.append(f"семь минут: {format_left(420)}")
    if format_left(93_600) != "~1 дн 2 ч":
        problems.append(f"сутки с хвостом: {format_left(93_600)}")

    if format_left(30, "en") != "under a minute":
        problems.append(f"полминуты по-английски: {format_left(30, 'en')}")
    if format_left(420, "en") != "~7 min":
        problems.append(f"семь минут по-английски: {format_left(420, 'en')}")
    if eta.update(10, 100, now=10.0, lang="en") != tr("en", "eta_calculating"):
        problems.append("оценка по-английски осталась русской")
    return problems


def case_eta_is_steady(_work: Path) -> list[str]:
    eta = Estimator()
    eta.reset(0.0)
    eta.update(25, 100, now=600.0)

    texts = [
        eta.update(done, 100, now=600.0)
        for done in (26, 24, 27, 25)
    ]
    problems: list[str] = []
    minutes = {t for t in texts}
    if len(minutes) > 2:
        problems.append(f"метка дёргается: {texts}")
    return problems


def case_eta_tail(_work: Path) -> list[str]:
    eta = Estimator()
    eta.reset(0.0)
    eta.update(99.9, 100, now=600.0)
    tail = eta.update(99.95, 100, now=601.0, tail_pending=True)

    expected = format_left(ETA_TAIL_MINIMUM)
    problems: list[str] = []
    if tail != expected:
        problems.append(f"на хвосте показано «{tail}», ожидали «{expected}»")
    if eta.update(99.95, 100, now=601.0, tail_pending=False) != "завершаем…":
        problems.append("без хвоста на 99,9% должно быть «завершаем…»")
    return problems


def case_progress_counts_bytes(_work: Path) -> list[str]:
    jobs = [
        fake_job(9_000_000_000, State.DONE),
        fake_job(100_000_000, State.WAITING),
        fake_job(100_000_000, State.ENCODING, progress=0.5),
    ]
    done, total = progress_bytes(jobs)

    problems: list[str] = []
    if total != 9_200_000_000:
        problems.append(f"всего байт {total}")
    if not 0.97 < done / total < 0.99:
        problems.append(f"доля по байтам {done / total:.3f}, ожидали ~0.98")
    return problems


def case_volume_info_is_memoized(work: Path) -> list[str]:
    calls: list[str] = []
    real_run = staging_module.subprocess.run

    def counting_run(args, **kwargs):
        if args and args[0] == "diskutil":
            calls.append(str(args[-1]))
        return real_run(args, **kwargs)

    staging_module.subprocess.run = counting_run
    reset_volume_cache()
    try:
        for _ in range(20):
            volume_info(work)
    finally:
        staging_module.subprocess.run = real_run
        reset_volume_cache()

    if len(calls) != 1:
        return [f"diskutil вызван {len(calls)} раз вместо одного"]
    return []


def case_looks_slow_trusts_solid_state(_work: Path) -> list[str]:
    problems: list[str] = []

    hdd_internal = VolumeInfo(mount_point=Path("/"), protocol="PCI-Express", solid_state=False)
    if not hdd_internal.looks_slow:
        problems.append("внутренний HDD не признан медленным")

    ssd_external = VolumeInfo(mount_point=Path("/Volumes/T7"), protocol="USB", solid_state=True)
    if ssd_external.looks_slow:
        problems.append("внешний SSD (Samsung T7 и подобные) всё ещё считается медленным")

    unknown_external = VolumeInfo(mount_point=Path("/Volumes/?"), protocol="USB", solid_state=None)
    if not unknown_external.looks_slow:
        problems.append("внешний диск с неизвестным типом не подстраховался кэшем")

    unknown_internal = VolumeInfo(mount_point=Path("/"), protocol="PCI-Express", solid_state=None)
    if unknown_internal.looks_slow:
        problems.append("внутренний диск с неизвестным типом ошибочно признан медленным")

    return problems


def case_fast_disk_encodes_in_place(work: Path) -> list[str]:
    slow_dir = work / "медленная"
    fast_dir = work / "быстрая"
    make_clip(slow_dir / "S0001.MP4")
    make_clip(fast_dir / "F0001.MP4")

    def fake_volume_info(path):
        text = str(path)
        slow = "медленная" in text or text == str(work)
        return VolumeInfo(mount_point=Path(text), protocol="USB" if slow else "PCI-Express",
                          solid_state=not slow, free_bytes=500 * 1024 ** 3)

    messages: dict[str, set[str]] = {}

    def on_update(job) -> None:
        if job.message:
            messages.setdefault(job.name, set()).add(job.message)

    real = pipeline_module.volume_info
    pipeline_module.volume_info = fake_volume_info
    try:
        settings = Settings(
            mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=work,
            recursive=True, jobs=1, use_staging=None, trash_originals=False,
        )
        todo, _ = scan(settings)
        done = Pipeline(settings, todo, on_update=on_update).run()
    finally:
        pipeline_module.volume_info = real

    problems: list[str] = []
    by_name = {j.name: j for j in done}
    if len(by_name) != 2:
        return [f"взято файлов: {sorted(by_name)}"]

    fast = by_name["F0001.MP4"]
    slow = by_name["S0001.MP4"]

    if fast.slot is not None:
        problems.append("файл с быстрого диска всё равно ушёл в кэш")
    if not any("на быстром диске" in m for m in messages.get("F0001.MP4", ())):
        problems.append(f"статус быстрого файла: {messages.get('F0001.MP4')}")
    if any("на быстром диске" in m for m in messages.get("S0001.MP4", ())):
        problems.append("медленный файл объявлен лежащим на быстром диске")
    if slow.slot is None:
        problems.append("файл с медленного диска кодировался на месте, а не через кэш")
    for job in (fast, slow):
        if job.state is not State.DONE:
            problems.append(f"{job.name}: состояние {job.state.value} — {job.message}")
    return problems


def case_external_ssd_encodes_in_place(work: Path) -> list[str]:
    make_clip(work / "T0001.MP4")

    def fake_volume_info(path):
        return VolumeInfo(mount_point=Path(str(path)), protocol="USB",
                           solid_state=True, free_bytes=500 * 1024 ** 3)

    real = pipeline_module.volume_info
    pipeline_module.volume_info = fake_volume_info
    try:
        settings = Settings(
            mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=work,
            recursive=True, jobs=1, use_staging=None, trash_originals=False,
        )
        todo, _ = scan(settings)
        done = Pipeline(settings, todo).run()
    finally:
        pipeline_module.volume_info = real

    problems: list[str] = []
    if len(done) != 1:
        return [f"взято файлов: {[j.name for j in done]}"]
    job = done[0]
    if job.slot is not None:
        problems.append("внешний SSD (протокол USB, SolidState) всё равно ушёл в кэш")
    if job.state is not State.DONE:
        problems.append(f"{job.name}: состояние {job.state.value} — {job.message}")
    return problems


def case_every_stage_reports_progress(work: Path) -> list[str]:
    make_clip(work / "C0001.MP4")

    seen: dict[State, float] = {}

    def on_update(job) -> None:
        seen[job.state] = max(seen.get(job.state, 0.0), job.progress)

    settings = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=work,
        jobs=1, use_staging=True, trash_originals=False,
    )
    todo, _ = scan(settings)
    done = Pipeline(settings, todo, on_update=on_update).run()

    problems: list[str] = []
    if done[0].state is not State.DONE:
        problems.append(f"состояние {done[0].state.value} — {done[0].message}")

    for state in (State.COPYING, State.ENCODING, State.VERIFYING, State.MOVING):
        if state not in seen:
            problems.append(f"этап «{state.value}» вообще не показался")
        elif seen[state] <= 0.0:
            problems.append(f"этап «{state.value}» не отдал прогресс")
    return problems


def case_verify_does_not_sit_at_zero(work: Path) -> list[str]:
    make_clip(work / "C0001.MP4")

    values: list[float] = []

    def on_update(job) -> None:
        if job.state is State.VERIFYING:
            values.append(job.progress)

    settings = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=work,
        jobs=1, use_staging=False, trash_originals=False,
    )
    todo, _ = scan(settings)
    done = Pipeline(settings, todo, on_update=on_update).run()

    problems: list[str] = []
    if done[0].state is not State.DONE:
        problems.append(f"состояние {done[0].state.value} — {done[0].message}")
    if not values:
        return problems + ["этап проверки не показался"]

    if values[0] <= 0.0:
        problems.append("проверка начинается с нуля — подсчёт кадров не учтён")
    if max(values) < 0.99:
        problems.append(f"шкала не дошла до конца: максимум {max(values):.0%}")
    if not any(0.0 < v < 0.5 for v in values):
        problems.append(f"нет промежуточных значений в первой половине: {values[:5]}")
    return problems


def case_many_folders(work: Path) -> list[str]:
    first = work / "08 Концерт 1"
    second = work / "09 Концерт 2"
    make_clip(first / "C0008.MP4")
    make_clip(second / "C0008.MP4")

    many = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=first,
        folders=(first, second), jobs=1, use_staging=False,
    )
    todo, _ = scan(many)

    problems: list[str] = []
    labels = sorted(j.label for j in todo)
    if labels != ["08 Концерт 1/C0008.MP4", "09 Концерт 2/C0008.MP4"]:
        problems.append(f"метки не различают папки: {labels}")
    if len({j.src for j in todo}) != 2:
        problems.append("файлы из разных папок слились в один")

    one = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODEC_HEVC, folder=first,
        jobs=1, use_staging=False,
    )
    single, _ = scan(one)
    if [j.label for j in single] != ["C0008.MP4"]:
        problems.append(f"с одной папкой метка лишняя: {[j.label for j in single]}")
    if one.roots() != [first]:
        problems.append(f"корни при пустом списке: {one.roots()}")
    return problems


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-прогресса-"))
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
        ("оценка времени: арифметика", case_eta_math),
        ("оценка времени: не дёргается", case_eta_is_steady),
        ("оценка времени: хвост", case_eta_tail),
        ("прогресс считается по байтам", case_progress_counts_bytes),
        ("тип диска спрашивается один раз на том", case_volume_info_is_memoized),
        ("looks_slow доверяет SolidState, а не только протоколу", case_looks_slow_trusts_solid_state),
        ("файл на быстром диске кодируется на месте", case_fast_disk_encodes_in_place),
        ("внешний SSD кодируется на месте, а не через кэш", case_external_ssd_encodes_in_place),
        ("прогресс есть на всех четырёх этапах", case_every_stage_reports_progress),
        ("шкала проверки не стоит в нуле", case_verify_does_not_sit_at_zero),
        ("несколько папок за прогон", case_many_folders),
    ]
    print("Показания интерфейса\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
