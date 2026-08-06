"""Нарезка записанных дублей на отдельные файлы.

Один файл с несколькими дублями подряд — естественный способ записать, но
дальше с ним ничего не сделать: преобразованию голоса нужен один дубль на вход.

Порог тишины и минимальный зазор подбираются **на каждый файл свои**, и это не
лень, а свойство материала: у «Ещё не спишь? Похвально.» внутри реплики своя
пауза между двумя предложениями, а у «Я не могу— они меня убьют—» их две. Единый
порог либо режет реплику пополам, либо склеивает два дубля в один. Числа ниже
сняты замером через --probe, а не выбраны на глаз.

После нарезки у каждого дубля обрезается тишина по краям. Без этого длина дубля
складывается из речи и пауз вокруг неё, а решает она всё: преобразование голоса
сохраняет тайминг ровно, и в номер дубль встанет ровно такой длины, какой записан.

Все дубли сохраняются рядом с исходником: выбранный сегодня может не подойти
завтра, а перезаписать его нечем — второй раз так же не сыграешь.

    python tools/split_takes.py --probe
    python tools/split_takes.py --cut
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MY = ROOT / "assets" / "voices" / "my"

# (порог dB, минимальный зазор с, ожидаемое число дублей или None).
# Ожидание — предохранитель: если нарезка даст другое число, значит порог уехал,
# и «четвёртый дубль» окажется не тем, который выбирали в чате.
PER_FILE = {
    "lohen_security": (-40.0, 0.9, 5),
    # В имени файла стоит all3, но дублей четыре: при пороге, дающем три,
    # второй кусок выходит 11.41 с — для этой реплики физически невозможно.
    # Верим замеру, а не имени.
    "lohen_impressed_all3": (-45.0, 1.2, 4),
    # Середина этого файла сегментируется плохо: паузы внутри реплики того же
    # порядка, что между дублями. Последний дубль при этом читается однозначно
    # при любых настройках, а он и нужен.
    "prisoner_refuse_all": (-40.0, 0.7, 4),
}

DEFAULT = (-40.0, 0.9, None)

MIN_TAKE = 0.35
# Обрезка краёв: порог ниже, чем при поиске дублей, и окно короткое — задача
# другая, снять тишину, а не найти границу.
EDGE_NOISE = -45.0
EDGE_WINDOW = 0.05
# Запас по краям после обрезки. Срез вплотную к первому отсчёту съедает атаку
# согласной, и «Вот!» превращается в «от!».
EDGE_KEEP = 0.04


class SplitError(RuntimeError):
    pass


def sources(only: str = "") -> list[Path]:
    """Исходные записи. Ищутся и в подпапках: перезаписи ложатся в my/v2, my/v3.

    Уже нарезанные дубли отсеиваются по `_take` в имени, иначе второй прогон
    начал бы резать собственный результат.
    """
    if only:
        path = Path(only)
        if not path.is_absolute():
            path = MY / only
        if not path.exists():
            raise SplitError(f"нет файла {path}")
        return [path]
    found = sorted(p for p in MY.rglob("*.wav") if "_take" not in p.stem)
    if not found:
        raise SplitError(f"в {MY} нет исходных записей")
    return found


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip())


def quiet_runs(path: Path, noise: float, gap: float) -> list[tuple[float, float]]:
    result = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af",
         f"silencedetect=noise={noise}dB:d={gap}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [(float(a), float(b)) for a, b in re.findall(
        r"silence_start: (-?[\d.]+)[\s\S]*?silence_end: ([\d.]+)",
        result.stderr)]


def segments(path: Path, noise: float, gap: float) -> list[tuple[float, float]]:
    total = duration(path)
    out, cur = [], 0.0
    for start, end in quiet_runs(path, noise, gap):
        if start - cur >= MIN_TAKE:
            out.append((cur, start))
        cur = end
    if total - cur >= MIN_TAKE:
        out.append((cur, total))
    return out


def speech_bounds(path: Path) -> tuple[float, float]:
    """Где в файле начинается и кончается речь."""
    total = duration(path)
    runs = quiet_runs(path, EDGE_NOISE, EDGE_WINDOW)
    head = 0.0
    for start, end in runs:
        if start <= 0.02:
            head = end
            break
    tail = total
    for start, end in runs:
        if end >= total - 0.02:
            tail = start
    if tail - head < MIN_TAKE:
        # Обрезка съела бы всё — значит порог не подходит этому дублю, и
        # безопаснее оставить как есть, чем выдать огрызок.
        return 0.0, total
    return max(0.0, head - EDGE_KEEP), min(total, tail + EDGE_KEEP)


def peak(path: Path) -> float:
    info = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True,
        encoding="utf-8", errors="replace").stderr
    found = re.findall(r"max_volume:\s*(-?[\d.]+) dB", info)
    return float(found[-1]) if found else 0.0


def slice_to(src: Path, start: float, length: float, target: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}",
        "-t", f"{length:.3f}", "-i", str(src),
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(target),
    ], check=True)


def settings(path: Path, expect: int | None, noise: float | None,
             gap: float | None) -> tuple[float, float, int | None]:
    base_noise, base_gap, base_want = PER_FILE.get(path.stem, DEFAULT)
    return (noise if noise is not None else base_noise,
            gap if gap is not None else base_gap,
            expect if expect is not None else base_want)


def probe(gaps: list[float], only: str = "", expect: int | None = None) -> None:
    for path in sources(only):
        noise, gap, want = settings(path, expect, None, None)
        print(f"\n{path.name}  {duration(path):.2f} с"
              + (f", ожидается {want}" if want else "")
              + f"   [настройка: {noise:.0f} dB / {gap} с]")
        for g in gaps:
            for n in (-30.0, -35.0, -40.0, -45.0, -50.0):
                found = segments(path, n, g)
                mark = ""
                if want is not None and len(found) == want:
                    mark = "  <-- совпало"
                if len(found) > 1:
                    lens = " ".join(f"{b - a:.2f}" for a, b in found)
                    print(f"  {n:>5.0f} dB / {g} с -> {len(found)}: "
                          f"{lens}{mark}")


def cut(only: str = "", expect: int | None = None,
        noise_in: float | None = None, gap_in: float | None = None,
        target_sec: float | None = None) -> None:
    for path in sources(only):
        noise, gap, want = settings(path, expect, noise_in, gap_in)
        found = segments(path, noise, gap)
        if want is not None and len(found) != want:
            raise SplitError(
                f"{path.name}: нарезка дала {len(found)} дублей вместо {want}. "
                f"Порог {noise:.0f} dB / {gap} с больше не подходит — проверь "
                "через --probe. Иначе выбранный дубль окажется не тем")
        print(f"\n{path.name}: {len(found)} дублей "
              f"[{noise:.0f} dB / {gap} с]")
        for i, (start, end) in enumerate(found, 1):
            raw = path.with_name(f"{path.stem}_take{i}.wav")
            slice_to(path, max(0.0, start - 0.06), (end - start) + 0.12, raw)
            head, tail = speech_bounds(raw)
            before = duration(raw)
            if tail - head < before - 0.02:
                slice_to(raw, head, tail - head,
                         raw.with_suffix(".trim.wav"))
                raw.with_suffix(".trim.wav").replace(raw)
            after = duration(raw)
            verdict = ""
            if target_sec is not None:
                verdict = ("   влезает" if after <= target_sec
                           else f"   ПЕРЕБОР {after - target_sec:.2f} с")
            print(f"  дубль {i}: {start:6.2f} - {end:6.2f}   было {before:5.2f} "
                  f"-> {after:5.2f} с   пик {peak(raw):6.1f} dB{verdict}   "
                  f"{raw.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--cut", action="store_true")
    parser.add_argument("--file", default="",
                        help="один файл вместо всех; путь от assets/voices/my")
    parser.add_argument("--expect", type=int,
                        help="сколько дублей ожидается — предохранитель")
    parser.add_argument("--noise", type=float, help="порог тишины, dB")
    parser.add_argument("--gap", type=float, help="минимальный зазор, с")
    parser.add_argument("--target", type=float,
                        help="цель по длине: пометить, какие дубли влезают")
    args = parser.parse_args()
    if args.cut:
        cut(args.file, args.expect, args.noise, args.gap, args.target)
        print(f"\nдубли лежат рядом с исходником")
    else:
        probe([0.7, 0.9, 1.2], args.file, args.expect)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SplitError as failure:
        print(f"ОШИБКА: {failure}", file=sys.stderr)
        sys.exit(1)
