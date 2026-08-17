"""Сборка дорожки счёта. Дорогое здесь — FFmpeg, поэтому нарезка и сведение
проверяются на уже собранных файлах, а не пересобираются под каждый тест."""

import subprocess

import pytest

from src.counting import STEP, WORDS
from src.render_count import GAP, NUMERALS, OUT_DIR, TAKE


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def test_there_are_ten_numerals_and_their_bounds_are_written_down():
    assert len(NUMERALS) == len(WORDS) == 10
    for word, (a, b) in zip(WORDS, NUMERALS):
        assert 0.0 <= a < b, word


def test_every_numeral_leaves_silence_before_the_next_digit():
    """Проверяется зазор, а не «влезает в шаг».

    Влезть впритык — этого мало: цифры состыкуются без тишины, и счёт станет
    сплошной речью, ровно как запись на скорости 1.2, которую пришлось
    отбросить. Поэтому цель сжатия — шаг МИНУС зазор, и сторожить надо её.
    """
    for i, word in enumerate(WORDS):
        path = OUT_DIR / ("count_%02d.wav" % (i + 1))
        if not path.exists():
            pytest.skip("числительные не нарезаны: python src/render_count.py --cut")
        length = probe(path)
        assert length <= STEP - GAP + 0.005, (
            "%s: %.3f с, зазора до следующей цифры не осталось" % (word, length))
        assert length <= STEP, word


def test_the_source_take_is_named_even_though_it_is_not_in_git():
    """Заказ лежит в assets/cues/archive/, который под .gitignore. Имя должно
    быть записано в коде: без него нарезку не повторить."""
    assert TAKE.name == "count_take1_speed100.mp3"
