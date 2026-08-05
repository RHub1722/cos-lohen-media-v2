"""Подсказки голосом: слова, наложения, сдвиг под ручной старт."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cues import (WORDS, Cue, CueError, all_cues, first_cues,  # noqa: E402
                      resolve_overlaps, shift, word_for)
from src.models import Timeline
from src.movements import load_movements, resolve_times
from src.peaks import peak_offsets
from src.strikes import Beat, Strike, load_strikes, resolve_strikes

ROOT = Path(__file__).resolve().parents[1]


def _beat(role: str, heard: float, cue: str = "") -> Beat:
    return Beat(role=role, trigger="x", what="", heard=heard, t=heard, cue=cue)


def _strike(sid: str, beats: tuple[Beat, ...]) -> Strike:
    return Strike(id=sid, movement=sid, title=sid, beats=beats)


LEN = {w: 0.45 for w in WORDS}


# --- слова -------------------------------------------------------------------


def test_word_comes_from_the_role_by_default():
    assert word_for(_beat("windup", 1.0)) == "ready"
    assert word_for(_beat("contact", 1.0)) == "hit"


def test_a_beat_can_override_the_word_of_its_role():
    """У приёма удара роль contact, но бьют его. «Бей» было бы обманом."""
    assert word_for(_beat("contact", 1.0, cue="head")) == "head"


def test_a_word_outside_the_set_is_refused():
    with pytest.raises(CueError, match="не из набора"):
        word_for(_beat("contact", 1.0, cue="ударь-его-сильно"))


def test_unresolved_beats_are_refused():
    """Доля без времени — это доля до resolve_strikes. Подсказка из неё встала
    бы в ноль секунд, то есть в начало номера, и молча."""
    with pytest.raises(CueError, match="без времени"):
        all_cues([_strike("a", (_beat("windup", -1.0),))])


# --- наложения ---------------------------------------------------------------


def test_overlapping_cues_lose_the_less_important_role():
    cues = [Cue(t=10.0, word="ready", role="windup", strike="a"),
            Cue(t=10.2, word="go", role="swing", strike="a")]
    kept, dropped = resolve_overlaps(cues, LEN)
    assert [c.role for c in kept] == ["windup"]
    assert [c.role for c in dropped] == ["swing"]


def test_preparation_beats_contact_when_they_collide():
    """Выбор задокументирован и не случаен: контакт исполнитель слышит сам —
    в этот момент играет удар, — а подготовку не слышит никто, кроме подсказки."""
    cues = [Cue(t=10.0, word="hold", role="hold", strike="a"),
            Cue(t=10.1, word="hit", role="contact", strike="a")]
    kept, _ = resolve_overlaps(cues, LEN)
    assert [c.role for c in kept] == ["contact"]

    cues = [Cue(t=10.0, word="ready", role="windup", strike="a"),
            Cue(t=10.1, word="hit", role="contact", strike="a")]
    kept, dropped = resolve_overlaps(cues, LEN)
    assert [c.role for c in kept] == ["windup"]
    assert [c.role for c in dropped] == ["contact"]


def test_cues_far_apart_all_survive():
    cues = [Cue(t=10.0, word="ready", role="windup", strike="a"),
            Cue(t=20.0, word="hit", role="contact", strike="a")]
    kept, dropped = resolve_overlaps(cues, LEN)
    assert len(kept) == 2 and not dropped


def test_a_word_of_unknown_length_is_refused():
    with pytest.raises(CueError, match="длина слова"):
        resolve_overlaps([Cue(t=1.0, word="ready", role="windup", strike="a")], {})


# --- ручной старт ------------------------------------------------------------


def test_shift_drops_what_already_passed():
    """Телефон запускают посреди номера: всё, что прошло до нажатия, в файл
    попасть не может, и уж точно не с отрицательным временем."""
    cues = [Cue(t=0.5, word="ready", role="windup", strike="a"),
            Cue(t=5.0, word="hit", role="contact", strike="a")]
    out = shift(cues, 1.0)
    assert [c.t for c in out] == [4.0]


def test_negative_start_is_refused():
    with pytest.raises(CueError, match="отрицательный"):
        shift([], -0.5)


# --- на настоящем сценарии ---------------------------------------------------


@pytest.fixture(scope="module")
def real():
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    return resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"),
                           tl, peaks, moves)


def test_every_word_has_an_asset():
    for word in WORDS:
        path = ROOT / "assets" / "cues" / f"cue_{word}.wav"
        assert path.exists(), f"нет файла слова {word!r}: {path}"


def test_each_action_gets_exactly_one_stage_cue(real):
    """Сценическая дорожка — одно слово на действие. Больше нельзя: старт
    телефона нажимается рукой, и слово в точку контакта при промахе 0.25 с
    вредит вместо помощи."""
    stage = first_cues(real)
    assert len(stage) == len(real)
    assert {c.strike for c in stage} == {s.id for s in real}


def test_a_stage_cue_always_comes_before_its_first_contact(real):
    stage = {c.strike: c for c in first_cues(real)}
    for strike in real:
        contacts = [b.heard for b in strike.beats if b.role == "contact"]
        if not contacts:
            continue
        cue = stage[strike.id]
        lead = min(contacts) - cue.t
        assert lead > 0, (
            f"{strike.id}: подсказка на {cue.t:.2f} не раньше контакта "
            f"{min(contacts):.2f}")
        # Меньше 0.15 с — это уже позже человеческой реакции на звук, и
        # подсказка перестаёт быть подсказкой.
        assert lead >= 0.15, (
            f"{strike.id}: до контакта {lead:.2f} с — быстрее реакции на звук")


def test_the_overrides_land_where_they_were_meant(real):
    by_id = {s.id: s for s in real}
    first = min(by_id["burst_3"].beats, key=lambda b: b.heard)
    assert word_for(first) == "wait", (
        "первая доля серии 3 — вход автоматона: бить в него рано, слово «жди»")
    hit = next(b for b in by_id["take_the_hit"].beats if b.role == "contact")
    assert word_for(hit) == "head", "в take_the_hit бьют его, а не он"


def test_nothing_overlaps_after_resolution(real):
    kept, _ = resolve_overlaps(all_cues(real), LEN)
    for before, after in zip(kept, kept[1:]):
        assert after.t >= before.t + LEN[before.word], (
            f"{before.word} на {before.t:.2f} и {after.word} на {after.t:.2f} "
            "наезжают друг на друга")


def test_dropped_cues_are_reported_not_swallowed(real):
    """У первой вспышки четыре доли в 1.47 с, а четыре слова занимают 1.8 с:
    что-то обязано уйти. Исполнитель должен знать, что именно, иначе он будет
    ждать слово, которого не будет."""
    every = all_cues(real)
    kept, dropped = resolve_overlaps(every, LEN)
    assert dropped, "на этом наборе наложения есть, а список снятых пуст"
    assert len(kept) + len(dropped) == len(every)
