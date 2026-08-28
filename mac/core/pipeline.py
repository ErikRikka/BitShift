from __future__ import annotations

import os
import shutil
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable

from .config import (
    JOBS_DEFAULT,
    COPY_JOBS_DEFAULT,
    DEFAULT_AUDIO,
    DEFAULT_RECURSIVE,
    PROGRESS_WEIGHT_AFTER_ENCODE,
    PROGRESS_WEIGHT_COPYING,
    PROGRESS_WEIGHT_ENCODING,
    STAGE_AHEAD,
    STAGING_HEADROOM,
    VERIFY_JOBS,
    VERIFY_JOBS_WHILE_ENCODING,
    VERIFY_SRC_FRAMES_SHARE,
    VERIFY_START_SHARE,
)
from .encode import (
    carry_timestamps, error_summary, is_result_name, result_path, run_encode,
)
from .estimate import output_bytes_guess
from .modes import AUDIO_AAC, AUDIO_ORIGINAL, Codec, Mode, should_skip, target_bitrate
from .probe import (
    MediaInfo, ProbeError, count_frames, frames_countable, probe, reset_probe_cache,
)
from .staging import (
    Slot, StagingArea, copy_in, move_out, reset_volume_cache, volume_info,
)
from .trash import move_to_trash
from .verify import VerifyReport, verify_pair


class State(str, Enum):
    WAITING = "ожидание"
    SKIPPED = "пропущен"
    COPYING = "копирую на SSD"
    QUEUED = "жду слот кодирования"
    ENCODING = "кодирую"
    ENCODED = "жду проверки"
    VERIFYING = "проверяю"
    VERIFIED = "проверен — жду переноса"
    MOVING = "переношу"
    DONE = "готово"
    TRASHED = "оригинал в Корзине"
    FAILED = "брак"
    STOPPED = "остановлено"


TERMINAL = {State.SKIPPED, State.DONE, State.TRASHED, State.FAILED, State.STOPPED}


@dataclass
class Job:
    src: Path
    info: MediaInfo
    final_dst: Path
    target: int
    src_bytes: int = 0
    root: Path | None = None
    label: str = ""
    state: State = State.WAITING
    progress: float = 0.0
    message: str = ""
    slot: Slot | None = None
    encoded: Path | None = None
    report: VerifyReport | None = None
    src_frames: int | None = None
    dst_bytes: int = 0
    saved_bytes: int = 0
    audio_fallback: bool = False
    note: str = ""
    source: Path | None = None
    stage_held: bool = False

    @property
    def name(self) -> str:
        return self.src.name


@dataclass
class Settings:
    mode: Mode
    codec: Codec
    folder: Path
    folders: tuple[Path, ...] = ()
    files: tuple[Path, ...] = ()
    recursive: bool = DEFAULT_RECURSIVE
    audio: str = DEFAULT_AUDIO
    jobs: int = JOBS_DEFAULT
    copy_jobs: int = COPY_JOBS_DEFAULT
    verify_jobs: int = VERIFY_JOBS
    verify_jobs_while_encoding: int = VERIFY_JOBS_WHILE_ENCODING
    use_staging: bool | None = None
    trash_originals: bool = False
    measure_quality: bool = False

    def effective_jobs(self) -> int:
        return 1 if self.codec.software else max(1, self.jobs)

    def roots(self) -> list[Path]:
        found: list[Path] = []
        for group in ([Path(p) for p in self.folders],
                      [Path(f).parent for f in self.files]):
            for path in group:
                if path not in found:
                    found.append(path)
        return found or [Path(self.folder)]

    def scan_dirs(self) -> list[Path]:
        if self.folders:
            return [Path(p) for p in self.folders]
        return [] if self.files else [Path(self.folder)]

    def picked_files(self) -> list[Path]:
        return [Path(f) for f in self.files]


def job_label(path: Path, root: Path, *, recursive: bool, many_roots: bool) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)

    tail = str(relative) if recursive and relative.parent != Path(".") else path.name
    return f"{root.name}/{tail}" if many_roots else tail


def scan(settings: Settings) -> tuple[list[Job], list[Job]]:
    roots = settings.roots()
    many = len(roots) > 1
    pattern = "**/*" if settings.recursive else "*"
    todo: list[Job] = []
    skipped: list[Job] = []
    seen: set[Path] = set()
    claimed: dict[str, Path] = {}

    def make_job(path: Path, root: Path, size: int, info, target: int, dst: Path) -> Job:
        return Job(
            src=path, info=info, final_dst=dst, target=target, src_bytes=size,
            root=root,
            label=job_label(path, root, recursive=settings.recursive, many_roots=many),
        )

    def consider(path: Path, root: Path, *, picked: bool) -> None:
        if not path.is_file() or path.name.startswith("."):
            return
        resolved = path.resolve()
        if resolved in seen:
            return

        wrong_mode = path.suffix.lower() not in settings.mode.exts
        if wrong_mode and not picked:
            return
        if is_result_name(path) and not picked:
            return

        seen.add(resolved)
        dst = result_path(path, settings.codec)

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        if wrong_mode:
            job = make_job(path, root, size, MediaInfo(path=path), 0, dst)
            job.state = State.SKIPPED
            job.message = "не для этого режима"
            skipped.append(job)
            return

        if is_result_name(path):
            job = make_job(path, root, size, MediaInfo(path=path), 0, dst)
            job.state = State.SKIPPED
            job.message = "это уже результат конвертации"
            skipped.append(job)
            return

        try:
            info = probe(path)
        except ProbeError as exc:
            job = make_job(path, root, size, MediaInfo(path=path), 0, dst)
            job.state = State.SKIPPED
            job.message = f"не читается: {exc}"
            skipped.append(job)
            return

        target = target_bitrate(
            settings.mode, info.bit_rate, info.pixel_rate, settings.codec
        )
        job = make_job(path, root, size, info, target, dst)

        if dst.exists():
            job.state = State.SKIPPED
            job.message = f"результат уже есть ({dst.name})"
            skipped.append(job)
            return

        decision = should_skip(
            settings.mode, settings.codec, info.bit_rate, info.codec,
            info.pixel_rate, target,
        )
        if decision.skip:
            job.state = State.SKIPPED
            job.message = decision.reason
            skipped.append(job)
            return

        claim = str(resolved.with_name(dst.name)).casefold()
        rival = claimed.get(claim)
        if rival is not None:
            job.state = State.SKIPPED
            job.message = f"результат совпал бы с «{rival.name}» → {dst.name}"
            skipped.append(job)
            return

        claimed[claim] = path
        todo.append(job)

    for root in settings.scan_dirs():
        for path in sorted(root.glob(pattern)):
            consider(path, root, picked=False)

    for path in settings.picked_files():
        consider(path, path.parent, picked=True)

    return todo, skipped


_STAGE_WEIGHT = {
    State.COPYING: PROGRESS_WEIGHT_COPYING,
    State.ENCODING: PROGRESS_WEIGHT_ENCODING,
}
AFTER_ENCODE = {State.ENCODED, State.VERIFYING, State.VERIFIED, State.MOVING}


def progress_bytes(jobs: Iterable[Job]) -> tuple[float, float]:
    done = 0.0
    total = 0.0
    for job in jobs:
        size = float(job.src_bytes)
        total += size
        if job.state in TERMINAL:
            done += size
        elif job.state in AFTER_ENCODE:
            done += size * PROGRESS_WEIGHT_AFTER_ENCODE
        else:
            done += size * _STAGE_WEIGHT.get(job.state, 0.0) * job.progress
    return done, total


def tail_pending(jobs: Iterable[Job]) -> bool:
    return any(job.state in AFTER_ENCODE for job in jobs)


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        jobs: Iterable[Job],
        on_update: Callable[[Job], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.jobs = list(jobs)
        self._on_update = on_update
        self._on_log = on_log

        self._stop = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set()

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._encoding_now = 0
        self._verifying_now = 0
        self._pids: set[int] = set()
        self._producing_done = False

        self._staging: StagingArea | None = None
        self._transfer_queue: list[Job] = []
        self._stage_slots = threading.Semaphore(
            max(1, settings.effective_jobs()) + STAGE_AHEAD
        )


    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            pids = list(self._pids)
            self._cond.notify_all()

        self._resumed.set()
        for pid in pids:
            self._signal(pid, signal.SIGCONT)
        for pid in pids:
            self._signal(pid, signal.SIGTERM)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @staticmethod
    def _signal(pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _track_pid(self, pid: int, started: bool) -> None:
        with self._cond:
            if not started:
                self._pids.discard(pid)
                return
            self._pids.add(pid)
            if self._stop.is_set():
                self._signal(pid, signal.SIGTERM)
                return
            if not self._resumed.is_set():
                self._signal(pid, signal.SIGSTOP)

    def pause(self) -> None:
        with self._cond:
            self._resumed.clear()
            for pid in self._pids:
                self._signal(pid, signal.SIGSTOP)

    def resume(self) -> None:
        with self._cond:
            self._resumed.set()
            for pid in self._pids:
                self._signal(pid, signal.SIGCONT)
            self._cond.notify_all()


    def _update(self, job: Job, state: State | None = None, message: str | None = None) -> None:
        if state is not None:
            job.state = state
        if message is not None:
            job.message = message
        if self._on_update:
            self._on_update(job)

    def _log(self, text: str) -> None:
        if self._on_log:
            self._on_log(text)

    def _wait_if_paused(self) -> None:
        self._resumed.wait()

    def _should_stage(self) -> bool:
        if self.settings.use_staging is not None:
            return self.settings.use_staging
        return any(volume_info(root).looks_slow for root in self.settings.roots())

    def _file_is_slow(self, job: Job) -> bool:
        if self.settings.use_staging is not None:
            return self.settings.use_staging
        return volume_info(job.src.parent).looks_slow

    def _fits_in_staging(self, job: Job) -> bool:
        if self._staging is None:
            return False
        try:
            free = shutil.disk_usage(self._staging.root).free
            need = job.src_bytes or job.src.stat().st_size
        except OSError:
            return False
        need += output_bytes_guess(
            job.info, job.target, self.settings.codec, self.settings.audio
        )
        return free >= need + STAGING_HEADROOM


    def _stage_in(self, job: Job) -> None:
        if self._stop.is_set() or self._staging is None:
            return

        if not self._file_is_slow(job):
            self._update(job, message="на быстром диске — кодирую на месте")
            return

        if not self._acquire_stage_slot():
            return
        job.stage_held = True

        if not self._fits_in_staging(job):
            self._log(f"{job.name}: в кэш не влезает, кодирую на месте")
            self._release_stage_slot(job)
            return

        job.progress = 0.0
        self._update(job, State.COPYING)
        slot = self._staging.slot(job.src, job.final_dst.name)

        def copy_progress(done: float) -> None:
            job.progress = done
            if self._on_update:
                self._on_update(job)

        try:
            job.source = copy_in(job.src, slot, copy_progress)
        except OSError as exc:
            slot.cleanup()
            self._log(f"{job.name}: кэш не удался ({exc}), кодирую на месте")
            self._release_stage_slot(job)
            return

        job.slot = slot

    def _acquire_stage_slot(self) -> bool:
        while not self._stop.is_set():
            if self._stage_slots.acquire(timeout=0.5):
                return True
        return False

    def _release_stage_slot(self, job: Job) -> None:
        if job.stage_held:
            job.stage_held = False
            self._stage_slots.release()

    def _encode_one(self, job: Job) -> None:
        if self._stop.is_set():
            return
        self._wait_if_paused()

        source = job.source or job.src
        dst = job.slot.dst if job.slot is not None else job.final_dst

        def progress(done: float) -> None:
            job.progress = done
            if self._on_update:
                self._on_update(job)

        def on_retry(reason: str) -> None:
            job.note = f"переделываю: {reason}"
            self._log(f"{job.name}: {reason} — переделываю с декодом на CPU")
            if self._on_update:
                self._on_update(job)

        def encode_with(audio_mode: str):
            with self._cond:
                self._encoding_now += 1
                self._cond.notify_all()
            try:
                job.progress = 0.0
                self._update(job, State.ENCODING)
                return run_encode(
                    source, dst, job.info, self.settings.codec, job.target,
                    audio_mode=audio_mode,
                    on_progress=progress, on_pid=self._track_pid,
                    should_stop=self._stop.is_set,
                    on_retry=on_retry,
                )
            finally:
                with self._cond:
                    self._encoding_now -= 1
                    self._cond.notify_all()

        audio_mode = AUDIO_AAC if job.audio_fallback else self.settings.audio
        result = encode_with(audio_mode)

        if not result.ok and audio_mode == AUDIO_ORIGINAL and not self._stop.is_set():
            job.audio_fallback = True
            job.note = "переделываю: звук не лёг, пересобираю в AAC-стерео"
            self._log(
                f"{job.name}: со звуком как есть не вышло "
                f"({error_summary(result.stderr)}) — повторяю с AAC-стерео"
            )
            result = encode_with(AUDIO_AAC)

        if not result.ok:
            if self._stop.is_set():
                self._update(job, State.STOPPED, "остановлено, файл не переделан")
            else:
                self._update(
                    job, State.FAILED,
                    f"кодирование не удалось: {error_summary(result.stderr)}",
                )
            if job.slot:
                job.slot.cleanup()
            self._release_stage_slot(job)
            return

        if job.slot is not None and job.source is not None:
            try:
                job.source.unlink()
            except OSError:
                pass
        self._release_stage_slot(job)

        job.encoded = dst
        job.progress = 1.0
        self._update(job, State.ENCODED)
        if job.audio_fallback:
            self._log(f"{job.name}: звук пересобран в AAC-стерео — иначе файл не собирался")
        if result.used_cpu_decode:
            self._log(f"{job.name}: аппаратный декод не пошёл, кодировали с CPU-декодом")

    def _verify_one(self, job: Job) -> None:
        if self._stop.is_set() or job.encoded is None:
            return
        self._wait_if_paused()

        with self._cond:
            while not self._stop.is_set():
                limit = (
                    self.settings.verify_jobs_while_encoding
                    if self._encoding_now > 0
                    else self.settings.verify_jobs
                )
                if self._verifying_now < max(1, limit):
                    break
                self._cond.wait(timeout=0.5)
            if self._stop.is_set():
                return
            self._verifying_now += 1

        try:
            job.progress = VERIFY_START_SHARE
            self._update(job, State.VERIFYING)

            def verify_progress(done: float) -> None:
                job.progress = VERIFY_SRC_FRAMES_SHARE + done * (1.0 - VERIFY_SRC_FRAMES_SHARE)
                if self._on_update:
                    self._on_update(job)

            if job.src_frames is None and frames_countable(job.src):
                try:
                    job.src_frames = count_frames(job.src, on_pid=self._track_pid)
                except ProbeError:
                    job.src_frames = None
            job.progress = VERIFY_SRC_FRAMES_SHARE
            self._update(job)

            job.report = verify_pair(
                job.info, job.encoded, self.settings.codec,
                src_frames=job.src_frames,
                measure_quality=self.settings.measure_quality,
                on_progress=verify_progress,
                on_pid=self._track_pid,
            )
        finally:
            with self._cond:
                self._verifying_now -= 1
                self._cond.notify_all()

        if not job.report.ok:
            if self._stop.is_set():
                if job.slot is not None:
                    self._update(job, State.STOPPED, "остановлено на проверке")
                else:
                    self._update(
                        job, State.STOPPED,
                        f"остановлено на проверке — {job.final_dst.name} "
                        f"не проверен",
                    )
                    self._log(
                        f"⚠️  {job.name}: остановлено на проверке, "
                        f"{job.final_dst.name} остался непроверенным"
                    )
                return

            problems = "; ".join(job.report.problems)
            self._update(job, State.FAILED, f"проверка не пройдена: {problems}")
            self._log(f"❌ {job.name}: {problems} — оригинал не тронут")
            if job.encoded and job.encoded.exists() and job.slot is not None:
                job.slot.cleanup()
            elif job.encoded and job.encoded.exists():
                job.encoded.unlink()
            return

        if job.report.decoded_on_cpu:
            self._log(f"{job.name}: аппаратный декодер ругался, проверено на CPU — файл цел")

        self._update(job, State.VERIFIED)
        with self._cond:
            self._transfer_queue.append(job)
            self._cond.notify_all()

    def _transfer_loop(self) -> None:
        while True:
            with self._cond:
                while True:
                    if self._transfer_queue:
                        break
                    if self._producing_done:
                        return
                    self._cond.wait(timeout=0.5)
                job = self._transfer_queue.pop(0)

            try:
                self._finish(job)
            except Exception as exc:
                self._update(job, State.FAILED, f"перенос не удался: {exc}")
                self._log(f"{job.name}: перенос не удался ({exc}), оригинал на месте")

    def _finish(self, job: Job) -> None:
        self._wait_if_paused()
        assert job.encoded is not None

        if job.encoded != job.final_dst:
            job.progress = 0.0
            self._update(job, State.MOVING)

            def move_progress(done: float) -> None:
                job.progress = done
                if self._on_update:
                    self._on_update(job)

            try:
                move_out(job.encoded, job.final_dst, move_progress)
            except OSError as exc:
                self._update(job, State.FAILED, f"не удалось перенести результат: {exc}")
                return
        if job.slot is not None:
            job.slot.cleanup()

        try:
            carry_timestamps(job.src, job.final_dst)
        except OSError:
            pass

        job.dst_bytes = job.final_dst.stat().st_size
        job.saved_bytes = max(0, job.src_bytes - job.dst_bytes)
        self._update(job, State.DONE, "")

        if self.settings.trash_originals and not self._stop.is_set():
            assert job.report is not None and job.report.ok
            result = move_to_trash(job.src)
            if result.ok:
                self._update(job, State.TRASHED)
                where = f" ({result.trashed_to})" if result.trashed_to is not None else ""
                self._log(f"🗑  {job.name} → Корзина{where}")
            else:
                self._log(f"{job.name}: в Корзину не ушёл ({result.error}), оригинал на месте")


    def run(self) -> list[Job]:
        if not self.jobs:
            return []

        reset_volume_cache()
        reset_probe_cache()

        if self._should_stage():
            self._staging = StagingArea()
            self._log(f"Кэш на быстром диске: {self._staging.root}")
        else:
            self._log("Кэширование не нужно — работаем прямо на месте")

        transfer = threading.Thread(target=self._transfer_loop, daemon=True)
        transfer.start()

        try:
            with ThreadPoolExecutor(max_workers=max(1, self.settings.copy_jobs)) as copiers, \
                 ThreadPoolExecutor(max_workers=self.settings.effective_jobs()) as encoders, \
                 ThreadPoolExecutor(max_workers=self.settings.verify_jobs) as verifiers:
                verify_futures: list = []
                staged = {job.src: copiers.submit(self._stage_in, job)
                          for job in self.jobs}

                def encode_then_verify(job: Job) -> None:
                    staged[job.src].result()
                    if not self._stop.is_set():
                        self._update(job, State.QUEUED)
                    try:
                        self._encode_one(job)
                    finally:
                        self._release_stage_slot(job)
                    if job.encoded is not None and not self._stop.is_set():
                        verify_futures.append(verifiers.submit(self._verify_one, job))

                for future in [encoders.submit(encode_then_verify, j) for j in self.jobs]:
                    future.result()
                for future in list(verify_futures):
                    future.result()
        finally:
            with self._cond:
                self._producing_done = True
                self._cond.notify_all()
            transfer.join(timeout=300)
            if self._staging is not None:
                self._staging.cleanup()
            if self._stop.is_set():
                for job in self.jobs:
                    if job.state not in TERMINAL:
                        self._update(job, State.STOPPED, "остановлено, файл не переделан")

        return self.jobs
