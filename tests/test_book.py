"""Книжка движений: данные, рисунки и то, что MD и HTML не разошлись.

Книжка — третий документ про один и тот же бой, после сценария и тренажёра.
Расхождение между ними этот проект уже оплачивал, поэтому тут сторожит тест, а
не память.
"""

import re

import pytest

from src.figures import box, floor_plan, panel, standalone
from src.models import Timeline
from src.movements import load_movements, resolve_times
from src.peaks import peak_offsets
from src.render_book import ROOT, build, to_html, to_md
from src.strikes import load_strikes, resolve_strikes
from src.technique import TechniqueError, check_against_strikes, load


@pytest.fixture(scope="module")
def fight():
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    moves = resolve_times(load_movements(ROOT / "scenario/movements.json"), tl)
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    strikes = resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"), tl,
                              peaks, [m.id for m in moves])
    return tl, moves, strikes


@pytest.fixture(scope="module")
def book():
    return load(ROOT / "scenario/technique.json")


@pytest.fixture(scope="module")
def blocks(book, fight):
    tl, moves, strikes = fight
    return build(book, strikes, tl, moves)


def test_every_strike_is_named_by_a_technique(book, fight):
    """Книжка существует ровно ради этого: назвать то, что уже поставлено."""
    check_against_strikes(book, fight[2])
    for strike in fight[2]:
        entry = book.strikes[strike.id]
        assert entry.get("uses") or entry.get("how"), strike.id


def test_every_video_says_what_to_watch_and_how_slow(book):
    """Туториалы идут по разделениям, в номере на удар 0.26 с. Ссылка без
    указания куска и замедления бесполезна."""
    groups = [t.videos for t in book.techniques]
    groups += [book.spins.get("videos", ()), book.stage.get("videos", ())]
    seen = 0
    for videos in groups:
        for v in videos:
            assert v.watch.strip(), v.title
            assert 0.1 <= v.slow <= 1.0, (v.title, v.slow)
            assert v.why.strip(), v.title
            assert v.url.startswith("https://"), v.url
            seen += 1
    assert seen >= 10


def test_a_spin_may_never_cover_a_contact(book, fight):
    """Удар читается остановкой. Вращение поверх неё её сотрёт — и это тот
    случай, когда узнать надо здесь, а не на сцене."""
    windows = [(p.id, p.start, p.end) for p in book.pauses]
    windows.append(("finale", book.finale["from"], book.finale["to"]))
    for name, start, end in windows:
        for strike in fight[2]:
            for beat in strike.beats:
                if beat.role in ("contact", "swing"):
                    assert not (start < beat.heard < end), (
                        f"{name} накрывает {strike.id}/{beat.role} на {beat.heard}")


def test_the_finale_declares_the_beats_it_replaces(book, fight):
    """Перекрут в концовке встаёт на место замаха. Доля, тихо исчезнувшая из
    номера, обнаружилась бы только на репетиции."""
    declared = set(book.finale.get("replaces", []))
    assert declared, "концовка закрывает доли, но не говорит какие"
    start, end = book.finale["from"], book.finale["to"]
    covered = {f"{s.id}/{b.role}" for s in fight[2] for b in s.beats
               if start < b.heard < end}
    assert covered == declared


def test_the_finale_window_fits_at_least_one_turn(book):
    """1.15 с при 0.85–1.7 об/с — это от одного оборота. Сузится окно в
    сценарии, и число оборотов перестанет сходиться молча."""
    length = book.finale["to"] - book.finale["from"]
    assert length >= 1.0 / 1.7, f"{length:.2f} с — на оборот не хватит"


def test_markdown_and_html_carry_the_same_beats(blocks, fight):
    """Две вёрстки по одним данным. Правка одной и забытая вторая — ровно тот
    класс расхождения, ради которого блоки собираются один раз."""
    html, _ = to_html(blocks)
    md = to_md(blocks, "../site/figures")
    for strike in fight[2]:
        for beat in strike.beats:
            stamp = "%.2f" % beat.heard
            assert stamp in html, f"{strike.id}/{beat.role} потерян в HTML"
            assert stamp in md, f"{strike.id}/{beat.role} потерян в markdown"


def test_every_beat_has_a_figure(blocks, fight):
    beats = sum(len(s.beats) for s in fight[2])
    drawn = sum(len(b[1]) for b in blocks if b[0] == "strip")
    plans = sum(1 for b in blocks if b[0] == "plan")
    assert drawn == beats, f"{drawn} рисунков на {beats} долей"
    assert plans == len(fight[2])


def test_figures_are_valid_svg_and_stand_alone(fight):
    strike = fight[2][0]
    svg = panel(strike.beats[0].pose, strike.beats[1].pose)
    assert svg.startswith("<svg ") and svg.endswith("</svg>")
    assert 'viewBox="' in svg
    # Отдельным файлом SVG уезжает в markdown, а внутри плана площадки есть
    # русские подписи: без объявления кодировки браузер покажет мусор.
    assert standalone(floor_plan(strike.floor)).startswith("<?xml")
    assert 'encoding="utf-8"' in standalone(floor_plan(strike.floor))


def test_one_frame_for_the_whole_strike_so_panels_compare(fight):
    """У всех долей удара общая рамка. Иначе у каждой свой масштаб, и полоса,
    которая нужна ровно для сравнения, сравнивать перестаёт."""
    poses = [b.pose for b in fight[2][0].beats]
    whole = box(poses)
    for pose in poses:
        assert box([pose]) != whole or len(poses) == 1
    frames = {panel(p, None, frame=whole)[:60] for p in poses}
    assert all('viewBox="%.0f %.0f %.0f %.0f"' % whole in panel(p, None, frame=whole)
               for p in poses)
    assert frames


def test_the_figure_follows_the_numbers_not_a_drawing(fight):
    """Поднял древко в сценарии — поднялось и на картинке. Если это перестанет
    быть правдой, рисунки начнут учить не тому, что написано рядом."""
    pose = dict(fight[2][0].beats[0].pose)
    low = panel({**pose, "spear": 60.0})
    high = panel({**pose, "spear": -60.0})
    assert low != high

    def top(svg):
        return min(float(y) for _, y in
                   (m.groups() for m in re.finditer(r"(-?\d+\.\d),(-?\d+\.\d)", svg)))

    assert top(high) < top(low), "древко вверх должно поднимать содержимое кадра"


def test_the_book_page_is_whole():
    page = ROOT / "site/book.html"
    assert page.exists(), "нет site/book.html: python src/render_book.py"
    html = page.read_text(encoding="utf-8")
    for anchor in ("how", "fight", "base", "skills", "strikes", "pauses",
                   "prop", "order"):
        assert 'id="%s"' % anchor in html, anchor
    assert '<!--__BODY__-->' not in html and '<!--__TOC__-->' not in html
    assert 'href="index.html"' in html, "нет ссылки на тренажёр"


def test_the_trainer_links_back_to_the_book():
    for page in (ROOT / "site/index.html", ROOT / "output/training.html"):
        if not page.exists():
            continue
        html = page.read_text(encoding="utf-8")
        assert 'href="book.html"' in html, f"{page.name} не ведёт в книжку"
        assert (page.parent / "book.html").exists(), (
            f"рядом с {page.name} нет book.html — ссылка ведёт в никуда")


def test_a_pause_pointing_at_an_unknown_skill_is_loud(tmp_path):
    import json
    raw = json.loads((ROOT / "scenario/technique.json").read_text(encoding="utf-8"))
    raw["pauses"]["windows"][0]["put"] = "нет_такого_навыка"
    bad = tmp_path / "technique.json"
    bad.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TechniqueError):
        load(bad)
