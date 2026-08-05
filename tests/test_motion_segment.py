"""Тесты 5-6 приёмки: режимы и переходы."""

import numpy as np
import pytest

from motion import envelope, segment, video
from tests import motion_clips


def analyse(path):
    clip = video.probe(path)
    frames = video.gray_frames(clip, width=160)
    env = envelope.build(frames, clip.fps)
    band = video.band_envelope(clip)
    trim = segment.camera_trim(band, clip.fps, clip.duration)
    return env, trim, clip


def test_5_a_static_clip_is_one_long_rest(tmp_path):
    """Неподвижный клип: один отрезок покоя, ноль ударов."""
    env, trim, clip = analyse(motion_clips.still(tmp_path / "s.mp4",
                                                 fps=30, total=120))
    hits = segment.strikes(env, trim)
    parts = segment.segments(env, trim)
    assert hits == []
    assert [p.role for p in parts] == ["покой"]
    assert parts[0].end - parts[0].start > 3.0


def test_6_dead_stop_between_strikes_is_detected(tmp_path):
    """Два всплеска с полной остановкой между ними."""
    env, trim, _ = analyse(motion_clips.two_sweeps(tmp_path / "d.mp4",
                                                   fps=30, dead=True))
    hits = segment.strikes(env, trim)
    assert len(hits) == 2, [round(h.t_peak, 2) for h in hits]
    assert hits[0].dead_stop_before is None, "у первого удара нет предыдущего"
    assert hits[1].dead_stop_before is True


def _envelope_with_trough(trough: float, fps: int = 30):
    """Два пика единичной высоты и заданная впадина между ними.

    Правило проверяется на огибающей, которую задаю сам, а не через кодек:
    у синтетического видео впадина получается такой, какой её сделает
    треугольник скорости, и подогнать её под нужное значение — значит
    подгонять стенд, а не проверять правило.
    """
    times = np.arange(0, 4, 1.0 / fps)
    vals = np.full(len(times), trough)
    vals[int(0.9 * fps):int(1.1 * fps)] = 1.0
    vals[int(2.9 * fps):int(3.1 * fps)] = 1.0
    # Порог всплеска 0.8: пики по 1.0 его перебивают, а впадина 0.6 — нет.
    # Иначе высокая впадина сама становится сплошным всплеском.
    return envelope.Envelope(
        values=vals, times=times, fps=fps, floor=0.0, noise=0.01,
        action_level=0.10, strike_level=0.80, scale=1.0,
        scale_source="нет", size_fix="нет")


def test_6b_a_dead_stop_is_a_dip_relative_to_its_peaks():
    """Мера связки — глубина впадины относительно соседних пиков.

    Уровень покоя для неё не нужен вовсе, и это главное: чистого покоя в
    тренировочном видео нет, исполнитель двигается почти всё время. Порог,
    выведенный из «уровня покоя», давал «мёртвых остановок 17 из 17» там, где
    глаз видит непрерывную работу.
    """
    trim = segment.Trim(0.0, 4.0, "тест")
    stopped = segment.strikes(_envelope_with_trough(0.02), trim)
    flowing = segment.strikes(_envelope_with_trough(0.60), trim)

    assert len(stopped) == 2 and len(flowing) == 2
    assert stopped[1].dead_stop_before is True
    assert stopped[1].dip_ratio == pytest.approx(0.02, abs=0.01)
    assert flowing[1].dead_stop_before is False
    assert flowing[1].dip_ratio == pytest.approx(0.60, abs=0.01)
    assert stopped[0].dip_ratio is None, "у первого всплеска нет предыдущего"


def test_windup_never_runs_through_a_neighbouring_peak():
    """Обход до уровня 10% ограничен соседними пиками.

    При непрерывной работе огибающая не опускается до 10% между всплесками, и
    без ограничения обход уходил сквозь чужие пики: у всплеска, отстоящего от
    предыдущего на 0.53 с, «замах» выходил 3.27 с.
    """
    trim = segment.Trim(0.0, 4.0, "тест")
    hits = segment.strikes(_envelope_with_trough(0.60), trim)
    assert len(hits) == 2
    gap = hits[1].t_peak - hits[0].t_peak
    for hit in hits:
        assert hit.windup <= gap, (
            f"замах {hit.windup:.2f} с больше расстояния до соседа {gap:.2f} с")
        assert hit.stop <= gap


def test_strike_carries_windup_and_stop(tmp_path):
    env, trim, _ = analyse(motion_clips.sweep(tmp_path / "s.mp4", fps=30,
                                              total=120, a=30, b=60))
    hits = segment.strikes(env, trim)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.windup > 0 and hit.stop > 0
    assert hit.windup + hit.stop <= (60 - 30) / 30 * 1.6
    assert hit.gap_before is None


def test_trim_names_itself_even_when_nothing_is_cut(tmp_path):
    """Обрезанное окно всегда попадает в отчёт, даже если резать нечего."""
    _, trim, clip = analyse(motion_clips.still(tmp_path / "s.mp4",
                                               fps=30, total=120))
    assert trim.start == 0.0
    assert trim.end == pytest.approx(clip.duration, abs=0.3)
    assert trim.reason


def test_trim_without_audio_says_so(tmp_path):
    trim = segment.camera_trim(np.zeros(0), fps=30, duration=4.0)
    assert trim.start == 0.0 and trim.end == 4.0
    assert "дорожки" in trim.reason
