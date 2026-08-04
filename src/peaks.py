"""Где внутри ассета лежит пик.

Ассет ставится на таймлайн НАЧАЛОМ файла, а слышен пиком. У быстрого взмаха
разница 0.376 с — треть секунды. Исполнителю нельзя показывать время начала
файла: он попадёт мимо и будет прав.

Замер, а не таблица в сценарии: таблицу пришлось бы править руками при каждой
перегенерации ассета, и разошлась бы она молча.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

import numpy as np

SR = 48000


class PeakError(Exception):
    """Файл не читается или в нём нет ни одного отсчёта."""


def peak_offset(path: str | Path) -> float:
    """Смещение самого громкого отсчёта от начала файла, секунды.

    Пик, а не начало атаки: порог начала атаки надо выбирать, и от выбора
    зависит ответ. У пика выбирать нечего.
    """
    path = Path(path)
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1",
             "-ar", str(SR), "-f", "f32le", "-"],
            capture_output=True,
        )
    except FileNotFoundError as exc:  # ffmpeg не установлен
        raise PeakError(
            "FFmpeg не найден, а без него смещение пика не замерить. "
            "Он нужен всему проекту, не только этому замеру."
        ) from exc

    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if not samples.size:
        raise PeakError(
            f"в {path} нет ни одного отсчёта. FFmpeg сказал: "
            f"{result.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    return float(np.argmax(np.abs(samples))) / SR


def peak_offsets(assets: str | Path, names: Iterable[str]) -> dict[str, float]:
    """Смещения пиков для набора ассетов. Ключ — путь, как в сценарии."""
    root = Path(assets)
    out: dict[str, float] = {}
    for name in names:
        if name in out:
            continue
        out[name] = round(peak_offset(root / name), 4)
    return out
