"""Ввод: сколько кадров, какой формы, и падает ли внятно на плохом файле."""

import numpy as np
import pytest

from motion import video
from tests import motion_clips


def test_probe_reads_size_and_fps(tmp_path):
    path = motion_clips.still(tmp_path / "a.mp4", fps=30, total=90)
    clip = video.probe(path)
    assert (clip.width, clip.height) == (motion_clips.W, motion_clips.H)
    assert clip.fps == 30
    assert clip.duration == pytest.approx(3.0, abs=0.2)


def test_gray_frames_shape_and_range(tmp_path):
    path = motion_clips.still(tmp_path / "a.mp4", fps=30, total=90)
    frames = video.gray_frames(video.probe(path), width=160)
    assert frames.ndim == 3
    assert frames.shape[2] == 160
    assert frames.shape[1] == 90          # пропорции 320x180 сохранены
    assert frames.dtype == np.float32
    assert 0.0 <= frames.min() and frames.max() <= 1.0
    assert len(frames) >= 88              # кодек может отдать на кадр меньше


def test_short_clip_is_refused(tmp_path):
    path = motion_clips.still(tmp_path / "a.mp4", fps=30, total=30)
    with pytest.raises(video.VideoError, match="от 2 с"):
        video.probe(path)


def test_a_russian_filename_is_read(tmp_path):
    """Имя файла с кириллицей и пробелами читается.

    Без явной кодировки Python декодировал вывод ffprobe локальной cp1252,
    падал на русских буквах, получал пустой JSON и сообщал «в файле нет
    видеодорожки». Один файл заказчика на 265 МБ так и не разобрался.
    """
    path = motion_clips.still(
        tmp_path / "VID_я думаю как это сделать и ппреминений нет.mp4",
        fps=30, total=90)
    clip = video.probe(path)
    assert clip.fps == 30
    assert clip.duration == pytest.approx(3.0, abs=0.2)
    assert len(video.gray_frames(clip, width=160)) >= 88


def test_missing_file_names_itself(tmp_path):
    with pytest.raises(video.VideoError, match="нет.mp4"):
        video.probe(tmp_path / "нет.mp4")


def test_strike_strip_has_four_columns(tmp_path):
    from PIL import Image

    from motion import frames as mframes
    from motion.segment import Strike

    clip = video.probe(motion_clips.sweep(tmp_path / "s.mp4", fps=30,
                                          total=120, a=30, b=60))
    hit = Strike(t_peak=1.5, peak=3.0, windup=0.4, stop=0.3, gap_before=None,
                 floor_before=None, dip_ratio=None, dead_stop_before=None)
    out = mframes.strike_strip(clip, hit, tmp_path / "strip.png")
    assert out.exists()
    with Image.open(out) as img:
        assert img.width > img.height * 3, "четыре кадра в ряд"


def test_overview_sheet_is_written(tmp_path):
    from motion import frames as mframes
    clip = video.probe(motion_clips.still(tmp_path / "s.mp4", fps=30, total=120))
    out = mframes.overview_sheet(clip, tmp_path / "sheet.png")
    assert out.exists() and out.stat().st_size > 1000
