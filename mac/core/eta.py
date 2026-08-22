from __future__ import annotations

import time

from .config import (
    DEFAULT_LANG,
    ETA_ALMOST_DONE,
    ETA_MIN_ELAPSED,
    ETA_SMOOTHING,
    ETA_TAIL_MINIMUM,
)
from .lang import t


def format_left(seconds: float, lang: str = DEFAULT_LANG) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return t(lang, "eta_under_minute")
    if seconds < 3600:
        return t(lang, "eta_minutes", m=round(seconds / 60))
    if seconds < 86400:
        hours = int(seconds // 3600)
        minutes = round((seconds - hours * 3600) / 60)
        if minutes == 60:
            hours, minutes = hours + 1, 0
        if minutes:
            return t(lang, "eta_hours", h=hours, m=minutes)
        return t(lang, "eta_hours_only", h=hours)
    days = int(seconds // 86400)
    hours = round((seconds - days * 86400) / 3600)
    if hours == 24:
        days, hours = days + 1, 0
    if hours:
        return t(lang, "eta_days", d=days, h=hours)
    return t(lang, "eta_days_only", d=days)


class Estimator:
    def __init__(self) -> None:
        self.started: float | None = None
        self.smoothed: float | None = None

    def reset(self, now: float | None = None) -> None:
        self.started = now if now is not None else time.time()
        self.smoothed = None

    def update(
        self,
        done_bytes: float,
        total_bytes: float,
        *,
        now: float | None = None,
        tail_pending: bool = False,
        lang: str = DEFAULT_LANG,
    ) -> str:
        now = now if now is not None else time.time()
        if self.started is None:
            self.started = now

        elapsed = now - self.started
        if total_bytes <= 0 or done_bytes <= 0 or elapsed < ETA_MIN_ELAPSED:
            return t(lang, "eta_calculating")

        share = done_bytes / total_bytes
        if share >= ETA_ALMOST_DONE and not tail_pending:
            return t(lang, "eta_finishing")

        left = elapsed * (1 - share) / share if share > 0 else 0.0

        if self.smoothed is None:
            self.smoothed = left
        else:
            self.smoothed = self.smoothed * ETA_SMOOTHING + left * (1 - ETA_SMOOTHING)

        shown = self.smoothed
        if tail_pending:
            shown = max(shown, ETA_TAIL_MINIMUM)
        return format_left(shown, lang)
