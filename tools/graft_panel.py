"""Врезка одной перерисованной панели в лист движений.

    python tools/graft_panel.py

Зачем отдельный инструмент. Лист копья переделывался дважды, и оба раза модель,
исправляя одну панель, ломала другую: то времена, то подписи, то каким концом
смотрит копьё. Целиком четыре панели она ровно не держит. Поэтому панель
заказывается ОДНА, отдельной картинкой без заголовка и подписей, а на место её
ставит этот скрипт: три остальные панели остаются байт в байт, терять нечего.

Заголовок, угол с пунктиром и подписи снизу берутся со старого листа — они верны,
и трогать их незачем. Меняется только фигура внутри панели.

Масштаб и положение НЕ подгоняются на глаз: у обеих картинок замеряются пол,
макушка и наконечник, и врезка считается из них. Иначе фигура вставала бы то
крупнее, то мельче соседних, а заметно это только когда лист уже собран.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "assets/sheets"
TEMP = SHEETS / "temp"

SHEET = SHEETS / "spear_down__45_98-47_63.png"
PATCH = TEMP / "ChatGPT Image Aug 10, 2026, 07_43_44 PM.png"

# Панель 2 листа 1491x1055. Числа сняты замером, а не на глаз: заголовок
# «2. ДЕРЖАТЬ 46.19» кончается на y=115, подписи начинаются с y=845.
PANEL = (352, 128, 690, 842)
# Пол панели: подошвы сапог соседних фигур.
FLOOR_Y = 828
# Рост фигуры в пикселях. У соседних стоящих фигур 580-595, и хотелось бы
# столько же. Нельзя: у этой доли наконечник поднят на 1.66 роста над полом —
# 273 см при росте 162, — а по высоте в панели всего 714 px. При росте 580
# наконечник влез бы в заголовок. Отсюда 415: фигура выходит меньше соседних
# примерно на четверть, зато силуэт правдивый.
#
# Старый лист решал это иначе — рисовал копьё короче, и силуэт выходил 198 см
# вместо 273. Для доли, которая целиком про «самый высокий силуэт», это хуже.
BODY_PX = 415
# Угол с пунктиром и надписью «90°» верен, его возвращаем поверх врезки. Рамка
# взята с запасом: переносятся не все пиксели, а только пунктир, дуга и цифры,
# по маске. Прямоугольником переносить нельзя — фон заплатки чуть светлее
# врезанного, и на листе проступал квадрат.
#
# Низ рамки на 552, а не ниже: с 555 начинается золотой кант старого мундира,
# и маска тянула его за собой — на листе оставался угловатый обрезок.
CALLOUT = (598, 125, 695, 552)


class GraftError(Exception):
    pass


@dataclass(frozen=True)
class Marks:
    tip_y: int        # верх наконечника
    head_y: int       # макушка
    floor_y: int      # подошвы
    shaft_x: int      # где древко по горизонтали

    @property
    def body(self) -> int:
        return self.floor_y - self.head_y


def measure(im: Image.Image) -> Marks:
    """Пол, макушка, наконечник и древко — по пикселям, а не по догадке.

    Пороги по яркости тут не работают, и это проверено на живой картинке: фон
    у панели сам тёмный, и «пол» ловился на нём же и на кромке кадра, а
    «волосы» — на золотом воротнике лезвия у самого верха.

    Поэтому фигура ищется как отличие от фона, а фон снимается с боковых полей
    построчно. Тело — там, где силуэт заметно шире древка.
    """
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    h, w = a.shape[:2]

    side = np.concatenate([a[:, :int(w * 0.12)], a[:, int(w * 0.88):]], axis=1)
    bg = np.median(side, axis=1)
    fig = np.abs(a - bg[:, None, :]).max(axis=2) > 20
    width = fig.sum(axis=1)

    body_rows = np.nonzero(width >= 90)[0]
    if not len(body_rows):
        raise GraftError("не нашёл фигуру: силуэт нигде не шире 90 px")
    head_y = int(body_rows[0])

    # Подошвы — первое сужение ниже тела. Ниже него силуэт снова расширяется,
    # но это уже светящийся круг на полу, а не фигура.
    narrow = [y for y in range(head_y, h) if width[y] < 30]
    floor_y = int(narrow[0]) if narrow else int(body_rows[-1])

    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    top = np.nonzero((lum[:head_y] > 170).sum(axis=1) > 0)[0]
    tip_y = int(top[0]) if len(top) else 0
    if not tip_y < head_y < floor_y:
        raise GraftError("приметы встали не по порядку: наконечник %d, макушка "
                         "%d, пол %d" % (tip_y, head_y, floor_y))

    shaft_x = int(np.argmax(fig[tip_y:floor_y].sum(axis=0)))
    return Marks(tip_y=tip_y, head_y=head_y, floor_y=floor_y, shaft_x=shaft_x)


def callout_mask(patch: Image.Image) -> Image.Image:
    """Маска угла: только пунктир, дуга и цифры, без фона вокруг них.

    Золото ищется по тому, что синий канал у него заметно ниже зелёного, а фон
    панели наоборот синий. Мундир фигуры темнее фона и в маску не попадает,
    поэтому обрезки старой фигуры за собой она не тянет.
    """
    a = np.asarray(patch.convert("RGB"), dtype=np.int16)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    gold = (a[..., 0] > 110) & (a[..., 1] > 85) & (a[..., 2] < a[..., 1] - 20)
    mask = Image.fromarray(((gold | (lum > 135)) * 255).astype(np.uint8), "L")
    # Расширяем на пиксель: у пунктира сглаженные края, без этого они рвутся.
    return mask.filter(ImageFilter.MaxFilter(3))


def graft(sheet_path: Path = SHEET, patch_path: Path = PATCH) -> Path:
    if not sheet_path.exists():
        raise GraftError("нет листа %s" % sheet_path)
    if not patch_path.exists():
        raise GraftError("нет панели %s" % patch_path)

    sheet = Image.open(sheet_path).convert("RGB")
    patch = Image.open(patch_path).convert("RGB")
    m = measure(patch)
    print("панель: наконечник y=%d, макушка y=%d, пол y=%d, древко x=%d, рост %d px"
          % (m.tip_y, m.head_y, m.floor_y, m.shaft_x, m.body))
    if m.body < 200:
        raise GraftError("рост фигуры вышел %d px — замер не сошёлся" % m.body)

    k = BODY_PX / m.body
    scaled = patch.resize((max(1, round(patch.width * k)),
                           max(1, round(patch.height * k))), Image.LANCZOS)
    # Древко ставим туда, где оно стояло у старой фигуры, пол — на пол панели.
    px = round((PANEL[0] + PANEL[2]) / 2 - 32 - m.shaft_x * k)
    py = round(FLOOR_Y - m.floor_y * k)
    tip_after = round(m.tip_y * k) + py
    print("масштаб %.4f, врезка в (%d, %d), наконечник встанет на y=%d"
          % (k, px, py, tip_after))
    if tip_after < PANEL[1]:
        raise GraftError("наконечник влезает в заголовок: y=%d при пределе %d. "
                         "Уменьши BODY_PX" % (tip_after, PANEL[1]))

    # Угол снимаем ДО врезки: он верен и должен уцелеть.
    callout = sheet.crop(CALLOUT)
    mask = callout_mask(callout)

    x0, y0, x1, y1 = PANEL
    win = scaled.crop((x0 - px, y0 - py, x1 - px, y1 - py))
    out = sheet.copy()
    out.paste(win, (x0, y0))
    out.paste(callout, (CALLOUT[0], CALLOUT[1]), mask)
    print("угол возвращён по маске: %d пикселей из %d"
          % (int(np.asarray(mask).astype(bool).sum()),
             callout.width * callout.height))
    out.save(sheet_path)
    print("лист перезаписан: %s" % sheet_path.relative_to(ROOT))
    return sheet_path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        graft()
    except GraftError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
