"""Сетка счёта: две отметки в секунду, цикл из десяти, якорь на круглых пятёрках."""

import pytest

from src.counting import CYCLE, STEP, WORDS, CountError, digit_at, grid


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


from src.counting import assign, collisions, repeated_digits


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
