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
DEAD_STOP_RATIO = 0.25    # впадина ниже четверти от соседних пиков — остановка
TRIM_DB = 12.0            # всплеск полосы выше медианы на столько — камера
TRIM_EDGE_S = 5.0         # искать только в первых и последних секундах

# Мёртвая остановка меряется ОТНОСИТЕЛЬНО соседних пиков, а не по уровню покоя.
# Причина: чистого покоя в этом материале нет, исполнитель двигается почти всё
# время, и любой порог из «уровня покоя» ложился выше медианы огибающей. Отсюда
# и брались «мёртвые остановки 17 из 17» в видео, где глаз видит непрерывную
# работу. Отношение впадины к пикам определено без покоя вовсе: на настоящей v1
# его медиана 0.64, то есть движение между всплесками держится на двух третях
# от них, а ниже 0.25 уходит примерно каждая шестая пара.


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
    dip_ratio: float | None       # впадина до этого пика / меньший из двух пиков
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
    head = _run_from_edge(loud[:edge], fps)
    if head:
        start = min(head / fps, duration * 0.5)
        parts.append(f"в начале срезано {start:.2f} с")
    tail = _run_from_edge(loud[max(len(loud) - edge, 0):][::-1], fps)
    if tail:
        end = max(duration - tail / fps, duration * 0.5)
        parts.append(f"в конце срезано {duration - end:.2f} с")
    reason = ("возня с камерой по звуку: " + ", ".join(parts)) if parts \
        else f"резать нечего: всплесков громче медианы на {db:g} dB у краёв нет"
    return Trim(start, end, reason)


def _run_from_edge(loud: np.ndarray, fps: int, gap_s: float = 0.5) -> int:
    """Докуда тянется возня с камерой от самого края, в отсчётах.

    Не «последний громкий отсчёт в окне»: одиночный посторонний звук на 4.9 с
    выбрасывал бы пять секунд, и на v1 первая версия так и сделала — срезала
    ровно предел окна поиска. Тянем от края и обрываемся на первой тишине
    длиннее gap_s. Если у самого края тихо, возни не было вовсе.
    """
    gap = max(1, int(round(gap_s * fps)))
    idx = np.flatnonzero(loud)
    if idx.size == 0 or int(idx[0]) > gap:
        return 0
    end = int(idx[0])
    for j in idx[1:]:
        if int(j) - end > gap:
            break
        end = int(j)
    return end + 1


def _inside(env: Envelope, trim: Trim) -> np.ndarray:
    return (env.times >= trim.start) & (env.times <= trim.end)


def segments(env: Envelope, trim: Trim) -> list[Segment]:
    """Разметка на покой, владение и удар. Владение короче 0.5 с не режим."""
    mask = _inside(env, trim)
    times, vals = env.times[mask], env.values[mask]
    if len(vals) == 0:
        return []

    # Граница владения — action_level, а НЕ дно: выше дна по построению лежит
    # 80% отсчётов, и неподвижный клип разметился бы как работа с оружием.
    roles = np.where(vals > env.strike_level, "удар",
                     np.where(vals > env.action_level, "владение", "покой"))
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
        # Обход ограничен соседними пиками. Без этого при непрерывной работе
        # он проходит сквозь них: у всплеска, отстоящего от предыдущего на
        # 0.53 с, «замах» выходил 3.27 с — обход добирался до уровня 10% через
        # три чужих всплеска.
        lower = peaks[k - 1] if k else 0
        upper = peaks[k + 1] if k + 1 < len(peaks) else len(vals) - 1
        left = i
        while left > lower and vals[left] > level:
            left -= 1
        right = i
        while right < upper and vals[right] > level:
            right += 1
        gap = floor_before = ratio = None
        dead = None
        if k:
            prev = peaks[k - 1]
            gap = float(times[i] - times[prev])
            floor_before = float(vals[prev:i].min())
            # Впадина считается от ДНА, а не от нуля: дно это уровень, ниже
            # которого огибающая не опускается и в самом спокойном месте.
            depth = max(floor_before - env.floor, 0.0)
            reach = max(min(vals[prev], vals[i]) - env.floor, 1e-12)
            ratio = float(depth / reach)
            dead = bool(ratio < DEAD_STOP_RATIO)
        out.append(Strike(
            t_peak=float(times[i]), peak=float(vals[i]),
            windup=float(times[i] - times[left]),
            stop=float(times[right] - times[i]),
            gap_before=gap, floor_before=floor_before,
            dip_ratio=ratio, dead_stop_before=dead))
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
