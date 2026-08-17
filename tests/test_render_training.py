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
