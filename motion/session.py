"""Один прогон в один словарь. Вся склейка модулей здесь и только здесь."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from motion import envelope, frames as mframes, pose, segment, video


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

    env = envelope.build(gray, clip.fps, body_frac=body)
    trim = segment.camera_trim(video.band_envelope(clip), clip.fps,
                               clip.duration)
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
        "strike_level": round(env.strike_level, 4),
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
            "hip_lead": round(pose.hip_lead(track.hip_speed,
                                            track.wrist_speed,
                                            clip.fps / pose.EVERY), 3)
                        if (track and track.trustworthy) else None,
            "stance_median": round(float(np.median(track.stance)), 2)
                             if (track and track.trustworthy) else None,
            "grip_median": round(float(np.median(track.grip)), 2)
                           if (track and track.trustworthy) else None,
        },
        "hits": [
            {"t_peak": round(h.t_peak, 3), "peak": round(h.peak, 3),
             "windup": round(h.windup, 3), "stop": round(h.stop, 3),
             "gap_before": round(h.gap_before, 3) if h.gap_before else None,
             "dead_stop_before": h.dead_stop_before}
            for h in hits
        ],
        "segments": [{"role": p.role, "start": round(p.start, 3),
                      "end": round(p.end, 3)} for p in parts],
        "pictures": pictures,
    }
