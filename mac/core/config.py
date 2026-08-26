from __future__ import annotations

from pathlib import Path

APP_NAME = "BitShift"
APP_VERSION = "3.8.4"
BUNDLED_TOOLS_SUBDIR = "bin"
NOTICE_NAMES = ("LICENSE", "COPYING.GPLv2", "THIRD-PARTY.md", "THIRD-PARTY.ru.md")
BUNDLE_REQUIRED = (
    f"{BUNDLED_TOOLS_SUBDIR}/ffmpeg",
    f"{BUNDLED_TOOLS_SUBDIR}/ffprobe",
    "ui/index.html",
    "ui/style.css",
    "ui/app.js",
) + NOTICE_NAMES
ICON_NAME = "icon.icns"

RESULT_SUFFIX = "_v2"

BITRATE_ABSOLUTE_MINIMUM = 500_000
ARCHIVE_BPP = 0.096
ARCHIVE_SKIP_MARGIN = 1.12
MIN_GAIN_RATIO = 0.9
LANGUAGES = ("ru", "en")
DEFAULT_LANG = "ru"
DEFAULT_MODE = "arc"
DEFAULT_CODEC = "hevc"
DEFAULT_AUDIO = "aac"
DEFAULT_RECURSIVE = True

AUDIO_BITRATE = "256k"
AUDIO_NOMINAL_BITRATE = 256_000
AUDIO_DOWNMIX_CHANNELS = "2"
AUDIO_COPY_MAX_CHANNELS = 2

ESTIMATE_OVERHEAD_HEVC = 1.05
ESTIMATE_OVERHEAD_AV1 = 1.10
ESTIMATE_UNKNOWN = -1
PRORES_HQ_BITS_PER_PIXEL = 3.4

PRORES_PROFILE_HQ = "3"
CODECS_WITHOUT_HW_DECODE = frozenset({"av1"})

FFMPEG_STDERR_TAIL_LINES = 400
FFMPEG_ERROR_MARKS = (
    "error", "unsupported", "invalid", "failed", "not supported",
    "no space", "denied", "cannot", "could not",
)
FFMPEG_NOISE_MARKS = ("Guessed Channel Layout",)
FFMPEG_HW_DECODE_FAILURE_MARKS = (
    "hardware accelerator failed",
    "No frame decoded",
    "Error submitting packet to decoder",
    "Failed setup for format videotoolbox",
)
FFMPEG_DECODE_TROUBLE_HINTS = (
    "videotoolbox", "hwaccel", "hardware", "decode", "decoder", "decoding",
)

PROBE_TIMEOUT = 120
PROBE_CACHE_MAX = 4096
COUNTABLE_EXTS = {".mp4", ".mov", ".m4v"}
EMPTY_COLOR_VALUES = {"", "unknown", "N/A", "reserved"}

DURATION_TOLERANCE_RATIO = 0.02
DURATION_TOLERANCE_MIN = 2.0
FRAME_TOLERANCE = 2
VERIFY_WEIGHT_PROBE = 0.04
VERIFY_WEIGHT_FRAMES = 0.26
VERIFY_WEIGHT_DECODE = 0.70
VERIFY_START_SHARE = 0.03
VERIFY_SRC_FRAMES_SHARE = 0.15

JOBS_DEFAULT = 2
COPY_JOBS_DEFAULT = 1
VERIFY_JOBS = 3
VERIFY_JOBS_WHILE_ENCODING = 1

STAGING_PREFIX = "конвертер-кэш-"
STAGING_COPY_CHUNK = 8 * 1024 ** 2
STAGING_HEADROOM = 5 * 1024 ** 3
STAGE_AHEAD = 1

PROGRESS_WEIGHT_COPYING = 0.05
PROGRESS_WEIGHT_ENCODING = 0.9
PROGRESS_WEIGHT_AFTER_ENCODE = 0.95

ETA_MIN_ELAPSED = 20.0
ETA_ALMOST_DONE = 0.999
ETA_SMOOTHING = 0.75
ETA_TAIL_MINIMUM = 60.0

WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 800
WINDOW_MIN_SIZE = (880, 695)
WINDOW_BACKGROUND = "#0A0A0C"
WINDOW_GLASS = True
GLASS_MATERIAL = "UnderWindowBackground"
GLASS_ATTEMPTS = 120
GLASS_RETRY_DELAY = 0.15
WINDOW_PUSH_INTERVAL = 0.2

NS_FULL_SIZE_CONTENT_VIEW = 1 << 15
NS_TITLE_HIDDEN = 1
NS_TOOLBAR_UNIFIED = 3
NS_SEPARATOR_NONE = 1

SHUTDOWN_DELAY = 120
SHUTDOWN_COMMAND = (
    "osascript", "-e", 'tell application "System Events" to shut down'
)

PREFS_PATH = (
    Path.home() / "Library" / "Application Support" / APP_NAME / "settings.json"
)

LOG_PATH = Path.home() / "Library" / "Logs" / f"{APP_NAME}.log"
