from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.encode as encode_module
from core.encode import hw_decode_broke, run_encode
from core.modes import CODEC_HEVC
from core.probe import count_frames, probe
from core.verify import verify_pair

HW_FAILURE_STDERR = (
    "[h264 @ 0x14e00] hardware accelerator failed to decode picture\n"
    "[h264 @ 0x14e00] Error submitting packet to decoder\n"
    "[vist#0:0/h264 @ 0x14f00] No frame decoded?\n"
)


def make_clip(path: Path, seconds: float, rate: int = 25, codec: str = "libx264") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"testsrc2=size=640x360:rate={rate}:duration={seconds}",
            "-c:v", codec, "-b:v", "3M", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def run_case(name: str, fn) -> bool:
    work = Path(tempfile.mkdtemp(prefix="тест-проверки-"))
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


def case_hw_marks_recognised(work: Path) -> list[str]:
    problems: list[str] = []
    if not hw_decode_broke(HW_FAILURE_STDERR):
        problems.append("жалобы аппаратного декодера не опознаны")
    if hw_decode_broke("frame= 100 fps=50 speed=2x"):
        problems.append("обычный вывод принят за поломку декодера")
    return problems


def case_zero_exit_with_broken_decoder_is_failure(work: Path) -> list[str]:
    src = work / "источник.mp4"
    make_clip(src, 2.0)
    dst = work / "результат.mp4"
    info = probe(src)

    calls: list[bool] = []
    real = encode_module.run_with_progress

    def fake(cmd, **kwargs):
        used_hw = "videotoolbox" in cmd
        calls.append(used_hw)
        if used_hw:
            dst.write_bytes(b"\x00" * 4096)
            return 0, HW_FAILURE_STDERR
        return real(cmd, **kwargs)

    encode_module.run_with_progress = fake
    try:
        result = run_encode(src, dst, info, CODEC_HEVC, 2_000_000)
    finally:
        encode_module.run_with_progress = real

    problems: list[str] = []
    if not calls or not calls[0]:
        problems.append("первый заход шёл не через аппаратный декодер")
    if len(calls) < 2:
        problems.append("код возврата 0 принят за успех — повтора не было")
    elif calls[1]:
        problems.append("повтор снова пошёл через аппаратный декодер")
    if not result.used_cpu_decode:
        problems.append("результат не помечен как декодированный на процессоре")
    if not result.ok:
        problems.append("повтор на процессоре тоже не удался")
    return problems


def case_no_pointless_retry(work: Path) -> list[str]:
    src = work / "источник.mp4"
    make_clip(src, 1.0)
    dst = work / "результат.mp4"
    info = probe(src)
    info.pix_fmt = "yuv422p10le"

    calls: list[list[str]] = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        return 1, "Error: что-то не так с декодированием"

    real = encode_module.run_with_progress
    encode_module.run_with_progress = fake
    try:
        run_encode(src, dst, info, CODEC_HEVC, 2_000_000)
    finally:
        encode_module.run_with_progress = real

    problems: list[str] = []
    if any("videotoolbox" in cmd for cmd in calls):
        problems.append("для 10 бит 4:2:2 всё-таки просили аппаратный декодер")
    if len(calls) != 1:
        problems.append(f"заходов {len(calls)}: повтор точно той же командой")
    return problems


def case_wrong_codec_rejected(work: Path) -> list[str]:
    src = work / "источник.mp4"
    dst = work / "результат.mp4"
    make_clip(src, 4.0)
    shutil.copy2(src, dst)

    report = verify_pair(probe(src), dst, CODEC_HEVC)
    problems: list[str] = []
    if report.ok:
        problems.append("h264 под видом hevc прошёл проверку")
    if report.checks.get("кодек") is not False:
        problems.append(f"провалилась не та проверка: {report.checks}")
    return problems


def case_short_result_rejected(work: Path) -> list[str]:
    src = work / "источник.mp4"
    dst = work / "результат.mp4"
    make_clip(src, 10.0)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", "4",
         "-c:v", "hevc_videotoolbox", "-tag:v", "hvc1", str(dst)],
        check=True,
    )

    report = verify_pair(probe(src), dst, CODEC_HEVC)
    problems: list[str] = []
    if report.ok:
        problems.append("обрезанный результат прошёл проверку")
    if report.checks.get("длительность") is not False:
        problems.append(f"провалилась не та проверка: {report.checks}")
    return problems


def case_missing_frames_rejected(work: Path) -> list[str]:
    src = work / "источник.mp4"
    dst = work / "результат.mp4"
    make_clip(src, 8.0)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-vf", "select='not(mod(n\\,20))',setpts=N/25/TB",
         "-c:v", "hevc_videotoolbox", "-tag:v", "hvc1", str(dst)],
        check=True,
    )

    real_frames = count_frames(dst)
    src_frames = count_frames(src)
    if abs(src_frames - real_frames) <= 2:
        return [f"подготовка не удалась: кадров {src_frames} → {real_frames}"]

    report = verify_pair(probe(src), dst, CODEC_HEVC, src_frames=src_frames)
    problems: list[str] = []
    if report.checks.get("кадры") is not False:
        problems.append(f"нехватка кадров не поймана: {report.checks}")
    if report.ok:
        problems.append("результат с потерянными кадрами прошёл проверку")
    return problems


def case_good_pair_passes(work: Path) -> list[str]:
    src = work / "источник.mp4"
    dst = work / "результат.mp4"
    make_clip(src, 6.0)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-c:v", "hevc_videotoolbox", "-b:v", "2M", "-tag:v", "hvc1", str(dst)],
        check=True,
    )

    report = verify_pair(probe(src), dst, CODEC_HEVC)
    problems: list[str] = []
    if not report.ok:
        problems.append(f"честная пара забракована: {report.problems}")
    for name in ("кодек", "длительность", "кадры", "декод"):
        if report.checks.get(name) is not True:
            problems.append(f"проверка «{name}» не отработала: {report.checks}")
    return problems


def main() -> int:
    cases = [
        ("жалобы аппаратного декодера опознаются", case_hw_marks_recognised),
        ("код возврата 0 при сломанном декодере — не успех",
         case_zero_exit_with_broken_decoder_is_failure),
        ("нет повтора той же командой", case_no_pointless_retry),
        ("чужой кодек бракуется", case_wrong_codec_rejected),
        ("короткий результат бракуется", case_short_result_rejected),
        ("потерянные кадры ловятся", case_missing_frames_rejected),
        ("честная пара проходит все четыре проверки", case_good_pair_passes),
    ]
    print("Проверка результата (CLAUDE.md §2 и §2.1)\n")
    results = [run_case(name, fn) for name, fn in cases]
    print(f"\nПройдено {results.count(True)} из {len(results)}")
    return 1 if results.count(False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
