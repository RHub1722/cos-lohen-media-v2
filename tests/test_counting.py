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
