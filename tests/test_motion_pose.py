"""Тест 8 приёмки: слой позы необязателен, и его отсутствие не ломает набор."""

import numpy as np
import pytest

from motion import pose


def test_available_always_answers_with_a_reason():
    ok, why = pose.available()
    assert isinstance(ok, bool)
    assert why, "причина обязательна и когда всё есть, и когда нет"


def test_track_returns_none_when_the_layer_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(pose, "available", lambda: (False, "выключено в тесте"))
    from motion import video
    from tests import motion_clips
    clip = video.probe(motion_clips.still(tmp_path / "s.mp4", fps=30, total=90))
    assert pose.track(clip) is None


def test_hip_lead_reads_the_sign_correctly():
    """Бёдра раньше кистей — плюс. Позже — минус. Это весь смысл метрики."""
    fps = 30
    hips = np.zeros(60)
    wrists = np.zeros(60)
    hips[20] = 1.0          # бёдра включились на 20-м кадре
    wrists[26] = 1.0        # кисти на 26-м, то есть на 0.2 с позже
    assert pose.hip_lead(hips, wrists, fps) == pytest.approx(0.2, abs=1e-6)
    assert pose.hip_lead(wrists, hips, fps) == pytest.approx(-0.2, abs=1e-6)


def test_empty_track_has_all_its_fields():
    """Трек без единого сустава собирается и не падает по числу полей."""
    empty = pose._empty(np.zeros(3))
    assert empty.coverage == 0.0
    assert not empty.trustworthy
    for name in ("body_frac", "shoulder_deg", "hip_deg", "wrist_speed",
                 "hip_speed", "stance", "grip"):
        assert getattr(empty, name).size == 0


@pytest.mark.skipif(not pose.available()[0], reason="модели позы нет")
def test_real_track_has_coverage_and_body_height(tmp_path):
    from motion import video
    from tests import motion_clips
    clip = video.probe(motion_clips.still(tmp_path / "s.mp4", fps=30, total=90))
    track = pose.track(clip)
    assert track is not None
    assert 0.0 <= track.coverage <= 1.0
    assert len(track.times) > 0
