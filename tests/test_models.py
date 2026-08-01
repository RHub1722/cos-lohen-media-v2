import pytest

from src.models import Event, ScenarioError, Timeline


def test_event_defaults():
    ev = Event.from_dict({"id": "click", "t": 18.0, "asset": "sfx/click.wav", "stem": "sfx"})
    assert ev.gain_db == 0.0
    assert ev.pan == 0.0
    assert ev.duration is None
    assert ev.fade_in == 0.01
    assert ev.fade_out == 0.01
    assert ev.video is None


def test_event_rejects_unknown_stem():
    with pytest.raises(ScenarioError, match="stem"):
        Event.from_dict({"id": "x", "t": 0.0, "asset": "a.wav", "stem": "drums"})


def test_event_rejects_pan_out_of_range():
    with pytest.raises(ScenarioError, match="pan"):
        Event.from_dict({"id": "x", "t": 0.0, "asset": "a.wav", "stem": "sfx", "pan": 1.5})


def test_event_rejects_negative_time():
    with pytest.raises(ScenarioError, match="отрицательное"):
        Event.from_dict({"id": "x", "t": -0.5, "asset": "a.wav", "stem": "sfx"})


def test_event_rejects_missing_required_field():
    with pytest.raises(ScenarioError, match="asset"):
        Event.from_dict({"id": "x", "t": 0.0, "stem": "sfx"})


def test_timeline_parses_events_and_meta():
    tl = Timeline.from_dict({
        "version": "v2",
        "total_duration": 60.0,
        "events": [{"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"}],
    })
    assert tl.total_duration == 60.0
    assert tl.sample_rate == 48000
    assert tl.target_lufs == -16.0
    assert tl.target_tp == -1.5
    assert len(tl.events) == 1


def test_timeline_events_sorted_by_time():
    tl = Timeline.from_dict({
        "total_duration": 60.0,
        "events": [
            {"id": "b", "t": 5.0, "asset": "b.wav", "stem": "sfx"},
            {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"},
        ],
    })
    assert [e.id for e in tl.events] == ["a", "b"]


def test_timeline_requires_total_duration():
    with pytest.raises(ScenarioError, match="total_duration"):
        Timeline.from_dict({"events": []})


def test_by_stem_filters():
    tl = Timeline.from_dict({
        "total_duration": 60.0,
        "events": [
            {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"},
            {"id": "v", "t": 2.0, "asset": "v.wav", "stem": "voices"},
        ],
    })
    assert [e.id for e in tl.by_stem("voices")] == ["v"]
    assert tl.by_stem("music") == ()
