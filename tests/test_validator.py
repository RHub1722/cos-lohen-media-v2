from src.models import Timeline
from src.validator import check_timeline, format_problems, has_errors


def _tl(events, total=60.0):
    return Timeline.from_dict({"total_duration": total, "events": events})


def _full(extra=()):
    """Сценарий, где заняты все четыре стема — чтобы не ловить их предупреждения."""
    base = [
        {"id": "v", "t": 1.0, "asset": "v.wav", "stem": "voices"},
        {"id": "s", "t": 1.0, "asset": "s.wav", "stem": "sfx"},
        {"id": "m", "t": 1.0, "asset": "m.wav", "stem": "music"},
        {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "ambience"},
    ]
    return _tl(base + list(extra))


def test_clean_timeline_has_no_problems_at_all():
    problems = check_timeline(_full(), probe_fn=lambda p: 0.5)
    assert problems == []
    assert format_problems(problems) == "Проверки пройдены, замечаний нет."


def test_duplicate_ids_are_an_error():
    tl = _full([{"id": "s", "t": 2.0, "asset": "b.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert any(p.level == "error" and "дубл" in p.message for p in problems)
    assert has_errors(problems)


def test_event_starting_past_total_duration_is_an_error():
    tl = _full([{"id": "late", "t": 61.0, "asset": "x.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert any(p.level == "error" and "late" in p.message for p in problems)


def test_event_overrunning_the_end_is_a_warning():
    tl = _full([{"id": "tail", "t": 59.0, "asset": "x.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 5.0)
    assert any(p.level == "warning" and "tail" in p.message for p in problems)
    assert not has_errors(problems)


def test_missing_asset_is_an_error():
    def probe_fn(path):
        if path == "nope.wav":
            raise FileNotFoundError(path)
        return 0.5

    tl = _full([{"id": "gone", "t": 1.0, "asset": "nope.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=probe_fn)
    assert any(p.level == "error" and "gone" in p.message for p in problems)


def test_duration_longer_than_source_warns_about_looping():
    tl = _full([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
                 "duration": 18.6}])
    problems = check_timeline(tl, probe_fn=lambda p: 5.0)
    assert any(p.level == "warning" and "петл" in p.message for p in problems)


def test_empty_stem_is_a_warning():
    tl = _tl([{"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert any(p.level == "warning" and "voices" in p.message for p in problems)


def test_empty_scenario_is_an_error():
    problems = check_timeline(_tl([]), probe_fn=lambda p: 0.5)
    assert any(p.level == "error" and "нет событий" in p.message for p in problems)


def test_format_problems_groups_errors_before_warnings():
    tl = _tl([
        {"id": "a", "t": 61.0, "asset": "a.wav", "stem": "sfx"},
    ])
    text = format_problems(check_timeline(tl, probe_fn=lambda p: 0.5))
    assert text.index("ОШИБКИ") < text.index("предупреждения")
