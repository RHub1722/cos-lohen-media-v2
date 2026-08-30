"""Якоря синхронизации: чем помощник ловит старт номера и как это считается.

Имя файла выбрано в стороне от `tests/test_sync_budget.py`: тот про совсем
другое — сколько вызовов play и перемоток тренажёр заказывает у планшета.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cues import (ANCHORS, CHAIN, CueError, anchor_by, first_cues,
                      shift, track_plan)
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


def test_the_key_matches_the_slot_it_sits_in():
    """Ключ словаря и поле объекта — два места для одного имени. Опечатку в
    одном из них не поймает больше ничто."""
    for key, anchor in ANCHORS.items():
        assert anchor.key == key


# --- какие дорожки собирать --------------------------------------------------


def test_without_an_anchor_every_track_is_built():
    """По умолчанию собираются все три: чем ловить — вопрос к площадке."""
    plan = track_plan(None, 0.25)
    assert [a.key for a, _ in plan] == ["laugh", "picture", "titles"]
    assert [s for _, s in plan] == [1.11, 0.45, 5.45]


def test_one_anchor_builds_one_track():
    assert [a.key for a, _ in track_plan("titles", 0.25)] == ["titles"]


def test_an_explicit_start_overrides_the_whole_sum():
    """Число, добытое замером на площадке, важнее любого расчёта."""
    (anchor, start), = track_plan("laugh", 0.25, start_at=0.95)
    assert anchor.key == "laugh"
    assert start == 0.95


def test_an_explicit_start_without_an_anchor_is_refused():
    """Три дорожки с одним сдвигом — это три одинаковых файла."""
    with pytest.raises(CueError, match="только с одним якорем"):
        track_plan(None, 0.25, start_at=0.95)


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


# --- собранные файлы ---------------------------------------------------------

import subprocess  # noqa: E402

from src.measure import peak_db  # noqa: E402

OUT = ROOT / "output"
STAGE = [OUT / f"stage_cues_{k}.wav" for k in ("laugh", "picture", "titles")]
BUILT = pytest.mark.skipif(not all(p.exists() for p in STAGE),
                           reason="сначала python src/render_cues.py")


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def _mean_db(path: Path, start: float, length: float) -> float:
    """Средний уровень окна. Цифровая тишина даёт около -91 dB и ниже."""
    done = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", f"{start:.4f}", "-t", f"{length:.4f}",
         "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in done.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0].strip())
    raise AssertionError(f"volumedetect не дал средний уровень для {path}")


@BUILT
@pytest.mark.parametrize("path", STAGE, ids=lambda p: p.stem)
def test_the_silence_between_words_is_not_digital_silence(path):
    """Наушник на цифровой тишине уходит в энергосбережение, и первое слово
    после паузы приходит обрезанным. Между шестью словами паузы по 4-10 с."""
    assert _mean_db(path, 8.0, 4.0) > -85.0


@BUILT
@pytest.mark.parametrize("path", STAGE, ids=lambda p: p.stem)
def test_the_floor_stays_far_under_the_words(path):
    """Подложка обязана быть неслышной: она страховка, а не звук."""
    assert peak_db(path) - _mean_db(path, 8.0, 4.0) > 50.0


@BUILT
@pytest.mark.parametrize("path", STAGE, ids=lambda p: p.stem)
def test_a_click_confirms_the_channel_is_alive(path):
    """Помощник нажал — исполнитель обязан услышать, что часы пошли. Без
    этого о разорванном Bluetooth станет известно на 28.50, посреди номера.

    Щелчок стоит не в нуле: первые ~0.2 с съедает пробуждение канала, и в
    нуле его срезало бы вместе с ними."""
    quiet = _mean_db(path, 0.05, 0.15)
    click = _mean_db(path, 0.25, 0.20)
    assert click - quiet > 20.0, f"тихо {quiet:.1f}, щелчок {click:.1f}"


# --- сверочные копии ---------------------------------------------------------

SYNC = [OUT / f"stage_cues_{k}_sync.wav" for k in ("laugh", "picture", "titles")]
BUILT_SYNC = pytest.mark.skipif(not all(p.exists() for p in SYNC),
                                reason="сначала python src/render_cues.py")


@BUILT_SYNC
@pytest.mark.parametrize("key", ["laugh", "picture", "titles"])
def test_the_sync_copy_carries_the_number_underneath(key):
    """Сверочная копия существует ради одного: две копии одного звука,
    разошедшиеся во времени, слышны как хлопок. Без номера под словами
    сравнивать не с чем, и вся затея рассыпается."""
    plain = _mean_db(OUT / f"stage_cues_{key}.wav", 12.0, 4.0)
    sync = _mean_db(OUT / f"stage_cues_{key}_sync.wav", 12.0, 4.0)
    assert sync - plain > 20.0, f"обычная {plain:.1f}, сверочная {sync:.1f}"


@BUILT_SYNC
@pytest.mark.parametrize("key", ["laugh", "picture", "titles"])
def test_the_number_stays_under_the_words(key):
    """Номер здесь фон, а не содержание. Перекрой он подсказку — копия стала
    бы второй репетиционной дорожкой, а её задача другая."""
    path = OUT / f"stage_cues_{key}_sync.wav"
    assert peak_db(path) - _mean_db(path, 12.0, 4.0) > 30.0


@BUILT_SYNC
@pytest.mark.parametrize("key", ["laugh", "picture", "titles"])
def test_the_sync_copy_is_the_same_length_as_the_one_it_checks(key):
    """Проверяет она ту дорожку, что рядом, и обязана идти с ней в ногу."""
    plain = OUT / f"stage_cues_{key}.wav"
    sync = OUT / f"stage_cues_{key}_sync.wav"
    assert abs(_duration(sync) - _duration(plain)) < 0.01


# --- ризы под якорями --------------------------------------------------------
# Тот же якорь, другой инструмент: вместо слова нарастающий шум, вершина ровно
# в контакт. Собирается сборщиком счёта, но якоря берёт отсюда же.

RISER_DIR = OUT / "cues"
RISERS = [RISER_DIR / f"lohen_riser_{k}.m4a"
          for k in ("laugh", "picture", "titles")]
BUILT_RISERS = pytest.mark.skipif(
    not all(p.exists() for p in RISERS),
    reason="сначала python src/render_count.py --cues --only riser")
KEYS = ["laugh", "picture", "titles"]


@BUILT_RISERS
@pytest.mark.parametrize("key", KEYS)
def test_the_riser_track_starts_where_the_helper_pressed(key):
    """Файл начинается с середины номера, значит и длина у него своя: ровно
    шестьдесят минус сдвиг. Полная длина означала бы прежнюю модель, где оба
    устройства пускают одновременно."""
    want = 60.0 - anchor_by(key).start_at(CHAIN)
    assert abs(_duration(RISER_DIR / f"lohen_riser_{key}.m4a") - want) < 0.10


@BUILT_RISERS
@pytest.mark.parametrize("key", KEYS)
def test_the_riser_ends_dead_on_the_contact(key):
    """Риз разгоняется В контакт и обрывается. Греми он после удара — означал
    бы «сейчас будет» тогда, когда уже было."""
    path = RISER_DIR / f"lohen_riser_{key}.m4a"
    peak = 47.00 - anchor_by(key).start_at(CHAIN)   # копьё в пол
    before = _mean_db(path, peak - 0.35, 0.30)
    after = _mean_db(path, peak + 0.20, 0.30)
    assert before - after > 40.0, f"перед {before:.1f}, после {after:.1f}"


@BUILT_RISERS
@pytest.mark.parametrize("key", KEYS)
def test_the_riser_sync_copy_carries_the_number(key):
    """У ризов сверочная копия своя, и нужна она ровно за тем же."""
    plain = _mean_db(RISER_DIR / f"lohen_riser_{key}.m4a", 12.0, 4.0)
    sync = _mean_db(RISER_DIR / f"lohen_riser_{key}_sync.m4a", 12.0, 4.0)
    assert sync - plain > 20.0, f"обычная {plain:.1f}, сверочная {sync:.1f}"
