"""Ввод: кадры и звук через FFmpeg. Своих алгоритмов здесь нет.

Кадры читает src.footage.ClipReader — он уже приводит клип любого разрешения
к нужному размеру через трубу и падает с внятной ошибкой, называя файл и
команду. Своей копии нет намеренно.

fill=False, чтобы кадр никогда не обрезался: у сегодняшних видео пропорции
совпадают с целевыми и разницы нет, но вертикальное видео с телефона на
следующем заходе обрезалось бы молча, а pad при совпадающих пропорциях не
делает ничего.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.footage import ClipReader

# Веса яркости BT.709 — те же, по которым живёт видеорендер проекта.
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

MIN_DURATION = 2.0


class VideoError(Exception):
    """Видео не читается или не годится для разбора."""


@dataclass(frozen=True)
class Clip:
    path: Path
    width: int
    height: int
    fps: int
    duration: float


def probe(path: str | Path) -> Clip:
    """Размер, частота и длина. Частота округляется до целой.

    Округление намеренное: ClipReader всё равно приводит поток к целой частоте
    фильтром fps, и время в замере считается по той же целой. Для 30000/1001
    это расхождение 0.1% и полная внутренняя согласованность вместо точности,
    которой в кадрах всё равно нет.
    """
    path = Path(path)
    if not path.exists():
        raise VideoError(f"{path.name}: файла нет ({path})")
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoError(f"{path.name}: ffprobe вернул {proc.returncode}.\n"
                         f"{proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    stream = next((s for s in data.get("streams", [])
                   if s.get("codec_type") == "video"), None)
    if stream is None:
        raise VideoError(f"{path.name}: в файле нет видеодорожки")
    num, _, den = str(stream.get("r_frame_rate", "0/1")).partition("/")
    fps = int(round(float(num) / float(den or 1))) or 1
    duration = float(data.get("format", {}).get("duration", 0.0))
    if duration < MIN_DURATION:
        raise VideoError(f"{path.name}: длина {duration:.2f} с, разбирать нечего "
                         f"(нужно от {MIN_DURATION:g} с)")
    return Clip(path=path, width=int(stream["width"]),
                height=int(stream["height"]), fps=fps, duration=duration)


def gray_frames(clip: Clip, width: int = 320) -> np.ndarray:
    """Все кадры серыми, (n, h, w) float32 в 0..1.

    Мелкое разрешение для сигнала: 3139 кадров в полном размере это около 6 ГБ,
    в 320x180 — 180 МБ.
    """
    height = max(2, int(round(width * clip.height / clip.width / 2)) * 2)
    reader = ClipReader(clip.path, width, height, clip.fps, fill=False)
    out: list[np.ndarray] = []
    try:
        while True:
            frame = reader.read()
            if frame is None:
                break
            out.append(frame[:, :, :3] @ LUMA)
    finally:
        reader.close()
    if not out:
        raise VideoError(f"{clip.path.name}: FFmpeg не отдал ни одного кадра")
    return np.stack(out)


def rgb_stream(clip: Clip, width: int = 640):
    """Кадры потоком: (время, (h, w, 3) uint8). Один процесс FFmpeg на клип.

    Слою позы нужны сотни кадров подряд. Дёргать их по одному через -ss значит
    завести полторы тысячи процессов на пятидесятисекундном видео; поток
    обходится одним.
    """
    height = max(2, int(round(width * clip.height / clip.width / 2)) * 2)
    reader = ClipReader(clip.path, width, height, clip.fps, fill=False)
    try:
        i = 0
        while True:
            frame = reader.read()
            if frame is None:
                return
            yield i / clip.fps, (frame[:, :, :3] * 255.0).astype(np.uint8)
            i += 1
    finally:
        reader.close()


def band_envelope(clip: Clip, hz: float = 2000.0) -> np.ndarray:
    """Пиковая огибающая полосы выше hz, по отсчёту на кадр видео.

    Нужна ровно для одного: найти возню с камерой в начале и в конце. Проба
    показала, что палка на этих скоростях не свистит вовсе, и как источник
    тайминга звук не годится. Дорожки может не быть — тогда пустой массив.
    """
    sr = 48000
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(clip.path),
         "-af", f"highpass=f={hz:g}", "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(proc.stdout, dtype=np.float32)
    hop = max(1, int(round(sr / clip.fps)))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.abs(x[:n * hop].reshape(n, hop)).max(axis=1)


def still_rgb(clip: Clip, t: float) -> np.ndarray:
    """Один кадр полного размера, (h, w, 3) uint8. Для картинок отчёта."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(clip.path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    need = clip.width * clip.height * 3
    if len(proc.stdout) < need:
        raise VideoError(f"{clip.path.name}: кадр на {t:.2f} с не прочитался")
    return np.frombuffer(proc.stdout[:need], np.uint8).reshape(
        clip.height, clip.width, 3)
