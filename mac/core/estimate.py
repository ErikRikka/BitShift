from __future__ import annotations

from .config import (
    AUDIO_NOMINAL_BITRATE,
    ESTIMATE_UNKNOWN,
    PRORES_HQ_BITS_PER_PIXEL,
)
from .modes import AUDIO_ORIGINAL, Codec
from .probe import MediaInfo


def audio_bytes(info: MediaInfo, audio_mode: str) -> float:
    if not info.audio_codec or info.duration <= 0:
        return 0.0
    if audio_mode == AUDIO_ORIGINAL:
        rate = info.audio_bit_rate
        if rate <= 0:
            return 0.0
        return rate * info.duration / 8.0
    if info.audio_codec == "aac" and info.audio_channels <= 2:
        rate = info.audio_bit_rate or AUDIO_NOMINAL_BITRATE
        return rate * info.duration / 8.0
    return AUDIO_NOMINAL_BITRATE * info.duration / 8.0


def forecast_bytes(
    info: MediaInfo,
    target: int,
    codec: Codec,
    audio_mode: str,
    *,
    src_bytes: int,
    skipped: bool,
) -> int:
    if skipped or target <= 0:
        return src_bytes
    if codec.by_profile:
        return ESTIMATE_UNKNOWN
    if info.duration <= 0:
        return ESTIMATE_UNKNOWN

    video = target * info.duration / 8.0 * codec.estimate_overhead
    return int(round(video + audio_bytes(info, audio_mode)))


def output_bytes_guess(
    info: MediaInfo, target: int, codec: Codec, audio_mode: str
) -> int:
    if info.duration <= 0:
        return 0
    if codec.by_profile:
        if info.pixel_rate <= 0:
            return 0
        video = info.pixel_rate * PRORES_HQ_BITS_PER_PIXEL / 8.0 * info.duration
        return int(round(video + audio_bytes(info, audio_mode)))
    guess = forecast_bytes(
        info, target, codec, audio_mode, src_bytes=0, skipped=False
    )
    return 0 if guess == ESTIMATE_UNKNOWN else guess


def forecast_total(rows: list[int]) -> tuple[int, bool]:
    total = 0
    complete = True
    for value in rows:
        if value == ESTIMATE_UNKNOWN:
            complete = False
            continue
        total += value
    return total, complete
