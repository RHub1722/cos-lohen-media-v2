"""Сборка дорожки счёта. Дорогое здесь — FFmpeg, поэтому нарезка и сведение
проверяются на уже собранных файлах, а не пересобираются под каждый тест."""

import subprocess

import numpy as np
import pytest

from src.counting import STEP, WORDS
from src.render_count import (DUCK_DB, GAP, NUMERALS, OUT_DIR, OUT_TRACK,
                              SOUNDTRACK, TAKE)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def channels(path, t0, t1, sr=16000):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "%.4f" % t0, "-t", "%.4f" % (t1 - t0),
         "-i", str(path), "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    return x[:, 0], x[:, 1]


@pytest.fixture(scope="module")
def track():
    if not OUT_TRACK.exists():
        pytest.skip("нет %s: python src/render_count.py" % OUT_TRACK.name)
    return OUT_TRACK


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


def test_the_track_is_exactly_the_length_of_the_number(track):
    assert probe(track) == pytest.approx(60.0, abs=0.002)


def test_the_left_ear_carries_the_number_and_nothing_else(track):
    """Главная проверка каналов. Вынув правый наушник, исполнитель обязан
    услышать выступление без единой подсказки — значит левый канал должен
    совпадать с приглушённым номером, а не просто «быть похожим»."""
    for t0 in (5.0, 29.0, 42.5, 47.0):
        left, _ = channels(track, t0, t0 + 1.0)
        ref_l, _ = channels(SOUNDTRACK, t0, t0 + 1.0)
        ref_l = ref_l * (10.0 ** (-DUCK_DB / 20.0))
        n = min(len(left), len(ref_l))
        assert np.abs(left[:n] - ref_l[:n]).max() < 2e-3, t0


def test_the_right_ear_is_louder_than_the_left_where_the_count_runs(track):
    for t0 in (5.0, 29.0, 42.5):
        left, right = channels(track, t0, t0 + 1.0)
        assert np.abs(right).max() > np.abs(left).max() * 1.5, t0


def test_the_number_is_ducked_by_exactly_nine_decibels(track):
    """Ровный гейн, а не трапеции: под непрерывным счётом трапеция всё время в
    нижней точке, так что это просто гейн, и он обязан быть ровно тем."""
    left, _ = channels(track, 10.0, 20.0)
    ref, _ = channels(SOUNDTRACK, 10.0, 20.0)
    n = min(len(left), len(ref))
    got = 20 * np.log10(np.sqrt((left[:n] ** 2).mean())
                        / np.sqrt((ref[:n] ** 2).mean()))
    assert got == pytest.approx(-DUCK_DB, abs=0.15)


def test_the_track_keeps_headroom(track):
    left, right = channels(track, 0.0, 60.0)
    peak = 20 * np.log10(max(np.abs(left).max(), np.abs(right).max()))
    assert peak < -1.0, "%.2f dBTP — нет запаса, счёт надо опустить" % peak
