import re

import pytest

from src.filtergraph import (DUCK_ATTACK, DUCK_HOLD, DUCK_HOLD_VOICE,
                             DUCK_RELEASE, build_stem_graph, duck_expression,
                             ffmpeg_input_args, pan_gains)
from src.models import ScenarioError, Timeline


def _tl(events, total=60.0):
    return Timeline.from_dict({"total_duration": total, "events": events})


def _hit(anchor, t, duck=0.0, **extra):
    raw = {"id": anchor, "t": t, "asset": f"{anchor}.wav", "stem": "sfx"}
    if duck:
        raw["duck_db"] = duck
    raw.update(extra)
    return raw


def _music(t=0.0, duration=60.0):
    return {"id": "bed", "t": t, "asset": "bed.wav", "stem": "music",
            "duration": duration}


# --- провал музыки под ударом ------------------------------------------------
# Глеб и Галя независимо сказали, что аудио и видео в бою не стыкуются. Замер
# показал, что дело не в таймингах: удар по нему на 42.80 имел запас над музыкой
# 0.2 dB в середине спектра и −9.7 в верхе, то есть музыка была ГРОМЧЕ удара.
# Отсюда эти поля. Ошибка здесь тихая: граф соберётся, а зал не услышит удара.


def test_nothing_to_duck_gives_no_expression():
    assert duck_expression(_tl([_hit("a", 5.0)])) == ""


def test_duck_reaches_the_requested_depth():
    """Шесть децибел — это множитель 0.5012, а не 0.6 и не 6."""
    expr = duck_expression(_tl([_hit("a", 5.0, duck=6.0)]))
    factor = 1.0 - 10.0 ** (-6.0 / 20.0)
    assert f"{factor:.6f}" in expr


def test_overlapping_ducks_take_the_deepest_not_the_sum():
    """Удары на 38.60 и 39.20 стоят в 0.6 с друг от друга, и их окна
    пересекаются. Сумма дала бы провал вдвое глубже заказанного, и музыка между
    ними пропала бы совсем."""
    expr = duck_expression(_tl([_hit("a", 38.60, duck=6.0),
                                _hit("b", 39.20, duck=8.0)]))
    assert "max(" in expr
    assert "+" not in expr, "провалы складываются вместо взятия максимума"


def test_duck_starts_before_the_impact_to_cover_the_swing():
    """Замах стоит за 0.30–0.45 с до удара. Если музыка уходит вниз ровно на
    ударе, слышно, как она дёргается посередине движения."""
    assert DUCK_ATTACK >= 0.25
    expr = duck_expression(_tl([_hit("a", 10.0, duck=6.0)]))
    assert f"(t-{10.0 - DUCK_ATTACK:.4f})" in expr


def test_duck_window_closes_after_hold_and_release():
    expr = duck_expression(_tl([_hit("a", 10.0, duck=6.0)]))
    assert f"({10.0 + DUCK_HOLD + DUCK_RELEASE:.4f}-t)" in expr


def test_commas_inside_the_expression_are_escaped():
    """В фильтрграфе запятая разделяет фильтры. Неэкранированная запятая внутри
    выражения не падает громко — граф просто не собирается, и разбираться
    приходится в четырёх тысячах символов stderr."""
    expr = duck_expression(_tl([_hit("a", 5.0, duck=6.0)]))
    unescaped = [i for i, ch in enumerate(expr)
                 if ch == "," and (i == 0 or expr[i - 1] != "\\")]
    assert not unescaped, f"неэкранированные запятые на позициях {unescaped}"


def test_only_the_music_stem_is_ducked():
    """Уводить эффекты под эффектами незачем, а голос — отдельное решение,
    которого мы не принимали."""
    events = [_hit("a", 5.0, duck=9.0), _music(),
              {"id": "v", "t": 5.0, "asset": "v.wav", "stem": "voices"},
              {"id": "amb", "t": 0.0, "asset": "amb.wav", "stem": "ambience",
               "duration": 60.0}]
    tl = _tl(events)
    assert "eval=frame" in build_stem_graph(tl, "music")[0]
    for stem in ("sfx", "voices", "ambience"):
        assert "eval=frame" not in build_stem_graph(tl, stem)[0], stem


def test_duck_on_a_music_event_is_refused():
    with pytest.raises(ScenarioError, match="duck_db"):
        _tl([{"id": "bed", "t": 0.0, "asset": "b.wav", "stem": "music",
              "duration": 60.0, "duck_db": 6.0}])


def test_a_line_holds_the_duck_longer_than_an_impact():
    """Удар длится сотые доли, фраза от 0.8 до 1.6 с. С полкой удара музыка
    вернулась бы на середине слова, и это слышно хуже, чем если бы её не
    уводили вовсе."""
    hit = duck_expression(_tl([_hit("a", 10.0, duck=6.0)]))
    line = duck_expression(_tl([{"id": "l", "t": 10.0, "asset": "l.wav",
                                 "stem": "voices", "duck_db": 6.0}]))
    assert f"({10.0 + DUCK_HOLD + DUCK_RELEASE:.4f}-t)" in hit
    assert f"({10.0 + DUCK_HOLD_VOICE + DUCK_RELEASE:.4f}-t)" in line
    assert DUCK_HOLD_VOICE > DUCK_HOLD


def test_the_drowned_lines_of_the_fight_are_all_ducked():
    """Замер: «Finally» 1.7 dB, «...Really?» 2.4, «Feel that?» 6.0, «Is that
    all» 7.2 — при 21–38 dB у тех же реплик в допросе."""
    tl = Timeline.load("scenario/timeline.json")
    ducked = {e.id for e in tl.events if e.duck_db > 0 and e.stem == "voices"}
    for anchor in ("lohen_finally", "lohen_really", "lohen_feel", "lohen_thatall"):
        assert anchor in ducked, f"{anchor} измерена как тонущая, но без провала"


def test_the_interrogation_lines_are_not_ducked():
    """В допросе музыка стоит на пороге слышимости, запас реплик 21–38 dB.
    Провал там убрал бы подложку, которой и так почти нет."""
    tl = Timeline.load("scenario/timeline.json")
    for ev in tl.events:
        if ev.stem == "voices" and ev.t < 22.3:
            assert ev.duck_db == 0.0, f"{ev.id} в допросе, провал не нужен"


def test_negative_duck_is_refused():
    with pytest.raises(ScenarioError, match="отрицательный"):
        _tl([_hit("a", 5.0, duck=-6.0)])


def test_the_real_timeline_ducks_every_masked_impact():
    """Три удара были измерены как маскирующиеся: серия 2, серия 3 Б и удар по
    нему. Ни один не должен остаться без провала.

    Четвёртым был burst4_impact, и он больше не существует: в картинке в окне
    44.60–47.00 удара нет вовсе, клип держит поднятое копьё почти две секунды. Удар
    был фантомным, и его убрали, а не приглушили.
    """
    tl = Timeline.load("scenario/timeline.json")
    ducked = {e.id for e in tl.events if e.duck_db > 0}
    for anchor in ("burst2_impact", "burst3_impact_b", "hit_on_lohen"):
        assert anchor in ducked, f"{anchor} измерен как маскирующийся, но без провала"
    assert "burst4_impact" not in {e.id for e in tl.events}, (
        "фантомный удар серии 4 вернулся: в картинке там нет удара")
    # Самый глухой удар обязан получить провал не меньше остальных серий.
    by = {e.id: e.duck_db for e in tl.events}
    assert by["hit_on_lohen"] >= by["burst1_impact"]


def test_the_phantom_hit_of_burst_three_stays_gone():
    """На 38.60 в картинке нет удара: прирост яркости 0.0010 при 0.4037 у
    настоящей первой вспышки на 39.89. Там стоял burst3_impact_a, и это второй
    фантом номера после burst4_impact — оба нашлись глазами пользователя, а не
    приёмкой.

    На 38.60 теперь automaton_advance: машина входит в кадр и наступает на камеру
    1.3 с. Это не удар, поэтому провала музыки у него быть не должно — провал
    трапеция с полкой 0.30 с, и под непрерывной фактурой он дал бы дыру.
    """
    tl = Timeline.load("scenario/timeline.json")
    by = {e.id: e for e in tl.events}
    assert "burst3_impact_a" not in by, (
        "фантомный удар серии 3 вернулся: в картинке на 38.60 удара нет")
    adv = by["automaton_advance"]
    assert adv.t == 38.6
    assert adv.duck_db == 0.0, "наступление не удар, провал ему не нужен"
    # Оба настоящих удара стоят на вспышках снятого материала: 39.89 и 40.89.
    assert by["burst3_impact_b"].t == 39.87
    assert by["burst3_impact_c"].t == 40.9
    # Взмах обязан вести в первый настоящий удар, а не в место, где его нет.
    assert 0.2 <= by["burst3_impact_b"].t - by["burst3_whoosh"].t <= 0.45


def test_the_chamber_clicks_sit_on_the_measured_turns():
    """Барабан в клипе 02_revolver проворачивается ровно четыре раза, и щелчков
    столько же.

    Ходы по замеру диска покадрово (24 кадра/с), пики: 16.78, 17.62, 18.62,
    20.12. Пятый ход, 21.28–21.49, делает взвод курка — на него звук уже стоял.
    Паузы между ходами растут: 0.84, 1.00, 1.52. Шесть щелчков, которые тут были
    раньше, шли с шагом 0.70, 0.70, 0.60, 0.50, 0.50 — то есть ускорялись, и
    рассинхрон был не в смещении, а в направлении.

    Пик внутри ассета стоит на 0.045 с, а событие ставит НАЧАЛО файла: сравнивать
    надо t + 0.045, иначе тест проверял бы не то, что слышно.
    """
    turns = (16.78, 17.62, 18.62, 20.12)
    peak_in_file = 0.045
    tl = Timeline.load("scenario/timeline.json")
    clicks = sorted((e for e in tl.events
                     if e.id.startswith("revolver_chamber_")),
                    key=lambda e: e.t)
    assert len(clicks) == len(turns), (
        f"щелчков {len(clicks)}, ходов барабана в картинке {len(turns)}")
    for click, turn in zip(clicks, turns):
        heard = click.t + peak_in_file
        assert abs(heard - turn) < 0.02, (
            f"{click.id} слышен на {heard:.3f}, ход барабана на {turn:.2f}")


def test_the_cylinder_spin_ends_before_the_barrel_is_shown():
    """Раскрутка это заряжание, и заряжают до того, как наводят.

    Ассет — 20 щелчков за 1.28 с, шаг 0.06 с; барабан на экране проворачивается
    раз в 0.84–1.34 с. Пока раскрутка стояла на 16.20, одновременно со склейкой на
    ствол, звук шёл в шестнадцать раз быстрее картинки и читался как заряжание —
    на это и была претензия. Ратчет обязан затихнуть до 16.20.
    """
    tl = Timeline.load("scenario/timeline.json")
    by = {e.id: e for e in tl.events}
    spin = by["revolver_cylinder_spin"]
    ratchet_ends = spin.t + 1.30      # последний щелчок внутри файла
    assert ratchet_ends <= 16.2 + 1e-9, (
        f"раскрутка звучит до {ratchet_ends:.2f}, а ствол на экране с 16.20")
    # Щелчки начинаются уже под стволом: с 16.20 барабан на экране, и с этого
    # места он идёт по одному ходу, а не свободной раскруткой.
    first_click = min(e.t for e in tl.events
                      if e.id.startswith("revolver_chamber_"))
    assert first_click > 16.2, "первый щелчок должен звучать уже под стволом"


def test_the_final_blow_is_not_ducked():
    """На 47.00 музыка обрывается по сценарию, на 55.20 играет только дрон на
    −20 dB. Провал там нечего уводить, и дописывать его «для симметрии» нельзя."""
    tl = Timeline.load("scenario/timeline.json")
    by = {e.id: e.duck_db for e in tl.events}
    assert by["ice_burst"] == 0.0
    assert by["ice_final_impact"] == 0.0


# --- низ на событии ----------------------------------------------------------


def test_bass_boost_reaches_the_chain_before_the_gain():
    """Полка ставится до volume, чтобы гейн события считался от готового
    тембра, а не наоборот."""
    graph, _ = build_stem_graph(_tl([_hit("door", 5.0, bass_db=7.0)]), "sfx")
    assert "bass=g=7.000000:f=110" in graph
    assert graph.index("bass=g=") < graph.index("volume=")


def test_no_bass_filter_when_not_asked():
    graph, _ = build_stem_graph(_tl([_hit("a", 5.0)]), "sfx")
    assert "bass=" not in graph


def test_only_the_door_carries_a_bass_boost():
    """Единственный удар набора, у которого низ тише верха: −3.5 dB против
    +11.6 у финального. Остальным полка не нужна, и лишняя размыла бы бой."""
    tl = Timeline.load("scenario/timeline.json")
    boosted = {e.id for e in tl.events if e.bass_db}
    assert boosted == {"door_breach"}, boosted


def test_treble_boost_reaches_the_chain():
    graph, _ = build_stem_graph(_tl([_hit("hit", 5.0, treble_db=6.0)]), "sfx")
    assert "treble=g=6.000000" in graph
    assert graph.index("treble=g=") < graph.index("volume=")


def test_the_treble_shelf_starts_inside_the_band_it_is_measured_in():
    """Приёмка мерит верх от 2000 Гц. Полка с 3500 подняла запас на 1.9 dB из
    заказанных шести — она просто не попадала в измеряемую область."""
    graph, _ = build_stem_graph(_tl([_hit("hit", 5.0, treble_db=6.0)]), "sfx")
    match = re.search(r"treble=g=[\d.]+:f=(\d+)", graph)
    assert match, "полка верха не найдена в графе"
    assert int(match.group(1)) <= 2500, (
        "полка начинается выше области, в которой мерится запас, "
        "и её подъём приёмка не увидит")


def test_only_the_hit_on_lohen_carries_a_treble_boost():
    """У остальных ударов верх в порядке: запас 12–23 dB. Лишняя полка сделала бы
    бой резким без причины."""
    tl = Timeline.load("scenario/timeline.json")
    boosted = {e.id for e in tl.events if e.treble_db}
    assert boosted == {"hit_on_lohen"}, boosted


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
               "duration": 18.6, "loop": True}])
    graph, inputs = build_stem_graph(tl, "ambience")
    assert inputs[0].loop is True
    assert "atrim=0:18.600000" in graph


def test_looped_input_is_bounded_by_t_so_ffmpeg_can_finish():
    """Без -t бесконечный вход не отдаёт EOF, и ffmpeg висит после сведения."""
    tl = _tl([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
               "duration": 18.6, "loop": True}])
    _, inputs = build_stem_graph(tl, "ambience")
    assert ffmpeg_input_args(inputs) == [
        "-stream_loop", "-1", "-t", "18.600000", "-i", "r.wav",
    ]


def test_trim_shorter_than_source_is_not_looped():
    """duration задан, но петля не запрошена: вход конечный, -stream_loop не нужен."""
    tl = _tl([{"id": "tail", "t": 55.3, "asset": "t.wav", "stem": "sfx",
               "duration": 4.7}])
    graph, inputs = build_stem_graph(tl, "sfx")
    assert inputs[0].loop is False
    assert ffmpeg_input_args(inputs) == ["-i", "t.wav"]
    assert "atrim=0:4.700000" in graph


def test_one_shot_event_is_not_looped():
    tl = _tl([{"id": "hit", "t": 3.0, "asset": "h.wav", "stem": "sfx"}])
    _, inputs = build_stem_graph(tl, "sfx")
    assert inputs[0].loop is False
    assert ffmpeg_input_args(inputs) == ["-i", "h.wav"]


def test_looped_event_fades_out_before_its_end():
    tl = _tl([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience",
               "duration": 10.0, "loop": True, "fade_out": 0.5}])
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
