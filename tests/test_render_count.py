"""Сборка дорожки счёта. Дорогое здесь — FFmpeg, поэтому нарезка и сведение
проверяются на уже собранных файлах, а не пересобираются под каждый тест."""

import subprocess

import numpy as np
import pytest

from src.counting import STEP, WORDS
from src.render_count import (DUCK_DB, GAP, NUMERALS, OUT_DIR, SHEET,
                              SOUNDTRACK, TAKE, TRACKS, track_path)


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
    """Дорожка «в правое ухо»: на ней проверяется разделение каналов."""
    path = track_path("right")
    if not path.exists():
        pytest.skip("нет %s: python src/render_count.py" % path.name)
    return path


@pytest.fixture(scope="module")
def sheet_text():
    if not SHEET.exists():
        pytest.skip("нет %s: python src/render_count.py" % SHEET.name)
    return SHEET.read_text(encoding="utf-8")


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


def test_the_sheet_names_all_eight_contacts(sheet_text):
    for t in ("29.14", "34.00", "36.58", "39.92",
              "40.95", "42.83", "44.98", "47.03"):
        assert t in sheet_text, t


def test_the_sheet_confesses_the_three_collisions(sheet_text):
    """Цена выбранного темпа перечислена поимённо. Если однажды столкновений
    станет больше, лист обязан назвать и их — иначе исполнитель будет ждать
    цифру, которой не будет."""
    assert "делят одну цифру" in sheet_text
    for t in ("28.88", "43.13", "46.19"):
        assert t in sheet_text, t


def test_the_sheet_warns_that_one_digit_serves_two_strikes(sheet_text):
    assert "«девять»" in sheet_text and "«один»" in sheet_text
    assert "разных цикла" in sheet_text


def test_the_sheet_explains_the_anchor(sheet_text):
    assert "круглой пятёрке" in sheet_text


def test_there_are_three_tracks_and_they_differ_in_kind_not_in_volume():
    """Не три громкости одного и того же: одна с ризом без счёта вовсе, две со
    счётом, но в разные уши. Если различие сведётся к гейну, выбирать будет
    незачем."""
    assert [t["key"] for t in TRACKS] == ["right", "stereo", "riser"]
    assert [t["count"] for t in TRACKS] == [True, True, False]
    assert len({t["pan"] for t in TRACKS}) == 2


def test_the_riser_only_track_leaves_the_number_alone_between_risers():
    """Постоянные 9 dB существовали ради непрерывного счёта. Без счёта ронять
    весь номер на минуту незачем — там провал только под ризом."""
    path = track_path("riser")
    if not path.exists() or not SOUNDTRACK.exists():
        pytest.skip("нет %s: python src/render_count.py" % path.name)
    for t0, t1 in ((10.0, 20.0), (30.0, 32.0)):
        left, _ = channels(path, t0, t1)
        ref, _ = channels(SOUNDTRACK, t0, t1)
        n = min(len(left), len(ref))
        got = 20 * np.log10(np.sqrt((left[:n] ** 2).mean())
                            / np.sqrt((ref[:n] ** 2).mean()))
        assert got == pytest.approx(0.0, abs=0.15), (t0, got)


def test_the_riser_duck_lets_go_by_the_moment_of_impact():
    """Риз кончается В контакт. Приглушить сам контакт значило бы убрать тот
    звук, под который надо попасть, — поэтому провал обязан отпустить.

    Меряется ниже 200 Гц: там у номера 63% энергии окна, а у риза почти ничего,
    так что изменение в этой полосе — это провал, а не сам риз.

    Окно взято у копья в пол (45.83 → 47.03). Раньше здесь стояла вспышка 4, но
    у неё риза больше нет вовсе: он снят полем `riser: false` в сценарии,
    потому что у встречного удара нет замаха и объявлять нечего.
    """
    path = track_path("riser")
    if not path.exists() or not SOUNDTRACK.exists():
        pytest.skip("нет %s: python src/render_count.py" % path.name)

    def low_db(src, t0, t1):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", "%.4f" % t0,
             "-t", "%.4f" % (t1 - t0), "-i", str(src), "-ac", "1",
             "-ar", "16000", "-af", "lowpass=f=200", "-f", "f32le", "-"],
            capture_output=True).stdout
        x = np.frombuffer(raw, dtype=np.float32)
        return 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-12)

    under = low_db(path, 46.2, 46.9) - low_db(SOUNDTRACK, 46.2, 46.9)
    at_hit = low_db(path, 47.03, 47.19) - low_db(SOUNDTRACK, 47.03, 47.19)
    assert under < -4.0, "под ризом провала нет: %+.2f dB" % under
    assert at_hit > -2.5, "провал не отпустил к удару: %+.2f dB" % at_hit


def test_the_number_is_untouched_where_the_riser_was_removed():
    """Снятый риз обязан снять и провал под собой. Иначе номер на 43.8–45.0 так
    и уходил бы вниз без всякой причины — тише, и ничего взамен."""
    path = track_path("riser")
    if not path.exists() or not SOUNDTRACK.exists():
        pytest.skip("нет %s: python src/render_count.py" % path.name)
    left, _ = channels(path, 43.78, 45.05)
    ref, _ = channels(SOUNDTRACK, 43.78, 45.05)
    n = min(len(left), len(ref))
    got = 20 * np.log10(np.sqrt((left[:n] ** 2).mean())
                        / np.sqrt((ref[:n] ** 2).mean()))
    assert got == pytest.approx(0.0, abs=0.15), (
        "в окне снятого риза номер тронут на %+.2f dB" % got)


def test_the_fight_clip_does_not_cut_off_the_last_strike():
    """Ролик боя режется НЕ по границе сцены.

    Сцена «Лёд» начинается в 47.00, а последний контакт боя — копьё в пол —
    стоит в 47.03, то есть на три сотых ПОЗЖЕ. Резать по сцене значило бы
    обрубить последний удар номера, поэтому конец считается от последней доли.
    """
    import json

    from src.models import Timeline
    from src.movements import load_movements, resolve_times
    from src.peaks import peak_offsets
    from src.render_count import OFFLINE_TAIL, ROOT, fight_window
    from src.render_rehearsal import build_scenes
    from src.strikes import load_strikes, resolve_strikes

    scenario = ROOT / "scenario/timeline.json"
    tl = Timeline.load(scenario)
    with open(scenario, encoding="utf-8") as fh:
        raw = json.load(fh)
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    strikes = resolve_strikes(
        load_strikes(ROOT / "scenario/strikes.json"), tl, peaks, moves)

    start, end = fight_window(strikes, tl, raw["events"])
    scenes = {s["key"]: s for s in build_scenes(raw["events"], tl.total_duration)}
    assert start == pytest.approx(scenes["combat"]["t"])

    beats = [b.heard for s in strikes for b in s.beats]
    assert end > max(beats), "последняя доля боя не влезла в окно"
    assert end == pytest.approx(max(beats) + OFFLINE_TAIL, abs=0.01)
    # Именно та ловушка: конец сцены раньше последнего удара.
    assert scenes["combat"]["end"] < max(beats), (
        "сцена перестала кончаться раньше последней доли — проверка потеряла смысл")
    # И всё, что он бьёт, обязано быть внутри.
    contacts = [b.heard for s in strikes for b in s.beats if b.role == "contact"]
    assert all(start < t < end for t in contacts), contacts


def test_no_track_runs_out_of_headroom():
    """Ограничителя в сведении нет намеренно, значит запас проверяется замером.
    У дорожки без счёта номер не приглушён постоянно, и сумма с ризом однажды
    уже упёрлась в потолок — 0.00 dBTP."""
    for spec in TRACKS:
        path = track_path(spec["key"])
        if not path.exists():
            pytest.skip("нет %s: python src/render_count.py" % path.name)
        left, right = channels(path, 0.0, 60.0)
        peak = 20 * np.log10(max(np.abs(left).max(), np.abs(right).max()))
        assert peak < -1.0, "%s: %.2f dBTP" % (spec["key"], peak)


def test_every_contact_of_the_number_gets_a_riser():
    """Сторож против ровно той дыры, которую нашёл исполнитель на линейке.

    Ризы ставились по одному на ПРИЁМ, целясь в первый контакт, и вторые
    попадания вспышки 2 и вспышки 3 оставались без предупреждения вовсе. 36.58
    оказался единственным контактом номера, у которого нет ни риза, ни клипа.
    """
    from src.models import Timeline
    from src.movements import load_movements, resolve_times
    from src.peaks import peak_offsets
    from src.strikes import load_strikes, resolve_strikes
    from src.counting import risers
    from src.render_count import ROOT

    tl = Timeline.load(ROOT / "scenario/timeline.json")
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    strikes = resolve_strikes(
        load_strikes(ROOT / "scenario/strikes.json"), tl, peaks, moves)

    contacts = sorted(b.heard for s in strikes for b in s.beats
                      if b.role == "contact")
    # Исключения объявляются полем `riser: false` в сценарии, рядом с долей.
    # Сейчас такое одно — встречный удар вспышки 4 на 44.98, у него нет замаха,
    # и объявлять подготовку, которой не существует, значит врать о движении.
    skipped = sorted(b.heard for s in strikes for b in s.beats
                     if b.role == "contact" and not b.riser)
    want = [t for t in contacts if t not in skipped]
    peaks_of_risers = sorted(r["peak"] for r in risers(strikes))
    assert peaks_of_risers == pytest.approx(want), (
        "без риза остались: %s"
        % [t for t in want
           if not any(abs(t - p) < 0.01 for p in peaks_of_risers)])
    assert len(contacts) == 8
    assert skipped == pytest.approx([44.9757], abs=0.001), skipped
