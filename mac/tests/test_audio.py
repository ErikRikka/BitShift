from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.encode import audio_args, error_summary
from core.modes import AUDIO_AAC, AUDIO_ORIGINAL, CODEC_HEVC, MODES_BY_KEY
from core.pipeline import Pipeline, Settings, State, scan
from core.probe import MediaInfo, probe

CHANNELS = 16
CLIP_SECONDS = 6.0


def make_multichannel_clip(path: Path) -> None:
    voices = "|".join(f"0.1*sin({200 + 40 * i}*t)" for i in range(CHANNELS))
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size=1280x720:rate=50:duration={CLIP_SECONDS:g}",
            "-f", "lavfi", "-i", f"aevalsrc={voices}:s=48000:d={CLIP_SECONDS:g}",
            "-c:v", "prores_ks", "-profile:v", "3",
            "-c:a", "pcm_s24le",
            str(path),
        ],
        check=True,
    )


def audio_of(path: Path) -> tuple[str, int]:
    info = probe(path)
    return info.audio_codec, info.audio_channels


def run_pipeline(work: Path, audio: str) -> tuple[list, Settings]:
    settings = Settings(
        mode=MODES_BY_KEY["arc"],
        codec=CODEC_HEVC,
        folder=work,
        jobs=1,
        use_staging=False,
        audio=audio,
        trash_originals=False,
    )
    todo, skipped = scan(settings)
    if not todo:
        raise AssertionError(f"файл не взят в работу: {[j.message for j in skipped]}")
    return Pipeline(settings, todo).run(), settings


def case_original_keeps_all_channels(work: Path) -> list[str]:
    src = work / "Capture0000.mov"
    make_multichannel_clip(src)

    done, _ = run_pipeline(work, AUDIO_ORIGINAL)
    job = done[0]

    problems: list[str] = []
    if job.state is not State.DONE:
        problems.append(f"состояние {job.state.value} — {job.message}")
        return problems
    if job.audio_fallback:
        problems.append("сработал аварийный откат, хотя звук должен был лечь копией")

    codec, channels = audio_of(job.final_dst)
    if channels != CHANNELS:
        problems.append(f"каналов на выходе {channels}, ожидали {CHANNELS}")
    if codec != "pcm_s24le":
        problems.append(f"кодек звука {codec}, ожидали pcm_s24le")
    if not src.exists():
        problems.append("ОРИГИНАЛ ПРОПАЛ")
    return problems


def case_aac_downmixes_to_stereo(work: Path) -> list[str]:
    src = work / "Capture0000.mov"
    make_multichannel_clip(src)

    done, _ = run_pipeline(work, AUDIO_AAC)
    job = done[0]

    problems: list[str] = []
    if job.state is not State.DONE:
        problems.append(f"состояние {job.state.value} — {job.message}")
        return problems

    codec, channels = audio_of(job.final_dst)
    if channels != 2:
        problems.append(f"каналов на выходе {channels}, ожидали 2")
    if codec != "aac":
        problems.append(f"кодек звука {codec}, ожидали aac")

    if job.final_dst.stat().st_size >= src.stat().st_size:
        problems.append("результат не меньше оригинала")
    return problems


def make_exotic_audio_clip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size=1280x720:rate=30:duration={CLIP_SECONDS:g}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={CLIP_SECONDS:g}",
            "-c:v", "libx264", "-b:v", "15M", "-pix_fmt", "yuv420p",
            "-c:a", "adpcm_ima_wav",
            str(path),
        ],
        check=True,
    )


def case_emergency_fallback(work: Path) -> list[str]:
    src = work / "Экзотика.mov"
    make_exotic_audio_clip(src)

    done, _ = run_pipeline(work, AUDIO_ORIGINAL)
    job = done[0]

    problems: list[str] = []
    if job.state is not State.DONE:
        problems.append(f"файл потерян: {job.state.value} — {job.message}")
        return problems
    if not job.audio_fallback:
        problems.append("откат не отмечен, хотя копией звук лечь не мог")

    codec, channels = audio_of(job.final_dst)
    if codec != "aac":
        problems.append(f"после отката кодек звука {codec}, ожидали aac")
    if channels != 2:
        problems.append(f"после отката каналов {channels}, ожидали 2")
    if not src.exists():
        problems.append("ОРИГИНАЛ ПРОПАЛ")
    return problems


def case_already_aac_stereo_is_copied(_work: Path) -> list[str]:
    problems: list[str] = []

    stereo_aac = MediaInfo(path=Path("x.mp4"), audio_codec="aac", audio_channels=2)
    if audio_args(stereo_aac, AUDIO_AAC) != ["-c:a", "copy"]:
        problems.append("aac-стерео пережимается заново — потеря качества на ровном месте")

    many_aac = MediaInfo(path=Path("x.mp4"), audio_codec="aac", audio_channels=6)
    if "-ac" not in audio_args(many_aac, AUDIO_AAC):
        problems.append("многоканальный aac идёт без -ac 2 — упадёт на 9+ каналах")

    pcm = MediaInfo(path=Path("x.mov"), audio_codec="pcm_s24le", audio_channels=16)
    if audio_args(pcm, AUDIO_ORIGINAL) != ["-c:a", "copy"]:
        problems.append("в режиме «оригинал» звук не копируется")
    if audio_args(pcm, AUDIO_AAC) != ["-c:a", "aac", "-b:a", "256k", "-ac", "2"]:
        problems.append("в режиме aac не выставлено принудительное стерео")

    silent = MediaInfo(path=Path("x.mp4"))
    if audio_args(silent, AUDIO_ORIGINAL) != ["-an"]:
        problems.append("файл без звука обрабатывается неверно")
    return problems


def case_error_summary_finds_real_error(_work: Path) -> list[str]:
    real_stderr = (
        '[aist#0:1/pcm_s24le] Guessed Channel Layout: 9.1.6\n'
        '[aac @ 0x14f8] Unsupported channel layout "9.1.6"\n'
        '[aost#0:1/aac] Error while opening encoder\n'
    )
    summary = error_summary(real_stderr)

    problems: list[str] = []
    if "Guessed Channel Layout" in summary:
        problems.append(f"в статус попало предупреждение: {summary}")
    if "Unsupported channel layout" not in summary:
        problems.append(f"настоящая ошибка не найдена: {summary}")
    if error_summary("") != "без сообщения":
        problems.append("пустой stderr не описан")
    tail = error_summary("строка один\nстрока два\nстрока три")
    if "строка три" not in tail:
        problems.append(f"без признаков ошибки взят не хвост: {tail}")
    return problems


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-звука-"))
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
        ("разбор stderr находит настоящую ошибку", case_error_summary_finds_real_error),
        ("логика выбора звука", case_already_aac_stereo_is_copied),
        ("«оригинал» сохраняет все 16 каналов", case_original_keeps_all_channels),
        ("«AAC стерео» сводит 16 каналов в 2", case_aac_downmixes_to_stereo),
        ("аварийный откат вместо потери файла", case_emergency_fallback),
    ]
    print("Звук: многоканальный вход и разбор ошибок\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
