"""Тест 7 приёмки: сверка с требованиями, и что требования читаются из сценария."""

import pytest

from motion import compare, requirements

STUB = {
    "actions": [
        {"id": "a_long", "name": "оборот", "duration": 2.4, "contacts": 2,
         "no_stance": True, "hold": "НЕ стойка"},
        {"id": "a_short", "name": "встречный", "duration": 1.2, "contacts": 1,
         "no_stance": False, "hold": "стоишь"},
    ],
    "longest_stillness": 4.8,
}


def test_7_a_short_session_fails_the_long_action():
    measured = {"longest_action": 1.0, "longest_stillness": 6.0,
                "strikes": 3, "dead_stops": 0, "transitions": 2}
    verdicts = {f.what: f.verdict for f in compare.compare(measured, STUB)}
    assert verdicts["оборот 2.4 с"] == "нет"
    assert verdicts["встречный 1.2 с"] == "нет"
    assert verdicts["неподвижность 4.8 с"] == "есть"


def test_7b_a_long_session_passes_both():
    measured = {"longest_action": 2.6, "longest_stillness": 2.0,
                "strikes": 5, "dead_stops": 0, "transitions": 4}
    verdicts = {f.what: f.verdict for f in compare.compare(measured, STUB)}
    assert verdicts["оборот 2.4 с"] == "есть"
    assert verdicts["встречный 1.2 с"] == "есть"
    assert verdicts["неподвижность 4.8 с"] == "нет"


def test_7c_dead_stops_break_the_no_stance_requirement():
    measured = {"longest_action": 3.0, "longest_stillness": 5.0,
                "strikes": 4, "dead_stops": 3, "transitions": 3}
    findings = {f.what: f for f in compare.compare(measured, STUB)}
    stance = findings["переходы без стойки"]
    assert stance.verdict == "нет"
    assert "3 из 3" in stance.detail


def test_7d_no_transitions_is_not_a_failure():
    """Один удар за прогон — переходов нет, и приговора по ним тоже."""
    measured = {"longest_action": 3.0, "longest_stillness": 5.0,
                "strikes": 1, "dead_stops": 0, "transitions": 0}
    stance = {f.what: f for f in compare.compare(measured, STUB)}[
        "переходы без стойки"]
    assert stance.verdict == "нечего проверять"


def test_requirements_come_from_the_real_scenario():
    """Требования читаются из scenario/, а не из копии в анализаторе."""
    reqs = requirements.from_scenario()
    ids = {a["id"] for a in reqs["actions"]}
    assert {"burst_1", "burst_2", "burst_3", "burst_4", "spear_down"} <= ids
    burst_3 = next(a for a in reqs["actions"] if a["id"] == "burst_3")
    assert burst_3["duration"] == pytest.approx(2.4)
    assert burst_3["contacts"] >= 2, "у burst_3 в сценарии два попадания"
    assert reqs["longest_stillness"] >= 4.0
    assert any(a["no_stance"] for a in reqs["actions"]), (
        "хотя бы у одного действия в hold написано НЕ стойка")
