import pytest

from src.models import Timeline
from src.movements import Movement, MovementError, load_movements, resolve_times


def _tl():
    return Timeline.from_dict({
        "total_duration": 60.0,
        "events": [
            {"id": "ice_burst", "t": 47.0, "asset": "a.wav", "stem": "sfx"},
            {"id": "lohen_final", "t": 51.0, "asset": "b.wav", "stem": "voices"},
        ],
    })


def _raw(**over):
    base = {"id": "spear_down", "trigger_event": "ice_burst", "name": "Копьё в пол",
            "what": "Удар в пол.", "speed": 5, "power": 5, "duration": 1.0}
    base.update(over)
    return base


def test_movement_parses_required_fields():
    m = Movement.from_dict(_raw())
    assert m.speed == 5
    assert m.hold == ""
    assert m.t == -1.0


def test_movement_rejects_speed_out_of_range():
    with pytest.raises(MovementError, match="speed"):
        Movement.from_dict(_raw(speed=7))


def test_movement_rejects_power_out_of_range():
    with pytest.raises(MovementError, match="power"):
        Movement.from_dict(_raw(power=0))


def test_movement_rejects_missing_field():
    raw = _raw()
    del raw["what"]
    with pytest.raises(MovementError, match="what"):
        Movement.from_dict(raw)


def test_resolve_times_takes_time_from_the_triggering_event():
    resolved = resolve_times([Movement.from_dict(_raw())], _tl())
    assert resolved[0].t == 47.0


def test_resolve_times_rejects_a_dangling_trigger():
    ghost = Movement.from_dict(_raw(id="ghost", trigger_event="no_such_event"))
    with pytest.raises(MovementError, match="no_such_event"):
        resolve_times([ghost], _tl())


def test_resolved_movements_are_sorted_by_time():
    later = Movement.from_dict(_raw(id="b", trigger_event="lohen_final"))
    earlier = Movement.from_dict(_raw(id="a", trigger_event="ice_burst"))
    assert [m.id for m in resolve_times([later, earlier], _tl())] == ["a", "b"]


def test_load_movements_reads_the_real_file():
    movements = load_movements("scenario/movements.json")
    assert len(movements) == 15
    assert all(1 <= m.speed <= 5 and 1 <= m.power <= 5 for m in movements)


def test_every_real_movement_resolves_against_the_real_scenario():
    tl = Timeline.load("scenario/timeline.json")
    resolved = resolve_times(load_movements("scenario/movements.json"), tl)
    assert len(resolved) == 15
    assert all(m.t >= 0 for m in resolved)
    assert resolved == sorted(resolved, key=lambda m: m.t)
