"""Нарезка листов движений на отдельные панели — вход для генерации видео.

    python tools/cut_panels.py

Лист целиком скармливать генератору нельзя: это сетка из трёх-пяти поз с
впечатанными заголовками, углами и подписями. Модель честно перерисует сетку и
попробует повторить текст. На вход нужна ОДНА поза на картинку.

Рамки заданы руками, по каждому листу отдельно. Автоматически их не найти:
у пяти листов пять разных раскладок (1x4, 3+2, 1x3), рамок между панелями
местами нет вовсе, а древко соседней позы заходит в чужую колонку. Числа сняты
с самих файлов; поменяется лист — править здесь.

Подписи из кадра убрать полностью нельзя, они лежат поверх фигуры. Поэтому
рамки выбраны так, чтобы захватить фигуру с древком и задеть как можно меньше
текста, а остальное закрывает запрет в промпте.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "assets/sheets"
OUT = SHEETS / "panels"

# Пределы приёмки картинок: Atlas требует сторону 300..6000 px и пропорции
# W/H от 0.4 до 2.5, OpenArt — сторону 300..6000. Узкая вертикальная вырезка
# фигуры даёт около 0.36 и не проходит, поэтому кадр добивается фоном.
MIN_SIDE = 300
MIN_RATIO = 0.50
MAX_RATIO = 2.00

# лист -> [(имя доли, время, x0, y0, x1, y1)]
PANELS: dict[str, list[tuple]] = {
    "burst_1__28_50-29_60": [
        ("windup",  "28.50",   35,  245,  345,  830),
        ("swing",   "28.88",  330,  245,  710,  790),
        ("contact", "29.14",  700,  245, 1155,  790),
        ("recover", "29.60",  1125, 240, 1430,  835),
    ],
    "burst_2__33_05-36_58": [
        ("windup",  "33.05",   18,  185,  300,  655),
        ("swing",   "33.45",  285,  185,  570,  650),
        ("contact", "34.00",  530,  300,  960,  680),
        # y0 ниже заголовка «4. ВОЗВРАТ 34.55», иначе он влезает в кадр
        ("recover", "34.55",   55,  800,  330, 1250),
        ("contact2", "36.58", 330,  880,  790, 1265),
    ],
    # Раскладка 3+3, единственный лист с шестью долями
    "burst_3__38_62-41_60": [
        ("hold",     "38.62",   38,  130,  352,  718),
        ("windup",   "39.20",  366,  130,  680,  718),
        ("swing",    "39.60",  686,  130, 1018,  718),
        ("contact",  "39.92",   38,  800,  352, 1400),
        ("contact2", "40.95",  366,  800,  680, 1400),
        ("recover",  "41.60",  686,  800, 1018, 1400),
    ],
    "take_the_hit__42_40-43_63": [
        # y не до самого низа: лист обведён светлой рамкой, и угол вырезки
        # попадал в неё — добивка получалась белой
        ("hold",    "42.40",   32,  155,  400,  915),
        ("contact", "42.83",  440,  155,  800,  915),
        ("hold2",   "43.13",  850,  155, 1150,  915),
        ("recover", "43.63", 1260,  155, 1560,  915),
    ],
    "burst_4__44_60-45_50": [
        ("swing",   "44.60",   35,  240,  460,  875),
        ("contact", "44.98",  455,  295, 1060,  880),
        ("recover", "45.50", 1055,  215, 1450,  895),
    ],
    # Лист перерисован 10 августа под починенную позу финала и приехал другого
    # размера: 1491x1055 вместо 1672x941. Рамки сняты заново, по сетке.
    "spear_down__45_98-47_63": [
        ("windup",  "45.98",   12,  140,  300,  838),
        # y0 ниже заголовка «2. ДЕРЖАТЬ 46.19»: кончик древка теряется, зато в
        # кадре нет текста
        ("hold",    "46.19",  350,  130,  610,  838),
        ("contact", "47.03",  700,  140,  940,  838),
        ("hold2",   "47.63", 1055,  140, 1290,  838),
    ],
}


class PanelError(Exception):
    pass


def background(im: Image.Image) -> tuple[int, int, int]:
    """Цвет фона — по углам САМОЙ панели, а не листа.

    По углам листа считать нельзя: у «приёма удара» лист обведён светлой рамкой,
    и добивка получалась белой. В кадре это читается как часть картинки, а не
    как поле, и генератор честно её повторит.

    Из четырёх углов берём САМЫЙ ТЁМНЫЙ, а не средний: фон у всех листов тёмный,
    а всё светлое по краям — это рамка или подпись. Ошибиться в тёмную сторону
    безопасно, в светлую — нет.
    """
    w, h = im.size
    pts = [(3, 3), (w - 4, 3), (3, h - 4), (w - 4, h - 4)]
    px = [im.getpixel(p)[:3] for p in pts]
    return min(px, key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])


def trim_gutters(im: Image.Image) -> Image.Image:
    """Срезать по краям светлые ОДНОТОННЫЕ полосы — разделители панелей.

    У «приёма удара» панели разделены широкими светлыми полями, и они попадали
    в вырезку. Признак поля — не яркость сама по себе, а яркость ПЛЮС
    однородность: вспышка удара тоже яркая, но она пёстрая, и её так не срезать.
    """
    g = im.convert("L")
    w, h = g.size
    px = g.load()

    def uniform_bright(vals) -> bool:
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        return mean > 120 and var < 400

    left, right, top, bottom = 0, w, 0, h
    while left < right - MIN_SIDE // 2 and uniform_bright([px[left, y] for y in range(h)]):
        left += 1
    while right > left + MIN_SIDE // 2 and uniform_bright([px[right - 1, y] for y in range(h)]):
        right -= 1
    while top < bottom - MIN_SIDE // 2 and uniform_bright([px[x, top] for x in range(w)]):
        top += 1
    while bottom > top + MIN_SIDE // 2 and uniform_bright([px[x, bottom - 1] for x in range(w)]):
        bottom -= 1
    return im.crop((left, top, right, bottom))


def pad(im: Image.Image, fill) -> Image.Image:
    """Добить кадр фоном до допустимых пропорций и минимальной стороны."""
    w, h = im.size
    tw, th = w, h
    if tw / th < MIN_RATIO:
        tw = int(round(th * MIN_RATIO))
    elif tw / th > MAX_RATIO:
        th = int(round(tw / MAX_RATIO))
    tw, th = max(tw, MIN_SIDE), max(th, MIN_SIDE)
    if (tw, th) == (w, h):
        return im
    out = Image.new("RGB", (tw, th), fill)
    out.paste(im, ((tw - w) // 2, (th - h) // 2))
    return out


def cut(stem: str, boxes: list[tuple]) -> list[Path]:
    src = SHEETS / (stem + ".png")
    if not src.exists():
        raise PanelError("нет листа %s" % src.relative_to(ROOT))
    im = Image.open(src).convert("RGB")
    fill = background(im)
    strike = stem.split("__")[0]
    made = []
    for i, (role, when, x0, y0, x1, y1) in enumerate(boxes, 1):
        if not (0 <= x0 < x1 <= im.width and 0 <= y0 < y1 <= im.height):
            raise PanelError("%s: рамка %d,%d,%d,%d вне листа %dx%d"
                             % (stem, x0, y0, x1, y1, im.width, im.height))
        panel = trim_gutters(im.crop((x0, y0, x1, y1)))
        panel = pad(panel, background(panel))
        name = "%s__%d_%s__%s.png" % (strike, i, role, when.replace(".", "_"))
        out = OUT / name
        panel.save(out)
        made.append(out)
        print("   %-42s %4dx%-4d  %.2f" %
              (name, panel.width, panel.height, panel.width / panel.height))
    return made


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    total = 0
    for stem, boxes in PANELS.items():
        print("%s:" % stem)
        try:
            total += len(cut(stem, boxes))
        except PanelError as e:
            print("   ПРОПУСК: %s" % e)
        print()
    missing = sorted({p.stem.split("__")[0] for p in SHEETS.glob("*.png")}
                     ^ {s.split("__")[0] for s in PANELS})
    print("панелей нарезано: %d, в %s" % (total, OUT.relative_to(ROOT)))
    if missing:
        print("листов без рамок: %s" % ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
