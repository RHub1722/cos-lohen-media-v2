"""Пики акцентов в предмастере.

Замерять надо именно предмастер: в мастере лимитер нормализации сводит все
верхние транзиенты в один потолок, и иерархии по нему не видно.
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

ACCENTS = [
    ("дверь", 22.3, 23.2),
    ("раскрутка", 25.5, 26.9),
    ("вспышка 1", 28.4, 29.9),
    ("вспышка 3", 38.5, 39.9),
    ("удар по нему", 42.7, 44.0),
    ("копьё в пол", 46.9, 47.8),
    ("ФИНАЛЬНЫЙ УДАР", 55.1, 56.3),
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
    print("  Иерархия в порядке: финальный удар — абсолютный пик.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
