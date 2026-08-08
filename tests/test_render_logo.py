"""Знак в углу: геометрия, время и само появление.

ffmpeg тут не запускается — проверяется то, что считает Python: сколько кадров,
как растёт прозрачность, куда встаёт знак и не вылезает ли он за кадр. Сборка
ролика проверяется приёмкой готового файла, а не тестом.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from tools import render_logo as rl

ROOT = Path(__file__).resolve().parents[1]
FRAME = (1920, 1080)


@pytest.fixture(scope='module')
def logo():
    return rl.load_logo(rl.HEIGHT)


def test_знак_нужной_высоты_и_пропорций(logo):
    pre, al = logo
    assert al.shape[0] == rl.HEIGHT
    src = ROOT / 'assets' / 'Images' / 'logo_raymoon.png'
    from PIL import Image
    w, h = Image.open(src).size
    assert al.shape[1] == round(rl.HEIGHT * w / h)


def test_знак_помещается_в_угол_кадра(logo):
    _, al = logo
    h, w = al.shape
    x = FRAME[0] - rl.MARGIN - w
    assert x > FRAME[0] // 2, 'знак должен остаться в правой половине'
    assert x + w + rl.MARGIN == FRAME[0]
    assert rl.MARGIN + h < FRAME[1] // 2, 'знак должен остаться в верхней половине'


def test_появление_укладывается_в_концовку():
    """Знак приходит на последний удар и не выходит за конец номера."""
    tl = json.loads((ROOT / 'scenario' / 'timeline.json').read_text(encoding='utf-8'))
    hit = next(e for e in tl['events'] if e['id'] == 'ice_final_impact')
    assert rl.START == pytest.approx(hit['t']), 'старт привязан к ice_final_impact'
    assert rl.START + rl.DUR == pytest.approx(tl['total_duration'])
    assert rl.HOLD + rl.FADE < rl.DUR, 'знак обязан успеть проявиться до конца'


def test_кадров_ровно_по_длительности(logo):
    pre, al = logo
    assert len(list(rl.frames(pre, al))) == int(round(rl.DUR * rl.FPS))


def test_прозрачность_растёт_и_доходит_до_знака(logo):
    pre, al = logo
    seq = list(rl.frames(pre, al))
    strength = np.array([f[:, :, 3].mean() for f in seq])

    assert strength[0] == 0.0, 'первый кадр после удара — пустой'
    growth = np.diff(strength[: int((rl.HOLD + rl.FADE) * rl.FPS)])
    assert (growth >= -1e-6).all(), 'проявление не должно мигать'

    ready = int((rl.HOLD + rl.FADE) * rl.FPS) + 1
    assert strength[ready:].std() < 0.05, 'после проявления знак стоит неподвижно'
    assert strength[-1] == pytest.approx(al.mean() * 255, rel=0.02), \
        'в конце должен стоять сам знак, а не его тень'


def test_наплыв_идёт_на_уменьшение(logo):
    """Знак приходит крупнее и садится в размер, а не наоборот.

    Меряется размах, а не площадь: во время проявления вся альфа умножена на
    неполную силу, и площадь выше любого порога получается меньше, хотя знак в
    этот момент крупнее. Порог поэтому берётся долей от максимума кадра.
    """
    pre, al = logo

    def spread(frame):
        a = frame[:, :, 3].astype(np.float32)
        ys, xs = np.nonzero(a > 0.5 * a.max())
        return xs.max() - xs.min(), ys.max() - ys.min()

    seq = list(rl.frames(pre, al))
    ew, eh = spread(seq[int((rl.HOLD + rl.FADE * 0.5) * rl.FPS)])
    lw, lh = spread(seq[-1])
    assert ew > lw and eh > lh, 'на входе знак должен быть крупнее'
    assert ew / lw < rl.ZOOM + 0.02, 'наплыв не должен быть больше заявленного'


def test_smoothstep_не_вылезает_за_ноль_и_единицу():
    x = np.linspace(-2.0, 3.0, 101)
    y = rl.smoothstep(x)
    assert y.min() == 0.0 and y.max() == 1.0
    assert (np.diff(y) >= 0).all()
