"""Один прогон в один словарь. Вся склейка модулей здесь и только здесь."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from motion import envelope, frames as mframes, pose, segment, video


def _round_or_none(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def measure(path: str | Path, out_frames: Path | None = None,
            pose_on: bool = True) -> dict:
    """Замерить видео целиком. Картинки пишутся, если задан out_frames."""
    clip = video.probe(path)
    gray = video.gray_frames(clip)

    track = pose.track(clip) if pose_on else None
    ok, why = pose.available()
    if not pose_on:
        why = "слой отключён ключом --no-pose"

    body = None
    if track is not None and track.trustworthy and len(track.times) > 1:
        # Поза замеряется каждый второй кадр, а огибающая живёт на кадровой
        # сетке. Без растяжения длина не сойдётся, и починка масштаба МОЛЧА
        # не применится — а именно она чинит пропуск дальних движений.
        grid = np.arange(len(gray)) / clip.fps
        body = np.interp(grid, track.times, track.body_frac)
    if track is not None and not track.trustworthy:
        why = (f"суставы нашлись на {track.coverage:.0%} кадров, порог "
               f"{pose.MIN_COVERAGE:.0%} — выводы о теле подавлены")

    # Обрезка ПЕРЕД замером, а не после. Пороги считаются по максимуму того,
    # что подано, и возня с камерой, оставленная внутри, задаёт их сама: на v1
    # она в пять-восемь раз сильнее настоящих смахов, потому что руки у
    # объектива, а смахи в глубине кадра. Порог уезжал на 2.99 при смахах
    # 0.7–1.44, и ни один смах не находился.
    trim = segment.camera_trim(video.band_envelope(clip), clip.fps,
                               clip.duration)
    first = max(int(round(trim.start * clip.fps)), 0)
    last = min(int(round(trim.end * clip.fps)) + 1, len(gray))
    if last - first < 3:
        first, last = 0, len(gray)
    env = envelope.build(gray[first:last], clip.fps,
                         body_frac=None if body is None else body[first:last],
                         t0=first / clip.fps)
    parts = segment.segments(env, trim)
    hits = segment.strikes(env, trim)

    dead = [h for h in hits if h.dead_stop_before is True]
    pictures: dict[str, str] = {}
    if out_frames is not None:
        # Имена файлов латиницей, подписи русские — как во всём проекте.
        stem = clip.path.stem
        pictures["обзор"] = mframes.overview_sheet(
            clip, out_frames / f"{stem}-overview.png").name
        for i, hit in enumerate(hits, 1):
            pictures[f"удар {i}"] = mframes.strike_strip(
                clip, hit, out_frames / f"{stem}-strike-{i:02d}.png").name
        long_handling = [p for p in parts
                         if p.role == "владение" and p.end - p.start >= 2.0]
        for i, part in enumerate(long_handling, 1):
            pictures[f"владение {i}"] = mframes.handling_strip(
                clip, part, out_frames / f"{stem}-handling-{i:02d}.png").name

    return {
        "file": clip.path.name,
        "duration": round(clip.duration, 3),
        "fps": clip.fps,
        "trim": {"start": round(trim.start, 3), "end": round(trim.end, 3),
                 "reason": trim.reason},
        "scale_source": env.scale_source,
        "size_fix": env.size_fix,
        "floor": round(env.floor, 4),
        "action_level": round(env.action_level, 4),
        "strike_level": round(env.strike_level, 4),
        "dip_ratio_median": _round_or_none(
            float(np.median([h.dip_ratio for h in hits
                             if h.dip_ratio is not None]))
            if any(h.dip_ratio is not None for h in hits) else None, 2),
        "strikes": len(hits),
        "transitions": max(len(hits) - 1, 0),
        "dead_stops": len(dead),
        "longest_action": round(segment.longest(parts, ("удар", "владение")), 3),
        "longest_stillness": round(segment.longest(parts, ("покой",)), 3),
        "windup_median": round(float(np.median([h.windup for h in hits])), 3)
                         if hits else None,
        "stop_median": round(float(np.median([h.stop for h in hits])), 3)
                       if hits else None,
        "pose": {
            "used": bool(body is not None),
            "why": why,
            "coverage": round(track.coverage, 3) if track else None,
            "hip_lead": _round_or_none(
                pose.hip_lead_over_strikes(track, hits)
                if (track and track.trustworthy) else None),
            "stance_median": round(float(np.median(track.stance)), 2)
                             if (track and track.trustworthy) else None,
            "grip_median": round(float(np.median(track.grip)), 2)
                           if (track and track.trustworthy) else None,
        },
        "hits": [
            {"t_peak": round(h.t_peak, 3), "peak": round(h.peak, 3),
             "windup": round(h.windup, 3), "stop": round(h.stop, 3),
             "gap_before": round(h.gap_before, 3) if h.gap_before else None,
             "dip_ratio": _round_or_none(h.dip_ratio, 2),
             "dead_stop_before": h.dead_stop_before}
            for h in hits
        ],
        "segments": [{"role": p.role, "start": round(p.start, 3),
                      "end": round(p.end, 3)} for p in parts],
        "pictures": pictures,
    }
