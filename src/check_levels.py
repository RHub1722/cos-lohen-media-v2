"""Пики акцентов в предмастере и слышимость ударов под музыкой.

Замерять пики надо именно в предмастере: в мастере лимитер нормализации сводит
все верхние транзиенты в один потолок, и иерархии по нему не видно.

Второй раздел появился после отзывов. Иерархия пиков была в порядке, тест был
зелёный, а слушатели независимо сказали, что удары в бою не слышно и что аудио с
видео не стыкуется. Замер объяснил: у удара по Лоэну запас над музыкой в те же
120 мс был 0.2 dB в середине спектра и −9.7 в верхе, то есть музыка была ГРОМЧЕ
удара. Проверялся порядок акцентов, а не их слышимость.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PREMASTER = ROOT / "output/premaster_v2.wav"
SFX = ROOT / "output/sfx_v2.wav"
MUSIC = ROOT / "output/music_v2.wav"

ACCENTS = [
    ("дверь", 22.3, 23.2),
    ("раскрутка", 25.5, 26.9),
    ("вспышка 1", 28.4, 29.9),
    ("вспышка 3", 38.5, 39.9),
    ("удар по нему", 42.7, 44.0),
    ("копьё в пол", 46.9, 47.8),
    ("ФИНАЛЬНЫЙ УДАР", 55.1, 56.3),
]

# Тело удара. Окно тесное намеренно: в полсекунды попадает и замах, и удар, и
# пиком мог оказаться замах — запас выходил красивый, а удара всё равно не слышно.
BODY = 0.12

# Насколько удар должен быть громче музыки в те же 120 мс. Десять децибел —
# граница, ниже которой эффект перестаёт читаться отдельным событием и слышится
# частью подложки.
MARGIN_DB = 10.0

# По полосам требование другое, и это важно. Сначала я потребовал те же 10 dB в
# каждой из трёх областей — и правило оказалось невыполнимым: глухой удар не может
# доминировать там, где у него нет энергии, и приёмка ругалась на характер ассета,
# а не на дефект микса. Требование к полосам одно: музыка не должна быть ГРОМЧЕ
# удара нигде. Именно этот случай и был найден — у удара по Лоэну в верхней полосе
# музыка стояла на 9.7 dB выше удара.
BAND_FLOOR_DB = 0.0
# Ниже этого полоса печатается как тонкая, но приёмку не валит: это повод
# послушать, а не повод остановить сборку.
BAND_THIN_DB = 6.0

BANDS = (
    ("низ", "lowpass=f=200"),
    ("серед", "highpass=f=200,lowpass=f=2000"),
    ("верх", "highpass=f=2000"),
)

# Удары, которые обязаны пробиваться сквозь музыку. Копьё в пол и финальный тут
# не нужны: на 47.00 музыка обрывается по сценарию, на 55.20 играет только дрон.
IMPACTS = [
    (22.30, "дверь"),
    (28.80, "серия 1"),
    (33.85, "серия 2"),
    (38.60, "серия 3 А"),
    (39.20, "серия 3 Б"),
    (42.80, "удар по нему"),
    (44.90, "серия 4"),
]

VOICES = ROOT / "output/voices_v2.wav"

# Область разборчивости речи. Ниже 300 и выше 4000 Гц на понимание слова почти не
# влияет, а музыка там есть, и широкополосный замер из-за неё врёт.
SPEECH_BAND = "highpass=f=300,lowpass=f=4000"

# Реплики боя. В допросе запас 21–38 dB и проверять там нечего; в бою он был
# 1.7–7.2, то есть под подложку ушёл весь речевой слой. Крик охранника на 22.70
# сюда не входит намеренно: 11.8 dB, и это возглас из толпы, ему разборчивость
# нужна не так, как репликам Лоэна.
LINES = [
    (26.10, 1.4, "Finally"),
    (31.20, 1.6, "Feel that?"),
    (36.40, 1.6, "Is that all you brought?"),
    (41.60, 1.2, "...Really?"),
]


def peak(start: float, end: float) -> float | None:
    """None означает, что замер не удался.

    Нельзя возвращать 0.0 как признак неудачи: все реальные пики отрицательные,
    и ноль оказался бы громче любого из них. Скрипт обвинил бы не то событие, а
    настоящую причину — сорванный замер — не показал бы вообще.
    """
    out = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start}", "-to", f"{end}",
        "-i", str(PREMASTER), "-af", "volumedetect", "-f", "null", "-",
    ], capture_output=True, text=True).stderr
    m = re.search(r"max_volume: (-?[\d.]+)", out)
    return float(m.group(1)) if m else None


def mean(path: Path, start: float, end: float, chain: str = "") -> float | None:
    """Средний уровень в окне, опционально в одной полосе."""
    af = (chain + "," if chain else "") + "volumedetect"
    out = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}", "-i", str(path), "-af", af, "-f", "null", "-",
    ], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+)", out)
    return float(m.group(1)) if m else None


def audibility() -> list[str]:
    """Пробивается ли каждый удар сквозь музыку. Возвращает список провалов."""
    if not (SFX.is_file() and MUSIC.is_file()):
        return [f"нет стемов {SFX.name} и {MUSIC.name} — слышимость не проверить"]

    print(f"  запас удара над музыкой в те же {BODY * 1000:.0f} мс, "
          f"норма от {MARGIN_DB:.0f} dB")
    print(f"  {'удар':16} {'широко':>8} " + " ".join(f"{n:>7}" for n, _ in BANDS))
    failed = []
    for t, name in IMPACTS:
        a, b = t, t + BODY
        wide = [mean(SFX, a, b), mean(MUSIC, a, b)]
        if any(v is None for v in wide):
            failed.append(f"{name}: замер сорван")
            continue
        margins = [wide[0] - wide[1]]
        for _, chain in BANDS:
            s, m = mean(SFX, a, b, chain), mean(MUSIC, a, b, chain)
            margins.append(float("nan") if s is None or m is None else s - m)

        wide_margin = margins[0]
        bands = margins[1:]
        names = [n for n, _ in BANDS]

        marks = []
        if wide_margin < MARGIN_DB:
            marks.append("ТОНЕТ")
            failed.append(f"{name}: широкополосный запас {wide_margin:.1f} dB при "
                          f"норме {MARGIN_DB:.0f} — музыка перебивает удар")
        for label, value in zip(names, bands):
            if value != value:
                continue
            if value < BAND_FLOOR_DB:
                marks.append(f"МУЗЫКА ГРОМЧЕ В «{label}»")
                failed.append(f"{name}: в полосе «{label}» музыка громче удара на "
                              f"{-value:.1f} dB — этого не должно быть нигде")
            elif value < BAND_THIN_DB:
                marks.append(f"тонко в «{label}»")
        tail = "  " + ", ".join(marks) if marks else ""
        print(f"  {name:16} " + " ".join(f"{v:7.1f}" for v in margins) + tail)
    return failed


def dialogue() -> list[str]:
    """Разборчивы ли реплики боя. Возвращает список провалов.

    Удар зал может достроить по картинке, реплику нет. Поэтому норма здесь та же
    десятка, но окно шире: фраза длится от 0.8 до 1.6 с, и мерить её сотыми
    долями бессмысленно.
    """
    if not (VOICES.is_file() and MUSIC.is_file()):
        return [f"нет стемов {VOICES.name} и {MUSIC.name} — речь не проверить"]

    print(f"  запас реплики над музыкой в области разборчивости, "
          f"норма от {MARGIN_DB:.0f} dB")
    print(f"  {'реплика':26} {'голос':>7} {'музыка':>7} {'запас':>7}")
    failed = []
    for t, dur, name in LINES:
        v = mean(VOICES, t, t + dur, SPEECH_BAND)
        m = mean(MUSIC, t, t + dur, SPEECH_BAND)
        if v is None or m is None:
            failed.append(f"«{name}»: замер сорван")
            continue
        margin = v - m
        mark = "  ТОНЕТ" if margin < MARGIN_DB else ""
        print(f"  {name[:26]:26} {v:7.1f} {m:7.1f} {margin:7.1f}{mark}")
        if margin < MARGIN_DB:
            failed.append(f"«{name}»: запас {margin:.1f} dB при норме "
                          f"{MARGIN_DB:.0f} — музыка перебивает реплику")
    return failed


def main() -> int:
    if not PREMASTER.is_file():
        print(f"нет файла {PREMASTER} — сначала собери мастер")
        return 1

    rows = [(label, peak(a, b)) for label, a, b in ACCENTS]
    for label, value in rows:
        print(f"  {label:18} {'  замер сорван' if value is None else f'{value:6.1f} dB'}")
    print()

    failed = [label for label, value in rows if value is None]
    if failed:
        print(f"  ОШИБКА: не удалось замерить {', '.join(failed)} — судить об иерархии нельзя.")
        return 1

    loudest = max(rows, key=lambda r: r[1])
    if loudest[0] != "ФИНАЛЬНЫЙ УДАР":
        print(f"  ВНИМАНИЕ: главный акцент перекрыт — громче всех «{loudest[0]}».")
        return 1
    print("  Иерархия в порядке: финальный удар — абсолютный пик.\n")

    drowned = audibility()
    print()
    drowned += dialogue()
    print()
    if drowned:
        print(f"  НЕ СЛЫШНО {len(drowned)}:")
        for line in drowned:
            print(f"    — {line}")
        return 1
    print("  Каждый удар и каждая реплика пробиваются сквозь музыку.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
