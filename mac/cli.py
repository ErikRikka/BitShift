#!/usr/bin/env python3

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.eta import Estimator
from core.config import DEFAULT_AUDIO, DEFAULT_CODEC, DEFAULT_RECURSIVE, JOBS_DEFAULT
from core.lang import human_size
from core.modes import (
    AUDIO_MODES, AUDIO_MODES_BY_KEY, CODECS, DEFAULT_MODE,
    MODES, MODES_BY_KEY,
)
from core.pipeline import (
    Pipeline, Settings, State, TERMINAL, progress_bytes, scan, tail_pending,
)
from core.trash import trash_available


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BitShift — конвертер видео на VideoToolbox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Режимы:\n" + "\n".join(
            f"  {m.key:6} {m.name:26} {' '.join(m.exts)}" for m in MODES
        ),
    )
    parser.add_argument(
        "папка", type=Path, nargs="+",
        help="папка с исходниками (можно несколько — обойдём все)",
    )
    parser.add_argument(
        "--режим", "--mode", dest="mode", default=DEFAULT_MODE, choices=[m.key for m in MODES],
        help=f"профиль обработки (по умолчанию {DEFAULT_MODE})",
    )
    parser.add_argument(
        "--кодек", "--codec", dest="codec", default=DEFAULT_CODEC, choices=list(CODECS),
        help="целевой кодек (по умолчанию hevc)",
    )
    parser.add_argument(
        "--звук", "--audio", dest="audio", default=DEFAULT_AUDIO,
        choices=[a.key for a in AUDIO_MODES],
        help="aac — свести в стерео AAC 256k (по умолчанию); "
             "original — копировать как есть, все каналы",
    )
    parser.add_argument(
        "--без-подпапок", "--no-subfolders", dest="recursive", action="store_false",
        default=DEFAULT_RECURSIVE,
        help="не заходить во вложенные папки (по умолчанию заходим)",
    )
    parser.add_argument(
        "--потоков", "--jobs", dest="jobs", type=int, default=JOBS_DEFAULT,
        help="параллельных кодирований (по умолчанию 2; на M1 Pro больше не ускоряет)",
    )
    parser.add_argument(
        "--кэш", "--cache", dest="staging",
        choices=["авто", "да", "нет", "auto", "yes", "no"], default="авто",
        help="кэшировать на быстрый диск (по умолчанию — решать по типу тома)",
    )
    parser.add_argument(
        "--в-корзину", "--to-trash", dest="trash", action="store_true",
        help="🔒 удалять проверенные оригиналы в Корзину (по умолчанию выключено)",
    )
    parser.add_argument(
        "--список", "--dry-run", dest="dry_run", action="store_true",
        help="только показать, что будет сделано, и выйти",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    folders = [p.expanduser().resolve() for p in args.папка]
    for folder in folders:
        if not folder.is_dir():
            print(f"Не папка: {folder}")
            return 2
    folder = folders[0]

    staging = {"авто": None, "да": True, "нет": False,
               "auto": None, "yes": True, "no": False}[args.staging]
    settings = Settings(
        mode=MODES_BY_KEY[args.mode],
        codec=CODECS[args.codec],
        folder=folder,
        folders=tuple(folders),
        recursive=args.recursive,
        audio=args.audio,
        jobs=max(1, args.jobs),
        use_staging=staging,
        trash_originals=args.trash,
    )

    if settings.trash_originals and not trash_available():
        print("Удаление в Корзину запрошено, но PyObjC не установлен.")
        print("Выполните: pip install pyobjc-core pyobjc-framework-Cocoa")
        return 2

    for number, one in enumerate(folders):
        print(f"{'Папка: ' if number == 0 else '       '} {one}")
    print(f"Режим:  {settings.mode.name}")
    print(f"Кодек:  {settings.codec.name} ({settings.codec.encoder})")
    print(f"Звук:   {AUDIO_MODES_BY_KEY[settings.audio].name} "
          f"· {AUDIO_MODES_BY_KEY[settings.audio].note}")
    print(f"Оригиналы: {'в Корзину после проверки' if settings.trash_originals else 'остаются на месте'}")
    print("\nСмотрю, что есть...")

    todo, skipped = scan(settings)

    for job in skipped:
        print(f"  — {job.label}: {job.message}")
    if not todo:
        print("\nНечего делать.")
        return 0

    source_bytes = sum(j.src_bytes for j in todo)
    folders_note = f", папок {len(folders)}" if len(folders) > 1 else ""
    print(f"\nВ работу: {len(todo)} файлов, {human_size(source_bytes)}{folders_note}")
    for job in todo:
        print(
            f"  {job.label}  {job.info.bit_rate / 1e6:.1f} → "
            f"{job.target / 1e6:.1f} Мбит/с"
        )

    if args.dry_run:
        return 0

    if settings.trash_originals:
        print("\n🔒 Оригиналы, прошедшие проверку, уйдут в Корзину.")
        answer = input("Продолжить? [да/нет]: ").strip().lower()
        if answer not in ("да", "д", "yes", "y"):
            print("Отменено.")
            return 1

    log_path = folder / f"конвертер-{datetime.now():%Y-%m-%d-%H%M}.log"
    log_file = log_path.open("w", encoding="utf-8")
    log_lock = threading.Lock()

    def write_log(text: str) -> None:
        with log_lock:
            log_file.write(f"{datetime.now():%H:%M:%S}  {text}\n")
            log_file.flush()

    states: dict[Path, State] = {}
    shown_progress: dict[Path, int] = {}
    started = time.time()
    estimator = Estimator()
    estimator.reset(started)
    print_lock = threading.Lock()

    STAGE_NAMES = {
        State.COPYING: "копирование",
        State.ENCODING: "кодирование",
        State.VERIFYING: "проверка",
        State.MOVING: "перенос",
    }

    def bar(share: float, width: int = 10) -> str:
        filled = int(round(min(max(share, 0.0), 1.0) * width))
        return "▓" * filled + "░" * (width - filled)

    def left_note() -> str:
        text = estimator.update(
            *progress_bytes(todo), tail_pending=tail_pending(todo)
        )
        return f" · осталось {text}" if text else ""

    def on_update(job) -> None:
        previous = states.get(job.src)
        stage = STAGE_NAMES.get(job.state)

        if previous == job.state:
            if stage is None:
                return
            percent = round(job.progress * 100)
            step = percent // 5
            if shown_progress.get(job.src) == step or step == 0:
                return
            shown_progress[job.src] = step
            with print_lock:
                print(
                    f"  [{stage} {bar(job.progress)} "
                    f"{percent}%] {job.label}{left_note()}"
                )
            return

        states[job.src] = job.state
        shown_progress.pop(job.src, None)
        done = sum(1 for s in states.values() if s in TERMINAL)
        line = f"[{done}/{len(todo)}] {job.label}: {job.state.value}"
        if job.message:
            line += f" — {job.message}"
        with print_lock:
            print(line + (left_note() if job.state in TERMINAL else ""))
        write_log(line)

    print()
    pipeline = Pipeline(settings, todo, on_update=on_update, on_log=lambda t: (print(f"  {t}"), write_log(t)))

    interrupted = threading.Event()

    def on_interrupt(signum: int, frame: object) -> None:
        if interrupted.is_set():
            raise KeyboardInterrupt
        interrupted.set()
        with print_lock:
            print("\nОстанавливаюсь... (ещё раз Ctrl-C — выйти сразу)")
        threading.Thread(target=pipeline.stop, daemon=True).start()

    previous = signal.signal(signal.SIGINT, on_interrupt)
    try:
        done = pipeline.run()
    except KeyboardInterrupt:
        pipeline.stop()
        done = todo
    finally:
        signal.signal(signal.SIGINT, previous)

    log_file.close()
    elapsed = time.time() - started

    ok = [j for j in done if j.state in (State.DONE, State.TRASHED)]
    bad = [j for j in done if j.state == State.FAILED]
    stopped = [j for j in done if j.state == State.STOPPED]
    saved = sum(j.saved_bytes for j in ok)

    print(f"\n{'Остановлено' if stopped else 'Готово'} за {elapsed / 60:.1f} мин")
    print(f"  успешно: {len(ok)}")
    if stopped:
        print(f"  остановлено: {len(stopped)} — оригиналы целы")
        for job in stopped:
            if job.message:
                print(f"    {job.label}: {job.message}")
    if bad:
        print(f"  брак: {len(bad)} — оригиналы не тронуты")
        for job in bad:
            print(f"    {job.label}: {job.message}")
    if saved:
        print(f"  сэкономлено: {human_size(saved)} (−{saved * 100 / source_bytes:.0f}%)")
    print(f"  лог: {log_path}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
