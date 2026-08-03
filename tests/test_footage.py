import json

import numpy as np
import pytest

from src.footage import (
    BaseShot,
    FootageError,
    FootageSource,
    despill,
    green_alpha,
    load_shots,
    missing,
    paste,
    resolve,
)
from src.models import Timeline
from src.video_plan import build_plan


def _real_plan():
    with open("scenario/timeline.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    return build_plan(raw["events"], Timeline.load("scenario/timeline.json").total_duration)


def _write(tmp_path, data):
    path = tmp_path / "shots.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# --- разбор списка кадров ----------------------------------------------------


def test_shots_parse_with_defaults(tmp_path):
    path = _write(tmp_path, {
        "base": [{"anchor": "combat", "clip": "b.mp4"}],
        "fx": [{"anchor": "burst1_whoosh", "clip": "f.mov"}],
    })
    bases, fx = load_shots(path)
    assert bases[0].speed == 1.0 and bases[0].grade == "none" and bases[0].gain == 1.0
    assert fx[0].scale == 1.0 and fx[0].key == "alpha" and fx[0].opacity == 1.0


def test_base_loops_by_default(tmp_path):
    path = _write(tmp_path, {"base": [{"anchor": "combat", "clip": "b.mp4"}]})
    assert load_shots(path)[0][0].loop is True


def test_base_can_be_told_not_to_loop(tmp_path):
    path = _write(tmp_path, {"base": [{"anchor": "combat", "clip": "b.mp4",
                                       "loop": False}]})
    assert load_shots(path)[0][0].loop is False


def test_the_breach_does_not_loop():
    """Кадр-событие нельзя закольцовывать: пятисекундный клип на шестисекундном
    куске вылетел бы дверью дважды, и это читается как поломка файла."""
    bases, _ = load_shots("scenario/shots.json")
    breach = next(b for b in bases if b.anchor == "combat")
    assert breach.loop is False
    assert all(b.loop for b in bases if b.anchor != "combat")


def test_procedural_is_empty_by_default(tmp_path):
    path = _write(tmp_path, {"base": [{"anchor": "combat", "clip": "b.mp4"}]})
    assert load_shots(path)[0][0].procedural == ""


def test_the_breach_has_a_procedural_fallback():
    """Единственный кадр, который обязан объяснять, не должен зависеть ни от
    оплаты, ни от гео-блока: LTX Studio Молдове закрыт целиком."""
    bases, _ = load_shots("scenario/shots.json")
    breach = next(b for b in bases if b.anchor == "combat")
    assert breach.procedural == "breach"


def test_procedural_fallback_only_inside_its_own_window(tmp_path):
    from src.footage import FootageSource
    bases, fx = resolve(*load_shots("scenario/shots.json"), _real_plan())
    source = FootageSource(bases, fx, tmp_path, 64, 36, 30, seek=True)
    assert source.procedural_at(22.4) == ("breach", pytest.approx(0.1))
    assert source.procedural_at(28.4)[0] == "breach"
    assert source.procedural_at(22.2)[0] == ""
    assert source.procedural_at(28.6)[0] == ""
    assert source.procedural_at(50.0)[0] == ""


def test_procedural_fallback_steps_aside_when_the_clip_exists(tmp_path):
    from src.footage import FootageSource
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "breach.mp4").write_bytes(b"x")
    bases, fx = resolve(*load_shots("scenario/shots.json"), _real_plan())
    source = FootageSource(bases, fx, tmp_path, 64, 36, 30, seek=True)
    assert source.procedural_at(24.0)[0] == ""


def test_shots_reject_a_missing_clip_field(tmp_path):
    path = _write(tmp_path, {"base": [{"anchor": "combat"}]})
    with pytest.raises(FootageError, match="clip"):
        load_shots(path)


def test_shots_reject_an_unknown_grade(tmp_path):
    path = _write(tmp_path, {"base": [{"anchor": "combat", "clip": "b.mp4",
                                       "grade": "sepia"}]})
    with pytest.raises(FootageError, match="sepia"):
        load_shots(path)


def test_shots_reject_an_unknown_key(tmp_path):
    path = _write(tmp_path, {"fx": [{"anchor": "x", "clip": "f.mov", "key": "luma"}]})
    with pytest.raises(FootageError, match="luma"):
        load_shots(path)


@pytest.mark.parametrize("key", ["alpha", "green", "add"])
def test_shots_accept_every_supported_key(key, tmp_path):
    """Три формата, в которых сток реально поставляет эффекты: с альфа-каналом,
    на зелёном и на чёрном."""
    path = _write(tmp_path, {"fx": [{"anchor": "x", "clip": "f.mov", "key": key}]})
    assert load_shots(path)[1][0].key == key


def test_shots_reject_zero_speed(tmp_path):
    """speed=0 уводит setpts в деление на ноль, а сообщение FFmpeg об этом
    ничего не говорит про список кадров."""
    path = _write(tmp_path, {"base": [{"anchor": "combat", "clip": "b.mp4", "speed": 0}]})
    with pytest.raises(FootageError, match="speed"):
        load_shots(path)


def test_shots_reject_zero_scale(tmp_path):
    path = _write(tmp_path, {"fx": [{"anchor": "x", "clip": "f.mov", "scale": 0}]})
    with pytest.raises(FootageError, match="scale"):
        load_shots(path)


# --- привязка к якорям -------------------------------------------------------


def test_resolve_takes_times_from_the_scenario(tmp_path):
    path = _write(tmp_path, {
        "base": [{"anchor": "ice", "clip": "i.mp4"},
                 {"anchor": "interrogation", "clip": "a.mp4"}],
        "fx": [{"anchor": "burst3_impact_a", "clip": "f.mov"}],
    })
    bases, fx = resolve(*load_shots(path), _real_plan())
    assert [b.t for b in bases] == [0.0, 47.0]
    assert fx[0].t == 38.6


def test_resolve_cuts_bases_at_each_other(tmp_path):
    path = _write(tmp_path, {"base": [
        {"anchor": "interrogation", "clip": "a.mp4"},
        {"anchor": "combat", "clip": "b.mp4"},
        {"anchor": "ice", "clip": "c.mp4"},
    ]})
    bases, _ = resolve(*load_shots(path), _real_plan())
    assert [(b.t, b.end) for b in bases] == [(0.0, 22.3), (22.3, 47.0), (47.0, 60.0)]


def test_resolve_lets_a_base_hang_on_an_event_not_only_on_a_state(tmp_path):
    path = _write(tmp_path, {"base": [
        {"anchor": "interrogation", "clip": "a.mp4"},
        {"anchor": "hit_on_lohen", "clip": "b.mp4"},
    ]})
    bases, _ = resolve(*load_shots(path), _real_plan())
    assert [(b.t, b.end) for b in bases] == [(0.0, 42.8), (42.8, 60.0)]


def test_resolve_applies_lead(tmp_path):
    path = _write(tmp_path, {"fx": [
        {"anchor": "burst1_whoosh", "clip": "f.mov", "lead": 0.2}]})
    _, fx = resolve(*load_shots(path), _real_plan())
    assert fx[0].t == pytest.approx(28.3)


def test_resolve_rejects_a_dangling_anchor(tmp_path):
    path = _write(tmp_path, {"base": [{"anchor": "no_such_thing", "clip": "b.mp4"}]})
    with pytest.raises(FootageError, match="no_such_thing"):
        resolve(*load_shots(path), _real_plan())


def test_missing_lists_only_absent_clips(tmp_path):
    (tmp_path / "here.mp4").write_bytes(b"x")
    path = _write(tmp_path, {"base": [
        {"anchor": "interrogation", "clip": "here.mp4"},
        {"anchor": "combat", "clip": "gone.mp4"},
    ]})
    bases, _ = resolve(*load_shots(path), _real_plan())
    assert missing(bases, tmp_path) == ["gone.mp4"]


def test_the_real_shot_list_resolves_against_the_real_scenario():
    """Опечатка в имени якоря должна падать здесь, а не на рендере через
    восемь минут."""
    bases, fx = resolve(*load_shots("scenario/shots.json"), _real_plan())
    assert [b.anchor for b in bases] == [
        "interrogation", "combat", "burst1_whoosh", "ice"]
    assert len(fx) == 5
    assert all(f.t >= 0 for f in fx)
    assert bases[-1].end == 60.0


def test_the_breach_gets_its_own_shot_and_it_is_long_enough_to_read():
    """22.30-28.50 — кадр, из которого зал узнаёт, что в комнату вломились.

    Если его слить с боевым фоном, пролом снова превратится во вспышку, а это
    единственное место номера, где зрителю нужно объяснение, а не атмосфера.
    """
    bases, _ = resolve(*load_shots("scenario/shots.json"), _real_plan())
    breach = next(b for b in bases if b.anchor == "combat")
    assert breach.t == 22.3
    assert breach.end == 28.5
    assert breach.end - breach.t >= 4.0


# --- композиция --------------------------------------------------------------


def _frame(value=0.0, size=(6, 8)):
    return np.full((*size, 3), value, dtype=np.float32)


def test_paste_puts_the_patch_where_it_is_told():
    base = _frame(0.0)
    patch = np.ones((2, 2, 3), dtype=np.float32)
    out = paste(base, patch, np.ones((2, 2), dtype=np.float32), 3, 1)
    assert out[1:3, 3:5].min() == 1.0
    assert out[0, 0].max() == 0.0


def test_paste_clips_at_the_edge_instead_of_wrapping():
    """Увеличенный слэш со сдвигом обязан обрезаться, а не переползти на
    другую сторону кадра."""
    base = _frame(0.0)
    patch = np.ones((4, 4, 3), dtype=np.float32)
    out = paste(base, patch, np.ones((4, 4), dtype=np.float32), -2, -2)
    assert out[0:2, 0:2].min() == 1.0
    assert out[-1, -1].max() == 0.0


def test_paste_is_a_noop_when_the_patch_is_fully_outside():
    base = _frame(0.25)
    patch = np.ones((3, 3, 3), dtype=np.float32)
    out = paste(base, patch, np.ones((3, 3), dtype=np.float32), 50, 50)
    assert out.min() == out.max() == pytest.approx(0.25)


def test_paste_can_add_instead_of_covering():
    """Световые эффекты на чёрном кладутся сложением: чёрное исчезает само,
    а мягкий ореол остаётся мягким."""
    base = _frame(0.2)
    patch = np.zeros((2, 2, 3), dtype=np.float32)
    patch[0, 0] = 0.5
    out = paste(base, patch, np.ones((2, 2), dtype=np.float32), 0, 0, "add")
    assert out[0, 0].max() == pytest.approx(0.7)
    assert out[1, 1].max() == pytest.approx(0.2)


def test_paste_respects_partial_alpha():
    base = _frame(0.0)
    patch = np.ones((2, 2, 3), dtype=np.float32)
    out = paste(base, patch, np.full((2, 2), 0.5, dtype=np.float32), 0, 0)
    assert out[0, 0].max() == pytest.approx(0.5)


def test_green_screen_becomes_transparent():
    rgb = np.zeros((2, 2, 3), dtype=np.float32)
    rgb[:, :, 1] = 1.0
    assert green_alpha(rgb).max() == pytest.approx(0.0)


def test_non_green_stays_opaque():
    rgb = np.ones((2, 2, 3), dtype=np.float32)
    assert green_alpha(rgb).min() == pytest.approx(1.0)


def test_despill_pulls_green_down_to_the_other_channels():
    rgb = np.zeros((1, 1, 3), dtype=np.float32)
    rgb[0, 0] = (0.2, 0.9, 0.3)
    assert despill(rgb)[0, 0, 1] == pytest.approx(0.3)


def test_despill_leaves_honest_green_alone():
    rgb = np.zeros((1, 1, 3), dtype=np.float32)
    rgb[0, 0] = (0.4, 0.2, 0.5)
    assert despill(rgb)[0, 0, 1] == pytest.approx(0.2)


# --- заморозка держит и снятый материал --------------------------------------


@pytest.fixture
def moving_clip(tmp_path):
    """Трёхсекундный клип, у которого каждый кадр отличается от соседнего.

    На клипе из одинаковых кадров тест на заморозку прошёл бы и на сломанном
    коде: держим мы кадр или читаем следующий, картинка была бы та же.
    """
    import subprocess
    (tmp_path / "base").mkdir()
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
        "-i", "testsrc=size=64x36:rate=30", "-t", "3",
        "-pix_fmt", "yuv420p", str(tmp_path / "base" / "c.mp4"),
    ], check=True)
    return tmp_path


def test_footage_holds_its_frame_while_time_is_frozen(moving_clip):
    """На 55.2 исполнитель держит позу, и шевелиться в зале не должно ничто.

    Процедурный фон замирал и раньше, а снятый материал продолжал ехать: труба
    FFmpeg отдаёт следующий кадр на каждый вызов, и никакое время её не
    остановит. Пока фона не было, это не проявлялось.
    """
    bases = [BaseShot(anchor="ice", clip="base/c.mp4", t=0.0, end=3.0)]
    source = FootageSource(bases, [], moving_clip, 64, 36, 30)
    try:
        moving = [source.base(i / 30.0, i / 30.0) for i in range(10)]
        held = [source.base(0.5 + i / 30.0, 0.5) for i in range(4)]
    finally:
        source.close()
    assert not np.array_equal(moving[0], moving[5]), "клип должен ехать"
    assert all(np.array_equal(held[0], frame) for frame in held[1:])


def test_footage_freeze_works_in_seek_mode_too(moving_clip):
    """Кадры-образцы идут вразнобой, поэтому держать последний прочитанный
    нельзя — надо перематывать на замороженный момент."""
    bases = [BaseShot(anchor="ice", clip="base/c.mp4", t=0.0, end=3.0)]
    source = FootageSource(bases, [], moving_clip, 64, 36, 30, seek=True)
    try:
        frozen_early = source.base(1.0, 0.5)
        frozen_late = source.base(2.0, 0.5)
        running = source.base(2.0, 2.0)
    finally:
        source.close()
    assert np.array_equal(frozen_early, frozen_late)
    assert not np.array_equal(frozen_early, running)


def test_footage_runs_normally_when_time_is_not_frozen(moving_clip):
    """Заморозка не должна протечь на остальной номер."""
    bases = [BaseShot(anchor="ice", clip="base/c.mp4", t=0.0, end=3.0)]
    source = FootageSource(bases, [], moving_clip, 64, 36, 30, seek=True)
    try:
        a = source.base(0.5, 0.5)
        b = source.base(1.5, 1.5)
    finally:
        source.close()
    assert not np.array_equal(a, b)
