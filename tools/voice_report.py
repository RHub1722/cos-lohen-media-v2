"""Два отчёта по озвучке: выбранные дубли и потраченные голоса.

Отчёты собираются из данных, а не пишутся руками: выбранные дубли берутся из
scenario/takes_chosen.json и перепроверяются замером с диска, генерации — из
docs/eleven-voice-ledger.csv. Руками написанный отчёт устаревает на следующей
генерации и начинает врать, а этот пересобирается одной командой.

    python tools/voice_report.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Timeline  # noqa: E402
from src.voice_lines import (MARGIN, budgets, effective_budget,  # noqa: E402
                             load_lines)

ROOT = Path(__file__).resolve().parents[1]
MY = ROOT / "assets" / "voices" / "my"
CHOSEN = ROOT / "scenario" / "takes_chosen.json"
LEDGER = ROOT / "docs" / "eleven-voice-ledger.csv"
OUT_TAKES = ROOT / "docs" / "takes-report.md"
OUT_VOICES = ROOT / "docs" / "voices-report.md"

# Три отсчёта подряд у вершины — срез. Порог тот же, что в проверках дублей.
PLATEAU_CLIP = 3


def measure(path: Path) -> tuple[float, float, int] | None:
    """Длина, пик и длина площадки у вершины. None, если файла нет."""
    if not path.exists():
        return None
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s32le",
         "-acodec", "pcm_s32le", "-ac", "1", "-"], capture_output=True).stdout
    if not raw:
        return None
    import numpy as np
    x = np.frombuffer(raw, dtype="<i4").astype(np.int64)
    peak = int(np.abs(x).max())
    near = np.abs(x) >= peak * 0.9995
    longest = run = 0
    for flag in near:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return (len(x) / 48000.0,
            20.0 * float(np.log10(peak / (2 ** 31 - 1))), longest)


def level_word(peak: float, plateau: int) -> str:
    if plateau >= PLATEAU_CLIP:
        return f"**срез**, площадка {plateau}"
    if peak > -0.5:
        return "впритык"
    return "чисто"


def takes_report() -> Path:
    data = json.loads(CHOSEN.read_text(encoding="utf-8"))
    tl = Timeline.load(ROOT / "scenario" / "timeline.json")
    lines = {ln.event: ln for ln in load_lines()}
    room = budgets(tl)

    body = [
        "# Выбранные дубли: что записано и что пойдёт в номер",
        "",
        "Собран командой `python tools/voice_report.py` из"
        " `scenario/takes_chosen.json`. Все длины и уровни **перемерены с"
        " диска** при сборке отчёта, а не переписаны из файла отметок: если"
        " числа расходятся, это видно сразу.",
        "",
        "Уровень: «чисто» — площадка у вершины 1–2 отсчёта. «Срез» — три и"
        " более подряд, неисправимо. «Впритык» — пик выше −0.5 dB без площадки,"
        " не дефект, но запаса нет.",
        "",
    ]

    order = [e.id for e in sorted(
        [e for e in tl.events if e.asset.startswith("voices/")],
        key=lambda e: e.t)]
    ready = open_ = 0
    for event in order:
        entry = data["chosen"].get(event)
        if entry is None:
            continue
        line = lines.get(event)
        status = entry.get("status", "?")
        if status == "ready":
            ready += 1
        else:
            open_ += 1
        hard = effective_budget(line, room) if line else None
        body.append(f"## {event} — {status}")
        body.append("")
        if line:
            body.append(f"> «{line.line}»")
            body.append("")
            body.append(f"- **цель:** {hard - MARGIN:.2f} с, "
                        f"жёсткий предел {hard:.2f} с")
            body.append(f"- **как играть:** {line.play or line.direction}")
        if entry.get("who"):
            body.append(f"- **выбор:** {entry['who']}")
        if entry.get("source"):
            body.append(f"- **запись:** {entry['source']}")
        body.append("")

        rows = []
        if entry.get("in_use"):
            rows.append(("**в работе**", entry["in_use"], entry.get("why", "")))
        for cand in entry.get("candidates", []):
            rows.append((cand.get("rank", "кандидат"), cand["file"],
                         cand.get("why", "")))
        if entry.get("file") and not entry.get("in_use"):
            rows.append(("заявлен", entry["file"], entry.get("why", "")))

        if rows:
            body.append("| роль | файл | сек | предел | уровень | почему |")
            body.append("|---|---|---|---|---|---|")
            for role, name, why in rows:
                got = measure(MY / name)
                if got is None:
                    body.append(f"| {role} | `{name}` | — | нет файла | — | {why} |")
                    continue
                sec, peak, plateau = got
                fits = "влезает" if hard is None or sec <= hard else \
                    f"**+{sec - hard:.2f}**"
                body.append(f"| {role} | `{name}` | {sec:.3f} | {fits} | "
                            f"{level_word(peak, plateau)} | {why} |")
            body.append("")

        for extra in ("rescue", "warning_cut", "also_fit", "note"):
            if entry.get(extra):
                titles = {"rescue": "Как спасти",
                          "warning_cut": "Про нарезку",
                          "also_fit": "Годны, но не названы",
                          "note": "Замечание"}
                body.append(f"**{titles[extra]}.** {entry[extra]}")
                body.append("")
        if entry.get("avoid"):
            body.append("**Не брать:**")
            for item in entry["avoid"]:
                body.append(f"- `{item['file']}` — {item['why']}")
            body.append("")
        if entry.get("superseded"):
            sup = entry["superseded"]
            body.append(f"**Отменено:** `{sup['file']}` — {sup['why']}")
            body.append("")

    missing = [e for e in order if e not in data["chosen"]]
    head = [f"Реплик в номере {len(order)}, решено {ready}, "
            f"открыто {open_}, не записано {len(missing)}.", ""]
    if missing:
        head += ["**Ещё не записаны:** "
                 + ", ".join(f"`{e}`" for e in missing), ""]
    body[3:3] = head

    OUT_TAKES.write_text("\n".join(body), encoding="utf-8")
    return OUT_TAKES


def voices_report() -> Path:
    if not LEDGER.exists():
        raise SystemExit(f"нет журнала {LEDGER}")
    with open(LEDGER, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    by_voice: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_voice[row["voice"]].append(row)

    total_credits = sum(int(r["credits_estimate"] or 0) for r in rows)
    body = [
        "# Голоса: что использовалось и что сгенерировано",
        "",
        "Собран командой `python tools/voice_report.py` из"
        " `docs/eleven-voice-ledger.csv` — журнала, который пишется при каждом"
        " обращении к API. Кредиты — оценка на момент запроса; настоящее"
        " списание смотреть в дашборде.",
        "",
        f"Всего обращений: **{len(rows)}**, голосов задействовано:"
        f" **{len(by_voice)}**, оценка расхода: **{total_credits} кредитов**.",
        "",
        "## Как читать метки",
        "",
        "- `lo_v2`, `lo_v41`, `lo_v43` и прочие — **синтез** из текста"
        " соответствующим голосом аккаунта;",
        "- `mysts<-lo_v2` — **преобразование живой записи**: игра и тайминг от"
        " исполнителя, тембр от `lo_v2`. Модель `eleven_multilingual_sts_v2`;",
        "- `mystsalt<-lo_v2` — то же, но альтернативный дубль, только для"
        " сравнения на слух.",
        "",
        "## Сводка по голосам",
        "",
        "| метка | обращений | реплик | кредитов | модель |",
        "|---|---|---|---|---|",
    ]
    for voice in sorted(by_voice, key=lambda v: -len(by_voice[v])):
        items = by_voice[voice]
        credits = sum(int(r["credits_estimate"] or 0) for r in items)
        models = sorted({r["model"] for r in items})
        events = len({r["event"] for r in items})
        body.append(f"| `{voice}` | {len(items)} | {events} | {credits} | "
                    f"{', '.join(models)} |")
    body.append("")

    body += ["## Что сгенерировано по репликам", "",
             "| реплика | метка | сек | предел | влезает | файл |",
             "|---|---|---|---|---|---|"]
    # Столбца status в этом журнале нет — он есть только у журнала Atlas.
    # Неудачные обращения сюда не попадают вовсе: клиент падает до записи,
    # и это стоит знать при чтении отчёта.
    for row in rows:
        body.append(f"| {row['event']} | `{row['voice']}` | {row['seconds']} | "
                    f"{row['budget']} | {row['fits']} | `{row['file']}` |")
    body.append("")

    misfits = [r for r in rows if r["fits"] == "нет"]
    if misfits:
        body += ["## Не влезли в своё окно", "",
                 "Эти генерации остались на диске, но в номер поставить их"
                 " нельзя — реплика заехала бы на следующую.", ""]
        for row in misfits:
            body.append(f"- `{row['file']}` — {row['seconds']} с при пределе "
                        f"{row['budget']}: {row['notes'][:120]}")
        body.append("")

    OUT_VOICES.write_text("\n".join(body), encoding="utf-8")
    return OUT_VOICES


if __name__ == "__main__":
    print("отчёт по дублям:", takes_report().relative_to(ROOT))
    print("отчёт по голосам:", voices_report().relative_to(ROOT))
