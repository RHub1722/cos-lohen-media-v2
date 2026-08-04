"""Сборка тренажёра целиком. Дешёвый тест, который ловит самое дорогое:
разъехавшийся шаблон и данные, которые не доехали до страницы.

Данные собираются один раз на весь модуль: сборка замеряет пики двадцати трёх
ассетов через FFmpeg, и на каждый тест это шестнадцать секунд.
"""

import pytest

from src.render_training import MARKER, build_payload, render


@pytest.fixture(scope="module")
def payload():
    return build_payload("final_v2.mp4")


def test_payload_carries_everything_the_page_reads(payload):
    assert payload["total"] == 60.0
    assert payload["video"] == "final_v2.mp4"
    assert [s["key"] for s in payload["scenes"]] == [
        "interrogation", "combat", "ice"]
    assert len(payload["movements"]) == 15
    assert len(payload["strikes"]) == 6
    assert len(payload["shots"]) == 10
    assert payload["lines"] and payload["hits"]


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


def test_render_leaves_no_marker_and_closes_no_script():
    """`</` внутри данных оборвал бы <script> посреди JSON."""
    html = render({"total": 60.0, "video": "v.mp4", "note": "</script>"})
    assert MARKER not in html
    assert "<\\/script>" in html
    tail = html.split("const DATA = ")[-1]
    assert not tail.startswith("{\"total\": 60.0, \"video\": \"v.mp4\", \"note\": \"</")
