"""Сетка счёта: две отметки в секунду, цикл из десяти, якорь на круглых пятёрках."""

import pytest

from src.counting import (CYCLE, RISER, STEP, WORDS, CountError, assign,
                          collisions, digit_at, grid, repeated_digits, risers)


def test_the_grid_covers_the_number_exactly():
    marks = grid(60.0)
    assert len(marks) == 120
    assert marks[0].t == 0.0
    assert marks[0].word == "один"
    assert marks[-1].t == 59.5
    assert marks[-1].word == "десять"


def test_one_lands_on_every_round_five():
    """Якорь, ради которого выбран шаг 0.5 с. Цикл ровно 5.000 с, значит счёт
    и таймер видео не разъезжаются: на любой круглой пятёрке звучит «один»."""
    for t in (0.0, 5.0, 10.0, 30.0, 45.0, 55.0):
        assert digit_at(t)[0] == "один", t


def test_the_cycle_is_ten_words_and_five_seconds():
    assert len(WORDS) == CYCLE == 10
    assert CYCLE * STEP == 5.0


def test_the_digit_is_the_nearest_one_not_the_containing_one():
    """Доля на 93% пятёрки слышится как шестёрка. Называть её пятой значит
    врать: исполнитель услышит «шесть» ровно в момент удара."""
    word, miss = digit_at(1.47)   # 94% ячейки «три», k=3
    assert word == "четыре"
    assert miss == pytest.approx(-0.03, abs=1e-9)
    word, miss = digit_at(1.53)
    assert word == "четыре"
    assert miss == pytest.approx(0.03, abs=1e-9)


def test_a_negative_time_is_refused():
    with pytest.raises(CountError):
        digit_at(-0.1)


class FakeBeat:
    def __init__(self, role, heard):
        self.role, self.heard, self.what = role, heard, ""


class FakeStrike:
    def __init__(self, sid, beats):
        self.id, self.beats = sid, tuple(beats)


def _burst_1():
    return FakeStrike("burst_1", [
        FakeBeat("windup", 28.50), FakeBeat("swing", 28.88),
        FakeBeat("contact", 29.14), FakeBeat("recover", 29.60)])


def test_every_beat_gets_a_digit_and_a_signed_miss():
    rows = assign([_burst_1()])
    assert [r["word"] for r in rows] == ["восемь", "девять", "девять", "десять"]
    assert rows[2]["strike"] == "burst_1"
    assert rows[2]["role"] == "contact"
    assert rows[2]["miss"] == pytest.approx(0.14, abs=0.001)


def test_two_beats_in_one_cell_are_reported_not_hidden():
    """Взмах и контакт серии 1 стоят в 0.26 с, а шаг 0.5 с. Счёт их не
    различает, и это цена выбранного темпа. Молчать о ней нельзя: исполнитель
    будет ждать вторую цифру, которой не будет."""
    found = collisions([_burst_1()])
    assert len(found) == 1
    word, beats = found[0]
    assert word == "девять"
    assert [b["role"] for b in beats] == ["swing", "contact"]


def test_the_same_digit_on_two_different_strikes_is_not_a_collision():
    """29.14 и 34.00 оба зовутся «девять», но между ними 4.86 с — целый цикл, и
    у каждого свой риз. Путаницы нет, но в листе это оговаривается."""
    second = FakeStrike("burst_2", [FakeBeat("contact", 34.00)])
    assert collisions([_burst_1(), second]) == collisions([_burst_1()])
    repeats = repeated_digits([_burst_1(), second])
    assert repeats["девять"] == [29.14, 34.00]


def test_a_riser_peaks_exactly_on_the_first_contact():
    rows = risers([_burst_1()])
    assert len(rows) == 1
    assert rows[0]["strike"] == "burst_1"
    assert rows[0]["peak"] == pytest.approx(29.14)
    assert rows[0]["start"] == pytest.approx(29.14 - RISER)


def test_a_riser_aims_at_the_first_contact_when_a_strike_has_two():
    """У серии 2, серии 3 и копья в пол в бою РЕАЛЬНО по два контакта. Если
    риз нацелится на второй, его вершина уедет на 2.58 с — и вести он будет
    в пустоту. Тест на приёме с одним контактом эту подмену не заметил бы."""
    two = FakeStrike("burst_2", [FakeBeat("windup", 33.05),
                                 FakeBeat("contact", 34.00),
                                 FakeBeat("contact", 36.58)])
    assert risers([two])[0]["peak"] == pytest.approx(34.00)


def test_a_riser_never_starts_before_the_previous_strike_ended():
    """Проверяется сам клин, а не совпадение.

    Зазор между приёмами взят 0.93 с — МЕНЬШЕ, чем длина риза 1.2 с. Значит
    начало 41.90 достижимо только через ограничение концом прошлого приёма:
    без клина риз начался бы в 41.63 и наехал бы на предыдущее действие,
    перестав означать «сейчас будет удар».
    """
    early = FakeStrike("burst_3", [FakeBeat("contact", 40.95),
                                   FakeBeat("recover", 41.90)])
    late = FakeStrike("take_the_hit", [FakeBeat("hold", 42.40),
                                       FakeBeat("contact", 42.83)])
    rows = risers([early, late])
    assert 42.83 - 41.90 < RISER, "фикстура перестала упражнять клин"
    assert rows[1]["start"] == pytest.approx(41.90)
    assert rows[1]["peak"] == pytest.approx(42.83)


def test_a_strike_without_a_contact_is_refused():
    with pytest.raises(CountError):
        risers([FakeStrike("empty", [FakeBeat("hold", 10.0)])])


def test_a_contact_with_no_room_left_for_a_riser_is_refused():
    """Приём, начинающийся раньше, чем кончился предыдущий, — это ошибка
    сценария, а не повод молча выдать риз нулевой длины."""
    early = FakeStrike("first", [FakeBeat("contact", 10.0),
                                 FakeBeat("recover", 12.0)])
    late = FakeStrike("second", [FakeBeat("contact", 11.5)])
    with pytest.raises(CountError):
        risers([early, late])


def test_a_beat_without_a_time_is_named_as_such():
    """Доля с heard = -1 приходит от resolve_strikes, который не отработал.
    Без явной проверки ошибка вылезала бы как «на риз не осталось места» и
    посылала бы чинить не то место."""
    with pytest.raises(CountError, match="без времени"):
        risers([FakeStrike("unplaced", [FakeBeat("contact", -1.0)])])
