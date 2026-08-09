"""Рисунки книжки: персонаж и стрелки, посчитанные из чисел позы.

Ни одного рисунка руками. Всё, что видно на странице, считается из полей `pose`
и `floor` в scenario/strikes.json, поэтому разойтись с текстом рядом рисунок не
может: поменяется поза в сценарии — перерисуется и он.

Это черновой слой книжки. Позже часть кадров заменяется генерацией, но SVG
никуда не девается и остаётся под ней: не понравилась картинка — доля
откатывается к рисунку. И промпт генератору пишется по этому же рисунку, а не по
воображению: с него видно ракурс, положение древка и рамку кадра.

СИСТЕМА КООРДИНАТ. Внутри модуля всё в долях роста, начало на полу между
стопами, y вверх. В SVG y переворачивается один раз, в самом конце, функцией
`_p`. Держать переворот в одном месте дешевле, чем помнить о нём в двадцати.

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
# Три четверти, а не фас: плечи и таз сжаты поперёк, иначе фигура читается
# плоской и теряет глубину дуги, ради которой ракурс и выбран.
SHOULDER_W = 0.17
HIP_W = 0.12
TORSO = 0.30
NECK = 0.045
# Голова крупнее анатомической: шесть с половиной голов в росте вместо семи с
# половиной. Это и есть разница между «человек» и «персонаж», и она же делает
# наклон головы читаемым — а наклон головы у нас несёт целую долю в приёме удара.
HEAD_R = 0.078
LEG = 0.50
THIGH = 0.26
SHIN = 0.26
UPPER_ARM = 0.17
FOREARM = 0.17
FOOT = 0.09
# Ширина «шага» hands[0]: единица — рука, уведённая в сторону на всю длину.
HAND_X = 0.26
# Копьё 1.80 м при росте 1.62 — 1.11 роста. Замер реквизита, не оценка:
# от него зависят и вылет древка в кадре, и радиус, нужный на площадке.
SPEAR_LEN = 1.11
BLADE = 0.17

SCALE = 132.0
VIEW_X = (-0.95, 0.95)
VIEW_Y = (-0.08, 1.42)

# --- палитра: светлая фигура на тёмном, как в тренажёре --------------------
INK = "#f2f2f5"
SKIN = "#cfd3e0"
COAT = "#3b4a6b"
COAT_BACK = "#28324a"
LIMB_BACK = "#6f768c"
SHAFT = "#c8a271"
BLADE_C = "#9be8ff"
ARROW = "#ffb020"
GHOST = "#5fd4ff"


def _rad(deg: float) -> float:
    return deg * math.pi / 180.0


def _p(x: float, y: float) -> tuple[float, float]:
    """Доли роста -> пиксели SVG. Единственное место, где y переворачивается."""
    return ((x - VIEW_X[0]) * SCALE, (VIEW_Y[1] - y) * SCALE)


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
    """Локоть или колено. Если не дотягивается — сустав выпрямляется.

    bend — в какую сторону выгибается сустав: +1 против часовой от линии
    «корень-цель», -1 по часовой. У руки и ноги стороны разные, и задавать их
    надо снаружи: изнутри не видно, какая это конечность.
    """
    delta = _sub(target, root)
    dist = math.hypot(*delta)
    reach = upper + lower
    if dist >= reach - 1e-6:
        along = _norm(delta)
        return _add(root, _mul(along, upper * reach / max(dist, 1e-6) * (dist / reach)))
    along = _norm(delta)
    cos_a = (upper * upper + dist * dist - lower * lower) / (2 * upper * dist)
    cos_a = max(-1.0, min(1.0, cos_a))
    off = upper * cos_a
    height = math.sqrt(max(0.0, upper * upper - off * off))
    perp = (-along[1] * bend, along[0] * bend)
    return _add(_add(root, _mul(along, off)), _mul(perp, height))


@dataclass(frozen=True)
class Skeleton:
    """Собранная фигура: все точки уже в долях роста."""

    hip: tuple
    shoulder: tuple
    head: tuple
    feet: tuple
    knees: tuple
    hands: tuple
    elbows: tuple
    butt: tuple          # задний конец древка
    tip: tuple           # наконечник
    lean: float
    head_tilt: float


def build(pose: dict) -> Skeleton:
    lean = float(pose.get("lean", 0.0))
    crouch = max(0.0, min(1.0, float(pose.get("crouch", 0.0))))
    stance = max(0.0, float(pose.get("stance", 0.8)))
    spear_a = float(pose.get("spear", 0.0))
    hx, hy = pose.get("hands", [0.2, 0.6])
    grip = max(0.0, min(1.0, float(pose.get("grip", 0.35))))
    head_tilt = float(pose.get("head", 0.0))

    half = stance * 0.22 / 2.0
    # Присед опускает таз, разножка опускает его же — ноги расходятся и
    # становятся короче по вертикали. Второе считается честно теоремой
    # Пифагора, а не коэффициентом: при широкой стойке разница заметная.
    upright = math.sqrt(max(0.04, LEG * LEG - half * half))
    hip_y = upright * (1.0 - 0.30 * crouch)
    hip = (0.0, hip_y)

    t = _rad(lean)
    shoulder = (hip[0] + TORSO * math.sin(t), hip[1] + TORSO * math.cos(t))
    ht = _rad(lean + head_tilt * 0.6)
    head = (shoulder[0] + (NECK + HEAD_R) * math.sin(ht),
            shoulder[1] + (NECK + HEAD_R) * math.cos(ht))

    feet = ((-half, 0.0), (half, 0.0))
    hips_l = (hip[0] - HIP_W / 2, hip[1])
    hips_r = (hip[0] + HIP_W / 2, hip[1])
    # Колено уходит вперёд, то есть в сторону своей стопы.
    knees = (two_bone(hips_l, feet[0], THIGH, SHIN, -1.0),
             two_bone(hips_r, feet[1], THIGH, SHIN, +1.0))

    hand = (hx * HAND_X, float(hy))
    d = (math.cos(_rad(spear_a)), -math.sin(_rad(spear_a)))
    butt = _add(hand, _mul(d, -grip * SPEAR_LEN))
    tip = _add(hand, _mul(d, (1.0 - grip) * SPEAR_LEN))
    # Вторая кисть отступает назад по древку: двуручный хват так и читается.
    hand_back = _add(hand, _mul(d, -min(0.16, grip * SPEAR_LEN * 0.8)))

    sh_l = (shoulder[0] - SHOULDER_W / 2, shoulder[1])
    sh_r = (shoulder[0] + SHOULDER_W / 2, shoulder[1])
    elbows = (two_bone(sh_l, hand_back, UPPER_ARM, FOREARM, -1.0),
              two_bone(sh_r, hand, UPPER_ARM, FOREARM, +1.0))

    return Skeleton(hip=hip, shoulder=shoulder, head=head, feet=feet,
                    knees=knees, hands=(hand_back, hand), elbows=elbows,
                    butt=butt, tip=tip, lean=lean, head_tilt=head_tilt)


def _limb(a, b, c, width: float, color: str) -> str:
    return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.1f" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
            % (_fmt([a, b, c]), color, width))


def _coat(sk: Skeleton) -> str:
    """Силуэт пальто: масса, из-за которой фигура перестаёт быть палками.

    Подол отстаёт от корпуса: при наклоне вправо он уходит влево. Без этого
    фигура выглядит как наклонённая доска, а не как человек в движении.
    """
    waist_y = sk.hip[1] + 0.07
    sway = math.sin(_rad(sk.lean)) * 0.14
    hem = max(0.13, sk.hip[1] - 0.27)
    pts = [(sk.hip[0] - HIP_W * 0.80, waist_y),
           (sk.hip[0] - HIP_W * 2.00 - sway, hem + 0.07),
           (sk.hip[0] - HIP_W * 1.45 - sway, hem),
           (sk.hip[0] - sway * 0.5, hem + 0.05),
           (sk.hip[0] + HIP_W * 1.45 - sway, hem),
           (sk.hip[0] + HIP_W * 2.00 - sway, hem + 0.07),
           (sk.hip[0] + HIP_W * 0.80, waist_y)]
    return '<polygon points="%s" fill="%s"/>' % (_fmt(pts), COAT)


def _torso(sk: Skeleton) -> str:
    t = _rad(sk.lean)
    nx, ny = math.cos(t), -math.sin(t)      # поперёк корпуса
    sl = (sk.shoulder[0] - nx * SHOULDER_W / 2, sk.shoulder[1] - ny * SHOULDER_W / 2)
    sr = (sk.shoulder[0] + nx * SHOULDER_W / 2, sk.shoulder[1] + ny * SHOULDER_W / 2)
    hl = (sk.hip[0] - nx * HIP_W / 2, sk.hip[1] - ny * HIP_W / 2)
    hr = (sk.hip[0] + nx * HIP_W / 2, sk.hip[1] + ny * HIP_W / 2)
    return ('<polygon points="%s" fill="%s"/>' % (_fmt([sl, sr, hr, hl]), COAT_BACK)
            + '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2" '
              'stroke-linecap="round"/>' % (_fmt([sl, sr]), COAT))


def _head(sk: Skeleton) -> str:
    cx, cy = _p(*sk.head)
    r = HEAD_R * SCALE
    t = _rad(sk.lean + sk.head_tilt * 0.6)
    # Волосы: клин назад, против наклона головы. Одна форма на все позы —
    # силуэт узнаётся именно ей.
    back = (sk.head[0] - math.cos(t) * HEAD_R * 1.5,
            sk.head[1] + math.sin(t) * HEAD_R * 0.6 + HEAD_R * 0.5)
    up = (sk.head[0] + math.sin(t) * HEAD_R * 1.35,
          sk.head[1] + math.cos(t) * HEAD_R * 1.35)
    side = (sk.head[0] + math.cos(t) * HEAD_R * 0.9,
            sk.head[1] - math.sin(t) * HEAD_R * 0.9 + HEAD_R * 0.35)
    return ('<polygon points="%s" fill="%s"/>' % (_fmt([back, up, side]), COAT)
            + '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>' % (cx, cy, r, SKIN))


def _spear(sk: Skeleton) -> str:
    d = _norm(_sub(sk.tip, sk.butt))
    neck = _sub(sk.tip, _mul(d, BLADE))
    wing = (-d[1] * BLADE * 0.22, d[0] * BLADE * 0.22)
    blade = [sk.tip, _add(neck, wing), _add(neck, _mul(wing, -1.0))]
    return ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="4.0" stroke-linecap="round"/>'
            % (*_p(*sk.butt), *_p(*neck), SHAFT)
            + '<polygon points="%s" fill="%s"/>' % (_fmt(blade), BLADE_C))


def figure(pose: dict, ghost: dict | None = None) -> str:
    """Одна фигура. ghost — следующая поза бледным контуром позади."""
    out = []
    if ghost:
        # Следующая доля пунктиром и только костяком: корпус, ноги, древко,
        # голова. Рисовать её целиком уже пробовал — два полных силуэта в одном
        # кадре сливаются, и перестаёт читаться который из них главный.
        g = build(ghost)
        out.append('<g opacity="0.45" fill="none" stroke="%s" stroke-width="2.6" '
                   'stroke-dasharray="6 5" stroke-linecap="round" '
                   'stroke-linejoin="round">' % GHOST)
        out.append('<polyline points="%s"/>'
                   % _fmt([g.feet[0], g.knees[0], g.hip, g.knees[1], g.feet[1]]))
        out.append('<polyline points="%s"/>' % _fmt([g.hip, g.shoulder]))
        out.append('<polyline points="%s"/>' % _fmt([g.butt, g.tip]))
        out.append('<circle cx="%.1f" cy="%.1f" r="%.1f"/>'
                   % (*_p(*g.head), HEAD_R * SCALE))
        out.append('</g>')

    sk = build(pose)
    out.append(_limb(sk.feet[0], sk.knees[0], (sk.hip[0] - HIP_W / 2, sk.hip[1]),
                     9.0, LIMB_BACK))
    out.append(_limb((sk.shoulder[0] - SHOULDER_W / 2, sk.shoulder[1]),
                     sk.elbows[0], sk.hands[0], 7.5, LIMB_BACK))
    out.append(_coat(sk))
    out.append(_limb(sk.feet[1], sk.knees[1], (sk.hip[0] + HIP_W / 2, sk.hip[1]),
                     10.0, SKIN))
    out.append(_torso(sk))
    out.append(_head(sk))
    # Передняя рука с тёмной подложкой: без неё она сливается с корпусом того
    # же цвета, и хват — то, ради чего кадр и нужен, — просто не виден.
    out.append(_limb((sk.shoulder[0] + SHOULDER_W / 2, sk.shoulder[1]),
                     sk.elbows[1], sk.hands[1], 12.0, COAT_BACK))
    out.append(_limb((sk.shoulder[0] + SHOULDER_W / 2, sk.shoulder[1]),
                     sk.elbows[1], sk.hands[1], 8.0, SKIN))
    out.append(_spear(sk))
    # Стопы: без них фигура висит в воздухе и стойку не прочитать.
    for fx, fy in sk.feet:
        x0, y0 = _p(fx - FOOT / 2, fy)
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="5" rx="2.5" '
                   'fill="%s"/>' % (x0, y0 - 2.5, FOOT * SCALE, SKIN))
    return "".join(out)


def _arrow(a, b, color: str = ARROW, curve: float = 0.18) -> str:
    """Дуга со стрелкой: движение идёт по дуге, а прямая врёт о траектории."""
    ax, ay = _p(*a)
    bx, by = _p(*b)
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy)
    if dist < 14:
        return ""
    mx, my = (ax + bx) / 2 - dy * curve, (ay + by) / 2 + dx * curve
    ex, ey = bx - (bx - mx) / max(1e-6, math.hypot(bx - mx, by - my)) * 9, \
             by - (by - my) / max(1e-6, math.hypot(bx - mx, by - my)) * 9
    ang = math.atan2(by - my, bx - mx)
    head = [(bx, by),
            (bx - 13 * math.cos(ang - 0.42), by - 13 * math.sin(ang - 0.42)),
            (bx - 13 * math.cos(ang + 0.42), by - 13 * math.sin(ang + 0.42))]
    return ('<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f" fill="none" stroke="%s" '
            'stroke-width="3.2" stroke-linecap="round" opacity="0.95"/>'
            '<polygon points="%s" fill="%s"/>'
            % (ax, ay, mx, my, ex, ey, color,
               " ".join("%.1f,%.1f" % p for p in head), color))


def arrows(pose: dict, nxt: dict | None) -> str:
    """Куда идёт кисть, наконечник и таз на следующей доле."""
    if not nxt:
        return ""
    a, b = build(pose), build(nxt)
    out = [_arrow(a.hands[1], b.hands[1]),
           _arrow(a.tip, b.tip, BLADE_C, 0.22)]
    if math.dist(a.hip, b.hip) > 0.05:
        out.append(_arrow(a.hip, b.hip, "#ff4d4f", 0.10))
    return "".join(out)


def box(poses) -> tuple[float, float, float, float]:
    """Рамка по содержимому: x, y, ширина, высота в пикселях SVG.

    Считается по ВСЕМ долям удара сразу, а не по каждой отдельно. Иначе у
    каждой доли получился бы свой масштаб, и рядом стоящие кадры перестали бы
    сравниваться — а вся полоса нужна ровно для сравнения.
    """
    xs, ys = [], []
    pad = HEAD_R * 1.9 * SCALE
    for pose in poses:
        sk = build(pose)
        pts = [sk.head, sk.hip, sk.shoulder, sk.butt, sk.tip,
               *sk.feet, *sk.knees, *sk.hands, *sk.elbows,
               (sk.hip[0], max(0.10, sk.hip[1] - 0.27))]
        for pt in pts:
            x, y = _p(*pt)
            xs.append(x)
            ys.append(y)
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    return x0, y0, x1 - x0, y1 - y0


def panel(pose: dict, nxt: dict | None = None, ghost: bool = True,
          frame: tuple | None = None) -> str:
    poses = [pose] + ([nxt] if nxt else [])
    x, y, w, h = frame or box(poses)
    return ('<svg viewBox="%.0f %.0f %.0f %.0f" xmlns="http://www.w3.org/2000/svg" '
            'role="img" width="100%%" preserveAspectRatio="xMidYMid meet">%s%s</svg>'
            % (x, y, w, h, figure(pose, nxt if ghost else None), arrows(pose, nxt)))


def strip(beats: list[dict], ghost: bool = True) -> list[str]:
    """Полоса долей одного удара: у всех кадров общая рамка и общий масштаб."""
    poses = [b["pose"] for b in beats if b.get("pose")]
    if not poses:
        return []
    frame = box(poses)
    out = []
    for i, beat in enumerate(beats):
        nxt = beats[i + 1]["pose"] if i + 1 < len(beats) else None
        out.append(panel(beat["pose"], nxt, ghost=ghost, frame=frame))
    return out


def standalone(svg: str) -> str:
    """SVG отдельным файлом — для markdown, который картинки не вставляет.

    Объявление кодировки обязательно: внутри плана площадки есть русские
    подписи, и без него браузер читает файл как latin-1 и показывает мусор.
    """
    return '<?xml version="1.0" encoding="utf-8"?>\n' + svg


# --- план площадки сверху --------------------------------------------------
FLOOR_W, FLOOR_H = 300.0, 260.0


def _fp(x: float, y: float) -> tuple[float, float]:
    """План: x от -1 (его лево) до +1, y от -1 (глубина) до +1 (зал)."""
    return (FLOOR_W / 2 + x * FLOOR_W * 0.40, FLOOR_H / 2 - y * FLOOR_H * 0.38)


def floor_plan(floor: dict) -> str:
    out = ['<svg viewBox="0 0 %.0f %.0f" xmlns="http://www.w3.org/2000/svg" '
           'width="100%%">' % (FLOOR_W, FLOOR_H)]
    out.append('<rect x="6" y="6" width="%.0f" height="%.0f" rx="12" fill="#14141b" '
               'stroke="#262633"/>' % (FLOOR_W - 12, FLOOR_H - 12))
    out.append('<text x="%.0f" y="%.0f" fill="#8b8b98" font-size="12" '
               'text-anchor="middle">зал</text>' % (FLOOR_W / 2, FLOOR_H - 12))
    out.append('<line x1="20" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#262633" '
               'stroke-dasharray="4 5"/>' % (FLOOR_H - 30, FLOOR_W - 20, FLOOR_H - 30))

    arc = floor.get("arc") or []
    if len(arc) >= 3:
        p0, p1, p2 = (_fp(*arc[0]), _fp(*arc[1]), _fp(*arc[2]))
        out.append('<path d="M %.1f %.1f Q %.1f %.1f %.1f %.1f" fill="none" '
                   'stroke="%s" stroke-width="3" stroke-linecap="round" '
                   'opacity="0.9"/>' % (*p0, *p1, *p2, ARROW))
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        head = [(p2[0], p2[1]),
                (p2[0] - 12 * math.cos(ang - 0.42), p2[1] - 12 * math.sin(ang - 0.42)),
                (p2[0] - 12 * math.cos(ang + 0.42), p2[1] - 12 * math.sin(ang + 0.42))]
        out.append('<polygon points="%s" fill="%s"/>'
                   % (" ".join("%.1f,%.1f" % p for p in head), ARROW))

    feet = floor.get("feet") or {}
    for key, color in (("back", LIMB_BACK), ("front", SKIN)):
        if key in feet:
            x, y = _fp(*feet[key])
            out.append('<ellipse cx="%.1f" cy="%.1f" rx="9" ry="13" fill="%s" '
                       'opacity="0.85"/>' % (x, y, color))

    if "enemy" in floor:
        x, y = _fp(*floor["enemy"])
        out.append('<circle cx="%.1f" cy="%.1f" r="11" fill="none" stroke="#ff4d4f" '
                   'stroke-width="2.5"/>' % (x, y))
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#ff4d4f" '
                   'stroke-width="2.5"/>' % (x - 5, y - 5, x + 5, y + 5))
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#ff4d4f" '
                   'stroke-width="2.5"/>' % (x + 5, y - 5, x - 5, y + 5))

    cx, cy = _fp(0.0, 0.0)
    out.append('<circle cx="%.1f" cy="%.1f" r="7" fill="%s"/>' % (cx, cy, GHOST))
    out.append('</svg>')
    return "".join(out)
