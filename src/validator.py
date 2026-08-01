"""Проверки сценария до рендера. Ничего не бросает — возвращает список проблем."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

from src.models import STEMS, Timeline


@dataclass(frozen=True)
class Problem:
    level: str  # "error" | "warning"
    message: str


def check_timeline(tl: Timeline, probe_fn: Callable[[str], float]) -> list[Problem]:
    """probe_fn получает путь к ассету и возвращает его длительность в секундах."""
    problems: list[Problem] = []

    counts = Counter(e.id for e in tl.events)
    for event_id, n in sorted(counts.items()):
        if n > 1:
            problems.append(Problem("error", f"дублирующийся id {event_id!r}: {n} события"))

    if not tl.events:
        problems.append(Problem("error", "в сценарии нет событий"))

    lengths: dict[str, float] = {}  # id -> разрешённая длина, для проверки наложений ниже
    for ev in tl.events:
        if ev.t >= tl.total_duration:
            problems.append(Problem(
                "error",
                f"{ev.id}: начинается на {ev.t:.3f}, за границей {tl.total_duration:.3f}",
            ))
            continue

        try:
            source_len = probe_fn(ev.asset)
        except Exception as exc:
            problems.append(Problem("error", f"{ev.id}: ассет недоступен — {exc}"))
            continue

        length = ev.duration if ev.duration is not None else source_len
        lengths[ev.id] = length
        end = ev.t + length
        if end > tl.total_duration + 1e-6:
            problems.append(Problem(
                "warning",
                f"{ev.id}: кончается на {end:.3f}, будет обрезан по {tl.total_duration:.3f}",
            ))

        if ev.duration is not None:
            longer_than_source = ev.duration > source_len + 1e-6
            if longer_than_source and not ev.loop:
                problems.append(Problem(
                    "error",
                    f"{ev.id}: duration={ev.duration:.3f} длиннее файла {source_len:.3f}, "
                    f"а loop не включён — событие молча выйдет короче заявленного",
                ))
            if ev.loop and not longer_than_source:
                problems.append(Problem(
                    "warning",
                    f"{ev.id}: loop включён, но duration={ev.duration:.3f} не длиннее "
                    f"файла {source_len:.3f} — петля не нужна",
                ))

    # Наложение реплик — тихий дефект: два голоса звучат одновременно, и это
    # слышно только на прослушивании. У sfx наложение штатное: взмах и
    # попадание намеренно перекрываются. Длина берётся из lengths, посчитанных
    # в основном цикле выше, а не повторным probe_fn: недоступный ассет уже
    # получил свою ошибку там, второй раз жаловаться не на чем.
    voices = sorted(tl.by_stem("voices"), key=lambda e: e.t)
    for earlier, later in zip(voices, voices[1:]):
        length = lengths.get(earlier.id)
        if length is None:
            continue
        overlap = (earlier.t + length) - later.t
        if overlap > 1e-3:
            problems.append(Problem(
                "error",
                f"{earlier.id} и {later.id} накладываются на {overlap:.3f} с — "
                f"два голоса зазвучат одновременно",
            ))

    used = {e.stem for e in tl.events}
    for stem in STEMS:
        if stem not in used:
            problems.append(Problem("warning", f"стем {stem} пуст, будет собран как тишина"))

    return problems


def format_problems(problems: list[Problem]) -> str:
    if not problems:
        return "Проверки пройдены, замечаний нет."
    lines: list[str] = []
    for level in ("error", "warning"):
        chunk = [p for p in problems if p.level == level]
        if chunk:
            title = "ОШИБКИ" if level == "error" else "предупреждения"
            lines.append(f"{title} ({len(chunk)}):")
            lines.extend(f"  - {p.message}" for p in chunk)
    return "\n".join(lines)


def has_errors(problems: list[Problem]) -> bool:
    return any(p.level == "error" for p in problems)
