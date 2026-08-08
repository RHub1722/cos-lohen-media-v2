"""Знак в углу: геометрия, время и сама прорисовка.

ffmpeg тут не запускается — проверяется то, что считает Python: сколько кадров,
в каком порядке появляются части знака, куда он встаёт и не вылезает ли за кадр.
Сборка ролика проверяется приёмкой готового файла, а не тестом.
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


@pytest.fixture(scope='module')
def seq(logo):
    return list(rl.frames(*logo))


def test_знак_нужной_высоты_и_пропорций(logo):
    _, al = logo
    assert al.shape[0] == rl.HEIGHT
    from PIL import Image
    w, h = Image.open(ROOT / 'assets' / 'Images' / 'logo_raymoon.png').size
    assert al.shape[1] == round(rl.HEIGHT * w / h)


def test_знак_помещается_в_угол_кадра(logo):
    _, al = logo
    h, w = al.shape
    x = FRAME[0] - rl.MARGIN - w
    assert x > FRAME[0] // 2, 'знак должен остаться в правой половине'
    assert x + w + rl.MARGIN == FRAME[0]
    assert rl.MARGIN + h < FRAME[1] // 2, 'знак должен остаться в верхней половине'


def test_ось_раскрытия_это_луч_а_не_середина(logo):
    """Ось ищется по нижнему хвосту: сверху её тянет влево рог полумесяца."""
    _, al = logo
    axis = rl.beam_column(al)
    top = al[:110].sum(0)
    from_top = float(np.arange(len(top)) @ top / top.sum())
    assert abs(axis - al.shape[1] / 2) < 6, 'луч проходит почти по середине знака'
    assert from_top < axis - 20, 'по верхним строкам замер обязан промахиваться'


def test_появление_укладывается_в_концовку():
    """Знак приходит на последний удар и не выходит за конец номера."""
    tl = json.loads((ROOT / 'scenario' / 'timeline.json').read_text(encoding='utf-8'))
    hit = next(e for e in tl['events'] if e['id'] == 'ice_final_impact')
    assert rl.START == pytest.approx(hit['t']), 'старт привязан к ice_final_impact'
    assert rl.START + rl.DUR == pytest.approx(tl['total_duration'])
    assert rl.CALM < rl.DUR, 'знак обязан успеть собраться до конца'
    assert rl.OPEN_FROM < rl.DRAW, 'раскрытие начинается, не дожидаясь конца прочерка'


def test_кадров_ровно_по_длительности(seq):
    assert len(seq) == int(round(rl.DUR * rl.FPS))


def test_сначала_луч_потом_остальное(seq, logo):
    """На первой трети прочерка знака ещё нет — только узкая вертикаль."""
    _, al = logo
    axis = rl.beam_column(al)
    early = seq[int(rl.DRAW * 0.35 * rl.FPS)][:, :, 3]
    cols = np.nonzero(early.max(0) > 20)[0]
    assert len(cols), 'луч должен быть виден с самого начала'
    assert cols.max() - cols.min() < 0.1 * al.shape[1], 'в начале это должна быть вертикаль'
    assert abs(0.5 * (cols.min() + cols.max()) - axis) < 4, 'вертикаль стоит на оси'

    drawn = np.nonzero(early.max(1) > 20)[0]
    assert drawn.min() == 0, 'луч чертится сверху'
    assert drawn.max() < 0.6 * al.shape[0], 'и до низа ещё не дошёл'


def test_луч_доходит_до_низа_к_концу_прочерка(seq, logo):
    _, al = logo
    f = seq[int(rl.DRAW * rl.FPS)][:, :, 3]
    drawn = np.nonzero(f.max(1) > 20)[0]
    assert drawn.max() >= al.shape[0] - 2


def test_раскрытие_идёт_наружу_и_не_мигает(seq, logo):
    """Ширина видимого растёт всё раскрытие и садится ровно по знаку.

    После раскрытия ширину мерить нельзя: блик уходит на 8% дальше края знака,
    и когда он гаснет, ширина законно уменьшается на эти проценты.
    """
    _, al = logo

    def width(a):
        c = np.nonzero(a.max(0) > 20)[0]
        return (c.max() - c.min()) if len(c) else 0

    w = np.array([width(f[:, :, 3]) for f in seq])
    top = int(np.argmax(w))
    assert (np.diff(w[:top + 1]) >= -1).all(), 'раскрытие не должно схлопываться'
    assert w[top] > w[0] * 3, 'знак обязан раскрыться шире прочерка'
    assert w[top] <= width(al * 255) * 1.10, 'блик уходит за край знака самую малость'
    assert abs(width(seq[-1][:, :, 3]) - width(al * 255)) <= 2, 'в конце ровно по знаку'


def test_в_конце_остаётся_сам_знак_без_служебного_луча(seq, logo):
    """После CALM альфа кадра должна совпасть с альфой ассета."""
    _, al = logo
    last = seq[-1][:, :, 3].astype(np.float32) / 255.0
    assert np.abs(last - al).max() < 0.01
    calm = seq[int(rl.CALM * rl.FPS) + 2][:, :, 3].astype(np.float32) / 255.0
    assert np.abs(calm - al).max() < 0.05


def test_smoothstep_не_вылезает_за_ноль_и_единицу():
    x = np.linspace(-2.0, 3.0, 101)
    y = rl.smoothstep(x)
    assert y.min() == 0.0 and y.max() == 1.0
    assert (np.diff(y) >= 0).all()
