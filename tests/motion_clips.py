"""Синтетические клипы с известным ответом.

Тот же приём, что в tools/make_test_clips.py: кадры рисует numpy, кодирует
FFmpeg. Настоящие тренировочные видео в тестах не используются — они медленные,
и на них нет известного правильного ответа.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

W, H = 320, 180


def encode(path: Path, frames: np.ndarray, fps: int) -> Path:
    """Массив (n, H, W) в 0..1 -> mp4 без потерь качества для замера."""
    raw = (np.clip(frames, 0.0, 1.0) * 255).astype(np.uint8)
    rgb = np.repeat(raw[:, :, :, None], 3, axis=3)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{frames.shape[2]}x{frames.shape[1]}", "-framerate", str(fps),
         "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
         str(path)],
        input=rgb.tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg не собрал клип: "
                           f"{proc.stderr.decode(errors='replace')}")
    return path


def scene(n: int, contrast: float = 1.0) -> np.ndarray:
    """Неподвижный фон: горизонтальные полосы. Ничем не отличается от кадра
    к кадру, поэтому вся разница в клипе будет от того, что мы нарисуем сверху."""
    base = np.zeros((H, W), dtype=np.float32) + 0.35
    base[::8, :] = 0.5
    return np.repeat(base[None, :, :], n, axis=0) * contrast


BAR_LEVEL = 0.80


def bar(frames: np.ndarray, i: int, x: float, contrast: float = 1.0) -> None:
    """Вертикальная полоса шириной 10 px с центром в x. Это «палка».

    Яркость умножается на contrast так же, как у фона: иначе разница
    «полоса минус фон» менялась бы непропорционально, и тест на нормировку
    проверял бы не то, что заявлено.

    0.80, а не почти единица: bright_step добавляет ко всему кадру 0.18, и на
    0.95 полоса упёрлась бы в потолок. Тогда фон сдвинулся бы на 0.18, а
    полоса на 0.05 — вычитание среднего такое не сокращает, и «глобальный»
    скачок перестал бы быть глобальным.
    """
    x0 = int(np.clip(x - 5, 0, frames.shape[2] - 1))
    x1 = int(np.clip(x + 5, 1, frames.shape[2]))
    frames[i, 20:160, x0:x1] = np.clip(BAR_LEVEL * contrast, 0.0, 1.0)


def triangle(total: int, a: int, b: int, x0: float, x1: float,
             rise: float = 0.5) -> np.ndarray:
    """Положение полосы: стоит, проезжает от x0 до x1, снова стоит.

    Скорость идёт по треугольнику с вершиной на кадре a + rise*(b-a). Пик
    скорости и есть известный ответ теста. Ровная скорость не годится: у неё
    плато вместо пика, и на плато любой шум даёт лишние локальные максимумы.

    rise=0.5 — симметрично; rise=0.85 — долгий замах и резкая остановка, то
    есть «палку остановили».
    """
    peak = a + rise * (b - a)
    speed = np.zeros(total)
    for i in range(a, min(b, total)):
        speed[i] = (i - a) / max(peak - a, 1e-9) if i <= peak \
            else (b - i) / max(b - peak, 1e-9)
    pos = np.cumsum(np.clip(speed, 0.0, None))
    span = float(pos[-1] - pos[0])
    if span > 1e-9:
        pos = pos * ((x1 - x0) / span)
    return pos - pos[0] + x0


def sweep(path: Path, fps: int, total: int, a: int, b: int,
          rise: float = 0.5, contrast: float = 1.0) -> Path:
    """Один смах через кадр с известным моментом пика скорости."""
    frames = scene(total, contrast)
    pos = triangle(total, a, b, 40.0, float(W - 40), rise)
    for i in range(total):
        bar(frames, i, float(pos[i]), contrast)
    encode(path, frames, fps)
    return path


def still(path: Path, fps: int, total: int) -> Path:
    """Ничего не двигается вовсе."""
    frames = scene(total)
    for i in range(total):
        bar(frames, i, 160.0)
    return encode(path, frames, fps)


def bright_step(path: Path, fps: int, total: int, at: int,
                step: float = 0.18) -> Path:
    """Ничего не двигается, но на кадре `at` вся яркость разом растёт.

    Это автоэкспозиция телефона. На настоящем материале она красила кадр
    целиком и читалась как движение."""
    frames = scene(total)
    for i in range(total):
        bar(frames, i, 160.0)
    frames[at:] += step
    return encode(path, frames, fps)


def spike_then_sweeps(path: Path, fps: int) -> Path:
    """Огромный всплеск в начале, потом два умеренных смаха.

    Это v1 в миниатюре: возня с камерой у объектива в разы сильнее настоящих
    смахов в глубине кадра. Если пороги считать по всему клипу, всплеск задаёт
    их сам и смахи не находятся.
    """
    total = fps * 5
    frames = scene(total)
    pos = np.full(total, 30.0)
    # Возня: большой блок у объектива ездит по кадру. Именно площадь, а не
    # размах: полоса, перепрыгивающая кадр, меняет всего две своих ширины
    # пикселей — энергия движения упирается в размер объекта, и такой всплеск
    # выходит не сильнее смаха.
    for i in range(1, 9):
        x0 = 20 + 40 * i
        frames[i, 10:170, max(x0 - 100, 0):min(x0 + 100, W)] = 0.15
    # Смахи: втрое меньше по размаху и вдвое медленнее.
    slow_1 = triangle(total, int(fps * 2.0), int(fps * 2.6), 60.0, 150.0)
    slow_2 = triangle(total, int(fps * 3.6), int(fps * 4.2), 150.0, 240.0)
    pos[8:int(fps * 2.0)] = 60.0
    pos[int(fps * 2.0):int(fps * 3.6)] = slow_1[int(fps * 2.0):int(fps * 3.6)]
    pos[int(fps * 3.6):] = slow_2[int(fps * 3.6):]
    for i in range(total):
        bar(frames, i, float(pos[i]))
    return encode(path, frames, fps)


def two_sweeps(path: Path, fps: int, dead: bool) -> Path:
    """Два смаха с переходом между ними.

    dead=True — между смахами полная остановка, то есть стойка.
    dead=False — полоса продолжает ползти, связка не прерывается.

    Оба смаха идут по треугольнику скорости: на ровной скорости у всплеска
    плато, и детектор пиков ловит на нём лишние максимумы.
    """
    total = fps * 4
    frames = scene(total)
    a1, b1 = int(fps * 0.4), int(fps * 0.9)
    a2, b2 = int(fps * 2.6), int(fps * 3.1)

    pos = triangle(total, a1, b1, 40.0, 140.0)
    if dead:
        middle = np.full(total, 140.0)
    else:
        # 80 px за 1.7 с — заметно выше шума, но много ниже смаха.
        middle = np.clip(np.interp(np.arange(total), [b1, a2], [140.0, 220.0]),
                         140.0, 220.0)
    pos[b1:] = middle[b1:]
    start = float(pos[a2 - 1])
    second = triangle(total, a2, b2, start, float(W - 30))
    pos[a2:] = second[a2:]

    for i in range(total):
        bar(frames, i, float(pos[i]))
    return encode(path, frames, fps)
