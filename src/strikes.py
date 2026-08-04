"""Разбор боя по долям. Своих таймкодов нет — только событие и смещение.

Тот же принцип, что у `movements.py` и `footage.py`: доля висит на событии
звука, и если событие уехало, доля уезжает вместе с ним. Разошлись бы они молча,
а исполнитель узнал бы об этом на репетиции.

Время доли считается дважды. `t` — время события в сценарии, то есть начало
файла ассета. `heard` — то же плюс смещение пика внутри файла, то есть момент,
когда звук слышно. Исполнителю показывается `heard`: у быстрого взмаха эти два
числа расходятся на 0.376 с.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from src.models import Timeline

# Роль доли внутри удара. Порядок здесь — порядок в кадре: замах, взмах,
# контакт, возврат. hold — доля без движения, ею удар заканчивается.
ROLES = ("windup", "swing", "contact", "recover", "hold")

ROLE_NAMES = {
    "windup": "замах",
    "swing": "взмах",
    "contact": "КОНТАКТ",
    "recover": "возврат",
    "hold": "держать",
}


class StrikeError(Exception):
    """Разбор боя не соответствует схеме или ссылается в пустоту."""


@dataclass(frozen=True)
class Beat:
    """Одна опора внутри удара.

    peak=False — считать от начала файла, а не от пика. Нужно фактурам:
    у наступления автоматона самый громкий отсчёт лежит на 1.08 с, но событием
    является момент, когда машина входит в кадр, то есть начало файла. У удара
    и взмаха наоборот: событие — это пик, начало файла не слышно вовсе.
    """

    role: str
    trigger: str
    what: str
    offset: float = 0.0
    screen: str = ""
    peak: bool = True
    pose: dict = field(default_factory=dict)
    t: float = -1.0
    heard: float = -1.0

    @staticmethod
    def from_dict(raw: dict, owner: str) -> "Beat":
        for key in ("role", "trigger", "what"):
            if key not in raw:
                raise StrikeError(f"{owner}: доля без обязательного поля {key!r}: {raw}")
        role = str(raw["role"])
        if role not in ROLES:
            raise StrikeError(
                f"{owner}: неизвестная роль доли {role!r}, допустимы {ROLES}"
            )
        return Beat(
            role=role,
            trigger=str(raw["trigger"]),
            what=str(raw["what"]),
            offset=float(raw.get("offset", 0.0)),
            screen=str(raw.get("screen", "")),
            peak=bool(raw.get("peak", True)),
            pose=dict(raw.get("pose", {})),
        )


@dataclass(frozen=True)
class Strike:
    """Одно боевое действие: вспышка, приём удара или копьё в пол."""

    id: str
    movement: str
    title: str
    beats: tuple[Beat, ...]
    family: str = ""
    why: str = ""
    reference: dict = field(default_factory=dict)
    floor: dict = field(default_factory=dict)
    drill: tuple[str, ...] = ()
    mistakes: tuple[str, ...] = ()
    loop: dict = field(default_factory=dict)
    # Окно петли, посчитанное из loop. Отдельные поля, а не словарь: страница
    # получает готовые секунды и ничего не считает сама.
    loop_from: float = -1.0
    loop_to: float = -1.0

    @staticmethod
    def from_dict(raw: dict) -> "Strike":
        for key in ("id", "movement", "title", "beats"):
            if key not in raw:
                raise StrikeError(f"удар без обязательного поля {key!r}: {raw}")
        strike_id = str(raw["id"])
        beats = tuple(Beat.from_dict(b, strike_id) for b in raw["beats"])
        if not beats:
            raise StrikeError(f"{strike_id}: удар без долей")
        if not any(b.role == "contact" for b in beats):
            raise StrikeError(
                f"{strike_id}: в ударе нет доли contact. Момент попадания и есть "
                "то, ради чего разбор существует"
            )
        loop = dict(raw.get("loop", {}))
        for key in ("from", "to"):
            if key not in loop:
                raise StrikeError(f"{strike_id}: в loop нет поля {key!r}")
        return Strike(
            id=strike_id,
            movement=str(raw["movement"]),
            title=str(raw["title"]),
            beats=beats,
            family=str(raw.get("family", "")),
            why=str(raw.get("why", "")),
            reference=dict(raw.get("reference", {})),
            floor=dict(raw.get("floor", {})),
            drill=tuple(str(x) for x in raw.get("drill", [])),
            mistakes=tuple(str(x) for x in raw.get("mistakes", [])),
            loop=loop,
        )


def load_strikes(path: str | Path) -> list[Strike]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    strikes = [Strike.from_dict(s) for s in raw.get("strikes", [])]
    seen: set[str] = set()
    for strike in strikes:
        if strike.id in seen:
            raise StrikeError(f"удар {strike.id!r} описан дважды")
        seen.add(strike.id)
    return strikes


def resolve_strikes(
    strikes: list[Strike],
    tl: Timeline,
    peaks: dict[str, float] | None = None,
    movements: Iterable[str] = (),
) -> list[Strike]:
    """Проставляет времена долей и окна петель.

    `peaks` — смещения пиков внутри ассетов из `peaks.peak_offsets`. Без них
    `heard` совпадёт с `t`, и страница покажет время начала файла: для взмаха это
    ошибка на треть секунды, поэтому замер обязателен, а не опционален.
    """
    peaks = peaks or {}
    known_moves = set(movements)
    by_id = {e.id: e for e in tl.events}

    def event(name: str, owner: str):
        found = by_id.get(name)
        if found is None:
            raise StrikeError(
                f"{owner}: ссылка на событие {name!r}, которого нет в сценарии"
            )
        return found

    out: list[Strike] = []
    for strike in strikes:
        if known_moves and strike.movement not in known_moves:
            raise StrikeError(
                f"{strike.id}: ссылка на движение {strike.movement!r}, которого "
                "нет в хореографии"
            )

        placed = []
        for beat in strike.beats:
            source = event(beat.trigger, f"{strike.id}/{beat.role}")
            peak = peaks.get(source.asset, 0.0) if beat.peak else 0.0
            placed.append(replace(
                beat,
                t=round(source.t + beat.offset, 4),
                heard=round(source.t + peak + beat.offset, 4),
            ))
        for before, after in zip(placed, placed[1:]):
            if after.heard < before.heard:
                raise StrikeError(
                    f"{strike.id}: доля {after.role!r} на {after.heard:.2f} стоит "
                    f"раньше предыдущей {before.role!r} на {before.heard:.2f}"
                )

        start = event(str(strike.loop["from"]), f"{strike.id}/loop")
        end = event(str(strike.loop["to"]), f"{strike.id}/loop")
        loop_from = max(0.0, start.t + peaks.get(start.asset, 0.0)
                        - float(strike.loop.get("pre", 1.5)))
        loop_to = min(tl.total_duration, end.t + peaks.get(end.asset, 0.0)
                      + float(strike.loop.get("post", 1.5)))
        if loop_to <= loop_from:
            raise StrikeError(
                f"{strike.id}: окно петли {loop_from:.2f}–{loop_to:.2f} пустое"
            )
        for beat in placed:
            if not loop_from <= beat.heard <= loop_to:
                raise StrikeError(
                    f"{strike.id}: доля {beat.role!r} на {beat.heard:.2f} вне окна "
                    f"петли {loop_from:.2f}–{loop_to:.2f} — на репетиции её просто "
                    "не будет слышно"
                )

        out.append(replace(strike, beats=tuple(placed),
                           loop_from=round(loop_from, 3),
                           loop_to=round(loop_to, 3)))

    return sorted(out, key=lambda s: s.beats[0].heard)
