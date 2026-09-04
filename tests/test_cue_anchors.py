"""Якоря синхронизации: чем помощник ловит старт номера и как это считается.

Имя файла выбрано в стороне от `tests/test_sync_budget.py`: тот про совсем
другое — сколько вызовов play и перемоток тренажёр заказывает у планшета.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cues import (ANCHORS, CHAIN, CueError, anchor_by, first_cues,
                      shift, track_plan, LAGS_MS, PRESS)
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
    assert [t.anchor.key for t in plan] == ["laugh", "picture", "titles"]
    assert [t.start_at for t in plan] == [1.11, 0.45, 5.45]
    assert [t.name for t in plan] == ["laugh", "picture", "titles"]


def test_one_anchor_builds_one_track():
    assert [t.anchor.key for t in track_plan("titles", 0.25)] == ["titles"]


def test_an_explicit_start_overrides_the_whole_sum():
    """Число, добытое замером на площадке, важнее любого расчёта."""
    track, = track_plan("laugh", 0.25, start_at=0.95)
    assert track.anchor.key == "laugh"
    assert track.start_at == 0.95


def test_an_explicit_start_without_an_anchor_is_refused():
    """Три дорожки с одним сдвигом — это три одинаковых файла."""
    with pytest.raises(CueError, match="только с одним якорем"):
        track_plan(None, 0.25, start_at=0.95)


# --- лесенка компенсаций радиоканала -----------------------------------------
# Имена написаны БУКВАМИ, а не собраны из кода. Тест, спрашивающий имя у той же
# функции, которую проверяет, не может заметить, что имя неверное: однажды
# мутация, схлопнувшая имена сверочных копий в одно, прошла мимо именно так.
# А имя здесь — единственное, чем выбирают файл на телефоне в темноте.
LADDER_NAMES = ("titles_lag0", "titles_lag100", "titles_lag200")


def test_the_ladder_names_the_files_the_way_the_phone_will_show_them():
    plan = track_plan("titles", CHAIN, lags=LAGS_MS)
    assert tuple(t.name for t in plan) == LADDER_NAMES
    assert all(t.anchor.key == "titles" for t in plan)


def test_the_ladder_steps_only_the_radio_link_and_leaves_the_press_alone():
    """Нажатие постоянно, гуляет только канал — лесенка перебирает его одного.

    Проверяется разностями, а не суммами: сумма сойдётся и при неверном
    слагаемом, а шаг между ступенями обязан быть ровно тем, что обещан именем.
    """
    plan = track_plan("titles", CHAIN, lags=LAGS_MS)
    steps = [round(b.start_at - a.start_at, 6)
             for a, b in zip(plan, plan[1:])]
    assert steps == [(b - a) / 1000.0 for a, b in zip(LAGS_MS, LAGS_MS[1:])]
    first = plan[0]
    assert first.start_at == pytest.approx(
        first.anchor.t + first.anchor.reaction + PRESS)


def test_the_top_of_the_ladder_is_the_track_that_already_existed():
    """Верхняя ступень обязана совпасть с дорожкой по умолчанию.

    Иначе в папке телефона окажутся два правильных файла на один случай под
    разными именами — ровно то, из-за чего якорные ризы уже убирались целиком.
    """
    top = track_plan("titles", CHAIN, lags=LAGS_MS)[-1]
    plain, = track_plan("titles", CHAIN)
    assert top.start_at == plain.start_at
    assert top.name != plain.name


def test_the_ladder_needs_exactly_one_anchor():
    """На трёх якорях вышло бы девять дорожек и восемнадцать файлов."""
    with pytest.raises(CueError, match="только с одним якорем"):
        track_plan(None, CHAIN, lags=LAGS_MS)


def test_the_ladder_and_a_measured_start_exclude_each_other():
    """`--start-at` задаёт сумму целиком, а лесенка её и перебирает: вместе
    они дали бы три одинаковых файла с разными именами."""
    with pytest.raises(CueError, match="исключают друг друга"):
        track_plan("titles", CHAIN, start_at=5.45, lags=LAGS_MS)


def test_the_track_list_matches_what_the_builder_would_name():
    """Список выше написан буквами, и он обязан сойтись с планом сборки.

    Сам список менять по коду нельзя — тогда он перестанет что-либо ловить, —
    но разойтись молча они тоже не должны: тогда проверки уедут на файлы,
    которых сборщик уже не делает, и пропуск станет тихим.
    """
    names = {t.name for t in track_plan("titles", CHAIN, lags=LAGS_MS)}
    names |= {t.name for t in track_plan("laugh", CHAIN)}
    names |= {t.name for t in track_plan("picture", CHAIN)}
    assert names == set(TRACKS)
    for track in track_plan("titles", CHAIN, lags=LAGS_MS):
        assert STARTS[track.name] == pytest.approx(track.start_at)


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
# Собранные дорожки, БУКВАМИ. Не через track_plan(): тест, спрашивающий имя у
# того же кода, который проверяет, не заметит ошибки в нём — однажды мутация,
# схлопнувшая имена сверочных копий, прошла мимо ровно так.
#
# У титров лесенка: одной дорожки под этим якорем больше нет, вместо неё три с
# разной компенсацией радиоканала. Держать рядом ещё и безымянную значило бы
# положить в телефон два правильных файла на один случай.
TRACKS = ("laugh", "picture", "titles_lag0", "titles_lag100", "titles_lag200")

# Сдвиг каждой, числом. Тоже не из кода: это и есть то, что проверяется.
STARTS = {"laugh": 1.11, "picture": 0.45,
          "titles_lag0": 5.25, "titles_lag100": 5.35, "titles_lag200": 5.45}


def stage(name: str, sync: bool = False) -> Path:
    """Путь дорожки, а нет её — пропуск ТОЛЬКО этой строки.

    Гейт был общий, на весь список: один отсутствующий файл гасил проверки и
    по тем, что лежат на месте. Обошлось это в двадцать один молча пропущенный
    тест, и заметить их удалось только по счётчику.
    """
    path = OUT / ("stage_cues_%s%s.wav" % (name, "_sync" if sync else ""))
    if not path.exists():
        pytest.skip("нет %s: python src/render_cues.py --anchor titles --lags"
                    % path.name)
    return path


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


@pytest.mark.parametrize("name", TRACKS)
def test_the_silence_between_words_is_not_digital_silence(name):
    """Наушник на цифровой тишине уходит в энергосбережение, и первое слово
    после паузы приходит обрезанным. Между шестью словами паузы по 4-10 с."""
    assert _mean_db(stage(name), 8.0, 4.0) > -85.0


@pytest.mark.parametrize("name", TRACKS)
def test_the_floor_stays_far_under_the_cue(name):
    """Подложка обязана быть неслышной: она страховка, а не звук."""
    path = stage(name)
    assert peak_db(path) - _mean_db(path, 8.0, 4.0) > 50.0


@pytest.mark.parametrize("name", TRACKS)
def test_a_click_confirms_the_channel_is_alive(name):
    """Помощник нажал — исполнитель обязан услышать, что часы пошли. Без
    этого о разорванном Bluetooth станет известно на 28.50, посреди номера.

    Щелчок стоит не в нуле: первые ~0.2 с съедает пробуждение канала, и в
    нуле его срезало бы вместе с ними."""
    path = stage(name)
    quiet = _mean_db(path, 0.05, 0.15)
    click = _mean_db(path, 0.25, 0.20)
    assert click - quiet > 20.0, f"тихо {quiet:.1f}, щелчок {click:.1f}"


# --- сверочные копии ---------------------------------------------------------

@pytest.mark.parametrize("name", TRACKS)
def test_the_sync_copy_carries_the_number_underneath(name):
    """Сверочная копия существует ради одного: две копии одного звука,
    разошедшиеся во времени, слышны как хлопок. Без номера под словами
    сравнивать не с чем, и вся затея рассыпается."""
    plain = _mean_db(stage(name), 12.0, 4.0)
    sync = _mean_db(stage(name, sync=True), 12.0, 4.0)
    assert sync - plain > 20.0, f"обычная {plain:.1f}, сверочная {sync:.1f}"


@pytest.mark.parametrize("name", TRACKS)
def test_the_number_stays_under_the_cue(name):
    """Номер здесь фон, а не содержание. Перекрой он подсказку — копия стала
    бы второй репетиционной дорожкой, а её задача другая."""
    path = stage(name, sync=True)
    assert peak_db(path) - _mean_db(path, 12.0, 4.0) > 30.0


@pytest.mark.parametrize("name", TRACKS)
def test_the_sync_copy_is_the_same_length_as_the_one_it_checks(name):
    """Проверяет она ту дорожку, что рядом, и обязана идти с ней в ногу."""
    assert abs(_duration(stage(name, sync=True))
               - _duration(stage(name))) < 0.01


@pytest.mark.parametrize("name", TRACKS)
def test_the_stage_track_carries_risers_not_words(name):
    """Риз разгоняется В контакт и обрывается: перед вершиной громко, сразу
    после неё подложка. У слова такого профиля нет — оно ровное и кончается
    там, где кончается, а не в точке удара."""
    path = stage(name)
    peak = 47.03 - STARTS[name]   # копьё в пол
    before = _mean_db(path, peak - 0.35, 0.30)
    after = _mean_db(path, peak + 0.20, 0.30)
    assert before - after > 40.0, f"перед {before:.1f}, после {after:.1f}"
