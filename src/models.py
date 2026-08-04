"""Схема сценария. Ничего не знает про FFmpeg и файловую систему."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STEMS = ("voices", "sfx", "music", "ambience")


class ScenarioError(Exception):
    """Сценарий не соответствует схеме."""


@dataclass(frozen=True)
class Event:
    """Одно звуковое событие на таймлайне.

    duration=None означает «взять файл целиком», иначе источник обрезается.

    loop включается только для фоновых слоёв, которые надо растянуть длиннее
    исходника. Автоматически выводить его из duration нельзя: обрезка короче
    исходника петли не требует, а лишний бесконечный вход не отдаёт ffmpeg EOF,
    и рендер зависает после сведения.
    """

    id: str
    t: float
    asset: str
    stem: str
    gain_db: float = 0.0
    pan: float = 0.0
    duration: float | None = None
    loop: bool = False
    fade_in: float = 0.01
    fade_out: float = 0.01
    # На сколько децибел это событие уводит музыку вниз под собой. Ноль — не
    # уводит. Нужно ударам: подложка боя стоит на −10 dB и накрывает их, а
    # поднять сами удары нельзя — их пики уже вплотную к финальному, который
    # обязан остаться абсолютным. Значит вниз идёт музыка, а не вверх удар.
    duck_db: float = 0.0
    # Подъём низа и верха на самом событии. Громкость и тембр — разные вещи.
    # Вышибленная дверь по уровню в порядке, но низа у неё меньше, чем верха, и
    # читается она треском, а не взрывом. У удара по Лоэну обратная беда: даже
    # после провала музыки запас в верхней полосе всего 2.2 dB, то есть у самого
    # ценного места номера нет щелчка, только глухой толчок.
    bass_db: float = 0.0
    treble_db: float = 0.0
    video: dict | None = None
    note: str = ""

    @staticmethod
    def from_dict(raw: dict) -> "Event":
        for key in ("id", "t", "asset", "stem"):
            if key not in raw:
                raise ScenarioError(f"событие без обязательного поля {key!r}: {raw}")

        event_id = str(raw["id"])

        stem = raw["stem"]
        if stem not in STEMS:
            raise ScenarioError(
                f"{event_id}: неизвестный stem {stem!r}, допустимы {STEMS}"
            )

        pan = float(raw.get("pan", 0.0))
        if not -1.0 <= pan <= 1.0:
            raise ScenarioError(f"{event_id}: pan={pan} вне диапазона -1..1")

        t = float(raw["t"])
        if t < 0:
            raise ScenarioError(f"{event_id}: отрицательное время {t}")

        duration = raw.get("duration")
        if duration is not None and float(duration) <= 0:
            raise ScenarioError(f"{event_id}: duration должен быть больше нуля")

        loop = bool(raw.get("loop", False))
        if loop and duration is None:
            raise ScenarioError(f"{event_id}: loop без duration зациклится навсегда")

        duck_db = float(raw.get("duck_db", 0.0))
        if duck_db < 0:
            raise ScenarioError(
                f"{event_id}: duck_db={duck_db} отрицательный. Поле означает "
                "глубину провала музыки в децибелах, и отрицательное значение "
                "подняло бы её на ударе вместо того, чтобы убрать."
            )
        if duck_db and stem != "sfx":
            raise ScenarioError(
                f"{event_id}: duck_db на стеме {stem!r}. Уводить музыку под "
                "музыкой бессмысленно, а под голосом это отдельное решение, "
                "которого мы не принимали."
            )

        return Event(
            id=event_id,
            t=t,
            asset=str(raw["asset"]),
            stem=stem,
            gain_db=float(raw.get("gain_db", 0.0)),
            pan=pan,
            duration=None if duration is None else float(duration),
            loop=loop,
            fade_in=float(raw.get("fade_in", 0.01)),
            fade_out=float(raw.get("fade_out", 0.01)),
            duck_db=duck_db,
            bass_db=float(raw.get("bass_db", 0.0)),
            treble_db=float(raw.get("treble_db", 0.0)),
            video=raw.get("video"),
            note=str(raw.get("note", "")),
        )


@dataclass(frozen=True)
class Timeline:
    total_duration: float
    events: tuple[Event, ...]
    version: str = "v2"
    sample_rate: int = 48000
    target_lufs: float = -16.0
    target_tp: float = -1.5

    @staticmethod
    def from_dict(raw: dict) -> "Timeline":
        if "total_duration" not in raw:
            raise ScenarioError("в сценарии нет total_duration")
        events = tuple(
            sorted(
                (Event.from_dict(e) for e in raw.get("events", [])),
                key=lambda e: e.t,
            )
        )
        return Timeline(
            total_duration=float(raw["total_duration"]),
            events=events,
            version=str(raw.get("version", "v2")),
            sample_rate=int(raw.get("sample_rate", 48000)),
            target_lufs=float(raw.get("target_lufs", -16.0)),
            target_tp=float(raw.get("target_tp", -1.5)),
        )

    @staticmethod
    def load(path: str | Path) -> "Timeline":
        with open(path, encoding="utf-8") as fh:
            return Timeline.from_dict(json.load(fh))

    def by_stem(self, stem: str) -> tuple[Event, ...]:
        return tuple(e for e in self.events if e.stem == stem)
