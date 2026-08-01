"""Точка входа сборки.

    python src/build.py [--scenario ...] [--suffix ...] [--check-only]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Консоль Windows по умолчанию в cp1252 и падает на кириллице в выводе.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.measure import measure_duration, measure_loudness, measure_window  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.probe import probe  # noqa: E402
from src.render_audio import render_all  # noqa: E402
from src.validator import check_timeline, format_problems, has_errors  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Границы блоков из спеки, раздел 12. Нужны для проверки сжатия динамики:
# допрос не должен быть тише боя больше чем на 8 LU, иначе в шумном зале
# первые восемнадцать секунд просто не разберут.
INTERROGATION = (0.0, 18.6)
COMBAT = (20.6, 44.0)
MAX_SPREAD_LU = 8.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(ROOT / "scenario" / "timeline.json"))
    ap.add_argument("--suffix", default="v2")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    tl = Timeline.load(args.scenario)
    assets = ROOT / "assets"
    print(f"Сценарий: {args.scenario}")
    print(f"Событий: {len(tl.events)}, длительность {tl.total_duration:.3f} с\n")

    problems = check_timeline(tl, probe_fn=lambda p: probe(assets / p).duration)
    print(format_problems(problems), "\n")
    if has_errors(problems):
        print("Сборка остановлена: есть ошибки.")
        return 1
    if args.check_only:
        return 0

    result = render_all(tl, assets, ROOT / "output", args.suffix)
    master = result["master"]

    duration = measure_duration(str(master))
    loud = measure_loudness(str(master))
    quiet = measure_window(str(master), *INTERROGATION)
    fight = measure_window(str(master), *COMBAT)
    spread = fight - quiet

    report = {
        "master": str(master),
        "events": len(tl.events),
        "duration": duration,
        "integrated_lufs": loud.integrated_lufs,
        "true_peak_dbtp": loud.true_peak_dbtp,
        "lra": loud.lra,
        "interrogation_lufs": quiet,
        "combat_lufs": fight,
        "dynamic_spread_lu": spread,
    }
    (ROOT / "output" / f"render-report-{args.suffix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Мастер:       {master}")
    print(f"Длительность: {duration:.3f} с (цель {tl.total_duration:.3f})")
    print(f"LUFS:         {loud.integrated_lufs:.2f} (цель {tl.target_lufs})")
    print(f"True Peak:    {loud.true_peak_dbtp:.2f} dBTP (потолок {tl.target_tp})")
    print(f"Допрос:       {quiet:.2f} LUFS")
    print(f"Бой:          {fight:.2f} LUFS")
    print(f"Разброс:      {spread:.2f} LU (норма не больше {MAX_SPREAD_LU:.0f})")

    if abs(duration - tl.total_duration) > 0.001:
        print("  ВНИМАНИЕ: длительность разошлась с целевой.")
    if loud.true_peak_dbtp > tl.target_tp:
        print("  ВНИМАНИЕ: True Peak выше потолка, есть риск клиппинга.")
    if spread > MAX_SPREAD_LU:
        print("  ВНИМАНИЕ: динамика шире нормы, допрос потеряется в шумном зале.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
