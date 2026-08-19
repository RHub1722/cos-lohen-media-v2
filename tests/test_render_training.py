"""Сборка тренажёра целиком. Дешёвый тест, который ловит самое дорогое:
разъехавшийся шаблон и данные, которые не доехали до страницы.

Данные собираются один раз на весь модуль: сборка замеряет пики двадцати трёх
ассетов через FFmpeg, и на каждый тест это шестнадцать секунд.
"""

import re
import subprocess

import pytest

from src.render_training import (MARKER, NUMBER_VIDEO, ROOT, SITE_DIR,
                                 SITE_VIDEO, SOUNDTRACK, build_payload, render)
from src.soundcheck import match_windows


@pytest.fixture(scope="module")
def payload():
    return build_payload(NUMBER_VIDEO)


def test_payload_carries_everything_the_page_reads(payload):
    assert payload["total"] == 60.0
    assert payload["video"] == NUMBER_VIDEO
    assert [s["key"] for s in payload["scenes"]] == [
        "interrogation", "combat", "ice"]
    assert len(payload["movements"]) == 15
    assert len(payload["strikes"]) == 6
    assert len(payload["shots"]) == 10
    assert payload["lines"] and payload["hits"]


def test_the_lines_are_the_ones_he_will_hear(payload):
    """Номер звучит по-русски с 6 августа, а поле text в timeline.json осталось
    английским — по нему собраны титры. Тренажёр, показывающий английскую
    строку под русскую реплику, врёт в самом простом месте."""
    texts = {line["id"]: line["text"] for line in payload["lines"]}
    assert texts["lohen_final"].startswith("Они просили шедевр")
    assert texts["lohen_thatall"] == "Это всё, что у вас есть?"
    # Смех своей реплики не имеет: у него в сценарии русская ремарка.
    assert texts["lohen_laugh_2"].startswith("(смех")
    latin = [t for t in texts.values() if any("a" <= c.lower() <= "z" for c in t)]
    assert not latin, f"английский текст доехал до страницы: {latin}"


def test_the_page_plays_the_soundtrack_of_the_number():
    """Тот самый дефект, ради которого написан src/soundcheck.py.

    Тренажёр месяц играл августовскую сборку с английским голосом и нашими
    процедурными FX, пока номер уже звучал ручной фонограммой из монтажки.
    Разошлось молча — значит сторожить это должен тест, а не память.
    """
    video = ROOT / "output" / NUMBER_VIDEO
    if not video.exists() or not SOUNDTRACK.exists():
        pytest.skip(f"нет {video.name} или {SOUNDTRACK.name} — собрать нечем")
    worst = min(corr for _, corr in match_windows(video, SOUNDTRACK))
    assert worst > 0.90, (
        f"худшее окно {worst:.3f}: видео тренажёра играет не фонограмму номера")


def test_every_shot_says_what_is_on_screen(payload):
    """Пустое описание кадра — это карточка «на экране: —» на прогоне."""
    for shot in payload["shots"]:
        assert shot["screen"], shot["anchor"]
        assert shot["end"] > shot["t"]


def test_hits_are_sorted_and_land_inside_the_number(payload):
    times = [h["t"] for h in payload["hits"]]
    assert times == sorted(times)
    assert all(0 < t < 60 for t in times)
    assert len(times) == 8


def test_loop_windows_cover_their_own_beats(payload):
    for s in payload["strikes"]:
        low, high = s["loop"]
        for beat in s["beats"]:
            assert low <= beat["heard"] <= high, f"{s['id']}/{beat['role']}"


def test_the_published_copy_is_whole():
    """`site/` — единственное место, где производный файл лежит в репозитории, и
    лежит намеренно: иначе страницу не открыть с гита на планшете. Значит следить
    за его целостностью надо тестом, а не памятью."""
    index = SITE_DIR / "index.html"
    video = SITE_DIR / SITE_VIDEO
    assert index.exists(), "нет site/index.html: python src/render_training.py --site"
    assert video.exists(), f"нет site/{SITE_VIDEO}: страница откроет диалог выбора файла"
    html = index.read_text(encoding="utf-8")
    assert f'"video": "{SITE_VIDEO}"' in html
    # Запасной адрес нужен прокси, которые отдают mp4 как octet-stream: без него
    # на планшете вместо видео открывается диалог выбора файла.
    assert f'"video_fallback": "https://' in html
    megabytes = video.stat().st_size / 1024 / 1024
    assert megabytes < 12, (
        f"{megabytes:.1f} МБ — многовато и для репозитория, и для мобильной связи; "
        "поднимите crf в render_training.py")
    # Сжатая копия — единственное видео, которое реально открывают с планшета.
    # Пережатие не имеет права подменить фонограмму, и проверяется это здесь.
    if SOUNDTRACK.exists():
        worst = min(corr for _, corr in match_windows(video, SOUNDTRACK))
        assert worst > 0.90, (
            f"худшее окно {worst:.3f}: site/{SITE_VIDEO} играет не фонограмму номера")


def test_the_payload_carries_the_seven_training_clips(payload):
    clips = payload["clips"]
    assert len(clips) == 7
    assert {c["id"] for c in clips} == {"burst_1", "burst_2", "burst_3a",
                                       "burst_3b", "take_the_hit", "burst_4",
                                       "spear_down"}
    for clip in clips:
        assert clip["file"] == "clips/%s.mp4" % clip["id"]
        assert clip["poster"] == "clips/%s.webp" % clip["id"]
        assert clip["beats"], clip["id"]
        assert 3.0 < clip["slow"] < 6.0, clip["id"]
        assert clip["watch"] and clip["missing"], clip["id"]
        # Отметка доли внутри клипа: по паре (heard, at) пульт сопоставляет время
        # кусочно. Без `at` он молча вернулся бы к прямой.
        for beat in clip["beats"]:
            assert isinstance(beat["at"], (int, float)), (clip["id"], beat["role"])
        marks = [b["at"] for b in clip["beats"]]
        assert marks == sorted(marks) and marks[0] == 0.0, clip["id"]
        assert marks[-1] <= clip["duration"], clip["id"]


def test_every_published_clip_lies_next_to_the_page(payload):
    """Клип отдаётся тем же Pages, что и страница, поэтому лежать он должен
    рядом с ней, а не в assets/train_clips/: та папка не версионируется, там же
    лежат отклонённые попытки, и по мобильной связи её нет вовсе."""
    for clip in payload["clips"]:
        video = SITE_DIR / clip["file"]
        poster = SITE_DIR / clip["poster"]
        assert video.exists(), (
            "нет %s: python src/render_training.py --site" % clip["file"])
        assert poster.exists(), (
            "нет постера %s — при preload=none карточка будет чёрной"
            % clip["poster"])


def test_the_page_knows_the_frame_size_before_anything_loads(payload):
    """Пропорции кадра снимаются с самого файла и уезжают в данные. Без них при
    preload="none" семь карточек прыгают, когда догружаются постеры."""
    for clip in payload["clips"]:
        assert clip["w"] > 0 and clip["h"] > 0, clip["id"]
        assert 1.5 < clip["w"] / clip["h"] < 2.0, clip["id"]


def test_no_published_clip_brings_its_own_sound(payload):
    """Репетируют под фонограмму номера, которая играет в плеере слева. Клип со
    своей дорожкой перебивал бы её ровно в тот момент, когда сверяют попадание."""
    for clip in payload["clips"]:
        streams = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(SITE_DIR / clip["file"])],
            capture_output=True, text=True).stdout.split()
        assert streams == ["video"], "%s: %s" % (clip["id"], streams)


def test_the_published_clips_stay_light_enough_for_mobile(payload):
    """Их семь, и открывают их с телефона на площадке. Предел взят с запасом к
    нынешним 9.7 МБ: перегенерируем в 720p — и тест скажет об этом раньше, чем
    страница перестанет открываться."""
    weight = sum((SITE_DIR / c["file"]).stat().st_size
                 + (SITE_DIR / c["poster"]).stat().st_size
                 for c in payload["clips"])
    megabytes = weight / 1024 / 1024
    assert megabytes < 14, (
        "%.1f МБ на семь клипов — многовато для мобильной связи" % megabytes)


def test_every_tab_of_the_page_has_a_section_to_show():
    """Вкладка без раздела открывает пустой экран, и заметить это можно только
    щёлкнув по ней. Виды объявлены в шаблоне списком, разделы — разметкой, и
    сойтись они обязаны."""
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    block = html.split("const VIEWS = [")[1].split("];")[0]
    names = re.findall(r'\["(\w+)", "', block)
    assert names == ["run", "pult", "fight", "clips", "moves", "grip", "how"]
    for name in names:
        assert 'id="view-%s"' % name in html, name
        # id раздела не равен имени вида намеренно: имя уезжает в хеш адреса, и
        # браузер прокрутил бы страницу к элементу с тем же id поверх showView.
        assert 'id="%s"' % name not in html, name


def test_the_windows_of_the_strikes_do_not_overlap(payload):
    """Окно приёма — от слышимого времени первой доли клипа до последней. Вид
    «Пульт» выбирает по ним, какой приём идёт сейчас, и если два окна налезут
    друг на друга, слот начнёт мигать между двумя клипами на каждом кадре."""
    windows = sorted(((c["beats"][0]["heard"], c["beats"][-1]["heard"], c["id"])
                      for c in payload["clips"]))
    for (start, end, cid) in windows:
        assert 0 < start < end < payload["total"], cid
    for (a_start, a_end, a_id), (b_start, b_end, b_id) in zip(windows, windows[1:]):
        assert a_end <= b_start, "окна %s и %s налезают" % (a_id, b_id)


def test_the_clips_reach_the_page_in_the_order_of_the_number(payload):
    """Вид «Пульт» сортирует окна сам, но если в данных порядок сбился, значит
    сбился он и в сценарии клипов — а там по нему читают глазами."""
    starts = [c["beats"][0]["heard"] for c in payload["clips"]]
    assert starts == sorted(starts)


def test_no_clip_asks_the_browser_for_an_impossible_speed(payload):
    """Слот «сейчас» ведётся темпом: playbackRate = темп номера × замедление
    клипа. Предел в браузере — 16, и выше он зажимает темп МОЛЧА: синхронизация
    выродится в перемотку каждые 0.15 с, и никто об этом не узнает."""
    for clip in payload["clips"]:
        assert 1.0 < clip["slow"] <= 16.0, (clip["id"], clip["slow"])


def test_only_the_second_contact_of_burst_2_has_no_clip(payload):
    """Дыра, о которой вид «Пульт» обязан сказать вслух: контакт в 36.58 не
    покрыт ни одним клипом — burst_2 показывает четыре доли из пяти. Тест
    сторожит и обратное: если однажды покрытие изменится, подпись на странице
    станет ложной, и заметить это будет негде."""
    windows = [(c["beats"][0]["heard"], c["beats"][-1]["heard"])
               for c in payload["clips"]]
    uncovered = [round(h["t"], 2) for h in payload["hits"]
                 if not any(start <= h["t"] <= end for start, end in windows)]
    assert uncovered == [36.58]


def test_render_leaves_no_marker_and_closes_no_script():
    """`</` внутри данных оборвал бы <script> посреди JSON."""
    html = render({"total": 60.0, "video": "v.mp4", "note": "</script>"})
    assert MARKER not in html
    assert "<\\/script>" in html
    tail = html.split("const DATA = ")[-1]
    assert not tail.startswith("{\"total\": 60.0, \"video\": \"v.mp4\", \"note\": \"</")


def test_the_page_offers_all_three_cue_tracks(payload):
    """Три дорожки различаются устройством, а не громкостью: счёт в правое ухо,
    счёт в оба, и только риз без счёта. Список берётся из самой сборки, чтобы
    страница не просила файл, которого нет."""
    assert [t["key"] for t in payload["count"]] == ["right", "stereo", "riser"]
    for track in payload["count"]:
        assert track["file"] == "count_%s.m4a" % track["key"]
        assert track["name"] and track["hint"], track["key"]


def test_every_cue_track_is_published_next_to_the_page(payload):
    weight = 0.0
    for track in payload["count"]:
        path = SITE_DIR / track["file"]
        assert path.exists(), (
            "нет site/%s: python src/render_count.py --site" % track["file"])
        weight += path.stat().st_size / 1024 / 1024
    assert weight < 4.0, (
        "%.1f МБ на три дорожки — многовато для мобильной связи" % weight)


def test_the_page_carries_the_track_switch():
    """Переключатель обязан быть и в разметке, и в скрипте: кнопки без
    обработчика выглядят рабочими и не делают ничего."""
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    assert 'id="countAudio"' in html
    assert 'id="countBtns"' in html
    assert "countBtns" in html.split("const VIEWS")[1]


def test_switching_tracks_does_not_throw_away_the_previous_one():
    """У каждой дорожки свой <audio>, и переключение их не выгружает.

    С одним элементом на всех возврат к уже слышанной дорожке заново тянул её
    из сети и вставал на буферизацию — на планшете это читалось как «тормозит».
    Прошлая дорожка обязана только ставиться на паузу.
    """
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    # Граница — обращение к контейнеру кнопок: внутри самой setCount его нет,
    # там только селектор "#countBtns .btn".
    start = html.index("function setCount(")
    body = html[start:html.index('$("countBtns")', start)]
    assert "countPlayer(countKey)" in body, "элемент дорожки не берётся из кэша"
    assert "prev.pause()" in body, "прошлая дорожка должна ставиться на паузу"
    assert "countPlayers.set" in html, "элементы дорожек не запоминаются"


def test_the_player_is_started_from_inside_the_tap():
    """Планшет разрешает автозапуск только изнутри касания.

    Прежде play() звался из обработчика загрузки — это уже другая задача, жест
    потерян, элемент оставался на паузе, и покадровая синхронизация начинала
    звать play() шестьдесят раз в секунду. На компьютере автозапуск разрешён,
    поэтому там этой ветки не существует вовсе — отсюда «на планшете тормозит,
    на компьютере нет».
    """
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    start = html.index("function setCount(")
    body = html[start:html.index('$("countBtns")', start)]
    assert "tryPlay(a)" in body, "запуск не зовётся из обработчика нажатия"
    # play() обязан стоять ДО ожидания загрузки, иначе жест уже потерян.
    assert body.index("tryPlay(a)") < body.index("addEventListener")


def test_the_sync_retries_playback_on_a_backoff_not_every_frame():
    """Отказ автозапуска — не повод звать play() на каждом кадре: шестьдесят
    отказов в секунду, и каждый создаёт обещание. Отсюда и брался разрыв
    кадров на планшете."""
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    start = html.index("function syncCount(")
    body = html[start:html.index("function setCount(", start)]
    assert "COUNT_PLAY_EVERY" in body
    assert body.index("COUNT_PLAY_EVERY") < body.index("tryPlay(a)")


def test_the_diagnostics_count_what_the_guards_suppress():
    """Иначе после починки нельзя узнать, что именно срабатывало.

    Подтормаживание не воспроизводится ни на компьютере, ни в сборке — значит
    мерить должен сам планшет, и придержанные события обязаны считаться
    отдельно от случившихся.
    """
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    for counter in ("playHeld", "fixHeld", "playFails", "maxDrift",
                    "stallAudio", "stallVideo", "worstFrame", "worstWork"):
        assert "diag." + counter in html, counter
    assert 'id="diag"' in html
    assert "diag=1" in html


def test_the_sync_never_seeks_on_an_unready_or_seeking_track():
    """Тот самый источник тормозов.

    syncCount зовётся каждый кадр. Пока дорожка буферизуется, её currentTime
    стоит, а время видео идёт — расхождение не сходится, и правка срывалась в
    перемотку сжатого потока шестьдесят раз в секунду. Нужны два предохранителя:
    не трогать неготовую или уже перематывающуюся дорожку, и не править чаще
    заданного интервала.

    Порог готовности именно 3, а не 2: на двойке поток как раз голодает —
    данные на сейчас есть, а на дальше нет, — и правка добивала бы его.
    """
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    start = html.index("function syncCount(")
    body = html[start:html.index("function setCount(", start)]
    assert "a.readyState < 3" in body
    assert "a.seeking" in body
    assert "COUNT_FIX_EVERY" in body
    # Правка обязана стоять ПОСЛЕ обеих проверок, иначе они бесполезны.
    assert body.index("a.readyState < 3") < body.index("a.currentTime = video")
    assert body.index("COUNT_FIX_EVERY") < body.index("a.currentTime = video")


def test_the_loop_takes_a_breath_between_rounds():
    """Без паузы круг склеивается со следующим, и на слух непонятно, где он
    начался: звук идёт непрерывно, а картинка прыгает на кадр, который глазом
    не поймать. Пауза обязана быть и в объявлении, и в самом покадровом цикле —
    иначе прыжок случится раньше, чем она сработает."""
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    assert "const LOOP_GAP = 500;" in html
    assert "function restartLoop()" in html
    body = html.split("function frame(")[1].split("requestAnimationFrame")[0]
    assert "loopPause" in body, "покадровый цикл не знает про паузу"
    assert "restartLoop()" in body
    assert "seek(loopWin[0]" not in body, "прыжок в обход паузы"


def test_the_count_track_is_kept_in_step_every_frame():
    """Дорожка ведётся часами видео, как клип приёма в виде «Пульт». Без вызова
    в покадровом цикле она разъедется с картинкой, и репетиция пойдёт по
    неверным цифрам."""
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    body = html.split("function frame(")[1].split("requestAnimationFrame")[0]
    assert "syncCount()" in body
