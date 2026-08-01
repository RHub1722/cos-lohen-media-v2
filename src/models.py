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

    duration=None означает «взять файл целиком». Если duration задан и длиннее
    файла, источник пойдёт петлёй — так собираются фоновые слои.
    """

    id: str
    t: float
    asset: str
    stem: str
    gain_db: float = 0.0
    pan: float = 0.0
    duration: float | None = None
    fade_in: float = 0.01
    fade_out: float = 0.01
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

        return Event(
            id=event_id,
            t=t,
            asset=str(raw["asset"]),
            stem=stem,
            gain_db=float(raw.get("gain_db", 0.0)),
            pan=pan,
            duration=None if duration is None else float(duration),
            fade_in=float(raw.get("fade_in", 0.01)),
            fade_out=float(raw.get("fade_out", 0.01)),
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
