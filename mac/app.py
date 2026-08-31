#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import AppKit
import webview
from PyObjCTools import AppHelper

from core.estimate import forecast_bytes, forecast_total
from core import prefs
from core.lang import human_size as size_text, normalize as normalize_lang, t as tr
from core.eta import Estimator
from core.modes import (
    AUDIO_MODES, AUDIO_MODES_BY_KEY, CODECS, Codec, DEFAULT_MODE,
    MODES, MODES_BY_KEY,
)
from core.pipeline import (
    AFTER_ENCODE, Job, Pipeline, Settings, State, TERMINAL, progress_bytes,
    scan, tail_pending,
)
from core.config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_AUDIO,
    DEFAULT_CODEC,
    DEFAULT_LANG,
    DEFAULT_RECURSIVE,
    LOG_PATH,
    NS_FULL_SIZE_CONTENT_VIEW,
    NS_SEPARATOR_NONE,
    NS_TITLE_HIDDEN,
    NS_TOOLBAR_UNIFIED,
    PROGRESS_WEIGHT_AFTER_ENCODE,
    PROGRESS_WEIGHT_ENCODING,
    SHUTDOWN_COMMAND,
    SHUTDOWN_DELAY,
    GLASS_ATTEMPTS,
    GLASS_MATERIAL,
    GLASS_RETRY_DELAY,
    WINDOW_BACKGROUND,
    WINDOW_GLASS,
    WINDOW_HEIGHT,
    WINDOW_MIN_SIZE,
    WINDOW_PUSH_INTERVAL,
    WINDOW_WIDTH,
)
from core.notify import play_completion_sound, send as send_notification
from core.staging import eject as eject_volume, volume_info
from core.tools import icon_path, resources_dir
from core.trash import move_to_trash, trash_available

TRASHABLE_STATES = {State.DONE}


def system_language() -> str:
    try:
        preferred = AppKit.NSLocale.preferredLanguages()
        if preferred:
            return normalize_lang(str(preferred[0]))
    except Exception:
        pass
    return DEFAULT_LANG


_CHIP_CACHE: str | None = None


def chip_name() -> str:
    global _CHIP_CACHE
    if _CHIP_CACHE is None:
        try:
            _CHIP_CACHE = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            _CHIP_CACHE = ""
    return _CHIP_CACHE


def hardware_name(codec: Codec | None, lang: str) -> str:
    chip = chip_name()
    engine = tr(lang, "engine_cpu") if codec is not None and codec.software else "VideoToolbox"
    return f"{chip} · {engine}" if chip else engine




def all_source_extensions() -> list[str]:
    found: list[str] = []
    for mode in MODES:
        for ext in mode.exts:
            bare = ext.lstrip(".")
            if bare not in found:
                found.append(bare)
    return found


class Api:
    def __init__(self) -> None:
        self.folders: list[Path] = []
        self.files: list[Path] = []
        self.mode = DEFAULT_MODE
        self.codec = DEFAULT_CODEC
        saved_prefs = prefs.load()
        self.lang = normalize_lang(saved_prefs.get("lang") or system_language())
        self.audio = DEFAULT_AUDIO
        self.recursive = DEFAULT_RECURSIVE
        self.trash = trash_available()
        self.shutdown_after = False
        self.eject_after = False
        self.history = saved_prefs.get("history") or {"files": 0, "saved_bytes": 0}
        self.measure_quality = False
        self.finish_id = 0

        self.jobs: list[Job] = []
        self.skipped: list[Job] = []
        self.deselected: set[Path] = set()

        self.pipeline: Pipeline | None = None
        self.worker: threading.Thread | None = None
        self.paused = False
        self.stopping = False
        self.eta = Estimator()
        self.eta_text = ""
        self._caffeinate_proc: subprocess.Popen | None = None
        self._shutdown_at: float | None = None
        self._shutdown_error = ""
        self._control = threading.Lock()
        self._trash_key: tuple | None = None
        self._trash_cache: list[Job] = []
        self._window: webview.Window | None = None


    def _codec_name(self, key: str) -> str:
        return self._t(f"codec_{key}") or CODECS[key].name

    def _size(self, value: float) -> str:
        return size_text(value, self.lang)

    def _t(self, key: str, **params: object) -> str:
        return tr(self.lang, key, **params)

    def attach(self, window: webview.Window) -> None:
        self._window = window

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    @property
    def folder(self) -> Path | None:
        if self.folders:
            return self.folders[0]
        return self.files[0].parent if self.files else None

    def _settings(self) -> Settings:
        return Settings(
            mode=MODES_BY_KEY[self.mode],
            codec=CODECS[self.codec],
            folder=self.folder or Path.home(),
            folders=tuple(self.folders),
            files=tuple(self.files),
            recursive=self.recursive,
            audio=self.audio,
            trash_originals=self.trash,
            measure_quality=self.measure_quality,
        )

    def _selected_jobs(self) -> list[Job]:
        return [j for j in self.jobs if j.src not in self.deselected]

    def _file_payload(self, job: Job, skipped: bool) -> dict:
        info = job.info
        if info.width and info.height:
            detail = f"{info.codec} {info.width}×{info.height} {info.fps:.0f}fps {info.pix_fmt}"
        else:
            detail = job.message or "—"

        if job.state in (State.DONE, State.TRASHED) and job.dst_bytes:
            share = f" · −{job.saved_bytes * 100 / job.src_bytes:.0f}%" if job.src_bytes else ""
            detail = self._t("detail_result", codec=self._codec_name(self.codec),
                             size=self._size(job.dst_bytes), share=share)
            if job.report is not None and job.report.vmaf is not None:
                detail += f" · VMAF {job.report.vmaf:.1f}"
        elif job.note and job.state in (State.ENCODING, State.QUEUED):
            detail = job.note
        elif job.state is State.FAILED and job.message:
            detail = job.message
        elif not skipped and job.target:
            detail = detail + " · " + self._t(
                "detail_bitrate",
                a=f"{info.bit_rate / 1e6:.1f}", b=f"{job.target / 1e6:.1f}",
            )

        size_label = self._size(job.src_bytes) if job.src_bytes else "—"

        return {
            "path": str(job.src),
            "label": job.label or job.name,
            "detail": detail,
            "size_text": size_label,
            "state": job.state.value,
            "state_key": job.state.name.lower(),
            "state_label": self._t(f"state_{job.state.name.lower()}") or job.state.value,
            "message": job.message,
            "progress": job.progress,
            "selected": (not skipped) and job.src not in self.deselected,
            "skipped": skipped,
        }

    def _trashable(self) -> list[Job]:
        key = tuple(job.state for job in self.jobs)
        if key == self._trash_key:
            return self._trash_cache

        result = []
        for job in self.jobs:
            if job.state not in TRASHABLE_STATES:
                continue
            if job.report is None or not job.report.ok:
                continue
            if not job.final_dst.exists() or not job.src.exists():
                continue
            result.append(job)

        self._trash_key = key
        self._trash_cache = result
        return result

    def _summary(self) -> tuple[float, str]:
        selected = self._selected_jobs()
        if not selected:
            return 0.0, self._t("ready")

        total = len(selected)
        done = sum(1 for j in selected if j.state in TERMINAL)
        encoding = sum(1 for j in selected if j.state is State.ENCODING)
        verifying = sum(1 for j in selected if j.state is State.VERIFYING)
        failed = sum(1 for j in selected if j.state is State.FAILED)
        encoded = sum(
            1 for j in selected
            if j.encoded is not None or j.state in (State.DONE, State.TRASHED)
        )
        verified = sum(1 for j in selected if j.report is not None and j.report.ok)

        progress = 0.0
        for job in selected:
            if job.state in TERMINAL:
                progress += 1.0
            elif job.state in AFTER_ENCODE:
                progress += PROGRESS_WEIGHT_AFTER_ENCODE
            elif job.state is State.ENCODING:
                progress += job.progress * PROGRESS_WEIGHT_ENCODING
        percent = progress / total if total else 0.0

        stopped = sum(1 for j in selected if j.state is State.STOPPED)

        if not self.running:
            if done == 0:
                return 0.0, self._t("files_ready", n=total)
            parts = [self._t("processed", done=done - stopped, total=total)]
            if stopped:
                parts.append(self._t("stopped_on", n=stopped))
            if failed:
                parts.append(self._t("failed_n", n=failed))
            return percent, " · ".join(parts)

        if self.stopping:
            parts = [self._t("stopping")]
            if any(j.state is State.MOVING for j in selected):
                parts.append(self._t("delivering"))
            return percent, " · ".join(parts)

        parts = [f"{percent * 100:.0f}%"]
        parts.append(
            self._t("encoding_count", done=encoded, total=total)
            + (self._t("in_flight", n=encoding) if encoding else "")
        )
        if verifying:
            parts.append(self._t("verified_count", done=verified, total=encoded)
                         + " · " + self._t("verifying_now", n=verifying))
        elif encoded:
            parts.append(self._t("verified_count", done=verified, total=encoded))
        if failed:
            parts.append(self._t("failed_n", n=failed))
        if self.paused:
            parts.append(self._t("paused"))
        return percent, " · ".join(parts)

    def _notify_text(self) -> str:
        selected = self._selected_jobs()
        total = len(selected)
        done = sum(1 for j in selected if j.state in TERMINAL)
        stopped = sum(1 for j in selected if j.state is State.STOPPED)
        failed = sum(1 for j in selected if j.state is State.FAILED)
        parts = [self._t("processed", done=done - stopped, total=total)]
        if failed:
            parts.append(self._t("failed_n", n=failed))
        return " · ".join(parts)

    def _folder_short(self) -> str:
        if not self.folder:
            return ""
        if len(self.folders) > 1:
            return self._t("title_more", name=self._short(self.folder), n=len(self.folders) - 1)
        return self._short(self.folder)

    def _folder_title(self) -> str:
        if not self.folder:
            return ""
        if self.files_only:
            return self._t("title_picked", name=self.folder.name, n=len(self.files))
        if len(self.folders) > 1:
            return self._t("title_more", name=self.folder.name, n=len(self.folders) - 1)
        return self.folder.name

    @staticmethod
    def _short(folder: Path) -> str:
        parts = folder.parts
        if len(parts) <= 3:
            return str(folder)
        return "…/" + "/".join(parts[-2:])

    @property
    def files_only(self) -> bool:
        return bool(self.files) and not self.folders

    def _forecast(self) -> str:
        if self.running:
            return ""
        selected = self._selected_jobs()
        if not selected:
            return ""
        codec = CODECS[self.codec]
        rows = [
            forecast_bytes(
                job.info, job.target, codec, self.audio,
                src_bytes=job.src_bytes, skipped=False,
            )
            for job in selected
        ]
        total, complete = forecast_total(rows)
        if not complete or total <= 0:
            return ""
        source = sum(j.src_bytes for j in selected)
        share = f" · −{(source - total) * 100 / source:.0f}%" if source else ""
        return f"~{self._size(total)}{share}"

    def _eta(self) -> str:
        if not self.running:
            return ""
        selected = self._selected_jobs()
        done, total = progress_bytes(selected)
        self.eta_text = self.eta.update(
            done, total, tail_pending=tail_pending(selected), lang=self.lang
        )
        return self.eta_text

    def get_state(self) -> dict:
        selected = self._selected_jobs()
        source_bytes = sum(j.src_bytes for j in selected)
        saved = sum(j.saved_bytes for j in selected)
        percent, summary = self._summary()

        files = [self._file_payload(j, False) for j in self.jobs]
        files += [self._file_payload(j, True) for j in self.skipped]

        meta = "—"
        if self.folder:
            shown = len(self.jobs) + len(self.skipped)
            parts = [self._t("meta_files", n=shown)]
            if len(self.folders) > 1:
                parts.append(self._t("meta_folders", n=len(self.folders)))
            if self.files:
                parts.append(self._t("meta_picked", n=len(self.files)))
            parts.append(self._t("meta_codec", name=self._codec_name(self.codec)))
            if self.skipped:
                parts.append(self._t("meta_skipped", n=len(self.skipped)))
            meta = " · ".join(parts)

        return {
            "hardware": hardware_name(CODECS[self.codec], self.lang),
            "modes": [
                {"key": m.key,
                 "name": self._t(f"mode_{m.key}") or m.name,
                 "hint": self._t("mode_hint",
                                 exts=", ".join(e.lstrip(".") for e in m.exts))}
                for m in MODES
            ],
            "codecs": [
                {"key": c.key,
                 "name": self._codec_name(c.key),
                 "note": self._t(f"codec_{c.key}_note") or c.note,
                 "hint": self._t(f"codec_{c.key}_hint") or c.hint}
                for c in CODECS.values()
            ],
            "audio_modes": [
                {"key": a.key,
                 "name": self._t(f"audio_{a.key}") or a.name,
                 "note": self._t(f"audio_{a.key}_note") or a.note,
                 "hint": self._t(f"audio_{a.key}_hint") or a.hint}
                for a in AUDIO_MODES
            ],
            "lang": self.lang,
            "languages": [
                {"key": "ru", "name": "Русский"},
                {"key": "en", "name": "English"},
            ],
            "version": APP_VERSION,
            "mode": self.mode,
            "codec": self.codec,
            "audio": self.audio,
            "folder": "\n".join(str(p) for p in self.folders),
            "folder_short": self._folder_short(),
            "forecast_text": self._forecast(),
            "files_only": self.files_only,
            "folder_name": self._folder_title(),
            "folder_meta": meta,
            "recursive": self.recursive,
            "shutdown_after": self.shutdown_after,
            "shutdown_in": self.shutdown_left(),
            "shutdown_error": self._shutdown_error,
            "eject_after": self.eject_after,
            "measure_quality": self.measure_quality,
            "history_text": self._history_text(),
            "trash": self.trash,
            "trash_available": trash_available(),
            "running": self.running,
            "finish_id": self.finish_id,
            "paused": self.paused,
            "stopping": self.stopping,
            "files": files,
            "selected_count": len(selected),
            "can_start": bool(selected),
            "source_text": self._size(source_bytes) if source_bytes else "—",
            "saved_text": (
                f"{self._size(saved)} · −{saved * 100 / source_bytes:.0f}%"
                if saved and source_bytes else (self._size(saved) if saved else "")
            ),
            "left_text": self._eta(),
            "percent": percent,
            "summary": summary,
            "trashable": len(self._trashable()),
        }


    def set_mode(self, key: str) -> dict:
        if not self.running and key in MODES_BY_KEY:
            self.mode = key
            self._rescan()
        return self.get_state()

    def set_codec(self, key: str) -> dict:
        if not self.running and key in CODECS:
            self.codec = key
            self._rescan()
        return self.get_state()

    def set_audio(self, key: str) -> dict:
        if not self.running and key in AUDIO_MODES_BY_KEY:
            self.audio = key
        return self.get_state()

    def set_recursive(self, value: bool) -> dict:
        if not self.running:
            self.recursive = bool(value)
            self._rescan()
        return self.get_state()

    def set_drag(self, enabled: bool) -> None:
        view = self._browser_view()
        if view is None:
            return
        view.frameless = bool(enabled)
        view.easy_drag = bool(enabled)

    def _browser_view(self):
        if self._window is None:
            return None
        try:
            from webview.platforms.cocoa import BrowserView
        except ImportError:
            return None
        return BrowserView.instances.get(self._window.uid)

    def set_shutdown_after(self, value: bool) -> dict:
        if not self.running:
            self.shutdown_after = bool(value)
        return self.get_state()

    def set_eject_after(self, value: bool) -> dict:
        if not self.running:
            self.eject_after = bool(value)
        return self.get_state()

    def set_measure_quality(self, value: bool) -> dict:
        if not self.running:
            self.measure_quality = bool(value)
        return self.get_state()

    def set_lang(self, key: str) -> dict:
        chosen = normalize_lang(key)
        if chosen != self.lang:
            self.lang = chosen
            prefs.remember(lang=chosen)
        return self.get_state()

    def set_trash(self, value: bool) -> dict:
        if not self.running:
            self.trash = bool(value) and trash_available()
        return self.get_state()

    def toggle_file(self, path: str, selected: bool) -> dict:
        if not self.running:
            target = Path(path)
            if selected:
                self.deselected.discard(target)
            else:
                self.deselected.add(target)
        return self.get_state()

    def set_selection(self, paths: list[str], selected: bool) -> dict:
        if not self.running:
            for raw in paths:
                target = Path(raw)
                if selected:
                    self.deselected.discard(target)
                else:
                    self.deselected.add(target)
        return self.get_state()


    def add_dropped(self, paths: list[str]) -> dict:
        if self.running:
            return self.get_state()

        folders: list[Path] = []
        files: list[Path] = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                folders.append(path)
            elif path.is_file():
                files.append(path)

        if folders or files:
            self.folders = folders
            self.files = files
            self.deselected.clear()
            self._rescan()
            self._push()
        return self.get_state()

    def choose_folder(self) -> dict:
        if self.running:
            return self.get_state()

        picked: list[str] = []
        done = threading.Event()

        def show_panel() -> None:
            try:
                panel = AppKit.NSOpenPanel.openPanel()
                panel.setCanChooseFiles_(True)
                panel.setCanChooseDirectories_(True)
                panel.setAllowsMultipleSelection_(True)
                panel.setAllowedFileTypes_(all_source_extensions())
                panel.setMessage_(self._t("picker_message"))
                panel.setPrompt_(self._t("picker_prompt"))
                if panel.runModal() == AppKit.NSModalResponseOK:
                    picked.extend(str(url.path()) for url in panel.URLs())
            finally:
                done.set()

        AppHelper.callAfter(show_panel)
        done.wait()

        if picked:
            folders: list[Path] = []
            files: list[Path] = []
            for raw in picked:
                path = Path(raw)
                (folders if path.is_dir() else files).append(path)
            self.folders = folders
            self.files = files
            self.deselected.clear()
            self._rescan()
        return self.get_state()

    def rescan(self) -> dict:
        if not self.running:
            self._rescan()
        return self.get_state()

    def _rescan(self) -> None:
        if not self.folder:
            return
        self.jobs, self.skipped = scan(self._settings())


    def start(self) -> dict:
        with self._control:
            if self.running:
                return self.get_state()
            jobs = self._selected_jobs()
            if not jobs:
                return self.get_state()
            self._launch(jobs)
        return self.get_state()

    def _launch(self, jobs: list[Job]) -> None:
        settings = self._settings()
        self.pipeline = Pipeline(settings, jobs, on_log=self._note)
        self.paused = False
        self.stopping = False
        self._shutdown_at = None
        self._shutdown_error = ""
        self.eta.reset()
        self.eta_text = ""
        self._start_caffeinate()

        def work() -> None:
            natural = False
            try:
                self.pipeline.run()
                natural = (
                    self.pipeline is not None
                    and not self.pipeline.stopped
                    and not self.stopping
                )
            finally:
                self.stopping = False
                if natural:
                    self.finish_id += 1
                    self._record_history()
                    send_notification(self._t("notify_title"), self._notify_text())
                    play_completion_sound()
                self._push()
                if self.eject_after and natural:
                    self._eject_volumes()
                if self.shutdown_after and natural:
                    self._arm_shutdown()

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        threading.Thread(target=self._push_loop, daemon=True).start()

    def pause_toggle(self) -> dict:
        with self._control:
            if self.pipeline and self.running and not self.stopping:
                if self.paused:
                    self.pipeline.resume()
                    self.paused = False
                else:
                    self.pipeline.pause()
                    self.paused = True
        return self.get_state()

    def stop(self) -> dict:
        with self._control:
            if self.pipeline and self.running and not self.stopping:
                self.stopping = True
                if self.paused:
                    self.pipeline.resume()
                    self.paused = False
                threading.Thread(target=self.pipeline.stop, daemon=True).start()
        return self.get_state()

    def trash_verified(self) -> dict:
        if self.running:
            return self.get_state()
        for job in self._trashable():
            assert job.report is not None and job.report.ok
            if not job.final_dst.exists():
                continue
            result = move_to_trash(job.src)
            if result.ok:
                job.state = State.TRASHED
            else:
                job.message = self._t("trash_failed", error=result.error)
        return self.get_state()


    def _note(self, text: str) -> None:
        note_to_log(text)

    def _record_history(self) -> None:
        done = [j for j in self._selected_jobs() if j.state in (State.DONE, State.TRASHED)]
        if not done:
            return
        self.history = {
            "files": int(self.history.get("files", 0)) + len(done),
            "saved_bytes": (
                int(self.history.get("saved_bytes", 0))
                + sum(j.saved_bytes for j in done)
            ),
        }
        prefs.remember(history=self.history)

    def _history_text(self) -> str:
        files = int(self.history.get("files", 0))
        if not files:
            return ""
        saved = self._size(float(self.history.get("saved_bytes", 0)))
        return self._t("history_summary", saved=saved, n=files)

    def _eject_volumes(self) -> None:
        mounts: list[Path] = []
        for job in self._selected_jobs():
            try:
                info = volume_info(job.src.parent)
            except OSError:
                continue
            if info.is_external_usb and info.mount_point not in mounts:
                mounts.append(info.mount_point)
        for mount in mounts:
            ok, error = eject_volume(mount)
            if not ok:
                self._note(f"извлечь {mount.name} не вышло: {error}")


    def shutdown_left(self) -> int | None:
        if self._shutdown_at is None:
            return None
        return max(0, int(round(self._shutdown_at - time.time())))

    def cancel_shutdown(self) -> dict:
        self._shutdown_at = None
        return self.get_state()

    def _arm_shutdown(self) -> None:
        self._shutdown_error = ""
        self._shutdown_at = time.time() + SHUTDOWN_DELAY
        threading.Thread(target=self._shutdown_countdown, daemon=True).start()

    def _shutdown_countdown(self) -> None:
        while True:
            left = self.shutdown_left()
            if left is None:
                self._push()
                return
            if left <= 0:
                break
            self._push()
            time.sleep(0.5)

        self._shutdown_at = None
        self._stop_caffeinate()
        try:
            proc = subprocess.run(
                list(SHUTDOWN_COMMAND), capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._shutdown_error = str(exc)
        else:
            if proc.returncode != 0:
                self._shutdown_error = (
                    (proc.stderr or "").strip()[:200]
                    or self._t("shutdown_no_command")
                )
        if self._shutdown_error:
            self._start_caffeinate()
        self._push()


    def _start_caffeinate(self) -> None:
        if self._caffeinate_proc:
            return
        try:
            self._caffeinate_proc = subprocess.Popen(["caffeinate", "-dim"])
        except OSError:
            self._caffeinate_proc = None

    def _stop_caffeinate(self) -> None:
        if self._caffeinate_proc:
            self._caffeinate_proc.terminate()
            self._caffeinate_proc = None

    def _push(self) -> None:
        if self._window is None:
            return
        try:
            payload = json.dumps(self.get_state(), ensure_ascii=False)
            self._window.evaluate_js(f"window.applyState({payload})")
        except Exception:
            pass

    def _push_loop(self) -> None:
        while self.running or self._shutdown_at is not None:
            self._push()
            time.sleep(WINDOW_PUSH_INTERVAL)
        self._push()


def apply_dock_identity() -> None:
    icon = icon_path()
    if icon is None:
        return
    def put() -> None:
        try:
            image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon))
            if image is not None:
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(image)
        except Exception as exc:
            note_to_log(f"значок в доке: не вышло ({exc})")
    AppHelper.callAfter(put)


def note_to_log(text: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
    except OSError:
        pass


def wait_for_native(window: webview.Window):
    for _ in range(60):
        native = getattr(window, "native", None)
        if native is not None:
            return native
        time.sleep(0.05)
    return None


def apply_dark_appearance() -> None:
    def put() -> None:
        try:
            dark = AppKit.NSAppearance.appearanceNamed_(
                AppKit.NSAppearanceNameDarkAqua
            )
            AppKit.NSApplication.sharedApplication().setAppearance_(dark)
        except Exception as exc:
            note_to_log(f"тёмный вид: не вышло ({exc})")

    AppHelper.callAfter(put)


def apply_glass(window: webview.Window) -> None:
    if not WINDOW_GLASS:
        return
    native = wait_for_native(window)
    if native is None:
        note_to_log("стекло: окна так и не появилось, слой не поставлен")
        return

    def put(left: int = GLASS_ATTEMPTS) -> None:
        try:
            host = native.contentView()
            below = next(iter(host.subviews()), None)
            if below is None:
                if left > 0:
                    AppHelper.callLater(GLASS_RETRY_DELAY, put, left - 1)
                else:
                    note_to_log(
                        f"стекло: за {GLASS_ATTEMPTS} попыток webview так и не появился"
                    )
                return
            if any(v.__class__.__name__ == "NSVisualEffectView"
                   for v in host.subviews()):
                return

            effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(host.bounds())
            effect.setAutoresizingMask_(
                AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
            )
            material = getattr(
                AppKit, f"NSVisualEffectMaterial{GLASS_MATERIAL}", None
            )
            if material is not None:
                effect.setMaterial_(material)
            else:
                note_to_log(
                    f"стекло: материала {GLASS_MATERIAL} нет, оставил стандартный"
                )
            effect.setState_(AppKit.NSVisualEffectStateActive)
            effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            host.addSubview_positioned_relativeTo_(
                effect, AppKit.NSWindowBelow, below
            )
            native.setHasShadow_(True)

            placed = any(v.__class__.__name__ == "NSVisualEffectView"
                         for v in host.subviews())
            note_to_log(f"стекло: слой {'поставлен' if placed else 'НЕ поставлен'}")
        except Exception as exc:
            note_to_log(f"стекло: не вышло ({exc})")

    AppHelper.callAfter(put)


def apply_native_titlebar(window: webview.Window) -> None:
    native = wait_for_native(window)
    if native is None:
        note_to_log("шапка: окна так и не появилось")
        return

    def apply() -> None:
        try:
            native.setStyleMask_(native.styleMask() | NS_FULL_SIZE_CONTENT_VIEW)
            native.setTitlebarAppearsTransparent_(True)
            native.setTitleVisibility_(NS_TITLE_HIDDEN)

            toolbar = AppKit.NSToolbar.alloc().initWithIdentifier_(APP_NAME)
            toolbar.setShowsBaselineSeparator_(False)
            native.setToolbar_(toolbar)
            native.setToolbarStyle_(NS_TOOLBAR_UNIFIED)
            native.setTitlebarSeparatorStyle_(NS_SEPARATOR_NONE)

            strip = native.contentView().superview().subviews().lastObject()
            strip.setBackgroundColor_(AppKit.NSColor.clearColor())

        except Exception as exc:
            note_to_log(f"шапка: не вышло ({exc})")

    AppHelper.callAfter(apply)


def setup_drag_drop(window: webview.Window, api: Api) -> None:
    def on_drop(event) -> None:
        files = (event.get("dataTransfer") or {}).get("files", [])
        paths = [f["pywebviewFullPath"] for f in files if "pywebviewFullPath" in f]
        if paths:
            api.add_dropped(paths)

    window.dom.body.events.drop += on_drop


def main() -> int:
    api = Api()
    api._start_caffeinate()
    window = webview.create_window(
        APP_NAME,
        str(resources_dir() / "ui" / "index.html"),
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN_SIZE,
        background_color=WINDOW_BACKGROUND,
        transparent=WINDOW_GLASS,
    )
    api.attach(window)
    if not WINDOW_GLASS:
        window.events.loaded += lambda: window.evaluate_js(
            f"document.body.style.background = {json.dumps(WINDOW_BACKGROUND)}"
        )
    window.events.shown += lambda: apply_native_titlebar(window)
    window.events.shown += lambda: apply_glass(window)
    window.events.shown += apply_dock_identity
    window.events.shown += lambda: setup_drag_drop(window, api)
    apply_dark_appearance()
    webview.start(apply_native_titlebar, window)
    api._stop_caffeinate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
