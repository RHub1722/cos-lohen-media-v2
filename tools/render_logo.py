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

ПОЯВЛЕНИЕ. Прозрачность плюс лёгкий наплыв масштаба: 0.25 с паузы после удара,
затем 1.4 с проявления, масштаб 1.05 -> 1.00. Выбор исполнителя из трёх
показанных вариантов.

Отвергнуты, но были собраны и просмотрены:
  «прорисовка» — луч знака чертит себя сверху вниз, и от него в обе стороны
    раскрывается луна и надпись. Красивее и сделано из самого знака, но это
    полноценный эффект в конце номера, где по сценарию уже тишина и покой;
  «вспышка» — знак приходит на удар пересветом и оседает. Читается как ещё
    одна вспышка боя, а бой к этому моменту кончился.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / 'assets' / 'Images' / 'logo_raymoon.png'
TITLES = 'scenario/titles.ass'

FPS = 30
START = 55.20          # ice_final_impact
DUR = 4.80             # до конца ролика
HEIGHT = 300           # высота знака в кадре
MARGIN = 70            # отступ от верхнего и правого краёв
HOLD = 0.25            # пауза после удара, прежде чем знак начнёт проявляться
FADE = 1.40            # проявление
ZOOM = 1.05            # с какого масштаба наплывает


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


def sample(img: np.ndarray, yy: np.ndarray, xx: np.ndarray) -> np.ndarray:
    """Билинейная выборка. Наплыв делается координатами, а не пересборкой PIL."""
    h, w = img.shape[:2]
    y = np.clip(np.broadcast_to(yy, (h, w)), 0, h - 1.001)
    x = np.clip(np.broadcast_to(xx, (h, w)), 0, w - 1.001)
    y0, x0 = y.astype(np.int32), x.astype(np.int32)
    fy, fx = (y - y0)[:, :, None], (x - x0)[:, :, None]
    top = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
    bot = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bot * fy


def frames(pre: np.ndarray, al: np.ndarray):
    """Кадры знака: RGBA uint8, альфа обычная, не премультиплированная."""
    h, w = al.shape
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]
    al3 = al[:, :, None]
    for i in range(int(round(DUR * FPS))):
        k = smoothstep((i / FPS - HOLD) / FADE)
        s = 1.0 + (ZOOM - 1.0) * (1.0 - k)
        sy = (yy - h * 0.5) / s + h * 0.5
        sx = (xx - w * 0.5) / s + w * 0.5
        p = sample(pre, sy, sx) * k
        a = sample(al3, sy, sx)[:, :, 0] * k
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
