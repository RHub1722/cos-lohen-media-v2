"""Карта хвата: где браться за копьё в каждом приёме.

Числа берутся из scenario/strikes.json, а не переписываются руками. В позах
хват задан долей `grip` — по определению в src/figures.py это часть древка,
которая остаётся позади кистей, то есть расстояние от пятки до передней кисти.
Здесь доля переводится в миллиметры и накладывается на физические пределы
настоящего копья из docs/spear-guide.md §8.

    python tools/grip_map.py

Пишет assets/screenshots/spear_grip_marks.svg и вставляет тот же SVG в
src/training_template.html и site/index.html между маркерами GRIP-MAP.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG_OUT = ROOT / "assets/screenshots/spear_grip_marks.svg"
TARGETS = [ROOT / "src/training_template.html", ROOT / "site/index.html"]
MARK_A, MARK_B = "<!-- GRIP-MAP:START -->", "<!-- GRIP-MAP:END -->"

L = 1800.0                      # длина копья, мм
WRAP0, WRAP1 = 336, 1000        # обмотка
MARK = 900                      # валик-метка, перекрут
STOP = 1000                     # валик-упор
S13, WING = 1057, 1127          # spear_13 и крылья
BACK_HAND = 275                 # задняя кисть ниже передней, мм (figures.py)

W, PAD_L, PAD_R = 1560, 210, 60
AX = W - PAD_L - PAD_R
ROW_H, TOP = 96, 300

BG, FG, MUT = "#12151b", "#e8e6e3", "#8b9099"
GOLD, BLUE, RED, GREY = "#d9b678", "#7b93d4", "#e0574f", "#3a4150"

ROLE = {"windup": "замах", "swing": "взмах", "contact": "контакт",
        "recover": "возврат", "hold": "держать"}


def x(mm):
    return PAD_L + AX * mm / L


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build():
    data = json.loads((ROOT / "scenario/strikes.json").read_text(encoding="utf-8"))
    strikes = data["strikes"] if isinstance(data, dict) else data

    H = TOP + ROW_H * len(strikes) + 200
    # без width/height: размер задаётся стилем, иначе на планшете картинка
    # сожмётся до нечитаемого вместо того, чтобы прокручиваться вбок
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'style="width:100%;height:auto;display:block;min-width:1080px" '
         f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    def t(tx, ty, s, size=13, fill=FG, weight="400", anchor="start", ls="0"):
        o.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{size}" fill="{fill}" '
                 f'font-weight="{weight}" text-anchor="{anchor}" letter-spacing="{ls}">{esc(s)}</text>')

    # ── заголовок ────────────────────────────────────────────────────────────
    t(PAD_L, 44, "ГДЕ БРАТЬСЯ ЗА КОПЬЁ", 21, FG, "700", ls="1.5")
    t(PAD_L, 68, "Хват каждой доли боя в миллиметрах от пятки · числа из scenario/strikes.json, "
                 "пределы из гайда §8", 13, MUT)

    # ── схема древка ─────────────────────────────────────────────────────────
    yb, hb = 104, 34
    o.append(f'<rect x="{x(0):.1f}" y="{yb}" width="{x(WRAP0)-x(0):.1f}" height="{hb}" '
             f'fill="#2a2f3c" rx="2"/>')
    o.append(f'<rect x="{x(WRAP0):.1f}" y="{yb}" width="{x(WRAP1)-x(WRAP0):.1f}" height="{hb}" '
             f'fill="{GOLD}" rx="2"/>')
    o.append(f'<rect x="{x(WRAP1):.1f}" y="{yb}" width="{x(L)-x(WRAP1):.1f}" height="{hb}" '
             f'fill="{RED}" fill-opacity="0.20" rx="2"/>')
    o.append(f'<rect x="{x(WRAP1):.1f}" y="{yb}" width="{x(L)-x(WRAP1):.1f}" height="{hb}" '
             f'fill="none" stroke="{RED}" stroke-opacity="0.5" stroke-dasharray="4 3" rx="2"/>')

    t(x(WRAP0/2), yb + 22, "ПЯТОЧНАЯ ГРУППА", 11, MUT, "700", "middle", "0.8")
    t((x(WRAP0)+x(WRAP1))/2, yb + 22, "ОБМОТКА ШНУРОМ — здесь и держат", 12, "#2a2214", "700", "middle", "0.5")
    t((x(WRAP1)+x(L))/2, yb + 22, "НЕ БРАТЬСЯ", 12, RED, "700", "middle", "0.8")

    # выноски: сначала линии, потом подписи — чтобы текст лёг поверх
    for mm, col in ((WRAP0, GOLD), (MARK, GOLD), (STOP, RED), (WING, RED)):
        o.append(f'<line x1="{x(mm):.1f}" y1="{yb-14}" x2="{x(mm):.1f}" y2="{yb+hb+8}" '
                 f'stroke="{col}" stroke-width="1.5"/>')
    t(x(WRAP0), yb - 20, f"{WRAP0} начало обмотки", 11, GOLD, "600", "middle")
    t(x(MARK) - 6, yb - 20, f"{MARK} ВАЛИК-МЕТКА · перекрут", 12, GOLD, "700", "end")
    t(x(STOP) + 6, yb - 20, f"{STOP} ВАЛИК-УПОР · выше рука не проедет", 12, RED, "700", "start")
    t(x(WING), yb - 40, f"{WING} крылья", 11, RED, "600", "middle")

    # ── линейка ──────────────────────────────────────────────────────────────
    yr = yb + hb + 26
    o.append(f'<line x1="{x(0):.1f}" y1="{yr}" x2="{x(L):.1f}" y2="{yr}" stroke="{GREY}"/>')
    for mm in range(0, 1801, 200):
        o.append(f'<line x1="{x(mm):.1f}" y1="{yr}" x2="{x(mm):.1f}" y2="{yr+5}" stroke="{GREY}"/>')
        t(x(mm), yr + 19, str(mm), 11, MUT, "400", "middle")

    # ── правило сверху ───────────────────────────────────────────────────────
    t(PAD_L, yr + 52, "Правило простое: ладонь всегда на золотом. Валик на 900 находится на ощупь — "
                      "это хват перекрута; валик на 1000 упирается в руку и дальше не пускает.",
      13, FG)
    t(PAD_L, yr + 72, "Задняя кисть идёт ниже передней примерно на 275 мм. Точки ниже — передняя кисть.",
      12, MUT)

    # ── строки приёмов ───────────────────────────────────────────────────────
    bad = []
    for i, s in enumerate(strikes):
        y = TOP + i * ROW_H
        o.append(f'<line x1="{PAD_L}" y1="{y-26}" x2="{W-PAD_R}" y2="{y-26}" '
                 f'stroke="{GREY}" stroke-opacity="0.5"/>')
        title = s.get("title", s["id"])
        t(PAD_L - 14, y - 4, title.split(":")[0], 14, FG, "700", "end")
        t(PAD_L - 14, y + 14, s["id"], 11, MUT, "400", "end")

        # дорожка
        o.append(f'<rect x="{x(WRAP0):.1f}" y="{y-6}" width="{x(WRAP1)-x(WRAP0):.1f}" '
                 f'height="12" fill="{GOLD}" fill-opacity="0.13" rx="6"/>')
        o.append(f'<line x1="{x(STOP):.1f}" y1="{y-20}" x2="{x(STOP):.1f}" y2="{y+22}" '
                 f'stroke="{RED}" stroke-width="1" stroke-opacity="0.55"/>')

        for j, b in enumerate(s["beats"]):
            g = b["pose"]["grip"]
            mm = g * L
            out = mm < WRAP0 or mm > STOP
            col = RED if out else BLUE
            if out:
                bad.append((s, j, mm))
            o.append(f'<circle cx="{x(mm):.1f}" cy="{y}" r="8" fill="{col}"/>')
            t(x(mm), y + 4, str(j + 1), 10, "#0d1016", "700", "middle")
            up = (j % 2 == 0)
            t(x(mm), y - 16 if up else y + 26, ROLE.get(b.get("role"), b.get("role") or ""),
              11, MUT if not out else RED, "600", "middle")
            t(x(mm), y - 28 if up else y + 38, f"{mm:.0f}", 11, col, "700", "middle")

    # ── что не помещается ────────────────────────────────────────────────────
    yw = TOP + ROW_H * len(strikes) + 16
    o.append(f'<rect x="{PAD_L-14}" y="{yw}" width="{W-PAD_L-PAD_R+28}" height="132" '
             f'fill="{RED}" fill-opacity="0.10" stroke="{RED}" stroke-opacity="0.5" rx="4"/>')
    t(PAD_L, yw + 26, f"ПЯТЬ ДОЛЕЙ ИЗ {sum(len(s['beats']) for s in strikes)} НЕ ПОМЕЩАЮТСЯ В ЭТО КОПЬЁ",
      14, RED, "700", ls="0.8")
    t(PAD_L, yw + 50,
      "«Принять удар», все четыре доли — 1008 и 1044 мм, выше упора. До крыла остаётся 83–119 мм, "
      "а гайд отверг 71 мм как «аварию, ждущую повода».", 12.5, FG)
    t(PAD_L, yw + 70,
      "Практически туда и не попасть: на 1000 стоит валик, рука упрётся. Позу опускать под 1000.", 12.5, MUT)
    t(PAD_L, yw + 94,
      "«Копьё в пол», доля 4 — 216 мм, на 120 мм ниже обмотки: ладонь ложится на лакированный "
      "пластик ровно в момент удара в пол.", 12.5, FG)
    t(PAD_L, yw + 114,
      "Либо поднимать хват до 336, либо не лакировать пятку. По §8 лак идёт на всё, кроме 336…1000.",
      12.5, MUT)

    t(PAD_L, yw + 168, "Копьё 1800 мм · обмотка 336…1000, диаметр в ладони 28 мм · "
                       "хват задан долей древка позади кистей, здесь переведён в миллиметры",
      11.5, MUT)
    o.append("</svg>")
    return "\n".join(o), bad


svg, bad = build()
SVG_OUT.parent.mkdir(parents=True, exist_ok=True)
SVG_OUT.write_text(svg, encoding="utf-8")
print(f"{SVG_OUT.relative_to(ROOT)}: {len(svg):,} байт, за пределами {len(bad)} долей")
for s, j, mm in bad:
    print(f"  {s['id']:14} доля {j+1}  {mm:6.0f} мм")

for tgt in TARGETS:
    if not tgt.exists():
        print(f"  пропущен, нет файла: {tgt.name}")
        continue
    h = tgt.read_text(encoding="utf-8")
    if MARK_A not in h or MARK_B not in h:
        print(f"  МАРКЕРОВ НЕТ в {tgt.name} — вставь {MARK_A}…{MARK_B}")
        continue
    a = h.index(MARK_A) + len(MARK_A)
    b = h.index(MARK_B)
    tgt.write_text(h[:a] + "\n" + svg + "\n" + h[b:], encoding="utf-8")
    print(f"  вставлено в {tgt.name}")
