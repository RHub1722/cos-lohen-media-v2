import pytest

from src.models import Timeline
from src.movements import load_movements
from src.strikes import Strike, StrikeError, load_strikes, resolve_strikes

# Пики внутри ассетов, замеренные src/peaks.py. В тестах они заданы руками, чтобы
# проверка не зависела от наличия FFmpeg и от самих файлов.
PEAKS = {
    "sfx/spear_whoosh_fast.wav": 0.3757,
    "sfx/spear_staff_impact.wav": 0.0085,
    "sfx/spear_armor_impact.wav": 0.05,
    "sfx/automaton_advance.wav": 1.0809,
}


def _tl():
    return Timeline.from_dict({
        "total_duration": 60.0,
        "events": [
            {"id": "burst1_whoosh", "t": 28.5,
             "asset": "sfx/spear_whoosh_fast.wav", "stem": "sfx"},
            {"id": "burst1_impact", "t": 29.13,
             "asset": "sfx/spear_staff_impact.wav", "stem": "sfx"},
            {"id": "automaton_advance", "t": 38.6,
             "asset": "sfx/automaton_advance.wav", "stem": "sfx"},
            {"id": "burst3_impact_b", "t": 39.87,
             "asset": "sfx/spear_armor_impact.wav", "stem": "sfx"},
        ],
    })


def _raw(**over):
    base = {
        "id": "burst_1", "movement": "burst_1", "title": "Вспышка 1",
        "loop": {"from": "burst1_whoosh", "pre": 1.5,
                 "to": "burst1_impact", "post": 1.5},
        "beats": [
            {"role": "swing", "trigger": "burst1_whoosh", "what": "взмах"},
            {"role": "contact", "trigger": "burst1_impact", "what": "контакт"},
        ],
    }
    base.update(over)
    return base


# ── схема ────────────────────────────────────────────────────────────────────

def test_strike_parses_required_fields():
    s = Strike.from_dict(_raw())
    assert s.id == "burst_1"
    assert len(s.beats) == 2
    assert s.beats[0].peak is True


def test_strike_rejects_a_beat_without_contact():
    raw = _raw(beats=[{"role": "swing", "trigger": "burst1_whoosh", "what": "x"}])
    with pytest.raises(StrikeError, match="contact"):
        Strike.from_dict(raw)


def test_strike_rejects_an_unknown_role():
    raw = _raw(beats=[{"role": "прыжок", "trigger": "burst1_whoosh", "what": "x"}])
    with pytest.raises(StrikeError, match="роль"):
        Strike.from_dict(raw)


def test_strike_rejects_a_loop_without_bounds():
    with pytest.raises(StrikeError, match="loop"):
        Strike.from_dict(_raw(loop={"from": "burst1_whoosh"}))


# ── времена ──────────────────────────────────────────────────────────────────

def test_beat_time_is_measured_from_the_peak_not_from_the_file_start():
    """Ассет ставится началом файла, а слышен пиком: у быстрого взмаха 0.376 с
    разницы. Показать исполнителю время файла — значит увести его на треть
    секунды, и он попадёт мимо, оставаясь правым."""
    s = resolve_strikes([Strike.from_dict(_raw())], _tl(), PEAKS)[0]
    swing = s.beats[0]
    assert swing.t == 28.5
    assert swing.heard == pytest.approx(28.8757, abs=1e-4)


def test_a_texture_beat_counts_from_the_file_start():
    """У наступления автоматона самый громкий отсчёт на 1.08 с, но событием
    является вход машины в кадр, то есть начало файла."""
    raw = _raw(beats=[
        {"role": "hold", "trigger": "automaton_advance", "peak": False,
         "what": "машина входит"},
        {"role": "contact", "trigger": "burst3_impact_b", "what": "к"},
    ], loop={"from": "automaton_advance", "pre": 1.5,
             "to": "burst3_impact_b", "post": 1.5})
    beats = resolve_strikes([Strike.from_dict(raw)], _tl(), PEAKS)[0].beats
    assert beats[0].heard == 38.6


def test_resolve_rejects_a_dangling_trigger():
    raw = _raw(beats=[{"role": "contact", "trigger": "no_such", "what": "x"}])
    with pytest.raises(StrikeError, match="no_such"):
        resolve_strikes([Strike.from_dict(raw)], _tl(), PEAKS)


def test_resolve_rejects_beats_out_of_order():
    raw = _raw(beats=[
        {"role": "contact", "trigger": "burst1_impact", "what": "контакт"},
        {"role": "swing", "trigger": "burst1_whoosh", "what": "взмах"},
    ])
    with pytest.raises(StrikeError, match="раньше предыдущей"):
        resolve_strikes([Strike.from_dict(raw)], _tl(), PEAKS)


def test_resolve_rejects_a_loop_that_misses_its_own_beats():
    raw = _raw(loop={"from": "burst1_whoosh", "pre": 0.0,
                     "to": "burst1_whoosh", "post": 0.1})
    with pytest.raises(StrikeError, match="вне окна петли"):
        resolve_strikes([Strike.from_dict(raw)], _tl(), PEAKS)


def test_resolve_rejects_a_movement_that_does_not_exist():
    with pytest.raises(StrikeError, match="хореографии"):
        resolve_strikes([Strike.from_dict(_raw(movement="ghost"))], _tl(),
                        PEAKS, movements=["circling", "burst_1"])


# ── настоящие данные ─────────────────────────────────────────────────────────

def _real():
    tl = Timeline.load("scenario/timeline.json")
    moves = load_movements("scenario/movements.json")
    strikes = load_strikes("scenario/strikes.json")
    peaks = {e.asset: PEAKS.get(e.asset, 0.05) for e in tl.events}
    return tl, resolve_strikes(strikes, tl, peaks, [m.id for m in moves])


def test_every_real_strike_resolves_against_the_real_scenario():
    _tl_, strikes = _real()
    assert len(strikes) == 6
    assert [s.id for s in strikes] == [
        "burst_1", "burst_2", "burst_3", "take_the_hit", "burst_4", "spear_down"]


def test_every_fight_movement_has_a_card():
    """Движение боя без карточки — это движение, которое нечем разучивать."""
    _tl_, strikes = _real()
    covered = {s.movement for s in strikes}
    fight = {"burst_1", "burst_2", "burst_3", "burst_4",
             "take_the_hit", "spear_down"}
    assert fight <= covered


def test_contacts_stand_on_sound_effects_not_on_music_or_speech():
    """Контакт ставится на слышимый эффект. На реплике или на музыке он
    означал бы, что попадание нечем проверить на слух."""
    tl, strikes = _real()
    stems = {e.id: e.stem for e in tl.events}
    for s in strikes:
        for b in s.beats:
            if b.role == "contact":
                assert stems[b.trigger] == "sfx", f"{s.id}/{b.trigger}"


def test_the_fourth_burst_has_no_impact_sound_of_its_own():
    """Замер: у четвёртой вспышки в сценарии только взмах, отдельного удара нет,
    и контакт стоит на пике свиста. Если удар когда-нибудь появится, карточку
    надо переставить на него — этот тест об этом напомнит."""
    tl, strikes = _real()
    ids = {e.id for e in tl.events}
    assert "burst4_impact" not in ids
    burst4 = next(s for s in strikes if s.id == "burst_4")
    contact = next(b for b in burst4.beats if b.role == "contact")
    assert contact.trigger == "burst4_whoosh"


def test_the_second_hit_of_burst_two_stays_in_the_sheet():
    """На 36.53 в звуке удар по броне и самая заметная вспышка серии, а в
    хореографии на это время движения нет. Карточка обязана про это говорить."""
    _tl_, strikes = _real()
    burst2 = next(s for s in strikes if s.id == "burst_2")
    contacts = [b for b in burst2.beats if b.role == "contact"]
    assert [b.trigger for b in contacts] == ["burst2_impact", "burst2_impact_b"]
    assert "хореографии" in contacts[1].what


def test_every_beat_carries_a_pose():
    """Без позы доля не рисуется, и карточка теряет половину смысла."""
    _tl_, strikes = _real()
    for s in strikes:
        for b in s.beats:
            assert b.pose, f"{s.id}/{b.role}"
            assert "spear" in b.pose, f"{s.id}/{b.role}"


def test_every_strike_explains_what_is_verified_and_what_is_staged():
    """Референс без пометки, что проверено и что поставлено мной, — это
    выдумка, поданная как факт."""
    _tl_, strikes = _real()
    for s in strikes:
        assert s.reference.get("verified"), s.id
        assert s.drill and s.mistakes, s.id
