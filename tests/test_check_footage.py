"""Приёмка материала: яркость по третям и движение.

Замер — единственное, что стоит между генерацией и залом, и ошибка в нём тише
любой ошибки в картинке: сломанный замер отчитывается «в порядке». Поэтому здесь
проверяется не только то, что числа считаются, но и то, что они считаются именно
так, а не похожим способом: Rec.709, а не средний RGB; отдельно по полосе, а не
по всему кадру; и стык между кадрами не выдаётся за движение внутри клипа.
"""

import json
import subprocess

import numpy as np
import pytest

from src.check_footage import (CENTRE_LIMIT, QUIET_MOTION_LIMIT, Sample,
                               clip_stream, quiet_windows, report, scan, zones)
from src.models import Timeline
from src.video_plan import build_plan

W, H = 200, 20


def _plan():
    with open("scenario/timeline.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    return build_plan(raw["events"],
                      Timeline.load("scenario/timeline.json").total_duration)


def _flat(value: float) -> np.ndarray:
    return np.full((H, W, 3), value, dtype=np.float32)


def _stream(frames, fps: int = 30):
    return [(i / fps, f) for i, f in enumerate(frames)]


# --- зоны --------------------------------------------------------------------


def test_centre_is_the_strip_the_safety_dims_not_a_third():
    """Полоса предохранителя — 40% ширины, треть — 33%. Это разные зоны, и порог
    0.12 стоит именно на полосе."""
    masks = zones(1000)
    assert masks["centre"].sum() == pytest.approx(400, abs=2)
    assert masks["middle"].sum() == pytest.approx(333, abs=2)


def test_thirds_cover_the_frame_without_overlap():
    masks = zones(999)
    total = masks["left"].astype(int) + masks["middle"].astype(int) + masks["right"].astype(int)
    assert (total == 1).all()


# --- яркость -----------------------------------------------------------------


def test_luma_is_rec709_not_mean_rgb():
    """Синий весит 0.0722, а не 0.333. По среднему RGB весь тёмно-синий трюм
    выглядел бы втрое ярче, чем его увидит глаз, и порог 0.12 срабатывал бы там,
    где в зале ничего нет."""
    blue = np.zeros((H, W, 3), dtype=np.float32)
    blue[:, :, 2] = 1.0
    sample = scan(_stream([blue]), W)[0]
    assert sample.centre == pytest.approx(0.0722, abs=1e-4)


def test_middle_hotter_needs_both_outer_thirds():
    """Ярче одной крайней трети — норма: у принятого пролома весь свет справа.
    Опасно, только когда середина ярче обеих."""
    assert Sample(0, 0.1, 0.2, 0.1, 0.2, 0, 0).middle_hotter
    assert not Sample(0, 0.1, 0.2, 0.3, 0.2, 0, 0).middle_hotter
    assert not Sample(0, 0.3, 0.2, 0.1, 0.2, 0, 0).middle_hotter


def test_centre_above_limit_is_reported():
    bright = _flat(0.5)
    problems = report("проба", scan(_stream([bright, bright]), W))
    assert problems and "центр выше" in problems[0]


# --- движение ----------------------------------------------------------------


def test_first_frame_motion_is_nan_not_zero():
    """Ноль здесь означал бы «замерли», и неизмеренный кадр оказался бы самым
    спокойным в отчёте. Та же ловушка, что в замере пиков звука."""
    samples = scan(_stream([_flat(0.0), _flat(0.1)]), W)
    assert np.isnan(samples[0].motion)
    assert np.isnan(samples[0].motion_centre)
    assert samples[1].motion == pytest.approx(0.1, abs=1e-4)


def test_motion_in_the_strip_is_measured_separately_from_the_whole_frame():
    """Суета по краям кадра исполнителю не мешает, суета за его спиной мешает.
    Замер по всему кадру не различает эти два случая вовсе."""
    dark = _flat(0.0)
    centre_move, edge_move = _flat(0.0).copy(), _flat(0.0).copy()
    centre_move[:, W // 2 - 10:W // 2 + 10] = 0.4
    edge_move[:, :10] = 0.4

    inside = scan(_stream([dark, centre_move]), W)[1]
    outside = scan(_stream([dark, edge_move]), W)[1]

    assert inside.motion_centre > 0.02
    assert outside.motion > 0.0
    assert outside.motion_centre == pytest.approx(0.0, abs=1e-6)


def test_motion_is_judged_only_inside_quiet_windows():
    """Пролом обязан двигаться. Предел, запрещающий это, был бы предел,
    запрещающий номер."""
    frames = [_flat(0.02), _flat(0.09), _flat(0.02), _flat(0.09)]
    loud = scan(_stream(frames), W, quiet=[(0.0, 10.0)])
    calm = scan(_stream(frames), W, quiet=[(100.0, 110.0)])
    assert report("в спокойном окне", loud)
    assert not report("вне спокойных окон", calm)


def test_cut_into_the_window_is_not_counted_as_motion():
    """Первый кадр куска отличается от последнего кадра предыдущего куска на всю
    склейку. Считать её движением — значит получать максимумом всегда стык и
    прятать под ним настоящую суету внутри клипа."""
    # Внутри куска картинка чуть дышит — 0.005 на кадр. Совсем замерший кусок
    # здесь не годится: он справедливо провалился бы на проверке мёртвого
    # разгона, и тест доказывал бы не то, что проверяет.
    frames = [_flat(0.0)] * 3 + [_flat(0.05), _flat(0.055)] * 4
    samples = scan(_stream(frames), W, quiet=[(0.0, 10.0)])
    window = samples[3:]
    assert window[0].motion == pytest.approx(0.05, abs=1e-4)
    assert window[0].motion > QUIET_MOTION_LIMIT, "склейка обязана быть выше порога"
    assert not report("кусок после склейки", window)


def test_real_motion_inside_the_window_still_fails():
    """Обратная сторона предыдущего теста: исключить стык нельзя ценой того, что
    перестанет ловиться движение вообще."""
    frames = [_flat(0.0)] * 3 + [_flat(0.05), _flat(0.10)] * 4
    samples = scan(_stream(frames), W, quiet=[(0.0, 10.0)])
    problems = report("суетливый кусок", samples[3:])
    assert problems and "движение в полосе" in problems[0]


def test_motion_is_not_judged_for_a_lone_file():
    """У отдельного файла нет места в номере, а значит нет ответа на вопрос,
    стоит ли в это время исполнитель неподвижно."""
    frames = [_flat(0.02), _flat(0.09)] * 3
    samples = scan(_stream(frames), W, quiet=[(0.0, 10.0)])
    assert not report("файл", samples, judge_motion=False)


# --- спокойные окна ----------------------------------------------------------


def test_quiet_windows_come_from_the_timeline():
    """Окна не назначены руками: допрос — это состояние из таймлайна, заморозка —
    якорь оттуда же. Сдвинется сценарий, и окна поедут за ним."""
    plan = _plan()
    windows = quiet_windows(plan)
    assert (0.0, 22.3) in windows
    freeze = [c for c in plan.cues if c.kind == "freeze"]
    assert freeze, "в таймлайне нет заморозки — окно финальной позы взять негде"
    assert (freeze[0].t, plan.total) in windows


def test_the_breach_is_not_in_a_quiet_window():
    windows = quiet_windows(_plan())
    assert not any(a <= 24.0 < b for a, b in windows)


def test_the_final_pose_is_in_a_quiet_window():
    """Почти пять секунд неподвижной финальной позы — худшее место во всём
    номере, чтобы за спиной исполнителя что-то шевелилось."""
    windows = quiet_windows(_plan())
    assert any(a <= 57.0 < b for a, b in windows)


# --- предохранитель в замере файла -------------------------------------------


def test_clip_stream_applies_the_safety_strip(tmp_path):
    """Без предохранителя замер отчитался бы о яркости, которой в зале не будет,
    и белый кадр провалил бы порог, к которому он не относится."""
    clip = tmp_path / "white.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=c=white:s=320x180:r=10", "-t", "0.5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)

    samples = scan(clip_stream(clip, 640, 360, 10), 640)
    assert samples, "клип не прочитался"
    # Белое поле, помноженное на пол предохранителя: 0.30, а не 1.0.
    assert samples[0].centre == pytest.approx(0.30, abs=0.03)
    # Крайние трети остаются яркими, но не на единице: треть — это 33% ширины, а
    # полоса — 40%, они пересекаются, и внутренний край трети всегда попадает под
    # гашение. Потолок трети на белом поле ~0.85, и ждать от неё 1.0 значило бы
    # ждать, что предохранитель не работает.
    assert samples[0].left == pytest.approx(0.85, abs=0.03)
    assert samples[0].right == pytest.approx(0.85, abs=0.03)
    assert samples[0].left > samples[0].centre * 2.5
