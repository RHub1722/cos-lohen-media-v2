"""Три режима, удары и обрезка возни с камерой.

Один порог на всё не годится: проба показала, что все 19 секунд медленного
владения в v3 лежат ниже порога удара, и детектор пиков их не видит вовсе.
Медленная работа и удар — разные вещи, и мерятся разными правилами.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motion.envelope import Envelope

HANDLING_MIN_S = 0.5      # владение короче этого — не режим, а дрожание
MIN_GAP_S = 0.35          # два пика ближе этого — один удар
TRIM_DB = 12.0            # всплеск полосы выше медианы на столько — камера
TRIM_EDGE_S = 5.0         # искать только в первых и последних секундах

# Мёртвая остановка — когда движение в паузе упало обратно в покой, то есть
# ниже той же границы, по которой отделяется движение вообще. Множителя на дно
# здесь нет намеренно: дно нормировано, и любой множитель на нём означал бы
# разное в разных видео.


@dataclass(frozen=True)
class Segment:
    role: str               # "покой" | "владение" | "удар"
    start: float
    end: float


@dataclass(frozen=True)
class Strike:
    t_peak: float
    peak: float
    windup: float           # от 10% до пика
    stop: float             # от пика до 10% — чем останавливают палку
    gap_before: float | None
    floor_before: float | None
    dead_stop_before: bool | None


@dataclass(frozen=True)
class Trim:
    start: float
    end: float
    reason: str


def camera_trim(band: np.ndarray, fps: int, duration: float,
                edge_s: float = TRIM_EDGE_S, db: float = TRIM_DB) -> Trim:
    """Отрезать возню с камерой по звуку.

    Проба: верхняя полоса стоит на -60 dB и подскакивает до -30...-47 только
    когда трогают камеру. Палка на этих скоростях не свистит, поэтому всплеск
    в первых или последних секундах — это руки на телефоне, а не движение.

    Обрезанное окно возвращается всегда, даже когда резать нечего: отчёт обязан
    его назвать.
    """
    if band.size == 0:
        return Trim(0.0, duration, "звуковой дорожки нет, обрезка не делалась")
    level = 20.0 * np.log10(np.maximum(band, 1e-9))
    median = float(np.median(level))
    loud = level > median + db
    edge = max(1, int(round(edge_s * fps)))

    start, end = 0.0, duration
    parts = []
    head = np.flatnonzero(loud[:edge])
    if head.size:
        start = min((int(head.max()) + 1) / fps, duration * 0.5)
        parts.append(f"в начале срезано {start:.2f} с")
    tail = np.flatnonzero(loud[max(len(loud) - edge, 0):])
    if tail.size:
        first = max(len(loud) - edge, 0) + int(tail.min())
        end = max(first / fps, duration * 0.5)
        parts.append(f"в конце срезано {duration - end:.2f} с")
    reason = ("возня с камерой по звуку: " + ", ".join(parts)) if parts \
        else f"резать нечего: всплесков громче медианы на {db:g} dB у краёв нет"
    return Trim(start, end, reason)


def _inside(env: Envelope, trim: Trim) -> np.ndarray:
    return (env.times >= trim.start) & (env.times <= trim.end)


def segments(env: Envelope, trim: Trim) -> list[Segment]:
    """Разметка на покой, владение и удар. Владение короче 0.5 с не режим."""
    mask = _inside(env, trim)
    times, vals = env.times[mask], env.values[mask]
    if len(vals) == 0:
        return []

    # Граница владения — handling_level, а НЕ дно: выше дна по построению
    # лежит 80% отсчётов, и неподвижный клип разметился бы как работа с
    # оружием. Три сигмы над покоем отделяют движение от шума.
    roles = np.where(vals > env.strike_level, "удар",
                     np.where(vals > env.handling_level, "владение", "покой"))
    out: list[Segment] = []
    i = 0
    while i < len(roles):
        j = i
        while j + 1 < len(roles) and roles[j + 1] == roles[i]:
            j += 1
        out.append(Segment(role=str(roles[i]), start=float(times[i]),
                           end=float(times[j])))
        i = j + 1

    # Короткое владение — не режим. Приклеивается к покою, чтобы дрожание
    # камеры не выглядело работой с оружием.
    fixed = [s if not (s.role == "владение"
                       and s.end - s.start < HANDLING_MIN_S)
             else Segment("покой", s.start, s.end) for s in out]
    merged: list[Segment] = []
    for part in fixed:
        if merged and merged[-1].role == part.role:
            merged[-1] = Segment(part.role, merged[-1].start, part.end)
        else:
            merged.append(part)
    return merged


def strikes(env: Envelope, trim: Trim) -> list[Strike]:
    """Удары: локальные максимумы выше порога, не ближе 0.35 с друг к другу."""
    mask = _inside(env, trim)
    if int(mask.sum()) < 3:
        return []
    times, vals = env.times[mask], env.values[mask]

    peaks: list[int] = []
    for i in range(1, len(vals) - 1):
        if vals[i] <= env.strike_level:
            continue
        if vals[i] < vals[i - 1] or vals[i] < vals[i + 1]:
            continue
        if peaks and times[i] - times[peaks[-1]] <= MIN_GAP_S:
            if vals[i] > vals[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)

    out: list[Strike] = []
    for k, i in enumerate(peaks):
        level = env.level_for(float(vals[i]))
        left = i
        while left > 0 and vals[left] > level:
            left -= 1
        right = i
        while right < len(vals) - 1 and vals[right] > level:
            right += 1
        gap = floor_before = None
        dead = None
        if k:
            prev = peaks[k - 1]
            gap = float(times[i] - times[prev])
            floor_before = float(vals[prev:i].min())
            dead = bool(floor_before <= env.handling_level)
        out.append(Strike(
            t_peak=float(times[i]), peak=float(vals[i]),
            windup=float(times[i] - times[left]),
            stop=float(times[right] - times[i]),
            gap_before=gap, floor_before=floor_before, dead_stop_before=dead))
    return out


def longest(parts: list[Segment], roles: tuple[str, ...]) -> float:
    """Самый длинный непрерывный отрезок из перечисленных режимов.

    Нужно для двух требований номера сразу: burst_3 просит 2.4 с непрерывного
    действия, финальная поза — 4.8 с неподвижности.
    """
    best = run = 0.0
    for part in parts:
        if part.role in roles:
            run += part.end - part.start
            best = max(best, run)
        else:
            run = 0.0
    return best
