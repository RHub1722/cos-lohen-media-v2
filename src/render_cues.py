"""Две дорожки голосовых подсказок и печатный лист ориентиров.

    python src/render_cues.py
    python src/render_cues.py --start-at 0.95      # свой замер промаха старта

Что получается:

    output/rehearsal_cues_v2.wav   номер + голос поверх, для репетиции дома
    output/stage_cues_v2.wav       только подсказки, для наушника на сцене
    output/cue_sheet.md            печатный лист: что слышно и за сколько

Почему сценическая дорожка не содержит слова в точку контакта — в docstring
`src/cues.py`. Коротко: старт телефона нажимается рукой, промах 0.25 с
систематически, и слово в точку при таком промахе вредит.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.cues import (Cue, all_cues, first_cues, lengths_of,  # noqa: E402
                      resolve_overlaps, shift)
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Куда упирается ручной старт. По умолчанию исполнитель жмёт play на первом
# звуке номера — смех на 0.70, — и человеческая реакция добавляет ещё 0.25 с.
# Оба числа заглушки: настоящее даёт один замер, описанный в листе ориентиров.
SYNC_ON = 0.70
REACTION = 0.25

# Провал номера под подсказкой в репетиционной дорожке. Глубоко: там важно
# слово, а не микс, и это единственный файл, который зал никогда не услышит.
DUCK_DB = 14.0
DUCK_ATTACK = 0.15
DUCK_RELEASE = 0.25

# Насколько подсказка громче номера. Это репетиция, голос главный.
CUE_GAIN_DB = 3.0


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    if not out:
        raise SystemExit(f"не читается длительность {path}")
    return float(out)


def duck_expression(cues: list[Cue], lengths: dict[str, float]) -> str:
    """Трапеция на каждую подсказку, наложения берутся по максимуму.

    Та же форма, что у провала музыки под ударами в `filtergraph`, но короче:
    там полка 0.30 с под транзиент, здесь полка равна длине слова. Складывать
    провалы нельзя — два подряд ушли бы в тишину.
    """
    if not cues:
        return ""
    depth = 1.0 - 10.0 ** (-DUCK_DB / 20.0)
    terms = []
    for cue in cues:
        a = max(0.0, cue.t - DUCK_ATTACK)
        b = cue.t + lengths[cue.word] + DUCK_RELEASE
        env = (f"max(0\\,min(1\\,min((t-{a:.4f})/{DUCK_ATTACK:.4f}\\,"
               f"({b:.4f}-t)/{DUCK_RELEASE:.4f})))")
        terms.append(f"{depth:.6f}*{env}")
    deepest = terms[0]
    for term in terms[1:]:
        deepest = f"max({deepest}\\,{term})"
    return f"1-({deepest})"


def render(cues: list[Cue], out: Path, total: float, assets: Path,
           bed: Path | None, channels: int = 2) -> None:
    """Собирает дорожку: слова через adelay, при наличии — поверх номера.

    channels=1 для сценической: она едет в один наушник, второе ухо обязано
    слышать зал. Моно и вдвое меньше файл на телефоне.
    """
    if not cues:
        raise SystemExit("ни одной подсказки — нечего собирать")

    lengths = lengths_of(assets, [c.word for c in cues], ffprobe_duration)
    inputs: list[str] = []
    if bed is not None:
        inputs += ["-i", str(bed)]
    for cue in cues:
        inputs += ["-i", str(assets / f"cues/cue_{cue.word}.wav")]

    base = 1 if bed is not None else 0
    parts = []
    labels = []
    for i, cue in enumerate(cues):
        ms = int(round(cue.t * 1000.0))
        parts.append(f"[{base + i}:a]adelay={ms}|{ms},"
                     f"volume={CUE_GAIN_DB}dB[c{i}]")
        labels.append(f"[c{i}]")

    if bed is not None:
        expr = duck_expression(cues, lengths)
        parts.append(f"[0:a]volume='{expr}':eval=frame[bed]")
        labels.insert(0, "[bed]")

    n = len(labels)
    parts.append("".join(labels) + f"amix=inputs={n}:normalize=0:"
                 f"dropout_transition=0[mix]")
    # Обрезка по длине номера обязательна: adelay продлевает поток, и последнее
    # слово вытянуло бы файл за 60 с.
    parts.append(f"[mix]atrim=0:{total:.4f},asetpts=N/SR/TB[out]")

    cmd = (["ffmpeg", "-v", "error", "-y"] + inputs
           + ["-filter_complex", ";".join(parts), "-map", "[out]"]
           + ["-ar", "48000", "-ac", str(channels), "-c:a", "pcm_s24le", str(out)])
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"ffmpeg: {done.stderr[-1500:]}")


def sheet(kept: list[Cue], dropped: list[Cue], stage: list[Cue],
          start_at: float, strikes) -> str:
    """Печатный лист. Пишется здесь, а не в шаблоне: он весь из чисел."""
    contacts = {}
    for strike in strikes:
        first = min((b.heard for b in strike.beats if b.role == "contact"),
                    default=None)
        if first is not None:
            contacts[strike.id] = first

    lines = [
        "# Лист ориентиров: когда наносить удары",
        "",
        "Сгенерирован `python src/render_cues.py`. Времена — из долей",
        "`scenario/strikes.json`, то есть из того же источника, что тренажёр.",
        "Руками здесь править нечего: сдвинется удар в сценарии — уедет и лист.",
        "",
        "## Главное правило",
        "",
        "На удар реагировать нельзя. Реакция на звук 0.15–0.20 с, взмах копьём",
        "от покоя 0.3–0.6 с: к моменту контакта движение уже должно идти.",
        "Поэтому ориентир всегда стоит на подготовке, а не на попадании.",
        "",
        "## Сценическая дорожка: одно слово на действие",
        "",
        "`output/stage_cues_v2.wav` — в наушник с телефона. Слова в точку",
        "контакта в ней нет намеренно: старт нажимается рукой, промах около",
        "0.25 с, и слово в точку при таком промахе вредит. Контакт несёт сам",
        "номер.",
        "",
        "| слово | в номере | в файле | действие | до первого контакта |",
        "|---|---|---|---|---|",
    ]
    for cue in stage:
        c = contacts.get(cue.strike)
        gap = f"{c - cue.t:.2f} с" if c is not None else "—"
        lines.append(f"| **{cue.text}** | {cue.t:.2f} | "
                     f"{max(0.0, cue.t - start_at):.2f} | {cue.strike} | {gap} |")

    lines += [
        "",
        f"Файл сдвинут на {start_at:.2f} с: столько проходит от начала номера до",
        "нажатия play. Число надо заменить своим — как замерить, ниже.",
        "",
        "## Репетиционная дорожка: все доли, какие влезли",
        "",
        "`output/rehearsal_cues_v2.wav` — номер плюс голос поверх. Только для",
        "репетиции: старта на сцене здесь нет, промаха нет, слова стоят точно.",
        "",
        "| время | слово | роль | действие |",
        "|---|---|---|---|",
    ]
    for cue in kept:
        lines.append(f"| {cue.t:.2f} | **{cue.text}** | {cue.role} | {cue.strike} |")

    if dropped:
        lines += [
            "",
            "### Что снято и почему",
            "",
            "Доли идут плотнее, чем произносятся слова: у первой вспышки четыре",
            "доли укладываются в 1.47 с, а четыре слова занимают 1.8 с. Снятое",
            "перечислено, чтобы не ждать слова, которого не будет. При наложении",
            "остаётся более важная роль, и подготовка важнее контакта: контакт",
            "слышен сам — в этот момент играет удар, — а подготовку не слышит",
            "никто, кроме подсказки.",
            "",
            "| время | слово | роль | действие |",
            "|---|---|---|---|",
        ]
        for cue in dropped:
            lines.append(f"| {cue.t:.2f} | {cue.text} | {cue.role} | {cue.strike} |")

    lines += [
        "",
        "## Как замерить свой промах старта",
        "",
        "1. Включи номер в зале или на колонках, телефон с",
        "   `stage_cues_v2.wav` — в руке.",
        "2. Жми play на телефоне на первом звуке номера (смех, 0.70).",
        "3. Пиши на диктофон второго устройства сразу и колонки, и наушник",
        "   (наушник поднеси к микрофону).",
        "4. В записи найди смех и первое слово подсказки. Разница минус",
        f"   {SYNC_ON:.2f} и есть твой промах.",
        "5. Пересобери с ним: `python src/render_cues.py --start-at ЧИСЛО`.",
        "",
        "Без этого замера сценическая дорожка стоит на заглушке",
        f"{SYNC_ON:.2f} + {REACTION:.2f} = {SYNC_ON + REACTION:.2f} с.",
        "",
        "## Чего эти дорожки не заменяют",
        "",
        "Прогон под запись. Все подготовительные точки в `strikes.json`",
        "поставлены по книжным 0.3–0.6 с на взмах. Твои числа могут отличаться",
        "вдвое, и тогда сдвигать надо доли, а не подсказки: подсказки",
        "пересчитаются сами.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", default=str(ROOT / "scenario" / "timeline.json"))
    ap.add_argument("--strikes", default=str(ROOT / "scenario" / "strikes.json"))
    ap.add_argument("--movements", default=str(ROOT / "scenario" / "movements.json"))
    ap.add_argument("--assets", default=str(ROOT / "assets"))
    ap.add_argument("--master", default=str(ROOT / "output" / "master_v2.wav"))
    ap.add_argument("--out", default=str(ROOT / "output"))
    ap.add_argument("--start-at", type=float, default=SYNC_ON + REACTION,
                    help="время номера, в которое нажат play на телефоне")
    args = ap.parse_args()

    tl = Timeline.load(args.scenario)
    assets = Path(args.assets)
    # Только эффекты: у долей опорами стоят удары и взмахи, а замер пика на
    # шестнадцатисекундной музыкальной подложке ничего не значит и стоит времени.
    peaks = peak_offsets(assets, sorted({e.asset for e in tl.events
                                         if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(load_movements(args.movements), tl)]
    strikes = resolve_strikes(load_strikes(args.strikes), tl, peaks, moves)

    every = all_cues(strikes)
    lengths = lengths_of(assets, [c.word for c in every], ffprobe_duration)
    kept, dropped = resolve_overlaps(every, lengths)
    stage = shift(first_cues(strikes), args.start_at)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"действий {len(strikes)}, долей {len(every)}, "
          f"подсказок в репетиционной {len(kept)}, снято {len(dropped)}")
    for cue in kept:
        print(f"  {cue.t:6.2f}  {cue.text:9} {cue.role:8} {cue.strike}")
    if dropped:
        print("снято из-за наложения:")
        for cue in dropped:
            print(f"  {cue.t:6.2f}  {cue.text:9} {cue.role:8} {cue.strike}")

    print(f"\nсценическая: {len(stage)} слов, сдвиг {args.start_at:.2f} с")
    for cue in stage:
        print(f"  файл {cue.t:6.2f}  номер {cue.t + args.start_at:6.2f}  "
              f"{cue.text:9} {cue.strike}")

    master = Path(args.master)
    if not master.exists():
        raise SystemExit(f"нет мастера {master}. Сначала python src/build.py")
    render(kept, out / "rehearsal_cues_v2.wav", tl.total_duration, assets, master)
    render(stage, out / "stage_cues_v2.wav",
           tl.total_duration - args.start_at, assets, None, channels=1)

    text = sheet(kept, dropped, first_cues(strikes), args.start_at, strikes)
    (out / "cue_sheet.md").write_text(text, encoding="utf-8")

    for name in ("rehearsal_cues_v2.wav", "stage_cues_v2.wav"):
        path = out / name
        print(f"\n{path}  {ffprobe_duration(path):.3f} с, "
              f"{path.stat().st_size / 1e6:.1f} МБ")
    print(f"{out / 'cue_sheet.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
