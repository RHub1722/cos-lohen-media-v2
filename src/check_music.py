"""Уровень музыкальных слоёв по секундам.

Раскрутка обязана расти от первой метки к последней, а боевой слой —
начинаться сразу на полном уровне: дроп стоит на первой доле.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Как в build.py и import_assets.py: консоль Windows по умолчанию в cp1252
# и падает на кириллице в выводе.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.measure import measure_duration  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

for name in ("music_interrogation", "music_tick", "music_riser",
             "music_combat", "music_ice_drone"):
    path = ROOT / "assets/music" / f"{name}.wav"
    if not path.is_file():
        print(f"{name}: нет файла")
        continue
    total = measure_duration(str(path))
    marks = []
    # Шаг — total/6, но не короче 1 с (иначе короткий файл дробится на
    # бессмысленные доли секунды). Граница цикла — total с микроскопическим
    # запасом (1e-6), а не total само по себе: шесть накопленных сложений
    # step почти никогда не дают total тютелька-в-тютельку из-за погрешности
    # float, и без запаса цикл делает лишний почти нулевой шаг в конце,
    # на котором ffmpeg не возвращает mean_volume ("?" в выводе). Прежний
    # вариант с "total - 0.5" был другой крайностью: на файле короче 6 с
    # такой запас молча терял настоящий хвост (4.4 с файл лишился бы 0.4 с) —
    # райзер однажды чуть не ушёл в релиз пятисекундным, и именно там старая
    # проверка срезала бы пик подъёма, который она должна ловить.
    step = max(1.0, total / 6)
    t = 0.0
    while t < total - 1e-6:
        end = min(t + step, total)
        out = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-to", f"{end:.2f}",
            "-i", str(path), "-af", "volumedetect", "-f", "null", "-",
        ], capture_output=True, text=True).stderr
        m = re.search(r"mean_volume: (-?[\d.]+)", out)
        marks.append(f"{t:4.1f}с {m.group(1):>6}" if m else f"{t:4.1f}с      ?")
        t = end
    print(f"{name:20} " + "  ".join(marks))
