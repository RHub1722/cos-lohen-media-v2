"""Якоря синхронизации: чем помощник ловит старт номера и как это считается.

Имя файла выбрано в стороне от `tests/test_sync_budget.py`: тот про совсем
другое — сколько вызовов play и перемоток тренажёр заказывает у планшета.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cues import ANCHORS, CueError, anchor_by, first_cues, shift
from src.models import Timeline
from src.movements import load_movements, resolve_times
from src.peaks import peak_offsets
from src.strikes import load_strikes, resolve_strikes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real():
    """Настоящие действия из сценария: якоря обязаны работать на них."""
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    assets = ROOT / "assets"
    peaks = peak_offsets(assets, sorted({e.asset for e in tl.events
                                         if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    return resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"),
                           tl, peaks, moves)


# --- арифметика якоря --------------------------------------------------------


def test_each_anchor_adds_its_own_time_and_reaction():
    """Якорь знает две вещи: когда он в номере и чем его ловят."""
    assert anchor_by("picture").start_at(0.25) == 0.45
    assert anchor_by("laugh").start_at(0.25) == 1.11
    assert anchor_by("titles").start_at(0.25) == 5.45


def test_the_chain_moves_every_anchor_by_the_same_amount():
    """Ради этого якорь и цепочка и разъезжались: замер один, дорожек три."""
    before = {k: a.start_at(0.20) for k, a in ANCHORS.items()}
    after = {k: a.start_at(0.30) for k, a in ANCHORS.items()}
    assert sorted(before) == sorted(after)
    assert all(round(after[k] - before[k], 4) == 0.10 for k in before)


def test_the_ear_reacts_faster_than_the_eye():
    """Не украшение: отсюда и следует, что якорь на звуке точнее прочих."""
    assert anchor_by("laugh").reaction < anchor_by("picture").reaction
    assert anchor_by("picture").reaction == anchor_by("titles").reaction


def test_an_unknown_anchor_is_refused():
    with pytest.raises(CueError, match="не из набора"):
        anchor_by("subtitles")


def test_a_negative_chain_is_refused():
    """Отрицательная задержка означала бы нажатие до сигнала."""
    with pytest.raises(CueError, match="отрицательный"):
        anchor_by("laugh").start_at(-0.1)


def test_every_anchor_says_what_to_catch():
    """Строка уезжает в лист ориентиров: без неё якорь — голое число."""
    for anchor in ANCHORS.values():
        assert anchor.catch.strip()
        assert anchor.sense in ("ухо", "глаз")


# --- на настоящих действиях --------------------------------------------------


def test_all_anchors_carry_the_same_words(real):
    """Якорь двигает дорожку, но не отбирает: отбор идёт ДО сдвига."""
    first = first_cues(real)
    words = {k: tuple(c.word for c in shift(first, a.start_at(0.25)))
             for k, a in ANCHORS.items()}
    assert len(set(words.values())) == 1, words


def test_the_latest_anchor_still_keeps_every_word(real):
    """Титры на 5.00 — самый поздний якорь. Резал бы он слова, это был бы
    другой инструмент, а не та же дорожка под другой старт."""
    first = first_cues(real)
    assert len(shift(first, anchor_by("titles").start_at(0.25))) == len(first)


def test_no_cue_lands_before_its_file_starts(real):
    first = first_cues(real)
    for anchor in ANCHORS.values():
        for cue in shift(first, anchor.start_at(0.25)):
            assert cue.t >= 0
