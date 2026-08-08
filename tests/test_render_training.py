"""Сборка тренажёра целиком. Дешёвый тест, который ловит самое дорогое:
разъехавшийся шаблон и данные, которые не доехали до страницы.

Данные собираются один раз на весь модуль: сборка замеряет пики двадцати трёх
ассетов через FFmpeg, и на каждый тест это шестнадцать секунд.
"""

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


def test_render_leaves_no_marker_and_closes_no_script():
    """`</` внутри данных оборвал бы <script> посреди JSON."""
    html = render({"total": 60.0, "video": "v.mp4", "note": "</script>"})
    assert MARKER not in html
    assert "<\\/script>" in html
    tail = html.split("const DATA = ")[-1]
    assert not tail.startswith("{\"total\": 60.0, \"video\": \"v.mp4\", \"note\": \"</")
