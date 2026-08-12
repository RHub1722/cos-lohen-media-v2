"""Задания на тренировочные клипы: что проверяется до того, как за них платят."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.models import Timeline
from src.movements import load_movements, resolve_times
from src.peaks import peak_offsets
from src.strikes import load_strikes, resolve_strikes
from src.train_clips import (CLIPS, DURATIONS, MAX_PANELS, MAX_REFS, PREDICTION,
                             ClipError, caveat, load)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def strikes():
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    moves = resolve_times(load_movements(ROOT / "scenario/movements.json"), tl)
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    return resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"), tl,
                           peaks, [m.id for m in moves])


@pytest.fixture(scope="module")
def clips(strikes):
    return load(strikes)


@pytest.fixture
def raw():
    return json.loads(CLIPS.read_text(encoding="utf-8"))


def write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "train_clips.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def pick(raw: dict, cid: str) -> dict:
    """Клип по id, а не по номеру в списке: список меняется."""
    return next(c for c in raw["clips"] if c["id"] == cid)


# --- то, что должно быть верно в самом файле -------------------------------

def test_every_strike_of_the_fight_has_a_clip(clips, strikes):
    assert {c.strike for c in clips} == {s.id for s in strikes}


def test_every_panel_the_clip_asks_for_is_on_disk(clips):
    for clip in clips:
        for panel in clip.panels:
            assert panel.exists(), "%s: нет %s" % (clip.id, panel.name)


def test_a_clip_has_exactly_one_panel_per_beat(clips):
    for clip in clips:
        assert len(clip.refs) <= MAX_REFS


# --- персонаж: то, из-за чего всё это переделывалось ------------------------

def test_the_look_comes_from_the_official_art_not_from_our_sheets(clips):
    """На листах движений персонаж уехал в русого — облик берём из арта."""
    for clip in clips:
        assert clip.faces, clip.id
        for ref in clip.faces:
            assert ref.exists(), "%s: нет %s" % (clip.id, ref.name)
            assert ref.parent.name == "screenshots"


def test_the_look_references_go_before_the_poses(clips):
    """Промпт адресует картинки по номерам, и номера считаны из этого порядка."""
    for clip in clips:
        assert clip.refs[:len(clip.faces)] == clip.faces
        assert clip.refs[len(clip.faces):] == clip.panels


def test_the_prompt_points_at_the_right_picture_numbers(clips):
    """«images 1 and 2» — внешность, «images 3-N» — позы. Считает загрузчик."""
    for clip in clips:
        n = len(clip.faces)
        first, last = n + 1, n + len(clip.panels)
        assert "images 1 and 2" in clip.prompt if n == 2 else True
        assert "images %d-%d" % (first, last) in clip.prompt


def test_the_character_is_lohen_and_not_the_one_on_the_sheets(clips):
    for clip in clips:
        low = clip.prompt.lower()
        assert "mint-green hair" in low
        assert "violet-pink eyes" in low
        # то, чем персонаж стал на листах, не должно вернуться
        for wrong in ("blond", "shoulder-length hair", "military greatcoat"):
            assert wrong not in low, "%s: вернулось %r" % (clip.id, wrong)


def test_the_description_of_the_character_is_one_and_the_same_everywhere(clips):
    """Одно описание на файл. Шесть копий уже расходились однажды."""
    marker = "SHORT pale mint-green hair"
    starts = [c.prompt.index(marker) for c in clips]
    length = 700
    blocks = {c.prompt[s:s + length] for c, s in zip(clips, starts)}
    assert len(blocks) == 1


def test_no_clip_carries_more_panels_than_the_look_can_survive(clips):
    """Шесть панелей против двух артов — и Лоэн уехал в русого на две секунды."""
    for clip in clips:
        assert len(clip.panels) <= MAX_PANELS, "%s: %d" % (clip.id, len(clip.panels))
        assert len(clip.panels) <= 2 * len(clip.faces)


def test_the_prompt_demands_the_look_holds_to_the_last_frame(clips):
    for clip in clips:
        assert "from the first frame to the last" in clip.prompt
        assert "never changes colour" in clip.prompt


def test_the_split_halves_of_burst_3_overlap_on_the_first_impact(clips):
    """Иначе ни одна половина не показала бы, как в удар приходят."""
    by_id = {c.id: c for c in clips}
    a, b = by_id["burst_3a"], by_id["burst_3b"]
    assert a.strike == b.strike == "burst_3"
    assert a.last == b.first
    shared = set(p.name for p in a.panels) & set(p.name for p in b.panels)
    assert len(shared) == 1


# --- кадр: камера уехала сама, и правила теперь лежат одним блоком ----------

def test_the_rules_of_the_shot_are_one_and_the_same_everywhere(clips):
    marker = "Single continuous shot from a locked-off camera"
    blocks = {c.prompt[c.prompt.index(marker):] for c in clips}
    assert len(blocks) == 1


def test_the_shot_forbids_the_camera_from_moving_at_all(clips):
    for clip in clips:
        assert "never changes focal length" in clip.prompt
        assert "WHOLE BODY" in clip.prompt
        assert "never a close-up" in clip.prompt


def test_the_ban_names_what_the_camera_did(clips):
    for clip in clips:
        for phrase in ("camera push-in", "dolly", "close-up", "cropped body",
                       "sparks", "impact flash", "orange light"):
            assert phrase in clip.negative


def test_a_file_without_the_rules_of_the_shot_is_loud(strikes, raw, tmp_path):
    raw["кадр"] = ""
    with pytest.raises(ClipError, match="камера уезжает сама"):
        load(strikes, write(tmp_path, raw))


def test_too_many_panels_is_loud(strikes, raw, tmp_path):
    clip = dict(raw["clips"][0])
    clip["id"] = "перебор"
    clip["beats"] = [1, 2, 3, 4]
    clip["panels"] = clip["panels"] + clip["panels"][:1]
    raw["clips"].append(clip)
    with pytest.raises(ClipError, match="уезжает в русого"):
        load(strikes, write(tmp_path, raw))


# --- копьё встало не тем концом --------------------------------------------

def test_the_finale_says_which_end_goes_into_the_floor(clips):
    """Первый заход поставил копьё украшенным наконечником вверх."""
    finale = next(c for c in clips if c.id == "spear_down")
    assert "ornate blade is DOWN, in the floor" in finale.prompt
    assert "Not the other way round" in finale.prompt


def test_the_prompt_says_the_poses_carry_the_wrong_look(clips):
    """Панели идут на вход с неверной внешностью — это надо сказать прямо."""
    for clip in clips:
        assert "design is WRONG" in clip.prompt
        assert "ONLY for body position" in clip.prompt


def test_the_ban_names_the_look_that_went_wrong(clips):
    for clip in clips:
        assert "blond hair" in clip.negative


# --- оружие: первая генерация выдала наконечник на обоих концах -------------

def test_the_word_head_never_means_the_weapon(clips):
    """Из-за этой двусмысленности копьё и вышло двуглавым.

    В промпте стояло «large ornate head» про верхний конец и «head of the
    polearm resting on the floor» про нижний. Модель выполнила буквально оба.
    Теперь head — только про его голову.
    """
    for clip in clips:
        for phrase in ("head of the polearm", "head of the weapon",
                       "the head lifts", "the head raised", "the head forward",
                       "the head drives", "its head", "heavy head"):
            assert phrase not in clip.prompt, "%s: %r" % (clip.id, phrase)


def test_the_prompt_says_the_weapon_is_asymmetric(clips):
    for clip in clips:
        assert "STRONGLY ASYMMETRIC" in clip.prompt
        assert "blade at ONE END ONLY" in clip.prompt
        assert "not double-headed" in clip.prompt


def test_the_ban_names_the_double_ended_weapon(clips):
    for clip in clips:
        for phrase in ("double-ended weapon", "blade at both ends",
                       "symmetrical polearm"):
            assert phrase in clip.negative


def test_the_dagger_in_the_reference_is_excluded(clips):
    """spear_full.png показывает копьё И отдельный кинжал. Кинжал не наш."""
    for clip in clips:
        assert "dagger is a DIFFERENT weapon" in clip.prompt
        assert "dagger" in clip.negative


def test_the_length_is_one_the_model_accepts(clips):
    for clip in clips:
        assert clip.duration in DURATIONS


def test_the_tempo_in_the_prompt_is_the_one_the_beats_give(clips):
    """Промпт обязан называть настоящую длину движения, а не выдуманную."""
    for clip in clips:
        assert "%.2f seconds in reality" % clip.real in clip.prompt
        assert clip.real == round(clip.last - clip.first, 2)


def test_no_clip_slows_the_fight_absurdly(clips):
    """Замедление держим в разумных пределах: от трёх до шести раз.

    Меньше трёх — движение снова не разглядеть, а ради этого всё и делается.
    Больше шести — модель начинает додумывать кадры, которых в движении нет.
    """
    for clip in clips:
        assert 3.0 <= clip.slow <= 6.0, "%s: %.1fx" % (clip.id, clip.slow)


def test_nothing_unsubstituted_reaches_the_prompt(clips):
    for clip in clips:
        assert "{" not in clip.prompt and "}" not in clip.prompt


def test_the_ban_covers_the_text_baked_into_the_panels(clips):
    """Панели режутся с подписями — запрет на текст обязателен."""
    for clip in clips:
        for word in ("text", "numbers", "arrows", "grid lines", "watermarks"):
            assert word in clip.negative


def test_the_clips_do_not_ask_for_sound(clips):
    """Звук выключается в запросе, но и промпт не должен его просить."""
    for clip in clips:
        low = clip.prompt.lower()
        for word in ("music", "soundtrack", "audio", "sound effect"):
            assert word not in low


# --- то, что должно громко падать -----------------------------------------

def test_a_clip_for_an_unknown_strike_is_loud(strikes, raw, tmp_path):
    raw["clips"][0]["strike"] = "burst_9"
    with pytest.raises(ClipError, match="burst_9"):
        load(strikes, write(tmp_path, raw))


def test_a_missing_panel_is_loud(strikes, raw, tmp_path):
    raw["clips"][0]["panels"][1] = "burst_1__nope.png"
    with pytest.raises(ClipError, match="cut_panels"):
        load(strikes, write(tmp_path, raw))


def test_a_pose_without_a_panel_is_loud(strikes, raw, tmp_path):
    """Долей четыре, панелей три — одна поза уехала бы молча."""
    raw["clips"][0]["panels"].pop()
    with pytest.raises(ClipError, match="уехала бы на сервер"):
        load(strikes, write(tmp_path, raw))


def test_a_length_the_model_rejects_is_caught_before_paying(strikes, raw, tmp_path):
    raw["clips"][0]["duration"] = 3
    with pytest.raises(ClipError, match="принимает только"):
        load(strikes, write(tmp_path, raw))


def test_a_prompt_without_the_tempo_placeholder_is_loud(strikes, raw, tmp_path):
    raw["clips"][0]["prompt"] = raw["clips"][0]["prompt"].replace("{slow}", "4x")
    with pytest.raises(ClipError, match=r"\{slow\}"):
        load(strikes, write(tmp_path, raw))


def test_beats_out_of_order_are_loud(strikes, raw, tmp_path):
    raw["clips"][0]["beats"] = [1, 3, 2, 4]
    with pytest.raises(ClipError, match="не по порядку"):
        load(strikes, write(tmp_path, raw))


def test_a_beat_the_strike_does_not_have_is_loud(strikes, raw, tmp_path):
    clip = pick(raw, "burst_4")          # у этого удара всего три доли
    clip["beats"] = [1, 2, 9]
    with pytest.raises(ClipError, match="всего"):
        load(strikes, write(tmp_path, raw))


def test_a_file_without_the_ban_is_loud(strikes, raw, tmp_path):
    raw["общий запрет"] = ""
    with pytest.raises(ClipError, match="уедет текст"):
        load(strikes, write(tmp_path, raw))


def test_two_clips_with_one_id_are_loud(strikes, raw, tmp_path):
    raw["clips"].append(dict(raw["clips"][0]))
    with pytest.raises(ClipError, match="дважды"):
        load(strikes, write(tmp_path, raw))


def test_more_refs_than_the_model_takes_is_loud(strikes, raw, tmp_path):
    """Панелей теперь не больше четырёх, так что предел девяти достигается
    только референсами внешности — но достигается, и он должен ловиться."""
    raw["character"]["refs"] = [
        "lohen_splash_art.png", "spear_full.png", "lohen_spear_static.png",
        "lohen_rage.png", "lohen_over_captive.png", "lohen_fullbody_green.png",
    ]
    with pytest.raises(ClipError, match="не больше 9"):
        load(strikes, write(tmp_path, raw))


def test_the_look_reference_budget_counts_both_kinds(strikes, raw, tmp_path):
    """Сообщение обязано назвать оба слагаемых, иначе непонятно, что убирать."""
    raw["character"]["refs"] = [
        "lohen_splash_art.png", "spear_full.png", "lohen_spear_static.png",
        "lohen_rage.png", "lohen_over_captive.png", "lohen_fullbody_green.png",
    ]
    with pytest.raises(ClipError, match="внешность 6 \\+ позы 4"):
        load(strikes, write(tmp_path, raw))


def test_a_file_without_a_character_description_is_loud(strikes, raw, tmp_path):
    raw["character"]["описание"] = ""
    with pytest.raises(ClipError, match="облик с панелей"):
        load(strikes, write(tmp_path, raw))


def test_a_file_without_look_references_is_loud(strikes, raw, tmp_path):
    raw["character"]["refs"] = []
    with pytest.raises(ClipError, match="персонаж уезжает"):
        load(strikes, write(tmp_path, raw))


def test_a_missing_look_reference_is_loud(strikes, raw, tmp_path):
    raw["character"]["refs"] = ["lohen_nope.png"]
    with pytest.raises(ClipError, match="lohen_nope"):
        load(strikes, write(tmp_path, raw))


# --- раскладка на диске ----------------------------------------------------

def test_the_clips_land_outside_the_folder_of_the_number():
    """Тренировочный клип не должен попасть в монтаж номера даже случайно."""
    from tools.atlas_train import OUT
    video = ROOT / "assets" / "video"
    assert video not in OUT.parents and OUT != video


def test_the_ledger_tells_a_training_clip_from_a_shot_of_the_number(clips):
    from tools.atlas_train import TAG, as_shot
    for clip in clips:
        assert as_shot(clip).anchor.startswith(TAG)


# --- отбор попыток: что уезжает на сайт ------------------------------------

def test_every_clip_says_which_attempt_was_accepted(clips):
    """Рядом с принятой попыткой лежат отклонённые, и отличаются они одной
    цифрой в имени: spear_down_a1 — копьё вверх ногами, burst_4_a1 — наезд
    камеры, take_the_hit_a1 — двухголовое копьё. Брать последнюю попытку нельзя:
    последняя не значит лучшая, у финала годной вышла третья из трёх, а у
    вспышки 4 — вторая."""
    for clip in clips:
        assert clip.attempt >= 1, clip.id
        assert PREDICTION.match(clip.prediction), (clip.id, clip.prediction)
        assert clip.accepted == "%s_a%d.mp4" % (clip.id, clip.attempt)


def test_the_name_of_the_accepted_file_is_built_in_one_place(clips):
    """Имя попытки складывают и генератор при скачивании, и страница при
    публикации. Разойдутся — на сайт молча уедет отклонённая попытка."""
    from tools.atlas_train import attempt_path
    for clip in clips:
        assert attempt_path(clip.id, clip.attempt).name == clip.accepted


def test_the_accepted_attempt_is_the_one_the_ledger_charged_for(clips):
    """Журнал — единственная запись о том, что было оплачено и чем кончилось.
    Если в сценарии стоит попытка, которой в журнале нет, значит либо номер
    выдуман, либо файл на диске не тот, за который заплатили."""
    rows = list(csv.DictReader(
        (ROOT / "docs/atlas-ledger.csv").read_text(encoding="utf-8").splitlines()))
    for clip in clips:
        want = [r for r in rows
                if r["shot"] == "train:" + clip.id
                and int(r["attempt"]) == clip.attempt]
        assert want, "%s: попытки %d нет в журнале" % (clip.id, clip.attempt)
        assert want[-1]["prediction_id"] == clip.prediction, clip.id
        assert want[-1]["file"] == clip.accepted, clip.id


def test_every_clip_says_what_to_watch_and_what_it_does_not_show(clips):
    """«Чего нет» важнее «что смотреть»: клип показывает, как движение выглядит,
    но врёт про то, когда оно случается."""
    for clip in clips:
        assert len(clip.watch) > 40, clip.id
        assert clip.missing, clip.id
        assert all(len(text) > 20 for text in clip.missing), clip.id


def test_the_clip_of_the_finale_admits_there_is_no_flip(clips):
    """Три попытки при верных панелях и прямом указании в промпте — переворота
    копья модель так и не сделала. Умолчать об этом на странице значит учить
    поднимать копьё не тем концом."""
    finale = next(c for c in clips if c.id == "spear_down")
    said = " ".join(finale.missing).lower()
    assert "переворот" in said and "книжк" in said


def test_the_clip_that_lost_the_stillness_admits_it(clips):
    """Приём удара — четыре секунды неподвижности на площадке, а на клипе корпус
    не замирает и голова не возвращается до конца."""
    hit = next(c for c in clips if c.id == "take_the_hit")
    said = " ".join(hit.missing).lower()
    assert "корпус не замирает" in said
    assert "голова не возвращается" in said


def test_the_general_caveat_sends_the_reader_back_to_the_scenario():
    """Время берётся из сценария и только оттуда. Доли внутри клипов стоят не
    там: у вспышки 3 оборот кончается на половине клипа."""
    text = caveat()
    assert "strikes.json" in text
    assert len(text) > 200


def test_a_clip_that_hides_which_attempt_was_accepted_is_loud(strikes, raw, tmp_path):
    pick(raw, "burst_1")["публикация"]["попытка"] = 0
    with pytest.raises(ClipError, match="какая попытка принята"):
        load(strikes, write(tmp_path, raw))


def test_a_clip_with_a_bogus_prediction_is_loud(strikes, raw, tmp_path):
    pick(raw, "burst_1")["публикация"]["prediction"] = "нет такого"
    with pytest.raises(ClipError, match="prediction"):
        load(strikes, write(tmp_path, raw))


def test_a_clip_that_hides_its_gaps_is_loud(strikes, raw, tmp_path):
    pick(raw, "spear_down")["публикация"]["чего нет"] = []
    with pytest.raises(ClipError, match="чего на нём нет"):
        load(strikes, write(tmp_path, raw))


def test_every_beat_has_a_mark_inside_its_clip(clips):
    """Двадцать шесть отметок: где каждая доля стоит ВНУТРИ клипа.

    Без них пульт сопоставлял время номера времени клипа одной прямой, а клипы
    внутри себя держат свой темп. Отметка обязана быть у каждой доли: лишняя или
    недостающая молча сдвинет все следующие.
    """
    assert sum(len(c.marks) for c in clips) == 26
    for clip in clips:
        assert len(clip.marks) == len(clip.beats), clip.id
        assert clip.marks[0] == 0.0, clip.id
        assert list(clip.marks) == sorted(clip.marks), clip.id
        assert clip.marks[-1] <= clip.duration, clip.id


def test_the_marks_are_measured_and_not_derived_from_the_clock(clips, strikes):
    """Если бы отметки просто считались из времён долей, они были бы прямой — и
    чинить было бы нечего. Проверка в том, что они от прямой ОТЛИЧАЮТСЯ, и
    сильнее всего там, где это и замерено: у части 1 вспышки 3 оборот кончен к
    2.45 с из 5.04, то есть контакт стоит вдвое раньше прямой."""
    by_id = {s.id: s for s in strikes}

    def straight(clip, number):
        """Куда поставила бы долю одна прямая — то, что и чинят отметки."""
        heard = by_id[clip.strike].beats[number - 1].heard
        return (heard - clip.first) / clip.real * clip.duration

    part1 = next(c for c in clips if c.id == "burst_3a")
    assert part1.marks[-1] == 2.45
    assert straight(part1, part1.beats[-1]) - part1.marks[-1] > 2.0, (
        "контакт части 1 вспышки 3 замерен на 2.45 при прямой в конце клипа")

    worst = max(abs(straight(clip, number) - mark)
                for clip in clips
                for number, mark in zip(clip.beats, clip.marks))
    assert worst > 1.0, ("отметки почти совпали с прямой — значит их не замеряли, "
                         "худшее расхождение всего %.2f с" % worst)


def test_a_clip_with_the_wrong_number_of_marks_is_loud(strikes, raw, tmp_path):
    pick(raw, "burst_1")["публикация"]["доли в клипе"] = [0.0, 1.0]
    with pytest.raises(ClipError, match="отметок долей"):
        load(strikes, write(tmp_path, raw))


def test_marks_that_go_backwards_are_loud(strikes, raw, tmp_path):
    pick(raw, "burst_1")["публикация"]["доли в клипе"] = [0.0, 2.0, 1.0, 3.0]
    with pytest.raises(ClipError, match="не по порядку"):
        load(strikes, write(tmp_path, raw))


def test_the_first_mark_must_sit_at_zero(strikes, raw, tmp_path):
    pick(raw, "burst_1")["публикация"]["доли в клипе"] = [0.4, 1.9, 4.1, 4.5]
    with pytest.raises(ClipError, match="обязана стоять в нуле"):
        load(strikes, write(tmp_path, raw))


def test_a_mark_past_the_end_of_the_clip_is_loud(strikes, raw, tmp_path):
    pick(raw, "burst_1")["публикация"]["доли в клипе"] = [0.0, 1.9, 4.1, 9.0]
    with pytest.raises(ClipError, match="а клип длится"):
        load(strikes, write(tmp_path, raw))


def test_a_file_without_the_general_caveat_is_loud(raw, tmp_path):
    raw.pop("общая оговорка")
    with pytest.raises(ClipError, match="метроном"):
        caveat(write(tmp_path, raw))


def test_the_page_builds_where_the_pictures_of_the_generation_are_absent(
        strikes, monkeypatch):
    """Панели и официальный арт в .gitignore: панели производные, арт чужой. А
    страница собирается и из свежего клона, где нет ни того, ни другого, и
    никаких картинок на сервер не отправляет. Проверка входа защищает оплату
    генерации, а не сборку страницы."""
    import src.train_clips as module
    # Папки нарочно внутри проекта, хоть их и нет: сообщения об ошибке называют
    # путь относительно корня, а на пути из чужого temp такой рассказ падает сам.
    monkeypatch.setattr(module, "PANELS", ROOT / "assets/нет-панелей")
    monkeypatch.setattr(module, "FACES", ROOT / "assets/нет-арта")
    with pytest.raises(ClipError, match="референсов внешности"):
        load(strikes, CLIPS)
    clips = load(strikes, CLIPS, require_refs=False)
    assert len(clips) == 7
    assert all(c.watch and c.missing for c in clips)
