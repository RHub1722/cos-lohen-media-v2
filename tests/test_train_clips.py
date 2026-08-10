"""Задания на тренировочные клипы: что проверяется до того, как за них платят."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import Timeline
from src.movements import load_movements, resolve_times
from src.peaks import peak_offsets
from src.strikes import load_strikes, resolve_strikes
from src.train_clips import CLIPS, DURATIONS, MAX_REFS, ClipError, load

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


def test_the_prompt_says_the_poses_carry_the_wrong_look(clips):
    """Панели идут на вход с неверной внешностью — это надо сказать прямо."""
    for clip in clips:
        assert "design is WRONG" in clip.prompt
        assert "ONLY for body position" in clip.prompt


def test_the_ban_names_the_look_that_went_wrong(clips):
    for clip in clips:
        assert "blond hair" in clip.negative


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
    raw["clips"][4]["beats"] = [1, 2, 3, 9]
    raw["clips"][4]["panels"].append(raw["clips"][4]["panels"][0])
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
    # Доли оставляем верными: предел на референсы обязан сработать раньше
    # любых проверок долей, иначе сообщение уведёт от настоящей причины.
    clip = raw["clips"][2]
    clip["panels"] = clip["panels"] + clip["panels"][:4]
    with pytest.raises(ClipError, match="не больше 9"):
        load(strikes, write(tmp_path, raw))


def test_the_look_reference_budget_counts_both_kinds(strikes, raw, tmp_path):
    """Восемь поз плюс два арта — это десять, и это уже перебор."""
    raw["character"]["refs"] = ["lohen_splash_art.png", "spear_full.png",
                               "lohen_spear_static.png", "lohen_rage.png"]
    clip = raw["clips"][2]
    with pytest.raises(ClipError, match="внешность 4"):
        load(strikes, write(tmp_path, raw))
    assert len(clip["panels"]) == 6


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
