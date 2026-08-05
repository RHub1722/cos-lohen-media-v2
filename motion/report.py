"""report.md и measurements.json.

Отчёт обязан назвать три вещи: обрезанное окно, источник нормировки и покрытие
позой. Это не украшение, а условие, при котором его числам можно верить.
"""

from __future__ import annotations

import json
from pathlib import Path

from motion import compare as mcompare
from motion import requirements

SPEC = ("../../../docs/superpowers/specs/"
        "2026-08-05-motion-analyzer-design.md")


def _session_block(data: dict) -> list[str]:
    out = [f"## {data['file']}", ""]
    out += [
        f"Длина {data['duration']:.2f} с, {data['fps']} fps. "
        f"Разбирается окно {data['trim']['start']:.2f}–"
        f"{data['trim']['end']:.2f} с.",
        "",
        f"- **Обрезка:** {data['trim']['reason']}",
        f"- **Нормировка:** {data['scale_source']}; масштаб внутри видео — "
        f"{data['size_fix']}",
        f"- **Поза:** {data['pose']['why']}",
        "",
    ]
    if not data["strikes"]:
        out += [
            "**Ударов не найдено.** Это не ошибка чтения: дно огибающей "
            f"{data['floor']:.3f}, порог удара {data['strike_level']:.3f}, "
            f"самое длинное непрерывное действие "
            f"{data['longest_action']:.2f} с. Всё движение в этом заходе идёт "
            "ниже порога удара.",
            "",
        ]
    else:
        out += [
            f"Ударов {data['strikes']}, переходов {data['transitions']}, из них "
            f"**мёртвых остановок {data['dead_stops']}**.",
            f"Медиана замаха {data['windup_median']:.3f} с, медиана торможения "
            f"{data['stop_median']:.3f} с.",
            f"Самое длинное непрерывное действие {data['longest_action']:.2f} с, "
            f"самая длинная неподвижность {data['longest_stillness']:.2f} с.",
            "",
            "| № | пик, с | замах | торможение | пауза до | мёртвая остановка |",
            "|---|---|---|---|---|---|",
        ]
        for i, hit in enumerate(data["hits"], 1):
            gap = f"{hit['gap_before']:.2f}" if hit["gap_before"] else "—"
            dead = {True: "да", False: "нет", None: "—"}[hit["dead_stop_before"]]
            out.append(f"| {i} | {hit['t_peak']:.2f} | {hit['windup']:.3f} | "
                       f"{hit['stop']:.3f} | {gap} | {dead} |")
        out.append("")

    if data["pose"]["used"]:
        out += [
            f"- Бёдра опережают кисти на **{data['pose']['hip_lead']:+.3f} с** "
            "(минус — ведут руки, сила не из корпуса)",
            f"- Стойка {data['pose']['stance_median']:.2f} плеча, хват "
            f"{data['pose']['grip_median']:.2f} плеча",
            "",
        ]
    for name, file in data.get("pictures", {}).items():
        out.append(f"![{name}](frames/{file})")
    out.append("")
    return out


def write(sessions: list[dict], out_dir: Path,
          reqs: dict | None = None) -> Path:
    """Записать report.md и measurements.json. Возвращает путь к отчёту."""
    out_dir = Path(out_dir)
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    (out_dir / "measurements.json").write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")

    reqs = reqs if reqs is not None else requirements.from_scenario()
    lines = ["# Разбор тренировки", "",
             f"Числа собраны `motion/analyze.py`. Метод и то, почему он такой, — "
             f"в [проектном решении]({SPEC}).",
             ""]
    for data in sessions:
        lines += _session_block(data)

    total = {
        "longest_action": max((s["longest_action"] for s in sessions),
                              default=0.0),
        "longest_stillness": max((s["longest_stillness"] for s in sessions),
                                 default=0.0),
        "strikes": sum(s["strikes"] for s in sessions),
        "transitions": sum(s["transitions"] for s in sessions),
        "dead_stops": sum(s["dead_stops"] for s in sessions),
    }
    lines += ["## Годность к прогону номера", "",
              "| требование | есть | замер |", "|---|---|---|"]
    for finding in mcompare.compare(total, reqs):
        lines.append(f"| {finding.what} | **{finding.verdict}** | "
                     f"{finding.detail} |")
    lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
