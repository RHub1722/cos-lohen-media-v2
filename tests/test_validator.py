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


def test_duration_longer_than_source_without_loop_is_an_error():
    """Ровно тот дефект, на котором встала первая сборка."""
    tl = _full([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
                 "duration": 18.6}])
    problems = check_timeline(tl, probe_fn=lambda p: 5.0)
    assert any(p.level == "error" and "loop не включён" in p.message for p in problems)


def test_duration_longer_than_source_with_loop_is_fine():
    tl = _full([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
                 "duration": 18.6, "loop": True}])
    problems = check_timeline(tl, probe_fn=lambda p: 5.0)
    assert not has_errors(problems)


def test_needless_loop_is_a_warning():
    tl = _full([{"id": "tail", "t": 0.0, "asset": "t.wav", "stem": "sfx",
                 "duration": 2.0, "loop": True}])
    problems = check_timeline(tl, probe_fn=lambda p: 5.0)
    assert any(p.level == "warning" and "петля не нужна" in p.message for p in problems)


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


def test_overlapping_voice_events_are_an_error():
    tl = _full([
        {"id": "line_a", "t": 1.0, "asset": "a.wav", "stem": "voices"},
        {"id": "line_b", "t": 2.0, "asset": "b.wav", "stem": "voices"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 3.0)
    assert any(p.level == "error" and "line_a" in p.message and "line_b" in p.message
               for p in problems)


def test_adjacent_voice_events_are_fine():
    # t подобраны так, чтобы не задеть "v" из _full (t=1.0) — иначе line_a
    # сама наложилась бы на "v", и тест держался бы не на своей логике.
    tl = _full([
        {"id": "line_a", "t": 20.0, "asset": "a.wav", "stem": "voices"},
        {"id": "line_b", "t": 24.0, "asset": "b.wav", "stem": "voices"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 2.0)
    assert not has_errors(problems)


def test_overlap_just_under_tolerance_is_not_flagged():
    """0.5 мс меньше порога 1e-3 — шум вычислений, а не реальное наложение."""
    tl = _full([
        {"id": "line_a", "t": 10.0, "asset": "a.wav", "stem": "voices"},
        {"id": "line_b", "t": 11.9995, "asset": "b.wav", "stem": "voices"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 2.0)
    assert not has_errors(problems)


def test_overlap_just_over_tolerance_is_flagged():
    """1.5 мс больше порога 1e-3 — уже настоящее наложение, а не шум."""
    tl = _full([
        {"id": "line_a", "t": 10.0, "asset": "a.wav", "stem": "voices"},
        {"id": "line_b", "t": 11.9985, "asset": "b.wav", "stem": "voices"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 2.0)
    assert has_errors(problems)


def test_overlapping_sfx_events_are_allowed():
    """Взмах и попадание накладываются намеренно — это не дефект."""
    tl = _full([
        {"id": "whoosh", "t": 1.0, "asset": "w.wav", "stem": "sfx"},
        {"id": "impact", "t": 1.3, "asset": "i.wav", "stem": "sfx"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 1.0)
    assert not any(p.level == "error" for p in problems)
