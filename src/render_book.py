"""Книжка движений: одна страница на планшет и одна на печать.

    python src/render_book.py        # site/book.html, docs/spear-book.md, site/figures/

Содержание собирается ОДИН раз в виде блоков, и уже блоки раскладываются в HTML
и в markdown. Написать две вёрстки по одним данным значит однажды поправить одну
и забыть вторую — а книжка и так третий документ про один и тот же бой.

Времена и позы приходят из scenario/strikes.json, названия приёмов и ссылки —
из scenario/technique.json, рисунки считает src/figures.py. Своих чисел у этого
модуля нет ни одного.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src import figures  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.strikes import ROLE_NAMES, load_strikes, resolve_strikes  # noqa: E402
from src.technique import Book, check_against_strikes, load  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/book_template.html"
SITE = ROOT / "site"
FIGURES = SITE / "figures"
HTML_OUT = SITE / "book.html"
OUT_HTML = ROOT / "output/book.html"
MD_OUT = ROOT / "docs/spear-book.md"
TOC_MARK = "<!--__TOC__-->"
BODY_MARK = "<!--__BODY__-->"


# --- блоки: единственное представление содержания -------------------------
def h2(text, anchor):
    return ("h2", text, anchor)


def h3(text):
    return ("h3", text)


def p(text):
    return ("p", text)


def warn(text):
    return ("warn", text)


def note(text):
    return ("note", text)


def ul(items):
    return ("ul", list(items))


def table(head, rows):
    return ("table", list(head), [list(r) for r in rows])


def strip(items):
    """items: (имя файла svg, разметка svg, подпись, время или пусто)"""
    return ("strip", list(items))


def plan(name, svg, caption):
    return ("plan", name, svg, caption)


def videos(items):
    return ("videos", list(items))


def kv(pairs):
    return ("kv", list(pairs))


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _rich(text: str) -> str:
    """Полужирный по **звёздочкам** — единственная разметка внутри текста."""
    out, bold = [], False
    for part in _esc(text).split("**"):
        out.append(part if not bold else "")
        if bold:
            out[-1] = "<b>%s</b>" % part
        bold = not bold
    return "".join(out)


# --- сборка содержания ----------------------------------------------------
def build(book: Book, strikes, tl: Timeline, moves) -> list:
    blocks: list = []
    by_id = {s.id: s for s in strikes}

    # 0 -------------------------------------------------------------------
    blocks.append(h2("Как пользоваться", "how"))
    blocks.append(p(
        "Тренажёр отвечает на вопрос **когда**: он играет номер и показывает, в "
        "какой момент что происходит. Эта книжка отвечает на вопрос **как**. Её "
        "читают без видео — на ковре, дома, с распечаткой."))
    blocks.append(ul([
        "**Рисунки посчитаны из чисел**, а не нарисованы от руки. Поменяется поза "
        "в сценарии — перерисуется и картинка, разойтись с текстом рядом она не может.",
        "**Жёлтая стрелка** — куда идёт кисть. **Голубая** — куда идёт наконечник. "
        "**Красная** — куда идёт таз, она появляется только когда таз реально едет.",
        "**Пунктирный силуэт** — следующая доля: где ты окажешься.",
        "**Время под кадром** — момент, когда звук СЛЫШНО, а не когда начинается "
        "файл. У быстрого взмаха разница треть секунды.",
        "**На плане площадки сверху:** голубая точка — ты, овалы — стопы (тёмный "
        "задняя, светлый передняя), красный крест — противник, жёлтая дуга — куда "
        "идёт наконечник. Низ картинки — зал.",
    ]))
    blocks.append(note(
        "Это черновая сборка: все рисунки — векторные схемы. Они точны по позе, "
        "но это не персонаж. Следующим шагом часть кадров заменяется рисованным "
        "Лоэном, и схемы останутся под ним."))

    # 1 -------------------------------------------------------------------
    blocks.append(h2("Бой целиком", "fight"))
    rows = []
    for s in strikes:
        first, last = s.beats[0].heard, s.beats[-1].heard
        uses = book.strikes.get(s.id, {}).get("uses", [])
        names = ", ".join(book.technique(u).name.split(" — ")[0] for u in uses) or "—"
        rows.append(["%.2f — %.2f" % (first, last), s.title, names,
                     "%d" % len(s.beats)])
    blocks.append(table(["время", "действие", "приёмы", "долей"], rows))
    blocks.append(p(
        "Между действиями остаются паузы, и их суммарно больше, чем всех ударов "
        "вместе. Что в них делать — в разделе «Развороты и переходы»."))

    # 2 -------------------------------------------------------------------
    blocks.append(h2("База: пять приёмов", "base"))
    blocks.append(p(
        "Весь бой собран из пяти вещей. Выучить пять приёмов один раз дешевле, "
        "чем шесть движений по отдельности: приём переносится, движение — нет."))
    for t in book.techniques:
        blocks.append(h3("%s %s" % (t.name, t.glyph)))
        blocks.append(p("**Что это.** %s" % t.what))
        blocks.append(p("**Тело.** %s" % t.body))
        blocks.append(p("**Хват.** %s" % t.grip))
        blocks.append(warn("**Ошибка.** %s" % t.mistake))
        blocks.append(p("**Упражнение.** %s" % t.drill))
        blocks.append(videos(t.videos))

    # 3 -------------------------------------------------------------------
    blocks.append(h2("Что ты уже умеешь", "skills"))
    blocks.append(p(
        "Разбор записей 5 августа, палка 1.5 м. Начинать надо с того, что есть."))
    for sk in book.skills:
        blocks.append(h3(sk.name))
        blocks.append(p("**Как.** %s" % sk.how))
        blocks.append(p("**Куда идёт в номере.** %s" % sk.where))
        blocks.append(p("**Что поправить.** %s" % sk.fix))
        blocks.append(note("Видно на записи: %s" % sk.seen))
    if book.problem:
        blocks.append(h3("Общая проблема, и она измерена"))
        blocks.append(p("**%s**" % book.problem.get("what", "")))
        blocks.append(p(book.problem.get("measured", "")))
        blocks.append(warn(book.problem.get("why", "")))
        blocks.append(p(book.problem.get("conclusion", "")))
    if book.hips:
        blocks.append(h3("Бёдра"))
        blocks.append(p(book.hips.get("what", "")))
        blocks.append(p(book.hips.get("means", "")))
        blocks.append(note(book.hips.get("caveat", "")))

    # 4 -------------------------------------------------------------------
    blocks.append(h2("Шесть действий по долям", "strikes"))
    for s in strikes:
        entry = book.strikes.get(s.id, {})
        blocks.append(h3(s.title))
        uses = entry.get("uses", [])
        if uses:
            blocks.append(p("**Приёмы:** " + ", ".join(
                "%s %s" % (book.technique(u).name, book.technique(u).glyph)
                for u in uses)))
        blocks.append(p(entry.get("how", "")))
        cells = []
        svgs = figures.strip(list(s.beats and [
            {"pose": b.pose, "role": b.role} for b in s.beats]))
        for beat, svg in zip(s.beats, svgs):
            name = "%s-%s-%.2f" % (s.id, beat.role, beat.heard)
            cells.append((name.replace(".", "_"), svg,
                          ROLE_NAMES.get(beat.role, beat.role),
                          "%.2f" % beat.heard))
        blocks.append(strip(cells))
        for beat in s.beats:
            blocks.append(p("**%s, %.2f.** %s" % (
                ROLE_NAMES.get(beat.role, beat.role), beat.heard, beat.what)))
        if s.floor:
            blocks.append(plan("floor-%s" % s.id, figures.floor_plan(s.floor),
                               s.floor.get("step", "")))
            if s.floor.get("note"):
                blocks.append(note(s.floor["note"]))
        if s.mistakes:
            blocks.append(warn("**Ошибки.** " + " ".join(s.mistakes)))
        if s.drill:
            blocks.append(ul(s.drill))

    # 5 -------------------------------------------------------------------
    blocks.append(h2("Развороты и переходы", "pauses"))
    blocks.append(p(
        "То, что между ударами. Сейчас там пусто, а времени больше, чем на все "
        "удары вместе."))
    rows = []
    for pause in book.pauses:
        rows.append(["%.2f — %.2f" % (pause.start, pause.end),
                     "%.2f с" % pause.length, pause.now,
                     book.skill(pause.put).name])
    blocks.append(table(["окно", "сколько", "что сейчас", "что ставим"], rows))
    for pause in book.pauses:
        blocks.append(h3("%.2f — %.2f, %.2f секунды"
                         % (pause.start, pause.end, pause.length)))
        blocks.append(p("**Ставим:** %s" % book.skill(pause.put).name))
        blocks.append(p(pause.why))

    fin = book.finale
    if fin:
        blocks.append(h3("Перекрут в концовке"))
        blocks.append(p("**Окно %.2f — %.2f, это %.2f секунды.** %s"
                        % (fin["from"], fin["to"], fin["to"] - fin["from"],
                           fin.get("how", ""))))
        blocks.append(p("**Сколько оборотов:** %s" % fin.get("turns", "")))
        blocks.append(p(fin.get("math", "")))
        blocks.append(p("**Почему именно сюда.** %s" % fin.get("why_here", "")))
        blocks.append(warn("**Чем платим.** %s" % fin.get("cost", "")))
        blocks.append(p("**Что это чинит.** %s" % fin.get("fixes", "")))
        if fin.get("replaces_note"):
            blocks.append(note(fin["replaces_note"]))

    # 6 -------------------------------------------------------------------
    blocks.append(h2("Реквизит: что померить", "prop"))
    prop = book.prop
    blocks.append(kv([
        ("рост исполнителя", "%.2f м" % prop.get("performer_height_m", 0)),
        ("копьё", "%.2f м" % prop.get("spear_m", 0)),
        ("тренировочная палка", "%.2f м" % prop.get("practice_staff_m", 0)),
        ("копьё в ростах", "%.2f" % prop.get("spear_in_heights", 0)),
        ("канон ушу для этого роста", "%.1f м" % prop.get("wushu_canon_m", 0)),
    ]))
    blocks.append(p(prop.get("comment", "")))
    blocks.append(warn(
        "Ниже — то, чего мы не знаем. Пока эти четыре числа не померены, кусок с "
        "перекрутами стоит на оценке, а не на факте."))
    for item in prop.get("measure", []):
        value = item.get("value")
        blocks.append(p("**%s** — %s\n\n%s" % (
            item["what"],
            "%s" % value if value is not None else "НЕ ПОМЕРЕНО",
            item["why"])))

    # 7 -------------------------------------------------------------------
    blocks.append(h2("Порядок репетиции", "order"))
    blocks.append(ul([
        "**Лань-на-чжа, сто повторов на четверти скорости.** Это база копья "
        "целиком. Одна выученная связка убирает «махание палкой» из всех четырёх "
        "вспышек сразу.",
        "**42.80, приём удара.** Самое ценное место номера и самое дешёвое по "
        "силам: голова, пауза, смех. Репетировать чаще всего остального.",
        "**47.03, копьё в пол.** Тишины перед ударом в фонограмме больше нет, "
        "время держишь счётом от верхней точки замаха. Плюс копьё обязано стоять само.",
        "**Четыре вспышки по порядку**, каждая по четырём ступеням тренажёра.",
        "**Перекруты в паузы** — последними, когда удары уже встали в тело. "
        "И только в разведённой стойке, 1.1–1.5 ширины плеча.",
    ]))
    blocks.append(videos(book.stage.get("videos", [])))
    return blocks


# --- раскладка в HTML -----------------------------------------------------
def to_html(blocks) -> tuple[str, str]:
    out, toc = [], []
    for block in blocks:
        kind = block[0]
        if kind == "h2":
            if out:
                out.append("</section>")
            out.append('<section id="%s"><h2>%s</h2>' % (block[2], _esc(block[1])))
            toc.append('<a href="#%s">%s</a>' % (block[2], _esc(block[1])))
        elif kind == "h3":
            out.append("<h3>%s</h3>" % _rich(block[1]))
        elif kind == "p":
            out.append("<p>%s</p>" % _rich(block[1]).replace("\n\n", "<br>"))
        elif kind == "warn":
            out.append('<p class="warn">%s</p>' % _rich(block[1]))
        elif kind == "note":
            out.append('<p class="note">%s</p>' % _rich(block[1]))
        elif kind == "ul":
            out.append("<ul>%s</ul>" % "".join(
                "<li>%s</li>" % _rich(i) for i in block[1]))
        elif kind == "table":
            head = "".join("<th>%s</th>" % _esc(h) for h in block[1])
            body = "".join("<tr>%s</tr>" % "".join(
                '<td class="num">%s</td>' % _rich(c) if j == 0
                else "<td>%s</td>" % _rich(c)
                for j, c in enumerate(row)) for row in block[2])
            out.append("<table><tr>%s</tr>%s</table>" % (head, body))
        elif kind == "strip":
            cells = []
            for _, svg, caption, when in block[1]:
                stamp = ('<div class="t">%s</div>' % _esc(when)) if when else ""
                cells.append("<figure>%s<figcaption>%s%s</figcaption></figure>"
                             % (svg, stamp, _esc(caption)))
            out.append('<div class="strip">%s</div>' % "".join(cells))
        elif kind == "plan":
            out.append('<div class="plan">%s</div>' % block[2])
            if block[3]:
                out.append('<p class="note">%s</p>' % _rich(block[3]))
        elif kind == "videos":
            for v in block[1]:
                out.append(
                    '<div class="vid"><a href="%s" target="_blank" rel="noopener">%s</a>'
                    '<div class="meta">Смотреть: %s · <span class="slow">×%.2g</span>'
                    ' — %s</div></div>'
                    % (_esc(v.url), _esc(v.title), _esc(v.watch), v.slow, _esc(v.why)))
        elif kind == "kv":
            out.append('<dl class="kv">%s</dl>' % "".join(
                "<dt>%s</dt><dd>%s</dd>" % (_esc(k), _esc(val))
                for k, val in block[1]))
    if out:
        out.append("</section>")
    return "".join(out), '<nav class="toc">%s</nav>' % "".join(toc)


# --- раскладка в markdown -------------------------------------------------
def to_md(blocks, figure_dir: str) -> str:
    out = ["# Книжка движений копья — Лоэн", "",
           "Собрано `python src/render_book.py`. Руками не править: времена и позы "
           "приходят из `scenario/strikes.json`, названия и ссылки — из "
           "`scenario/technique.json`.", ""]
    for block in blocks:
        kind = block[0]
        if kind == "h2":
            out += ["", "## %s" % block[1], ""]
        elif kind == "h3":
            out += ["", "### %s" % block[1], ""]
        elif kind == "p":
            out += [block[1], ""]
        elif kind == "warn":
            out += ["> **!** %s" % block[1].replace("\n", " "), ""]
        elif kind == "note":
            out += ["> %s" % block[1].replace("\n", " "), ""]
        elif kind == "ul":
            out += ["- %s" % i for i in block[1]] + [""]
        elif kind == "table":
            out += ["| %s |" % " | ".join(block[1]),
                    "|%s|" % "|".join("---" for _ in block[1])]
            out += ["| %s |" % " | ".join(str(c) for c in row) for row in block[2]]
            out += [""]
        elif kind == "strip":
            for name, _, caption, when in block[1]:
                label = ("%s, %s" % (caption, when)) if when else caption
                out.append("![%s](%s/%s.svg)" % (label, figure_dir, name))
            out += [""]
        elif kind == "plan":
            out += ["![план площадки](%s/%s.svg)" % (figure_dir, block[1]), ""]
            if block[3]:
                out += ["> %s" % block[3], ""]
        elif kind == "videos":
            for v in block[1]:
                out.append("- [%s](%s) — смотреть: %s, скорость ×%.2g. %s"
                           % (v.title, v.url, v.watch, v.slow, v.why))
            out += [""]
        elif kind == "kv":
            out += ["| | |", "|---|---|"]
            out += ["| %s | %s |" % (k, val) for k, val in block[1]]
            out += [""]
    return "\n".join(out) + "\n"


def write_figures(blocks) -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    count = 0
    for block in blocks:
        if block[0] == "strip":
            for name, svg, _, _ in block[1]:
                (FIGURES / ("%s.svg" % name)).write_text(
                    figures.standalone(svg), encoding="utf-8")
                count += 1
        elif block[0] == "plan":
            (FIGURES / ("%s.svg" % block[1])).write_text(
                figures.standalone(block[2]), encoding="utf-8")
            count += 1
    return count


def main() -> int:
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    moves = resolve_times(load_movements(ROOT / "scenario/movements.json"), tl)
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    strikes = resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"), tl,
                              peaks, [m.id for m in moves])
    book = load(ROOT / "scenario/technique.json")
    check_against_strikes(book, strikes)

    blocks = build(book, strikes, tl, moves)
    body, toc = to_html(blocks)
    template = TEMPLATE.read_text(encoding="utf-8")
    for mark in (TOC_MARK, BODY_MARK):
        if mark not in template:
            raise SystemExit("в шаблоне нет маркера %s" % mark)
    html = template.replace(TOC_MARK, toc).replace(BODY_MARK, body)

    SITE.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html, encoding="utf-8")
    # Вторая копия рядом с тренажёром в output/: страница самодостаточна, все
    # рисунки вшиты, внешних файлов у неё нет. Без неё ссылка «Книжка» в
    # тренажёре, открытом из output/, вела бы в никуда.
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(to_md(blocks, "../site/figures"), encoding="utf-8")
    drawn = write_figures(blocks)

    print("Готово:")
    print("  %s  (%.0f КБ)" % (HTML_OUT.relative_to(ROOT),
                               HTML_OUT.stat().st_size / 1024))
    print("  %s  (%.0f КБ)" % (MD_OUT.relative_to(ROOT),
                               MD_OUT.stat().st_size / 1024))
    print("  %s  %d рисунков" % (FIGURES.relative_to(ROOT), drawn))
    print("  приёмов %d, навыков %d, пауз %d, действий %d"
          % (len(book.techniques), len(book.skills), len(book.pauses),
             len(strikes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
