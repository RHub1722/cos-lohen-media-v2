"""Собрать копию для публикации: титры номера и знак RaYMoon в углу.

    python tools/render_logo.py --in output/final_ru_nostrip.mp4 \
                                --out output/final_ru_nostrip_titles_logo.mp4

Титры и знак кладутся за ОДИН прогон кодировщика, на исходник без того и
другого. Взять готовый файл с титрами и добить знак поверх было бы проще, но
это второе поколение H.264 по всему кадру ради угла в 311 пикселей.

ЗНАК. Кадры анимации считаются здесь numpy и уходят в ffmpeg трубой, без
временных файлов. Собственная картинка ролика не пересчитывается: знак ложится
фильтром overlay, звук копируется дорожкой как есть.

МЕСТО. Правый верхний угол, 311x300 при отступах 70. Выбрано замером: средняя
яркость этого места в последние секунды 6.7% из 255, серебро на нём читается
без обводки. Мерились четыре размера, этот самый тёмный из тех, где знак ещё не
мелкий (крупнее 340 — уже 7.2%).

ВРЕМЯ. Старт 55.2 — последний ледяной удар номера (ice_final_impact в
timeline.json), самый громкий акцент концовки. Знак приходит на него и стоит до
конца, 4.8 с.

ПОЯВЛЕНИЕ — «прорисовка». Знак рисует себя своим же лучом:

  0.00..0.62  луч чертит себя сверху вниз, на конце яркая головка;
  0.50..1.45  от прочерченной оси в обе стороны раскрывается луна и надпись,
              по фронту раскрытия бежит блик;
  ..1.90      служебный луч гаснет, остаётся собственный луч знака.

Ось раскрытия — не середина рамки, а столбец самого луча, найденный по нижнему
хвосту знака. По верхним строкам искать нельзя: туда попадает верхний рог
полумесяца и тянет замер влево на четверть ширины.

Блик раскрытия умножается на размытую альфу знака. Без этого он превращается в
две сплошные вертикальные полосы во всю высоту рамки — так и было в первой
сборке, видно на раскадровке.

Отвергнуты, но были собраны и просмотрены:
  «проявление» — прозрачность плюс наплыв масштаба 1.05 -> 1.00. Сначала
    выбрано исполнителем и собрано в полные ролики, затем заменено на
    прорисовку: тихо, но знак приходит ниоткуда и ничем не связан с картинкой;
  «вспышка» — знак приходит на удар пересветом и оседает за 0.9 с. Читается
    как ещё одна вспышка боя, а бой к этому моменту кончился.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / 'assets' / 'Images' / 'logo_raymoon.png'
TITLES = 'scenario/titles.ass'

FPS = 30
START = 55.20          # ice_final_impact
DUR = 4.80             # до конца ролика
HEIGHT = 300           # высота знака в кадре
MARGIN = 70            # отступ от верхнего и правого краёв

DRAW = 0.62            # луч чертит себя сверху вниз
OPEN_FROM = 0.50       # раскрытие начинается, не дожидаясь конца прочерка
OPEN_TO = 1.45
CALM = 1.90            # служебный луч погас
BEAM_RGB = np.array([205.0, 232.0, 255.0])   # цвет луча и блика


def smoothstep(x: np.ndarray | float) -> np.ndarray | float:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def load_logo(height: int) -> tuple[np.ndarray, np.ndarray]:
    """Знак нужного размера: премультиплированный цвет и альфа.

    Уменьшать нужно именно премультиплированным, иначе на краю букв вылезает
    кайма из цвета прозрачных пикселей.
    """
    im = Image.open(LOGO).convert('RGBA')
    a = np.asarray(im).astype(np.float32)
    al = a[:, :, 3:] / 255.0
    pre = Image.fromarray(
        np.clip(np.dstack([a[:, :, :3] * al, al * 255.0]), 0, 255).astype(np.uint8))
    width = int(round(height * im.width / im.height))
    p = np.asarray(pre.resize((width, height), Image.LANCZOS)).astype(np.float32)
    return p[:, :, :3], p[:, :, 3] / 255.0


def beam_column(alpha: np.ndarray) -> float:
    """Столбец луча — по нижнему хвосту, где кроме луча ничего нет."""
    tail = alpha[int(alpha.shape[0] * 0.86):].sum(0)
    return float(np.arange(len(tail)) @ tail / tail.sum())


def frames(pre: np.ndarray, al: np.ndarray):
    """Кадры знака: RGBA uint8, альфа обычная, не премультиплированная."""
    h, w = al.shape
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    axis = beam_column(al)
    dist = np.abs(xx - axis)                       # до оси раскрытия
    far = float(max(axis, w - axis))               # дальний край знака от оси
    art = np.clip(gaussian_filter(al, 5.0) * 2.5, 0.0, 1.0)   # где есть рисунок
    sig = max(1.6, w * 0.008)                      # толщина луча
    rim_sig = max(4.0, w * 0.028)                  # ширина блика на фронте

    for i in range(int(round(DUR * FPS))):
        t = i / FPS

        tip = smoothstep(t / DRAW) * (h + 6.0)
        gain = 1.0 - smoothstep((t - DRAW) / (CALM - DRAW))
        line = smoothstep((tip - yy) / 3.0) * np.exp(-0.5 * (dist / sig) ** 2)
        head = (np.exp(-0.5 * ((yy - tip) / 5.0) ** 2)
                * np.exp(-0.5 * (dist / (sig * 2.2)) ** 2)
                * (1.0 - smoothstep((t - DRAW) / 0.18)))
        beam = np.clip((line * 0.85 + head) * gain, 0.0, 1.0)

        r = smoothstep((t - OPEN_FROM) / (OPEN_TO - OPEN_FROM))
        radius = r * far * 1.08
        opened = smoothstep((radius - dist) / 9.0)
        rim = (np.exp(-0.5 * ((dist - radius) / rim_sig) ** 2) * art
               * (r > 0.001) * (1.0 - smoothstep((r - 0.85) / 0.15)) * 0.75)

        a = np.clip(al * opened + beam + rim, 0.0, 1.0)
        p = pre * opened[:, :, None] + BEAM_RGB[None, None, :] * (beam + rim)[:, :, None]
        rgb = np.where(a[:, :, None] > 1e-4, p / np.maximum(a[:, :, None], 1e-4), 0.0)
        yield np.dstack([np.clip(rgb, 0, 255), a * 255.0]).astype(np.uint8)


def build(src: Path, dst: Path, titles: str | None) -> int:
    pre, al = load_logo(HEIGHT)
    h, w = al.shape
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', str(src)],
        capture_output=True, text=True, check=True).stdout.strip()
    fw, fh = (int(v) for v in probe.split('x'))
    x, y = fw - MARGIN - w, MARGIN
    print('кадр %dx%d, знак %dx%d в x %d y %d, с %.2f по %.2f с'
          % (fw, fh, w, h, x, y, START, START + DUR))

    chain = []
    if titles:
        chain.append('[0:v]ass=%s[t]' % titles)
    chain.append('[1:v]setpts=PTS-STARTPTS+%.3f/TB[lg]' % START)
    chain.append('[%s][lg]overlay=x=%d:y=%d:eof_action=pass[v]' % ('t' if titles else '0:v', x, y))

    cmd = [
        'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', str(src),
        '-f', 'rawvideo', '-pix_fmt', 'rgba', '-video_size', '%dx%d' % (w, h),
        '-framerate', str(FPS), '-i', '-',
        '-filter_complex', ';'.join(chain),
        '-map', '[v]', '-map', '0:a',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p',
        '-c:a', 'copy', str(dst),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(ROOT))
    n = 0
    for f in frames(pre, al):
        proc.stdin.write(f.tobytes())
        n += 1
    proc.stdin.close()
    code = proc.wait()
    print('кадров знака: %d, ffmpeg вернул %d' % (n, code))
    return code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--out', dest='dst', required=True)
    ap.add_argument('--titles', default=TITLES,
                    help='файл ASS с титрами; --titles "" собирает только знак')
    args = ap.parse_args()
    src = Path(args.src)
    if not src.exists():
        print('нет исходника: %s' % src, file=sys.stderr)
        return 1
    return build(src, Path(args.dst), args.titles or None)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
