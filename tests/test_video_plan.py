import json

import numpy as np
import pytest

from src.models import Timeline
from src.render_video import (
    SAFE_FLOOR,
    SAFE_STRIP,
    Canvas,
    render_frame,
    safety_row,
)
from src.video_plan import VideoPlanError, build_plan

# Потолок из плана фазы 3: центральная полоса гасится множителем не выше этого.
PLANNED_CEILING = 0.35


def _real_plan():
    with open("scenario/timeline.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    return build_plan(raw["events"], Timeline.load("scenario/timeline.json").total_duration)


def _events(*extra):
    start = {"id": "start", "t": 0.0, "asset": "a.wav", "stem": "ambience",
             "video": {"cue": "state", "state": "interrogation"}}
    return [start, *extra]


def _ev(t, cue, **video):
    video["cue"] = cue
    return {"id": f"e{t}", "t": t, "asset": "a.wav", "stem": "sfx", "video": video}


# --- разбор сценария ---------------------------------------------------------


def test_real_scenario_yields_the_three_states():
    plan = _real_plan()
    assert [s.state for s in plan.segments] == ["interrogation", "combat", "ice"]
    assert [s.start for s in plan.segments] == [0.0, 22.3, 47.0]


def test_states_are_contiguous_and_cover_the_whole_number():
    plan = _real_plan()
    assert plan.segments[0].start == 0.0
    assert plan.segments[-1].end == plan.total
    for a, b in zip(plan.segments, plan.segments[1:]):
        assert a.end == b.start


def test_real_scenario_yields_every_anchor():
    kinds = sorted(c.kind for c in _real_plan().cues)
    assert kinds == ["drain", "flash", "flash", "flash", "flash",
                     "freeze", "tighten", "whiteflash"]


def test_tighten_runs_until_the_palette_changes():
    cue = next(c for c in _real_plan().cues if c.kind == "tighten")
    assert (cue.t, cue.end) == (16.2, 22.3)


def test_freeze_runs_to_the_end_of_the_number():
    plan = _real_plan()
    cue = next(c for c in plan.cues if c.kind == "freeze")
    assert cue.end == plan.total


def test_flash_is_a_short_transient():
    for cue in _real_plan().cues:
        if cue.kind == "flash":
            assert cue.end - cue.t == pytest.approx(0.22)


def test_phase_runs_from_zero_to_one_and_is_none_outside():
    cue = next(c for c in _real_plan().cues if c.kind == "flash")
    assert cue.phase(cue.t) == 0.0
    assert cue.phase(cue.t - 0.01) is None
    assert cue.phase(cue.end) is None
    assert cue.phase((cue.t + cue.end) / 2) == pytest.approx(0.5)


def test_plan_rejects_a_number_that_does_not_open_with_a_state():
    events = [_ev(3.0, "state", state="combat")]
    with pytest.raises(VideoPlanError, match="0.0"):
        build_plan(events, 60.0)


def test_plan_rejects_an_unknown_anchor():
    with pytest.raises(VideoPlanError, match="glitch"):
        build_plan(_events(_ev(5.0, "glitch")), 60.0)


def test_plan_rejects_an_unknown_state():
    with pytest.raises(VideoPlanError, match="twilight"):
        build_plan(_events(_ev(5.0, "state", state="twilight")), 60.0)


def test_plan_rejects_intensity_out_of_range():
    with pytest.raises(VideoPlanError, match="intensity"):
        build_plan(_events(_ev(5.0, "flash", intensity=1.4)), 60.0)


def test_plan_rejects_a_video_block_without_a_cue():
    broken = {"id": "x", "t": 5.0, "asset": "a.wav", "stem": "sfx", "video": {"intensity": 1}}
    with pytest.raises(VideoPlanError, match="cue"):
        build_plan(_events(broken), 60.0)


def test_plan_rejects_a_scenario_with_no_video_blocks():
    with pytest.raises(VideoPlanError, match="video"):
        build_plan([{"id": "x", "t": 0.0, "asset": "a.wav", "stem": "sfx"}], 60.0)


def test_plan_rejects_an_anchor_past_the_end_of_the_number():
    with pytest.raises(VideoPlanError, match="за концом"):
        build_plan(_events(_ev(90.0, "flash")), 60.0)


# --- предохранитель ----------------------------------------------------------


def test_safety_floor_stays_under_the_planned_ceiling():
    assert SAFE_FLOOR <= PLANNED_CEILING


def test_the_whole_declared_strip_is_darkened_not_just_its_middle():
    """Плавный подъём обязан лежать ЗА полосой.

    Если размазать его внутрь, сорок процентов ширины окажутся тёмными только
    в середине, а по краям полосы фон снова начнёт выедать силуэт.
    """
    width = 1920
    row = safety_row(width)
    core = np.isclose(row, SAFE_FLOOR)
    assert core.sum() / width >= SAFE_STRIP - 2.0 / width
    assert row[core].max() <= PLANNED_CEILING


def test_safety_row_leaves_the_edges_of_the_frame_alone():
    row = safety_row(1920)
    assert row[0] == pytest.approx(1.0)
    assert row[-1] == pytest.approx(1.0)


def test_safety_row_rises_monotonically_from_the_middle():
    row = safety_row(1920)
    half = row[row.size // 2:]
    assert np.all(np.diff(half) >= -1e-7)


def test_the_strip_is_applied_at_every_moment_of_the_number():
    """Ни одно состояние и ни один якорь не может обойти предохранитель."""
    plan = _real_plan()
    guarded, bare = Canvas(160, 90), Canvas(160, 90)
    bare.safe = np.ones_like(bare.safe)
    core = np.isclose(safety_row(160), SAFE_FLOOR)

    moments = [t / 4.0 for t in range(int(plan.total * 4))]
    moments += [c.t for c in plan.cues] + [c.t + 0.03 for c in plan.cues]
    moments += [s.start for s in plan.segments]

    for t in moments:
        a = render_frame(guarded, plan, t, 30)[:, core, :]
        b = render_frame(bare, plan, t, 30)[:, core, :]
        assert np.allclose(a, b * SAFE_FLOOR, atol=1e-5), f"полоса не применена на {t}"


def test_the_background_flashes_behind_the_performer_but_never_burns():
    """Вспышка на удар — можно, ровный свет за спиной — нет.

    Проверяется не множитель, а то, что получилось: сколько подряд кадров
    центр кадра остаётся ярким. Костюм судят, и съесть его может только
    длительная засветка, а не двухкадровый удар.
    """
    plan = _real_plan()
    canvas = Canvas(160, 90)
    core = np.isclose(safety_row(160), SAFE_FLOOR)
    fps = 30

    longest = run = 0
    for i in range(int(plan.total * fps)):
        frame = np.clip(render_frame(canvas, plan, i / fps, fps), 0.0, 1.0)
        run = run + 1 if frame[:, core, :].mean() > 0.18 else 0
        longest = max(longest, run)
    assert longest <= 0.40 * fps


# --- поведение во времени ----------------------------------------------------


def test_the_track_divides_into_whole_frames():
    total = _real_plan().total
    for fps in (25, 30, 50, 60):
        assert (total * fps) % 1 == 0


def test_the_white_flash_lasts_exactly_two_frames():
    """Регрессия: фаза якоря считалась по замороженному времени, и вспышка
    залипала на первом кадре все девять десятых секунды."""
    plan = _real_plan()
    canvas = Canvas(96, 54)
    cue = next(c for c in plan.cues if c.kind == "whiteflash")
    levels = [
        np.clip(render_frame(canvas, plan, cue.t + i / 30, 30), 0.0, 1.0).mean()
        for i in range(6)
    ]
    assert levels[0] > 0.4 and levels[1] > 0.4
    assert all(level < 0.10 for level in levels[2:])


def test_the_picture_goes_still_where_he_does_not_react():
    """42.8 — он принимает удар и не реагирует. Фон тоже."""
    plan = _real_plan()
    canvas = Canvas(96, 54)
    cue = next(c for c in plan.cues if c.kind == "whiteflash")
    a = render_frame(canvas, plan, cue.t + 0.20, 30)
    b = render_frame(canvas, plan, cue.t + 0.30, 30)
    assert np.array_equal(a, b)


def test_nothing_moves_after_the_freeze():
    plan = _real_plan()
    canvas = Canvas(96, 54)
    held = render_frame(canvas, plan, 57.5, 30)
    assert np.array_equal(held, render_frame(canvas, plan, 59.9, 30))
    assert not np.array_equal(held, render_frame(canvas, plan, 54.0, 30))
