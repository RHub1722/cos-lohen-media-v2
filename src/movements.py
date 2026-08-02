"""Движения исполнителя. Таймкод не хранится, а берётся из события звука.

Так постановка и дорожка не могут разойтись: если событие переименовали или
убрали, привязка ломается на валидации, а не на репетиции.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from src.models import Timeline


class MovementError(Exception):
    pass


@dataclass(frozen=True)
class Movement:
    id: str
    trigger_event: str
    name: str
    what: str
    speed: int
    power: int
    duration: float
    hold: str = ""
    t: float = -1.0  # проставляется в resolve_times

    @staticmethod
    def from_dict(raw: dict) -> "Movement":
        for key in ("id", "trigger_event", "name", "what", "speed", "power", "duration"):
            if key not in raw:
                raise MovementError(f"движение без обязательного поля {key!r}: {raw}")
        for scale in ("speed", "power"):
            value = int(raw[scale])
            if not 1 <= value <= 5:
                raise MovementError(f"{raw['id']}: {scale}={value} вне шкалы 1..5")
        return Movement(
            id=str(raw["id"]),
            trigger_event=str(raw["trigger_event"]),
            name=str(raw["name"]),
            what=str(raw["what"]),
            speed=int(raw["speed"]),
            power=int(raw["power"]),
            duration=float(raw["duration"]),
            hold=str(raw.get("hold", "")),
        )


def load_movements(path: str | Path) -> list[Movement]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Movement.from_dict(m) for m in raw.get("movements", [])]


def resolve_times(movements: list[Movement], tl: Timeline) -> list[Movement]:
    by_id = {e.id: e for e in tl.events}
    resolved = []
    for m in movements:
        event = by_id.get(m.trigger_event)
        if event is None:
            raise MovementError(
                f"{m.id}: движение ссылается на событие {m.trigger_event!r}, "
                f"которого нет в сценарии"
            )
        resolved.append(replace(m, t=event.t))
    return sorted(resolved, key=lambda m: m.t)
