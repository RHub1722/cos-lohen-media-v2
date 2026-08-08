"""Играет ли страница ту фонограмму, которая звучит в номере.

Тренажёр разучивают по видео, лежащему рядом со страницей. Пока номер собирался
одним пайплайном, вопроса не было: сборка была одна. С 8 августа звук берётся из
монтажки, копий номера стало четыре — а тренажёр продолжал играть августовскую
сборку с английским голосом и нашими процедурными FX.

Разошлось молча. Заметить это можно было только ушами, и то если знать, что
слушать. Поэтому сверка делается при сборке страницы, а не остаётся обязанностью
помнить: тренажёр, который учит попадать в звук, обязан играть тот звук, под
который выступают.

Мерится не «похоже ли на слух», а «тот ли это файл»: нормированная корреляция по
пятисекундным окнам. Вопрос двоичный, и ответ на него двоичный.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

# Для вопроса «тот ли это файл» шестнадцати килогерц достаточно с запасом, а
# декодирование минуты идёт вчетверо быстрее, чем на сорока восьми.
SR = 16000
WINDOW = 5.0

# Порог взят из замера, а не с потолка. Правильные копии номера дают в худшем
# окне 0.999. Наша же сборка с русским голосом, но без ручных FX, проваливается
# до 0.11, августовская английская — до 0.0008. Между 0.999 и 0.11 черту можно
# провести где угодно; 0.90 оставляет запас на перекодирование в AAC и не
# оставляет его ни на что другое.
MATCH = 0.90


class SoundcheckError(Exception):
    """Видео играет не ту фонограмму, под которую поставлен номер."""


def mono(path: str | Path, sr: int = SR) -> np.ndarray:
    """Звуковая дорожка файла одним каналом. Видео или wav — всё равно."""
    path = Path(path)
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1",
             "-ar", str(sr), "-f", "f32le", "-"],
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise SoundcheckError(
            "FFmpeg не найден, а без него звук не сверить. Он нужен всему "
            "проекту, не только этой сверке."
        ) from exc

    samples = np.frombuffer(result.stdout, dtype=np.float32).astype(np.float64)
    if not samples.size:
        raise SoundcheckError(
            f"в {path} нет звуковой дорожки или она не читается. FFmpeg сказал: "
            f"{result.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    return samples


def match_windows(video: str | Path, master: str | Path) -> list[tuple[float, float]]:
    """Совпадение звука видео с фонограммой по пятисекундным окнам.

    Окнами, а не одним числом на весь файл: подменённой может оказаться часть.
    Именно так и вышло у нас — допрос и финал совпадали, а бой в середине был
    переделан целиком, и среднее по файлу это спрятало бы.
    """
    a, b = mono(video), mono(master)
    n = min(len(a), len(b))
    step = int(WINDOW * SR)
    out: list[tuple[float, float]] = []
    for start in range(0, n, step):
        x = a[start:min(start + step, n)]
        y = b[start:min(start + step, n)]
        if len(x) < step // 2:      # хвост короче половины окна не судим
            break
        x = x - x.mean()
        y = y - y.mean()
        norm = np.linalg.norm(x) * np.linalg.norm(y)
        out.append((start / SR, float(abs(x @ y) / norm) if norm else 0.0))
    if not out:
        raise SoundcheckError(f"{video}: дорожка короче одного окна")
    return out


def check(video: str | Path, master: str | Path,
          threshold: float = MATCH) -> list[tuple[float, float]]:
    """Та же сверка, но молчит только при совпадении.

    Ошибка громкая и с раскладкой по окнам: «не совпало» без указания где —
    это повод гадать, а гадать тут не о чем.
    """
    windows = match_windows(video, master)
    bad = [(t, c) for t, c in windows if c < threshold]
    if bad:
        rows = "\n".join("  %5.1f-%4.1f с   совпадение %.3f"
                         % (t, t + WINDOW, c) for t, c in windows)
        raise SoundcheckError(
            f"{Path(video).name} играет не фонограмму номера.\n"
            f"Сверка с {Path(master).name} по окнам (порог {threshold:.2f}):\n"
            f"{rows}\n"
            f"Не совпало окон: {len(bad)} из {len(windows)}. Разучивать номер по "
            "этому файлу значит разучивать его под звук, которого на площадке не "
            "будет."
        )
    return windows
