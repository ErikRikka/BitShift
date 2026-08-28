from __future__ import annotations

from .config import DEFAULT_LANG, LANGUAGES

SIZE_UNITS = {
    "ru": ("Б", "КБ", "МБ", "ГБ", "ТБ"),
    "en": ("B", "KB", "MB", "GB", "TB"),
}

DECIMAL_MARK = {"ru": ",", "en": "."}

STRINGS: dict[str, dict[str, str]] = {
    "ready": {"ru": "Готов к работе", "en": "Ready"},
    "files_ready": {"ru": "{n} файлов готовы к работе", "en": "{n} files ready"},
    "processed": {"ru": "обработано {done} из {total}", "en": "{done} of {total} done"},
    "stopped_on": {
        "ru": "остановлено на {n} — оригиналы целы",
        "en": "stopped on {n} — originals intact",
    },
    "failed_n": {
        "ru": "брак {n} — оригиналы не тронуты",
        "en": "{n} rejected — originals untouched",
    },
    "stopping": {"ru": "останавливаю…", "en": "stopping…"},
    "delivering": {
        "ru": "доношу проверенные результаты",
        "en": "saving verified results",
    },
    "encoding_count": {"ru": "кодирование {done}/{total}", "en": "encoding {done}/{total}"},
    "in_flight": {"ru": " (в работе {n})", "en": " ({n} running)"},
    "verified_count": {"ru": "проверено {done}/{total}", "en": "verified {done}/{total}"},
    "verifying_now": {"ru": "проверяю {n}", "en": "verifying {n}"},
    "paused": {"ru": "пауза", "en": "paused"},
    "notify_title": {"ru": "BitShift — готово", "en": "BitShift — done"},
    "history_summary": {
        "ru": "Сэкономлено всего: {saved} · {n} файлов",
        "en": "Saved so far: {saved} · {n} files",
    },

    "meta_files": {"ru": "{n} файлов", "en": "{n} files"},
    "meta_folders": {"ru": "папок {n}", "en": "{n} folders"},
    "meta_picked": {"ru": "выбрано поштучно {n}", "en": "{n} picked files"},
    "meta_codec": {"ru": "кодек {name}", "en": "codec {name}"},
    "meta_skipped": {"ru": "{n} пропущено", "en": "{n} skipped"},

    "title_picked": {"ru": "{name} · выбрано {n}", "en": "{name} · {n} picked"},
    "title_more": {"ru": "{name} и ещё {n}", "en": "{name} and {n} more"},
    "no_folder": {"ru": "Папка не выбрана", "en": "No folder selected"},

    "detail_result": {"ru": "→ {codec} · {size}{share}", "en": "→ {codec} · {size}{share}"},
    "detail_bitrate": {"ru": "{a} → {b} Мбит/с", "en": "{a} → {b} Mbps"},

    "state_waiting": {"ru": "ожидание", "en": "waiting"},
    "state_skipped": {"ru": "пропущен", "en": "skipped"},
    "state_copying": {"ru": "копирую на SSD", "en": "copying to SSD"},
    "state_queued": {"ru": "жду слот кодирования", "en": "waiting for encoder"},
    "state_encoding": {"ru": "кодирую", "en": "encoding"},
    "state_encoded": {"ru": "жду проверки", "en": "waiting to verify"},
    "state_verifying": {"ru": "проверяю", "en": "verifying"},
    "state_verified": {"ru": "проверен — жду переноса", "en": "verified — waiting to move"},
    "state_moving": {"ru": "переношу", "en": "moving"},
    "state_done": {"ru": "готово", "en": "done"},
    "state_trashed": {"ru": "оригинал в Корзине", "en": "original in Trash"},
    "state_failed": {"ru": "брак", "en": "rejected"},
    "state_stopped": {"ru": "остановлено", "en": "stopped"},

    "mode_old": {"ru": "Старое видео", "en": "Old video"},
    "mode_slog": {"ru": "Съёмка с камеры", "en": "Camera footage"},
    "mode_arc": {"ru": "Обычное видео", "en": "Regular video"},
    "mode_hint": {"ru": "Берёт файлы: {exts}", "en": "Takes files: {exts}"},

    "codec_av1": {"ru": "AV1", "en": "AV1"},
    "codec_hevc": {"ru": "HEVC", "en": "HEVC"},
    "codec_prores": {"ru": "ProRes 422 HQ", "en": "ProRes 422 HQ"},
    "codec_av1_note": {"ru": "−20% к HEVC", "en": "−20% vs HEVC"},
    "codec_hevc_note": {"ru": "совместимый", "en": "compatible"},
    "codec_prores_note": {"ru": "грейдинг", "en": "grading"},
    "codec_av1_hint": {
        "ru": ("Считается на процессоре — аппаратного AV1 у M1 Pro нет. "
               "Примерно в полтора раза медленнее HEVC, но заметно компактнее "
               "при лучшем качестве. Перемотка и превью такого архива тоже "
               "пойдут через процессор."),
        "en": ("Encoded on the CPU — M1 Pro has no AV1 hardware encoder. "
               "Roughly 1.5× slower than HEVC but noticeably smaller at better "
               "quality. Scrubbing and previews will also use the CPU."),
    },
    "codec_hevc_hint": {"ru": "", "en": ""},
    "codec_prores_hint": {"ru": "", "en": ""},

    "audio_original": {"ru": "Оригинал", "en": "Original"},
    "audio_aac": {"ru": "AAC стерео", "en": "AAC stereo"},
    "audio_original_note": {"ru": "все каналы", "en": "all channels"},
    "audio_aac_note": {"ru": "компактно", "en": "compact"},
    "audio_original_hint": {
        "ru": ("Звук копируется как есть: все дорожки, все каналы, вся "
               "разрядность. Многоканальная запись концерта останется "
               "многоканальной, но и весить будет соответственно."),
        "en": ("Audio is copied untouched: every track, every channel, full "
               "bit depth. A multichannel concert recording stays "
               "multichannel — and stays large."),
    },
    "audio_aac_hint": {
        "ru": ("Звук сводится в стерео AAC 256 кбит/с. Для многодорожечных "
               "записей это разница в разы по размеру файла, но лишние каналы "
               "теряются безвозвратно — в результате их уже не будет."),
        "en": ("Audio is downmixed to stereo AAC 256 kbps. For multitrack "
               "recordings this cuts size several times over, but the extra "
               "channels are gone for good."),
    },

    "engine_cpu": {"ru": "кодирует процессор", "en": "CPU encoding"},

    "picker_message": {
        "ru": "Выберите папки и файлы",
        "en": "Choose folders and files",
    },
    "picker_prompt": {"ru": "Выбрать", "en": "Choose"},
    "trash_failed": {
        "ru": "в Корзину не ушёл: {error}",
        "en": "did not reach the Trash: {error}",
    },
    "shutdown_no_command": {
        "ru": "система не дала команду на выключение",
        "en": "the system refused the shutdown command",
    },

    "eta_calculating": {"ru": "считаю…", "en": "calculating…"},
    "eta_finishing": {"ru": "завершаем…", "en": "finishing…"},
    "eta_under_minute": {"ru": "меньше минуты", "en": "under a minute"},
    "eta_minutes": {"ru": "~{m} мин", "en": "~{m} min"},
    "eta_hours": {"ru": "~{h} ч {m} мин", "en": "~{h} h {m} min"},
    "eta_hours_only": {"ru": "~{h} ч", "en": "~{h} h"},
    "eta_days": {"ru": "~{d} дн {h} ч", "en": "~{d} d {h} h"},
    "eta_days_only": {"ru": "~{d} дн", "en": "~{d} d"},
}


def normalize(lang: str | None) -> str:
    if lang and lang.lower()[:2] in LANGUAGES:
        return lang.lower()[:2]
    return DEFAULT_LANG


def t(lang: str, key: str, **params: object) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(normalize(lang)) or entry.get(DEFAULT_LANG, "")
    return text.format(**params) if params else text


def human_size(size: float, lang: str = DEFAULT_LANG) -> str:
    units = SIZE_UNITS[normalize(lang)]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            text = f"{size:.1f}".rstrip("0").rstrip(".")
            return f"{text.replace('.', DECIMAL_MARK[normalize(lang)])} {unit}"
        size /= 1024
