"""Картинки отчёта: полосы кадров и обзорный лист.

Прожжённое время обязательно. Без него нельзя сослаться на момент, а весь
разбор ошибок по кадрам состоит из таких ссылок.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from motion.segment import Segment, Strike
from motion.video import Clip, still_rgb

THUMB_W = 480
FONT_BOX = (0, 0, 118, 26)


def _stamp(img: Image.Image, text: str) -> Image.Image:
    """Время в углу. Шрифт по умолчанию, чтобы не тащить файл шрифта."""
    draw = ImageDraw.Draw(img)
    draw.rectangle(FONT_BOX, fill=(0, 0, 0))
    draw.text((6, 7), text, fill=(255, 220, 0))
    return img


def _thumb(clip: Clip, t: float) -> Image.Image:
    img = Image.fromarray(still_rgb(clip, t))
    height = max(2, round(THUMB_W * clip.height / clip.width))
    img = img.resize((THUMB_W, height))
    return _stamp(img, f"{t:6.2f}s")


def _row(images: list[Image.Image], out_path: Path) -> Path:
    width = sum(i.width for i in images)
    height = max(i.height for i in images)
    sheet = Image.new("RGB", (width, height), (0, 0, 0))
    x = 0
    for img in images:
        sheet.paste(img, (x, 0))
        x += img.width
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def strike_strip(clip: Clip, strike: Strike, out_path: Path) -> Path:
    """Четыре кадра удара: начало замаха, пик, остановка, и через 0.3 с после."""
    times = [
        max(0.0, strike.t_peak - strike.windup),
        strike.t_peak,
        min(clip.duration - 0.05, strike.t_peak + strike.stop),
        min(clip.duration - 0.05, strike.t_peak + strike.stop + 0.30),
    ]
    return _row([_thumb(clip, t) for t in times], out_path)


def handling_strip(clip: Clip, part: Segment, out_path: Path,
                   every: float = 2.0) -> Path:
    """Медленное владение: кадр каждые две секунды."""
    times = list(np.arange(part.start, min(part.end, clip.duration - 0.05),
                           every))
    if not times:
        times = [part.start]
    return _row([_thumb(clip, float(t)) for t in times[:8]], out_path)


def overview_sheet(clip: Clip, out_path: Path, columns: int = 4,
                   rows: int = 4) -> Path:
    """Обзорный лист: весь заход равномерно, чтобы видеть его целиком."""
    count = columns * rows
    step = clip.duration / (count + 1)
    thumbs = [_thumb(clip, step * (i + 1)) for i in range(count)]
    width = thumbs[0].width * columns
    height = thumbs[0].height * rows
    sheet = Image.new("RGB", (width, height), (0, 0, 0))
    for i, img in enumerate(thumbs):
        sheet.paste(img, ((i % columns) * img.width,
                          (i // columns) * img.height))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
