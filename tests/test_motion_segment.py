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


def test_6b_a_continuous_transition_is_not_a_dead_stop(tmp_path):
    """Те же два всплеска, но между ними движение не прекращается."""
    env, trim, _ = analyse(motion_clips.two_sweeps(tmp_path / "c.mp4",
                                                   fps=30, dead=False))
    hits = segment.strikes(env, trim)
    assert len(hits) == 2, [round(h.t_peak, 2) for h in hits]
    assert hits[1].dead_stop_before is False


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
