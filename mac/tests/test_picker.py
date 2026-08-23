from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import DEFAULT_AUDIO, DEFAULT_CODEC, DEFAULT_RECURSIVE
from core.estimate import forecast_bytes
from core.modes import AUDIO_AAC, CODECS, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan


def make_clip(path: Path, seconds: float = 2.0, ext: str = "mp4") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=640x360:rate=25:duration={seconds}",
            "-c:v", "libx264", "-b:v", "8M", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-выбора-"))
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


def case_folder_plus_files(work: Path) -> list[str]:
    a, b = work / "A", work / "B"
    for name in ("a1.mp4", "a2.mp4", "a3.mp4"):
        make_clip(a / name)
    for name in ("b1.mp4", "b2.mp4", "b3.mp4"):
        make_clip(b / name)

    settings = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODECS[DEFAULT_CODEC], folder=a,
        folders=(a,), files=(b / "b1.mp4", b / "b2.mp4"), use_staging=False,
    )
    todo, _ = scan(settings)

    problems: list[str] = []
    names = sorted(j.src.name for j in todo)
    if names != ["a1.mp4", "a2.mp4", "a3.mp4", "b1.mp4", "b2.mp4"]:
        problems.append(f"взято не то: {names}")
    if any(j.src.name == "b3.mp4" for j in todo):
        problems.append("сосед по папке подтянулся вместе с выбранными файлами")
    if [r.name for r in settings.roots()] != ["A", "B"]:
        problems.append(f"корни: {[r.name for r in settings.roots()]}")
    return problems


def case_wrong_mode_is_visible(work: Path) -> list[str]:
    make_clip(work / "ролик.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x240:rate=25:duration=1",
         "-c:v", "libx264", "-b:v", "2M", str(work / "старое.avi")],
        check=True,
    )

    settings = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODECS[DEFAULT_CODEC], folder=work,
        files=(work / "старое.avi",), use_staging=False,
    )
    todo, skipped = scan(settings)

    problems: list[str] = []
    if todo:
        problems.append(f"файл чужого режима взят в работу: {[j.label for j in todo]}")
    if not any(j.message == "не для этого режима" for j in skipped):
        problems.append(f"нет строки «не для этого режима»: {[j.message for j in skipped]}")
    return problems


def case_defaults_match_brief(work: Path) -> list[str]:
    make_clip(work / "ролик.mp4")
    settings = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODECS[DEFAULT_CODEC], folder=work,
    )
    problems: list[str] = []
    if settings.audio != AUDIO_AAC:
        problems.append(f"звук по умолчанию {settings.audio}, ожидали aac")
    if DEFAULT_CODEC != "hevc":
        problems.append(f"кодек по умолчанию {DEFAULT_CODEC}, ожидали hevc")
    if not settings.recursive or not DEFAULT_RECURSIVE:
        problems.append("рекурсия по умолчанию выключена")
    if DEFAULT_AUDIO != AUDIO_AAC:
        problems.append("DEFAULT_AUDIO не aac")
    return problems


def case_forecast_matches_reality(work: Path) -> list[str]:
    for name in ("c1.mp4", "c2.mp4", "c3.mp4"):
        make_clip(work / name, seconds=3.0)

    settings = Settings(
        mode=MODES_BY_KEY["arc"], codec=CODECS["hevc"], folder=work,
        use_staging=False,
    )
    todo, _ = scan(settings)
    predicted = sum(
        forecast_bytes(j.info, j.target, settings.codec, settings.audio,
                       src_bytes=j.src_bytes, skipped=False)
        for j in todo
    )

    done = Pipeline(settings, todo).run()
    problems: list[str] = []
    if any(j.state is not State.DONE for j in done):
        return [f"не сконвертировалось: {[(j.name, j.state.value) for j in done]}"]

    actual = sum(j.final_dst.stat().st_size for j in done)
    error = abs(actual - predicted) / actual
    if error > 0.25:
        problems.append(
            f"прогноз разошёлся с фактом на {error:.0%}: "
            f"прогноз {predicted / 1e6:.1f} МБ, факт {actual / 1e6:.1f} МБ"
        )
    return problems


CYRILLIC = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")


def case_picker_is_translated(work: Path) -> list[str]:
    from core.lang import t as tr

    problems: list[str] = []
    for key, expected_ru in (("picker_prompt", "Выбрать"),
                             ("picker_message", "Выберите папки и файлы")):
        ru = tr("ru", key)
        en = tr("en", key)
        if ru != expected_ru:
            problems.append(f"по-русски «{key}» = «{ru}», ждали «{expected_ru}»")
        if en == key:
            problems.append(f"нет английского перевода для «{key}»")
        if CYRILLIC & set(en):
            problems.append(f"в английском «{key}» осталась кириллица: «{en}»")
    return problems


def case_ui_strings_go_through_lang(work: Path) -> list[str]:
    import inspect
    import app as gui

    problems: list[str] = []
    for func, keys in ((gui.Api.choose_folder, ("picker_message", "picker_prompt")),
                       (gui.Api.trash_verified, ("trash_failed",)),
                       (gui.Api._shutdown_countdown, ("shutdown_no_command",))):
        source = inspect.getsource(func)
        for key in keys:
            if key not in source:
                problems.append(
                    f"{func.__qualname__} не берёт «{key}» из словаря"
                )
        for line in source.splitlines():
            text = line.strip()
            if text.startswith("#"):
                continue
            if CYRILLIC & set(text):
                problems.append(
                    f"{func.__qualname__}: русский текст прямо в коде — {text}"
                )
    return problems


def main() -> int:
    cases = [
        ("диалог выбора говорит на своём языке", case_picker_is_translated),
        ("видимые строки идут через словарь", case_ui_strings_go_through_lang),
        ("папка целиком плюс отдельные файлы", case_folder_plus_files),
        ("файл чужого режима виден строкой", case_wrong_mode_is_visible),
        ("умолчания как в брифе части 2", case_defaults_match_brief),
        ("прогноз размера сходится с фактом", case_forecast_matches_reality),
    ]
    print("Выбор источников и прогноз (бриф, часть 2)\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
