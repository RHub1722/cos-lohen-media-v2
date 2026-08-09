"""Рисунки книжки: персонаж, стрелки и подписи, посчитанные из чисел позы.

Ни одного рисунка руками. Всё, что видно на странице, считается из полей `pose`
и `floor` в scenario/strikes.json, поэтому разойтись с текстом рядом рисунок не
может: поменяется поза в сценарии — перерисуется и он.

СТИЛЬ взят с образца, который принёс исполнитель: панель с сеткой, фигура по
центру, подписи с выносками по краям, две группы стрелок и двуязычная подпись
снизу. Разделение цветов оттуда же и оно смысловое, а не декоративное:

    ЖЁЛТАЯ стрелка  — что делает тело: поворот таза, вращение корпуса, присед.
    ГОЛУБАЯ стрелка — куда идёт сила: кисть, наконечник, направление удара.

Подписи двух родов. Механические — «кисть», «наконечник», «таз» — считаются из
разницы двух соседних поз и соврать не могут. Смысловые — «накопление энергии»,
«распределение веса» — написаны руками в scenario/technique.json и помечены в
книжке как постановка.

СИСТЕМА КООРДИНАТ. Внутри модуля всё в долях роста, начало на полу между
стопами, y вверх. В SVG y переворачивается один раз, функцией `_p`. Фигура потом
вписывается в панель одним `transform`, и вся арифметика кадрирования сидит в
`fit`, а не размазана по рисовалкам.

ЧТО ЗНАЧАТ ПОЛЯ ПОЗЫ (схема — в самом strikes.json):
    lean    наклон корпуса, градусы, плюс вправо
    crouch  0..1, насколько присел
    stance  0..1.4, разножка в ширинах плеча
    spear   угол древка: 0 горизонтально вправо, -90 вертикально вверх,
            +90 вниз, 180 влево
    hands   [x, y] — x поперёк тела, y в долях роста от пола
    grip    0..1, какая часть древка остаётся позади кистей
    head    наклон головы
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- пропорции тела, доли роста -------------------------------------------
SHOULDER_W = 0.17
HIP_W = 0.12
TORSO = 0.30
NECK = 0.045
# Шесть с половиной голов в росте вместо семи с половиной: это и есть разница
# между «человек» и «персонаж», и она же делает наклон головы читаемым.
HEAD_R = 0.078
LEG = 0.50
THIGH = 0.26
SHIN = 0.26
UPPER_ARM = 0.17
FOREARM = 0.17
FOOT = 0.10
HAND_X = 0.26
# Копьё 1.80 м при росте 1.62 — 1.11 роста. Замер реквизита, не оценка.
SPEAR_LEN = 1.11
BLADE = 0.19

SCALE = 132.0

# --- панель ----------------------------------------------------------------
PANEL_W, PANEL_H = 384.0, 336.0
CAPTION_H = 44.0
# Поля узкие: подпись ставится РЯДОМ со своей точкой, как на образце, а не у
# края с длинной выноской через весь кадр. Длинные выноски пробовал — они
# режут фигуру насквозь, и читать становится нечего.
MARGIN_X = 26.0
STAGE = (MARGIN_X, 26.0, PANEL_W - 2 * MARGIN_X, PANEL_H - CAPTION_H - 40.0)
GRID = 24.0
LABEL_SIZE = 12.5
LABEL_GAP = 15.5         # минимальный просвет между подписями по вертикали
MAX_LABELS = 5           # больше кадр не держит: наезжают друг на друга

# --- палитра, снята с образца ---------------------------------------------
BG_TOP = "#1e2b3c"
BG_BOTTOM = "#151d29"
GRID_C = "#2b3d52"
EDGE = "#3a5170"
SKIN = "#dfeaf7"
SKIN_DARK = "#93b6d6"
LIMB_BACK = "#7d9cbb"
DRESS = "#3f6fa2"
DRESS_DARK = "#2a4d75"
HAIR = "#a8d8f2"
HAIR_DARK = "#6ba7cd"
SHAFT = "#c3d2e2"
SHAFT_DARK = "#8fa3b8"
BLADE_C = "#a9ecff"
GOLD = "#ffc83d"          # тело: вращение, перенос веса
CYAN = "#69dcff"          # сила: кисть, наконечник, направление удара
LABEL = "#e8f4ff"
LABEL_DIM = "#9db6cf"
GHOST = "#5fd4ff"
IMPACT = "#bff2ff"


def _rad(d: float) -> float:
    return d * math.pi / 180.0


def _p(x: float, y: float) -> tuple[float, float]:
    """Доли роста -> внутренние пиксели. Единственное место с переворотом y."""
    return (x * SCALE, -y * SCALE)


def _fmt(pts) -> str:
    return " ".join("%.1f,%.1f" % _p(x, y) for x, y in pts)


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _mul(a, k):
    return (a[0] * k, a[1] * k)


def _norm(a):
    d = math.hypot(*a)
    return (a[0] / d, a[1] / d) if d > 1e-9 else (0.0, 0.0)


def two_bone(root, target, upper: float, lower: float, bend: float):
    """Локоть или колено. Не дотягивается — сустав выпрямляется."""
    delta = _sub(target, root)
    dist = math.hypot(*delta)
    if dist >= upper + lower - 1e-6:
        return _add(root, _mul(_norm(delta), upper))
    along = _norm(delta)
    cos_a = (upper * upper + dist * dist - lower * lower) / (2 * upper * dist)
    cos_a = max(-1.0, min(1.0, cos_a))
    off = upper * cos_a
    height = math.sqrt(max(0.0, upper * upper - off * off))
    perp = (-along[1] * bend, along[0] * bend)
    return _add(_add(root, _mul(along, off)), _mul(perp, height))


@dataclass(frozen=True)
class Skeleton:
    hip: tuple
    shoulder: tuple
    chest: tuple
    head: tuple
    feet: tuple
    knees: tuple
    hands: tuple
    elbows: tuple
    butt: tuple
    tip: tuple
    lean: float
    head_tilt: float
    crouch: float
    across: tuple            # единичный вектор поперёк корпуса


def build(pose: dict) -> Skeleton:
    lean = float(pose.get("lean", 0.0))
    crouch = max(0.0, min(1.0, float(pose.get("crouch", 0.0))))
    stance = max(0.0, float(pose.get("stance", 0.8)))
    spear_a = float(pose.get("spear", 0.0))
    hx, hy = pose.get("hands", [0.2, 0.6])
    grip = max(0.0, min(1.0, float(pose.get("grip", 0.35))))
    head_tilt = float(pose.get("head", 0.0))

    half = stance * 0.22 / 2.0
    # Разножка укорачивает ноги по вертикали — честно, теоремой Пифагора:
    # при широкой стойке разница заметная и её видно в кадре.
    upright = math.sqrt(max(0.04, LEG * LEG - half * half))
    hip = (0.0, upright * (1.0 - 0.30 * crouch))

    t = _rad(lean)
    up = (math.sin(t), math.cos(t))
    across = (math.cos(t), -math.sin(t))
    shoulder = _add(hip, _mul(up, TORSO))
    chest = _add(hip, _mul(up, TORSO * 0.62))
    ht = _rad(lean + head_tilt * 0.6)
    head = (shoulder[0] + (NECK + HEAD_R) * math.sin(ht),
            shoulder[1] + (NECK + HEAD_R) * math.cos(ht))

    feet = ((-half, 0.0), (half, 0.0))
    knees = (two_bone((hip[0] - HIP_W / 2, hip[1]), feet[0], THIGH, SHIN, -1.0),
             two_bone((hip[0] + HIP_W / 2, hip[1]), feet[1], THIGH, SHIN, +1.0))

    hand = (hx * HAND_X, float(hy))
    d = (math.cos(_rad(spear_a)), -math.sin(_rad(spear_a)))
    butt = _add(hand, _mul(d, -grip * SPEAR_LEN))
    tip = _add(hand, _mul(d, (1.0 - grip) * SPEAR_LEN))
    hand_back = _add(hand, _mul(d, -min(0.17, grip * SPEAR_LEN * 0.85)))

    sh_l = _sub(shoulder, _mul(across, SHOULDER_W / 2))
    sh_r = _add(shoulder, _mul(across, SHOULDER_W / 2))
    elbows = (two_bone(sh_l, hand_back, UPPER_ARM, FOREARM, -1.0),
              two_bone(sh_r, hand, UPPER_ARM, FOREARM, +1.0))

    return Skeleton(hip=hip, shoulder=shoulder, chest=chest, head=head, feet=feet,
                    knees=knees, hands=(hand_back, hand), elbows=elbows,
                    butt=butt, tip=tip, lean=lean, head_tilt=head_tilt,
                    crouch=crouch, across=across)


# --- рисование тела --------------------------------------------------------
def _taper(points, widths, fill: str, opacity: float = 1.0) -> str:
    """Конечность с переменной толщиной: у плеча толще, у кисти тоньше.

    Полилиния одной ширины даёт «палки» — то, из-за чего первый черновик и
    забраковали. Толщина здесь задаётся в каждой точке цепи, и контур строится
    по нормалям, поэтому рука сужается к запястью, а бедро к колену.
    """
    n = len(points)
    left, right = [], []
    for i, (pt, w) in enumerate(zip(points, widths)):
        if i == 0:
            d = _sub(points[1], points[0])
        elif i == n - 1:
            d = _sub(points[-1], points[-2])
        else:
            d = _sub(points[i + 1], points[i - 1])
        d = _norm(d)
        perp = (-d[1], d[0])
        left.append(_add(pt, _mul(perp, w)))
        right.append(_add(pt, _mul(perp, -w)))
    pts = left + list(reversed(right))
    caps = "".join('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>'
                   % (*_p(*pt), w * SCALE, fill)
                   for pt, w in ((points[0], widths[0]), (points[-1], widths[-1])))
    return ('<polygon points="%s" fill="%s" opacity="%.2f"/>%s'
            % (_fmt(pts), fill, opacity, caps))


def _torso(sk: Skeleton) -> str:
    """Корпус: плечи широкие, талия узкая, таз шире талии."""
    a = sk.across
    waist = _add(sk.hip, _mul(_sub(sk.chest, sk.hip), 0.55))
    pts = ([_add(sk.shoulder, _mul(a, SHOULDER_W * 0.52))] +
           [_add(sk.chest, _mul(a, SHOULDER_W * 0.46))] +
           [_add(waist, _mul(a, HIP_W * 0.42))] +
           [_add(sk.hip, _mul(a, HIP_W * 0.60))] +
           [_sub(sk.hip, _mul(a, HIP_W * 0.60))] +
           [_sub(waist, _mul(a, HIP_W * 0.42))] +
           [_sub(sk.chest, _mul(a, SHOULDER_W * 0.46))] +
           [_sub(sk.shoulder, _mul(a, SHOULDER_W * 0.52))])
    return ('<polygon points="%s" fill="%s"/>'
            '<polygon points="%s" fill="%s" opacity="0.55"/>'
            % (_fmt(pts), DRESS,
               _fmt(pts[4:] + pts[:1]), DRESS_DARK))


def _dress(sk: Skeleton, flow: tuple) -> str:
    """Подол: отстаёт от корпуса и от движения. Без этого фигура — доска."""
    sway = math.sin(_rad(sk.lean)) * 0.13 + flow[0] * 0.09
    hem = max(0.10, sk.hip[1] - 0.30 - sk.crouch * 0.04)
    a = sk.across
    l = _sub(sk.hip, _mul(a, HIP_W * 0.62))
    r = _add(sk.hip, _mul(a, HIP_W * 0.62))
    hl = (sk.hip[0] - HIP_W * 2.1 - sway, hem + 0.07)
    hr = (sk.hip[0] + HIP_W * 2.1 - sway, hem + 0.07)
    ml = (sk.hip[0] - HIP_W * 1.1 - sway, hem - 0.01)
    mr = (sk.hip[0] + HIP_W * 1.1 - sway, hem - 0.01)
    mid = (sk.hip[0] - sway * 0.6, hem + 0.06)
    return ('<path d="M %.1f %.1f L %.1f %.1f Q %.1f %.1f %.1f %.1f '
            'Q %.1f %.1f %.1f %.1f Q %.1f %.1f %.1f %.1f L %.1f %.1f Z" '
            'fill="%s"/>'
            % (*_p(*l), *_p(*hl), *_p(*ml), *_p(*mid),
               *_p(*mid), *_p(*mr), *_p(*mr), *_p(*hr), *_p(*r), DRESS))


def _cape(sk: Skeleton, flow: tuple) -> str:
    """Задняя пола, тянущаяся за движением. Даёт направление одним силуэтом."""
    back = -1.0 if flow[0] >= 0 else 1.0
    a = sk.across
    top = _add(sk.shoulder, _mul(a, SHOULDER_W * 0.38 * back))
    drag = 0.16 + abs(flow[0]) * 0.30
    mid = (top[0] + back * drag * 0.8, top[1] - 0.16)
    end = (top[0] + back * drag, sk.hip[1] - 0.22)
    near = _add(sk.hip, _mul(a, HIP_W * 0.5 * back))
    return ('<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f L %.1f %.1f Z" '
            'fill="%s" opacity="0.85"/>'
            % (*_p(*top), *_p(*mid), *_p(*end), *_p(*near), DRESS_DARK))


def _hair(sk: Skeleton, flow: tuple) -> str:
    """Длинные пряди, отстающие от движения. Читаются как скорость."""
    t = _rad(sk.lean + sk.head_tilt * 0.6)
    back = -1.0 if flow[0] >= 0 else 1.0
    out = []
    root = (sk.head[0] - math.cos(t) * HEAD_R * 0.35,
            sk.head[1] + math.sin(t) * HEAD_R * 0.35)
    for k, (length, spread, width) in enumerate(
            ((0.30, 0.02, 0.036), (0.24, -0.05, 0.028), (0.19, 0.07, 0.024))):
        drag = length * (0.45 + abs(flow[0]) * 0.9)
        mid = (root[0] + back * drag * 0.55, root[1] - length * 0.35 + spread)
        end = (root[0] + back * drag, root[1] - length + spread * 0.6)
        out.append(_taper([root, mid, end],
                          [width, width * 0.75, width * 0.28],
                          HAIR if k != 1 else HAIR_DARK))
    # Шапка волос поверх черепа: без неё голова читается как шар.
    cap = [(sk.head[0] + math.sin(t) * HEAD_R * 1.28,
            sk.head[1] + math.cos(t) * HEAD_R * 1.28),
           (sk.head[0] + math.cos(t) * HEAD_R * 1.0,
            sk.head[1] - math.sin(t) * HEAD_R * 1.0 + HEAD_R * 0.3),
           (root[0] + back * HEAD_R * 0.9, root[1] - HEAD_R * 0.2),
           (root[0] - back * HEAD_R * 0.2, root[1] + HEAD_R * 0.8)]
    out.append('<polygon points="%s" fill="%s"/>' % (_fmt(cap), HAIR))
    return "".join(out)


def _spear(sk: Skeleton) -> str:
    """Древко с обмоткой, листовидный наконечник, противовес на торце."""
    d = _norm(_sub(sk.tip, sk.butt))
    perp = (-d[1], d[0])
    neck = _sub(sk.tip, _mul(d, BLADE))
    mid = _sub(sk.tip, _mul(d, BLADE * 0.42))
    w = BLADE * 0.20
    blade = [sk.tip,
             _add(mid, _mul(perp, w)), _add(neck, _mul(perp, w * 0.42)),
             _sub(neck, _mul(perp, w * 0.42)), _sub(mid, _mul(perp, w))]
    tail = _add(sk.butt, _mul(d, 0.035))
    out = [_taper([sk.butt, neck], [0.017, 0.013], SHAFT),
           '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
           'stroke-width="1.6" opacity="0.7"/>' % (*_p(*sk.butt), *_p(*neck),
                                                   SHAFT_DARK),
           _taper([sk.butt, tail], [0.026, 0.022], SHAFT_DARK),
           '<polygon points="%s" fill="%s"/>' % (_fmt(blade), BLADE_C),
           '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#ffffff" '
           'stroke-width="1.4" opacity="0.85"/>' % (*_p(*neck), *_p(*sk.tip))]
    # Кисти поверх древка: хват — то, ради чего кадр и нужен.
    for h in sk.hands:
        out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>'
                   % (*_p(*h), 0.028 * SCALE, SKIN))
    return "".join(out)


def _trail(sk: Skeleton, prev: Skeleton | None) -> str:
    """След древка: где наконечник был мгновение назад.

    Рисуется только когда наконечник реально уехал. Дуга, а не прямая: копьё
    ходит по дуге, и прямая соврала бы о траектории.
    """
    if prev is None:
        return ""
    travel = math.dist(prev.tip, sk.tip)
    if travel < 0.18:
        return ""
    out = []
    for k, (frac, width, op) in enumerate(((0.30, 2.6, 0.42), (0.58, 1.9, 0.26),
                                           (0.80, 1.2, 0.15))):
        a = _add(prev.tip, _mul(_sub(sk.tip, prev.tip), frac))
        b = _add(prev.butt, _mul(_sub(sk.butt, prev.butt), frac))
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
                   'stroke-width="%.1f" opacity="%.2f" stroke-linecap="round"/>'
                   % (*_p(*a), *_p(*b), BLADE_C, width, op))
    return "".join(out)


def _impact(sk: Skeleton) -> str:
    """Вспышка в точке контакта. Ставится только на долю contact."""
    x, y = _p(*sk.tip)
    return ('<circle cx="%.1f" cy="%.1f" r="30" fill="%s" opacity="0.16"/>'
            '<circle cx="%.1f" cy="%.1f" r="17" fill="%s" opacity="0.30"/>'
            '<circle cx="%.1f" cy="%.1f" r="7" fill="#ffffff" opacity="0.75"/>'
            % (x, y, IMPACT, x, y, IMPACT, x, y))


def _flow(sk: Skeleton, nxt: Skeleton | None) -> tuple:
    """Куда идёт движение: по смещению кисти и наконечника. Им пляшут волосы."""
    if nxt is None:
        return (0.0, 0.0)
    d = _add(_mul(_sub(nxt.hands[1], sk.hands[1]), 0.6),
             _mul(_sub(nxt.tip, sk.tip), 0.4))
    return (max(-1.0, min(1.0, d[0] * 1.7)), max(-1.0, min(1.0, d[1] * 1.7)))


def figure(pose: dict, nxt: dict | None = None, prev: dict | None = None,
           impact: bool = False, ghost: bool = True) -> str:
    sk = build(pose)
    nx = build(nxt) if nxt else None
    pv = build(prev) if prev else None
    flow = _flow(sk, nx)
    out = []

    if ghost and nx:
        out.append('<g opacity="0.40" fill="none" stroke="%s" stroke-width="2.4" '
                   'stroke-dasharray="7 6" stroke-linecap="round" '
                   'stroke-linejoin="round">' % GHOST)
        out.append('<polyline points="%s"/>'
                   % _fmt([nx.feet[0], nx.knees[0], nx.hip, nx.knees[1], nx.feet[1]]))
        out.append('<polyline points="%s"/>' % _fmt([nx.hip, nx.shoulder]))
        out.append('<polyline points="%s"/>' % _fmt([nx.butt, nx.tip]))
        out.append('<circle cx="%.1f" cy="%.1f" r="%.1f"/>'
                   % (*_p(*nx.head), HEAD_R * SCALE))
        out.append('</g>')

    out.append(_trail(sk, pv))
    out.append(_cape(sk, flow))
    # Дальние конечности темнее: так три четверти читаются как глубина.
    out.append(_taper([sk.feet[0], sk.knees[0], (sk.hip[0] - HIP_W / 2, sk.hip[1])],
                      [0.030, 0.038, 0.052], LIMB_BACK))
    out.append(_taper([_sub(sk.shoulder, _mul(sk.across, SHOULDER_W / 2)),
                       sk.elbows[0], sk.hands[0]],
                      [0.040, 0.030, 0.021], LIMB_BACK))
    out.append(_dress(sk, flow))
    out.append(_taper([sk.feet[1], sk.knees[1], (sk.hip[0] + HIP_W / 2, sk.hip[1])],
                      [0.032, 0.042, 0.057], SKIN))
    out.append(_torso(sk))
    out.append(_hair(sk, flow))
    out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>'
               % (*_p(*sk.head), HEAD_R * SCALE, SKIN))
    out.append(_taper([_add(sk.shoulder, _mul(sk.across, SHOULDER_W / 2)),
                       sk.elbows[1], sk.hands[1]],
                      [0.043, 0.032, 0.022], SKIN))
    out.append(_spear(sk))
    for fx, fy in sk.feet:
        x0, y0 = _p(fx - FOOT / 2, fy)
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="6" rx="3" '
                   'fill="%s"/>' % (x0, y0 - 3, FOOT * SCALE, SKIN_DARK))
    if impact:
        out.append(_impact(sk))
    return "".join(out)


# --- кадрирование ----------------------------------------------------------
def content_box(poses) -> tuple[float, float, float, float]:
    """Рамка по ТЕЛУ, а не по всему кадру. Древку разрешено уходить за край.

    Считать рамку вместе с концами древка пробовал: у копья в пол оно ходит от
    вертикали вверх до вертикали вниз, объединённая рамка выходит в две с
    лишним высоты, и фигура в панели становится с ноготь. Тело же должно быть
    одного читаемого размера во всех кадрах удара — ради этого рамка и общая.

    В образце, который принёс исполнитель, древко тоже срезано краем кадра.
    """
    xs, ys = [], []
    pad = HEAD_R * 2.6 * SCALE
    for pose in poses:
        sk = build(pose)
        for pt in (sk.head, sk.hip, sk.shoulder, sk.chest, *sk.feet, *sk.knees,
                   *sk.hands, *sk.elbows,
                   (sk.hip[0], max(0.06, sk.hip[1] - 0.34))):
            x, y = _p(*pt)
            xs.append(x)
            ys.append(y)
    # Немного запаса вдоль древка, чтобы наконечник не отрезало вплотную к кисти.
    grow = 0.22 * SPEAR_LEN * SCALE
    return (min(xs) - pad - grow, min(ys) - pad - grow * 0.5,
            max(xs) - min(xs) + 2 * pad + 2 * grow,
            max(ys) - min(ys) + 2 * pad + grow)


def fit(cbox) -> tuple[float, float, float]:
    """Масштаб и сдвиг, вписывающие содержимое в сцену панели."""
    cx, cy, cw, ch = cbox
    sx, sy, sw, sh = STAGE
    k = min(sw / cw, sh / ch)
    return k, sx + (sw - cw * k) / 2 - cx * k, sy + (sh - ch * k) / 2 - cy * k


# --- подписи с выносками ---------------------------------------------------
ANCHORS = ("hand", "tip", "butt", "hip", "head", "shoulder", "foot", "knee")


def _anchor(sk: Skeleton, key: str) -> tuple:
    return {"hand": sk.hands[1], "tip": sk.tip, "butt": sk.butt, "hip": sk.hip,
            "head": sk.head, "shoulder": sk.shoulder, "foot": sk.feet[1],
            "knee": sk.knees[1]}.get(key, sk.hip)


def auto_labels(pose: dict, nxt: dict | None) -> list:
    """Механические подписи: что реально сдвинулось между двумя долями.

    Считаются, а не пишутся. Поэтому соврать не могут, и поэтому же их мало:
    числа знают, ЧТО поехало, но не знают, ЗАЧЕМ. «Зачем» пишется руками в
    technique.json и помечается в книжке отдельно.
    """
    if not nxt:
        return []
    a, b = build(pose), build(nxt)
    out = []
    if math.dist(a.hands[1], b.hands[1]) > 0.06:
        out.append(("кисть", "hand", CYAN))
    if math.dist(a.tip, b.tip) > 0.10:
        out.append(("наконечник", "tip", CYAN))
    if math.dist(a.hip, b.hip) > 0.045:
        out.append(("таз", "hip", GOLD))
    if abs(b.lean - a.lean) > 6.0:
        out.append(("вращение корпуса", "shoulder", GOLD))
    if abs(b.crouch - a.crouch) > 0.12:
        out.append(("присед" if b.crouch > a.crouch else "подъём", "knee", GOLD))
    if abs(float(nxt.get("head", 0)) - float(pose.get("head", 0))) > 8.0:
        out.append(("голова", "head", GOLD))
    return out


def place_labels(items, centre) -> list:
    """Разложить подписи вокруг фигуры, не давая им налезть друг на друга.

    Каждая уходит НАРУЖУ от центра фигуры — туда, где тела нет, — и потом
    раздвигается по вертикали, пока не перестанет задевать соседей. Порядок
    обхода от края к середине: у крайних точек свободы меньше, и место им
    достаётся первым.
    """
    out = []
    ordered = sorted(items, key=lambda it: -abs(it[2][0] - centre[0]))
    for text, colour, px in ordered:
        away = _norm((px[0] - centre[0], px[1] - centre[1] - 12.0))
        if abs(away[0]) < 0.25:
            away = (1.0 if px[0] >= centre[0] else -1.0, away[1] * 0.5)
        side = "right" if away[0] >= 0 else "left"
        width = len(text) * LABEL_SIZE * 0.50
        x = px[0] + away[0] * 30.0
        y = px[1] + away[1] * 22.0
        x = min(PANEL_W - 12.0 - (0.0 if side == "left" else 0.0),
                max(12.0 + (width if side == "left" else 0.0), x))
        if side == "left":
            x = max(12.0 + width, x)
        else:
            x = min(PANEL_W - 12.0 - width, x)
        y = min(PANEL_H - CAPTION_H - 12.0, max(20.0, y))
        for _, _, _, oy, ox, ow, oside in out:
            if oside != side:
                continue
            while abs(y - oy) < LABEL_GAP:
                y += LABEL_GAP if y >= oy else -LABEL_GAP
                y = min(PANEL_H - CAPTION_H - 12.0, max(20.0, y))
                if abs(y - oy) >= LABEL_GAP:
                    break
                y = oy + LABEL_GAP
        out.append((text, colour, px, y, x, width, side))
    return out


def _label(text: str, colour: str, anchor_px, x: float, y: float,
           side: str) -> str:
    """Подпись рядом со своей точкой и короткая выноска к ней."""
    align = "end" if side == "left" else "start"
    tip = (x - 4.0) if side == "left" else (x + 4.0)
    return ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="1.4" opacity="0.8"/>'
            '<circle cx="%.1f" cy="%.1f" r="2.8" fill="%s"/>'
            '<text x="%.1f" y="%.1f" fill="%s" font-size="%.1f" '
            'text-anchor="%s" font-family="Segoe UI, Roboto, sans-serif" '
            'paint-order="stroke" stroke="#111a26" stroke-width="3.4" '
            'stroke-linejoin="round">%s</text>'
            % (anchor_px[0], anchor_px[1], tip, y - 4, colour,
               anchor_px[0], anchor_px[1], colour,
               x, y, LABEL, LABEL_SIZE, align, _esc(text)))


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


# --- стрелки ---------------------------------------------------------------
def _arrow(a_px, b_px, colour: str, curve: float = 0.20, width: float = 3.4) -> str:
    ax, ay = a_px
    bx, by = b_px
    dx, dy = bx - ax, by - ay
    if math.hypot(dx, dy) < 12:
        return ""
    mx, my = (ax + bx) / 2 - dy * curve, (ay + by) / 2 + dx * curve
    tail = math.hypot(bx - mx, by - my) or 1.0
    ex, ey = bx - (bx - mx) / tail * 10, by - (by - my) / tail * 10
    ang = math.atan2(by - my, bx - mx)
    head = [(bx, by),
            (bx - 14 * math.cos(ang - 0.40), by - 14 * math.sin(ang - 0.40)),
            (bx - 14 * math.cos(ang + 0.40), by - 14 * math.sin(ang + 0.40))]
    pts = " ".join("%.1f,%.1f" % p for p in head)
    # Тёмная подложка под стрелкой: без неё голубая стрелка теряется на светлой
    # руке, а жёлтая — на подоле. Это тот же приём, что обводка у подписей.
    return ('<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f" fill="none" '
            'stroke="#111a26" stroke-width="%.1f" stroke-linecap="round" '
            'opacity="0.75"/>'
            '<polygon points="%s" fill="none" stroke="#111a26" stroke-width="3" '
            'stroke-linejoin="round" opacity="0.75"/>'
            '<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f" fill="none" stroke="%s" '
            'stroke-width="%.1f" stroke-linecap="round"/>'
            '<polygon points="%s" fill="%s"/>'
            % (ax, ay, mx, my, ex, ey, width + 3.0, pts,
               ax, ay, mx, my, ex, ey, colour, width, pts, colour))


# --- панель ----------------------------------------------------------------
def panel(pose: dict, nxt: dict | None = None, *, prev: dict | None = None,
          frame: tuple | None = None, index: int | None = None,
          title: str = "", title_en: str = "", when: str = "",
          extra_labels=(), impact: bool = False, ghost: bool = True) -> str:
    """Одна панель книжки: сетка, фигура, стрелки, подписи, номер и заголовок."""
    poses = [pose] + ([nxt] if nxt else [])
    cbox = frame or content_box(poses)
    k, tx, ty = fit(cbox)
    sk = build(pose)
    nx = build(nxt) if nxt else None

    def to_px(pt):
        """Точка в пикселях панели, зажатая в её границы.

        Наконечник при кадрировании по телу нередко уезжает за край. Стрелка и
        выноска к точке за кадром вели бы в пустоту, поэтому они упираются в
        край — там, где древко из кадра и выходит.
        """
        x, y = _p(*pt)
        return (min(PANEL_W - 14.0, max(14.0, x * k + tx)),
                min(PANEL_H - CAPTION_H - 12.0, max(14.0, y * k + ty)))

    out = ['<svg viewBox="0 0 %.0f %.0f" xmlns="http://www.w3.org/2000/svg" '
           'width="100%%" preserveAspectRatio="xMidYMid meet" role="img">'
           % (PANEL_W, PANEL_H)]
    uid = "g%d" % abs(hash((round(cbox[0], 1), index, title, when)) % 100000)
    out.append('<defs><linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
               '<stop offset="0" stop-color="%s"/>'
               '<stop offset="1" stop-color="%s"/></linearGradient>'
               '<clipPath id="c%s"><rect x="4" y="4" width="%.0f" height="%.0f" '
               'rx="12"/></clipPath></defs>'
               % (uid, BG_TOP, BG_BOTTOM, uid, PANEL_W - 8, PANEL_H - 8))
    out.append('<rect x="4" y="4" width="%.0f" height="%.0f" rx="12" fill="url(#%s)" '
               'stroke="%s"/>' % (PANEL_W - 8, PANEL_H - 8, uid, EDGE))
    grid = []
    x = 4 + GRID
    while x < PANEL_W - 4:
        grid.append('<line x1="%.0f" y1="4" x2="%.0f" y2="%.0f"/>'
                    % (x, x, PANEL_H - 4))
        x += GRID
    y = 4 + GRID
    while y < PANEL_H - 4:
        grid.append('<line x1="4" y1="%.0f" x2="%.0f" y2="%.0f"/>'
                    % (y, PANEL_W - 4, y))
        y += GRID
    out.append('<g clip-path="url(#c%s)" stroke="%s" stroke-width="1" '
               'opacity="0.45">%s</g>' % (uid, GRID_C, "".join(grid)))

    out.append('<g transform="translate(%.2f,%.2f) scale(%.4f)">%s</g>'
               % (tx, ty, k, figure(pose, nxt, prev, impact=impact, ghost=ghost)))

    if nx:
        out.append(_arrow(to_px(sk.hands[1]), to_px(nx.hands[1]), CYAN, 0.16, 4.4))
        out.append(_arrow(to_px(sk.tip), to_px(nx.tip), CYAN, 0.24, 3.8))
        if math.dist(sk.hip, nx.hip) > 0.045:
            out.append(_arrow(to_px(sk.hip), to_px(nx.hip), GOLD, 0.10, 4.4))
        if abs(nx.lean - sk.lean) > 6.0:
            out.append(_arrow(to_px(sk.shoulder), to_px(nx.shoulder), GOLD, 0.34, 4.0))

    # Смысловые подписи идут первыми и вытесняют механические: «плечи ведут»
    # полезнее, чем «вращение корпуса», хотя говорят об одном. Больше пяти
    # подписей кадр не держит — проверено глазами, дальше они наезжают друг на
    # друга и на фигуру.
    raw_labels = [(str(t), GOLD, to_px(_anchor(sk, str(a) if a in ANCHORS
                                               else "hip")))
                  for t, a in extra_labels][:MAX_LABELS]
    for text, anchor, colour in auto_labels(pose, nxt):
        if len(raw_labels) >= MAX_LABELS:
            break
        raw_labels.append((text, colour, to_px(_anchor(sk, anchor))))
    centre = to_px(sk.chest)
    for text, colour, px, y, x, _, side in place_labels(raw_labels, centre):
        out.append(_label(text, colour, px, x, y, side))

    base = PANEL_H - CAPTION_H
    out.append('<line x1="16" y1="%.0f" x2="%.0f" y2="%.0f" stroke="%s" '
               'opacity="0.7"/>' % (base, PANEL_W - 16, base, EDGE))
    if index is not None:
        out.append('<circle cx="30" cy="%.0f" r="12" fill="%s" opacity="0.28"/>'
                   '<text x="30" y="%.0f" fill="%s" font-size="13" font-weight="700" '
                   'text-anchor="middle" font-family="Segoe UI, Roboto, sans-serif">'
                   '%d</text>' % (base + 20, CYAN, base + 25, CYAN, index))
    if title:
        out.append('<text x="50" y="%.0f" fill="%s" font-size="13.5" '
                   'font-weight="700" font-family="Segoe UI, Roboto, sans-serif">'
                   '%s</text>' % (base + 19, LABEL, _esc(title.upper())))
    tail = " ".join(x for x in (title_en.upper() if title_en else "",
                                ("· %s С" % when) if when else "") if x)
    if tail:
        out.append('<text x="50" y="%.0f" fill="%s" font-size="11" '
                   'font-family="Segoe UI, Roboto, sans-serif">%s</text>'
                   % (base + 35, LABEL_DIM, _esc(tail)))
    out.append("</svg>")
    return "".join(out)


def strip(beats: list[dict], titles=None, ghost: bool = True) -> list[str]:
    """Полоса долей одного удара: у всех кадров общая рамка и общий масштаб."""
    poses = [b["pose"] for b in beats if b.get("pose")]
    if not poses:
        return []
    frame = content_box(poses)
    out = []
    for i, beat in enumerate(beats):
        meta = (titles or {}).get(i, {})
        out.append(panel(
            beat["pose"],
            beats[i + 1]["pose"] if i + 1 < len(beats) else None,
            prev=beats[i - 1]["pose"] if i else None,
            frame=frame, index=i + 1,
            title=meta.get("title", ""), title_en=meta.get("en", ""),
            when=meta.get("when", ""), extra_labels=meta.get("labels", ()),
            impact=beat.get("role") == "contact", ghost=ghost))
    return out


def standalone(svg: str) -> str:
    """SVG отдельным файлом — для markdown, который картинки не вставляет."""
    return '<?xml version="1.0" encoding="utf-8"?>\n' + svg


# --- план площадки сверху --------------------------------------------------
FLOOR_W, FLOOR_H = 330.0, 280.0


def _fp(x: float, y: float) -> tuple[float, float]:
    return (FLOOR_W / 2 + x * FLOOR_W * 0.38, FLOOR_H / 2 - y * FLOOR_H * 0.36)


def floor_plan(floor: dict) -> str:
    out = ['<svg viewBox="0 0 %.0f %.0f" xmlns="http://www.w3.org/2000/svg" '
           'width="100%%" role="img">' % (FLOOR_W, FLOOR_H)]
    out.append('<rect x="4" y="4" width="%.0f" height="%.0f" rx="12" fill="%s" '
               'stroke="%s"/>' % (FLOOR_W - 8, FLOOR_H - 8, BG_BOTTOM, EDGE))
    grid = []
    for x in range(28, int(FLOOR_W) - 8, 24):
        grid.append('<line x1="%d" y1="4" x2="%d" y2="%.0f"/>' % (x, x, FLOOR_H - 4))
    for y in range(28, int(FLOOR_H) - 8, 24):
        grid.append('<line x1="4" y1="%d" x2="%.0f" y2="%d"/>' % (y, FLOOR_W - 4, y))
    out.append('<g stroke="%s" stroke-width="1" opacity="0.35">%s</g>'
               % (GRID_C, "".join(grid)))
    out.append('<text x="%.0f" y="%.0f" fill="%s" font-size="11" '
               'text-anchor="middle" font-family="Segoe UI, Roboto, sans-serif">'
               'ЗАЛ</text>' % (FLOOR_W / 2, FLOOR_H - 12, LABEL_DIM))
    out.append('<line x1="20" y1="%.0f" x2="%.0f" y2="%.0f" stroke="%s" '
               'stroke-dasharray="5 6" opacity="0.8"/>'
               % (FLOOR_H - 28, FLOOR_W - 20, FLOOR_H - 28, EDGE))

    arc = floor.get("arc") or []
    if len(arc) >= 3:
        p0, p1, p2 = (_fp(*arc[0]), _fp(*arc[1]), _fp(*arc[2]))
        out.append('<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f" fill="none" '
                   'stroke="%s" stroke-width="3.4" stroke-linecap="round"/>'
                   % (*p0, *p1, *p2, CYAN))
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        head = [(p2[0], p2[1]),
                (p2[0] - 13 * math.cos(ang - 0.42), p2[1] - 13 * math.sin(ang - 0.42)),
                (p2[0] - 13 * math.cos(ang + 0.42), p2[1] - 13 * math.sin(ang + 0.42))]
        out.append('<polygon points="%s" fill="%s"/>'
                   % (" ".join("%.1f,%.1f" % p for p in head), CYAN))
        out.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10.5" '
                   'font-family="Segoe UI, Roboto, sans-serif">наконечник</text>'
                   % (p2[0] + 8, p2[1] - 8, CYAN))

    feet = floor.get("feet") or {}
    for key, colour, name in (("back", LIMB_BACK, "задняя"),
                              ("front", SKIN, "передняя")):
        if key in feet:
            x, y = _fp(*feet[key])
            out.append('<ellipse cx="%.1f" cy="%.1f" rx="9" ry="14" fill="%s" '
                       'opacity="0.9"/>' % (x, y, colour))
            out.append('<text x="%.1f" y="%.1f" fill="%s" font-size="9.5" '
                       'text-anchor="middle" font-family="Segoe UI, Roboto, '
                       'sans-serif">%s</text>' % (x, y + 26, LABEL_DIM, name))

    if "enemy" in floor:
        x, y = _fp(*floor["enemy"])
        out.append('<circle cx="%.1f" cy="%.1f" r="12" fill="none" stroke="#ff5b5d" '
                   'stroke-width="2.6"/>' % (x, y))
        for dx in (-1, 1):
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="#ff5b5d" stroke-width="2.6"/>'
                       % (x - 5 * dx, y - 5, x + 5 * dx, y + 5))
        out.append('<text x="%.1f" y="%.1f" fill="#ff5b5d" font-size="10.5" '
                   'text-anchor="middle" font-family="Segoe UI, Roboto, sans-serif">'
                   'цель</text>' % (x, y - 18))

    cx, cy = _fp(0.0, 0.0)
    out.append('<circle cx="%.1f" cy="%.1f" r="8" fill="%s"/>' % (cx, cy, GOLD))
    out.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10.5" '
               'text-anchor="middle" font-family="Segoe UI, Roboto, sans-serif">'
               'ты</text>' % (cx, cy - 14, GOLD))
    out.append('</svg>')
    return "".join(out)
