from __future__ import annotations

from dataclasses import dataclass, field

from .config import (
    ARCHIVE_BPP,
    ESTIMATE_OVERHEAD_AV1,
    ESTIMATE_OVERHEAD_HEVC,
    ARCHIVE_SKIP_MARGIN,
    BITRATE_ABSOLUTE_MINIMUM,
    DEFAULT_MODE,
    MIN_GAIN_RATIO,
    QUALITY_RESOLUTION_THRESHOLD,
    QUALITY_VALUES,
)


@dataclass(frozen=True)
class Codec:
    key: str
    name: str
    probe_name: str
    encoder: str
    note: str = ""
    hint: str = ""
    software: bool = False
    by_profile: bool = False
    estimate_overhead: float = 1.0
    preset: str = ""
    bitrate_scale: float = 1.0


CODEC_HEVC = Codec(
    key="hevc",
    name="HEVC",
    probe_name="hevc",
    encoder="hevc_videotoolbox",
    note="совместимый",
    estimate_overhead=ESTIMATE_OVERHEAD_HEVC,
)

CODEC_AV1 = Codec(
    key="av1",
    name="AV1",
    probe_name="av1",
    encoder="libsvtav1",
    note="−20% к HEVC",
    hint=(
        "Считается на процессоре — аппаратного AV1 у M1 Pro нет. "
        "Примерно в полтора раза медленнее HEVC, но заметно компактнее при "
        "лучшем качестве. Перемотка и превью такого архива тоже пойдут "
        "через процессор."
    ),
    software=True,
    preset="8",
    bitrate_scale=0.8,
    estimate_overhead=ESTIMATE_OVERHEAD_AV1,
)

CODEC_PRORES = Codec(
    key="prores",
    name="ProRes 422 HQ",
    probe_name="prores",
    encoder="prores_videotoolbox",
    note="грейдинг",
    by_profile=True,
)

CODECS = {c.key: c for c in (CODEC_AV1, CODEC_HEVC, CODEC_PRORES)}


KIND_OLD = "old"
KIND_CAM = "cam"
KIND_ARC = "arc"


@dataclass(frozen=True)
class Mode:
    key: str
    name: str
    kind: str
    ratio: int
    floor: int
    bpp_min: float
    bpp_max: float
    exts: tuple[str, ...] = field(default=())


MODES: tuple[Mode, ...] = (
    Mode(
        key="old",
        name="Старое видео",
        kind=KIND_OLD,
        ratio=55,
        floor=1_500_000,
        bpp_min=0.0,
        bpp_max=0.15,
        exts=(".avi", ".wmv", ".mts"),
    ),
    Mode(
        key="slog",
        name="Съёмка с камеры",
        kind=KIND_CAM,
        ratio=45,
        floor=0,
        bpp_min=0.10,
        bpp_max=0.20,
        exts=(".mp4", ".mov"),
    ),
    Mode(
        key="arc",
        name="Обычное видео",
        kind=KIND_ARC,
        ratio=100,
        floor=0,
        bpp_min=ARCHIVE_BPP,
        bpp_max=ARCHIVE_BPP,
        exts=(".mp4", ".mov"),
    ),
)

MODES_BY_KEY = {m.key: m for m in MODES}



AUDIO_ORIGINAL = "original"
AUDIO_AAC = "aac"


@dataclass(frozen=True)
class AudioMode:
    key: str
    name: str
    note: str = ""
    hint: str = ""


AUDIO_MODES: tuple[AudioMode, ...] = (
    AudioMode(
        key=AUDIO_ORIGINAL,
        name="Оригинал",
        note="все каналы",
        hint=(
            "Звук копируется как есть: все дорожки, все каналы, вся "
            "разрядность. Многоканальная запись концерта останется "
            "многоканальной, но и весить будет соответственно."
        ),
    ),
    AudioMode(
        key=AUDIO_AAC,
        name="AAC стерео",
        note="компактно",
        hint=(
            "Звук сводится в стерео AAC 256 кбит/с. Для многодорожечных "
            "записей это разница в разы по размеру файла, но лишние каналы "
            "теряются безвозвратно — в результате их уже не будет."
        ),
    ),
)

AUDIO_MODES_BY_KEY = {a.key: a for a in AUDIO_MODES}


def target_bitrate(
    mode: Mode, src_bitrate: int, px: float, codec: Codec | None = None
) -> int:
    target = float(src_bitrate) * mode.ratio / 100.0

    if px > 0:
        lo = px * mode.bpp_min
        hi = px * mode.bpp_max
        target = min(target, hi)
        target = max(target, lo)

    if codec is not None:
        target *= codec.bitrate_scale

    target = max(target, float(mode.floor))
    target = max(target, float(BITRATE_ABSOLUTE_MINIMUM))
    return int(round(target))


def quality_value(mode: Mode, width: int, height: int) -> int | None:
    tier = "4k" if max(width, height) >= QUALITY_RESOLUTION_THRESHOLD else "hd"
    return QUALITY_VALUES.get((mode.key, tier))


@dataclass(frozen=True)
class SkipDecision:
    skip: bool
    reason: str = ""


def should_skip(
    mode: Mode,
    codec: Codec,
    src_bitrate: int,
    src_codec: str,
    px: float,
    target: int,
) -> SkipDecision:
    if src_bitrate <= 0:
        return SkipDecision(True, "не удалось определить битрейт исходника")

    if mode.kind == KIND_CAM and src_codec == codec.probe_name:
        return SkipDecision(True, f"уже в целевом кодеке ({codec.name})")

    if mode.kind == KIND_ARC and px > 0:
        limit = px * ARCHIVE_BPP * ARCHIVE_SKIP_MARGIN
        if src_bitrate <= limit:
            return SkipDecision(True, "уже компактный для архива")

    if target >= src_bitrate * MIN_GAIN_RATIO:
        return SkipDecision(True, "выигрыш меньше 10%")

    return SkipDecision(False)
