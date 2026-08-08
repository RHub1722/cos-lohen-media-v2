"""Достать знак RaYMoon из листа генерации и снять с него нарисованную шахматку.

Исходник — лист Gemini с четырьмя вариантами знака. Нужен левый верхний:
полумесяц, луч и надпись. Выбор исполнителя.

    python tools/extract_logo.py

Пишет assets/Images/logo_raymoon.png — RGBA, готовый к наложению. Пересобирать
не нужно, файл версионируется; скрипт лежит рядом, чтобы решение можно было
повторить и оспорить.

ПОЧЕМУ НЕ ПРОСТО ОБРЕЗАТЬ. Прозрачности в листе нет: альфа-канал сплошь 255, а
«клетчатый фон» нарисован пикселями. Клетки к тому же неровные — рисовала
модель, а не программа: шаг гуляет от 18 до 24 пикселей, ряды не совпадают.
Подгонка сетки по этой причине проваливается (остаток 27 уровней из 255 при
шаге сетки 23.3), и вычесть фон формулой нельзя.

ЧЕМ ВЗЯТО. Знак — свечение на тёмном, и он ярче любой клетки: светлая клетка не
поднимается выше 120 из 255, буквы и луна держат 200 и выше. Поэтому альфа
берётся из яркости, с мягкой ступенью между этими двумя уровнями. Цвет остаётся
как есть: рисунок сделан «по чёрному» и поверх тёмного кадра ложится как свет.

ГДЕ ЭТО ЛОМАЕТСЯ. На луче. Он полупрозрачный, клетки сквозь него просвечивают,
и ключ по яркости превращает их в лесенку поперёк луча. Лечится вертикальным
сглаживанием, но только в тех строках, где кроме луча ничего нет — выше луны и
ниже надписи. Строки с луной и буквами не трогаются вообще, иначе размывается
край полумесяца и засечки букв.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d, uniform_filter1d

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'assets' / 'Images' / 'Gemini_Generated_Image_bugnxobugnxobugn.png'
DST = ROOT / 'assets' / 'Images' / 'logo_raymoon.png'

# Левый верхний знак с запасом: точные границы находятся по самой альфе.
QUADRANT = (0, 800, 250, 1180)          # y0, y1, x0, x1

KEY_LO = 118.0      # верх светлой клетки — ниже этого чистый фон
KEY_HI = 168.0      # выше этого знак в полную силу
CELL = 25           # клетка шахматки, px; окно сглаживания луча
BEAM_ROWS = 110     # верхние строки, по которым находится столбец луча
BEAM_PAD = 10
SOLID = 0.5         # альфа, выше которой строка считается занятой луной/буквами
PAD = 12            # поля вокруг знака в готовом файле


def key_alpha(lum: np.ndarray) -> np.ndarray:
    """Альфа из яркости: мягкая ступень между уровнем клетки и уровнем знака."""
    t = np.clip((lum - KEY_LO) / (KEY_HI - KEY_LO), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def beam_band(alpha: np.ndarray) -> tuple[int, int]:
    """Столбцы луча — по строкам выше луны, где кроме него ничего нет."""
    cols = np.nonzero(alpha[:BEAM_ROWS].max(0) > 0.05)[0]
    return int(cols.min()) - BEAM_PAD, int(cols.max()) + BEAM_PAD + 1


def repair_weight(alpha: np.ndarray, left: int, right: int) -> np.ndarray:
    """Вес лечения: полоса луча по горизонтали, «только луч» по вертикали."""
    outside = alpha.copy()
    outside[:, left:right] = 0.0
    rows = gaussian_filter1d((outside.max(1) < SOLID).astype(np.float32), 5.0)
    cols = np.zeros(alpha.shape[1], dtype=np.float32)
    cols[left:right] = 1.0
    return rows[:, None] * gaussian_filter1d(cols, 6.0)[None, :]


def calm(x: np.ndarray) -> np.ndarray:
    """Среднее в клетку гасит саму лесенку, размытие — стык между окнами."""
    y = uniform_filter1d(x, CELL, axis=0, mode='nearest')
    return gaussian_filter1d(y, 6.0, axis=0, mode='nearest')


def main() -> int:
    if not SRC.exists():
        print('нет исходника: %s' % SRC, file=sys.stderr)
        return 1

    y0, y1, x0, x1 = QUADRANT
    box = np.asarray(Image.open(SRC).convert('RGB')).astype(np.float32)[y0:y1, x0:x1]
    lum = 0.2126 * box[:, :, 0] + 0.7152 * box[:, :, 1] + 0.0722 * box[:, :, 2]

    alpha = key_alpha(lum)
    left, right = beam_band(alpha)
    w = repair_weight(alpha, left, right)

    before = alpha.copy()
    alpha = alpha * (1 - w) + calm(alpha) * w
    rgb = box.copy()
    for c in range(3):
        rgb[:, :, c] = rgb[:, :, c] * (1 - w) + calm(rgb[:, :, c]) * w

    ys, xs = np.nonzero(alpha > 0.03)
    ty0 = max(0, int(ys.min()) - PAD)
    ty1 = min(alpha.shape[0], int(ys.max()) + 1 + PAD)
    tx0 = max(0, int(xs.min()) - PAD)
    tx1 = min(alpha.shape[1], int(xs.max()) + 1 + PAD)
    rgb, alpha, before = rgb[ty0:ty1, tx0:tx1], alpha[ty0:ty1, tx0:tx1], before[ty0:ty1, tx0:tx1]

    prof_b, prof_a = before[:, left:right].max(1), alpha[:, left:right].max(1)
    tail = slice(int(0.8 * len(prof_a)), None)
    print('знак %dx%d, в координатах листа x %d..%d y %d..%d'
          % (tx1 - tx0, ty1 - ty0, x0 + tx0, x0 + tx1, y0 + ty0, y0 + ty1))
    print('лечится %.1f%% пикселей, полоса луча %d..%d'
          % (100 * (w > 0.5).mean(), left, right))
    print('лесенка в хвосте луча: было %.4f, стало %.4f'
          % (float(np.abs(np.diff(prof_b[tail])).mean()),
             float(np.abs(np.diff(prof_a[tail])).mean())))
    print('непрозрачных пикселей %.1f%%, полупрозрачных %.1f%%'
          % (100 * (alpha > 0.9).mean(), 100 * ((alpha > 0.03) & (alpha <= 0.9)).mean()))

    out = np.dstack([np.clip(rgb, 0, 255), alpha * 255.0]).astype(np.uint8)
    Image.fromarray(out, 'RGBA').save(DST)
    print('записано %s' % DST.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
