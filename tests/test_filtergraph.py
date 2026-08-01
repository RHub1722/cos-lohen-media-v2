from src.filtergraph import build_stem_graph, ffmpeg_input_args, pan_gains
from src.models import Timeline


def _tl(events, total=60.0):
    return Timeline.from_dict({"total_duration": total, "events": events})


def test_pan_gains_centre_is_equal_and_constant_power():
    left, right = pan_gains(0.0)
    assert abs(left - right) < 1e-9
    assert abs(left**2 + right**2 - 1.0) < 1e-9


def test_pan_gains_hard_left_silences_right():
    left, right = pan_gains(-1.0)
    assert abs(left - 1.0) < 1e-9
    assert abs(right) < 1e-9


def test_pan_gains_hard_right_silences_left():
    left, right = pan_gains(1.0)
    assert abs(left) < 1e-9
    assert abs(right - 1.0) < 1e-9


def test_graph_has_one_chain_per_event_and_one_amix():
    tl = _tl([
        {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"},
        {"id": "b", "t": 2.0, "asset": "b.wav", "stem": "sfx"},
    ])
    graph, inputs = build_stem_graph(tl, "sfx")
    assert len(inputs) == 2
    assert graph.count("adelay") == 2
    assert graph.count("amix=inputs=2") == 1


def test_delay_is_expressed_in_milliseconds():
    tl = _tl([{"id": "a", "t": 12.4, "asset": "a.wav", "stem": "sfx"}])
    graph, _ = build_stem_graph(tl, "sfx")
    assert "adelay=12400|12400" in graph


def test_zero_delay_event_still_gets_a_chain():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}])
    graph, inputs = build_stem_graph(tl, "sfx")
    assert len(inputs) == 1
    assert "adelay=0|0" in graph


def test_gain_is_applied_in_decibels():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx", "gain_db": -8.5}])
    graph, _ = build_stem_graph(tl, "sfx")
    assert "volume=-8.500000dB" in graph


def test_input_order_matches_chain_index():
    tl = _tl([
        {"id": "second", "t": 5.0, "asset": "second.wav", "stem": "sfx"},
        {"id": "first", "t": 1.0, "asset": "first.wav", "stem": "sfx"},
    ])
    graph, inputs = build_stem_graph(tl, "sfx")
    assert [i.path for i in inputs] == ["first.wav", "second.wav"]
    assert graph.index("[0:a]") < graph.index("[1:a]")


def test_looped_event_declares_stream_loop_and_trims():
    tl = _tl([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
               "duration": 18.6}])
    graph, inputs = build_stem_graph(tl, "ambience")
    assert inputs[0].loop is True
    assert "atrim=0:18.600000" in graph
    assert ffmpeg_input_args(inputs) == ["-stream_loop", "-1", "-i", "r.wav"]


def test_one_shot_event_is_not_looped():
    tl = _tl([{"id": "hit", "t": 3.0, "asset": "h.wav", "stem": "sfx"}])
    _, inputs = build_stem_graph(tl, "sfx")
    assert inputs[0].loop is False
    assert ffmpeg_input_args(inputs) == ["-i", "h.wav"]


def test_looped_event_fades_out_before_its_end():
    tl = _tl([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
               "duration": 10.0, "fade_out": 0.5}])
    graph, _ = build_stem_graph(tl, "ambience")
    assert "afade=t=out:st=9.500000:d=0.500000" in graph


def test_empty_stem_produces_a_silence_graph_with_no_inputs():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}])
    graph, inputs = build_stem_graph(tl, "music")
    assert inputs == []
    assert "anullsrc" in graph
    assert graph.rstrip().endswith("[out]")


def test_output_is_padded_and_trimmed_to_total_duration():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}], total=60.0)
    graph, _ = build_stem_graph(tl, "sfx")
    assert "apad" in graph
    assert "atrim=0:60.000000" in graph
    assert graph.rstrip().endswith("[out]")


def test_sample_rate_from_timeline_reaches_the_graph():
    tl = Timeline.from_dict({
        "total_duration": 60.0,
        "sample_rate": 44100,
        "events": [{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}],
    })
    graph, _ = build_stem_graph(tl, "sfx")
    assert "sample_rates=44100" in graph
