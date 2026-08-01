"""Уровень музыкальных слоёв по секундам.

Раскрутка обязана расти от первой метки к последней, а боевой слой —
начинаться сразу на полном уровне: дроп стоит на первой доле.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]

for name in ("music_interrogation", "music_tick", "music_riser",
             "music_combat", "music_ice_drone"):
    path = ROOT / "assets/music" / f"{name}.wav"
    if not path.is_file():
        print(f"{name}: нет файла")
        continue
    total = float(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], capture_output=True, text=True).stdout.strip())
    marks = []
    step = max(1.0, total / 6)
    t = 0.0
    while t < total - 0.5:
        end = min(t + step, total)
        out = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-to", f"{end:.2f}",
            "-i", str(path), "-af", "volumedetect", "-f", "null", "-",
        ], capture_output=True, text=True).stderr
        m = re.search(r"mean_volume: (-?[\d.]+)", out)
        marks.append(f"{t:4.1f}с {m.group(1):>6}" if m else f"{t:4.1f}с      ?")
        t = end
    print(f"{name:20} " + "  ".join(marks))
