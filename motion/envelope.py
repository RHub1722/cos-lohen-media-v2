"""Огибающая движения и её пороги.

Четыре починки здесь существуют не для аккуратности, а потому что без каждой
из них замер соврал на настоящем материале. Что именно ломалось — в
docs/superpowers/specs/2026-08-05-motion-analyzer-design.md, п. 2.

Модели фона нет вовсе. Она проваливалась трижды: медиана по времени оказывалась
самим исполнителем, когда он стоял на месте; автоэкспозиция красила кадр
целиком; эрозия назначала палкой торс. Разница соседних кадров ни одного из
этих провалов не имеет.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FLOOR_PCT = 20.0        # дно (уровень покоя) — 20-я процентиль
QUIET_PCT = 50.0         # по какой части огибающей мерить шум покоя
STRIKE_FRAC = 0.35      # порог удара — дно + 0.35 * (максимум - дно)
STRIKE_SIGMA = 6.0      # ...но не ближе шести сигм шума покоя
HANDLING_SIGMA = 3.0    # движение вообще — три сигмы над покоем
SMOOTH_S = 0.08         # окно сглаживания
LEVEL_FRAC = 0.10       # уровень, по которому мерятся замах и торможение
MAD_TO_SIGMA = 1.4826   # медианное отклонение в сигму для нормального шума

# 0.35 взят из пробы и подлежит настройке на трёх настоящих видео по одному
# критерию: найденные всплески должны совпадать с тем, что видно на контактном
# листе. Проба с 0.35 БЕЗ нормировки пропустила дальние смахи.
#
# Порога в шесть сигм в первом замысле не было, и это была ошибка: доля от
# «максимум минус дно» ВСЕГДА находит события там, где их нет. На неподвижном
# клипе максимум — это шум, и 0.35 от него лежит внутри шума. Событие обязано
# выситься над покоем, а не над собственным максимумом. Три сигмы для движения
# вообще — то же самое: выше 20-й процентили по построению лежит 80% отсчётов,
# и без этой поправки неподвижный клип разметился бы как работа с оружием.


@dataclass(frozen=True)
class Envelope:
    values: np.ndarray      # сглаженная и нормированная, отсчёт на пару кадров
    times: np.ndarray       # время каждого отсчёта, с
    fps: int
    floor: float            # уровень покоя, в тех же единицах что values
    noise: float            # сигма шума покоя
    handling_level: float   # выше этого — движение вообще
    strike_level: float     # выше этого — удар
    scale: float            # на что поделили
    scale_source: str       # "поза" | "разброс" | "нет"
    size_fix: str           # чем починен масштаб внутри видео

    def level_for(self, peak: float) -> float:
        """Уровень 10%, от которого мерятся замах и торможение."""
        return self.floor + LEVEL_FRAC * (peak - self.floor)


def raw_motion(frames: np.ndarray) -> np.ndarray:
    """Разница соседних кадров с подавлением автоэкспозиции.

    Вычитание собственного среднего каждого кадра ДО разницы — вся починка, и
    она одна строка. Без неё скачок экспозиции телефона отличается сразу в
    каждой точке и читается как движение: на настоящем материале он красил в
    маску весь навес, деревья и плитку.
    """
    levelled = frames - frames.mean(axis=(1, 2), keepdims=True)
    return np.abs(np.diff(levelled, axis=0)).mean(axis=(1, 2))


def smooth(values: np.ndarray, fps: int, window_s: float = SMOOTH_S) -> np.ndarray:
    """Скользящее среднее. Один кадр при 60 fps не бывает замахом.

    Без сглаживания проба выдавала подъём и спад по 0.017 с, то есть по одному
    кадру, — это артефакт спайкового сигнала, а не замер.
    """
    width = max(1, int(round(window_s * fps)))
    values = np.asarray(values, dtype=np.float64)
    if width < 2 or len(values) < width:
        return values
    return np.convolve(values, np.ones(width) / width, mode="same")


def build(frames: np.ndarray, fps: int,
          body_frac: np.ndarray | None = None) -> Envelope:
    """Огибающая из кадров.

    body_frac — рост исполнителя долей высоты кадра, по кадру, из позы. Если
    он есть, чинится ВТОРАЯ беда масштаба: один и тот же смах вблизи и вдалеке
    даёт разную энергию, потому что она растёт как площадь, то есть как
    квадрат роста в кадре. Проба пропустила дальние смахи ровно из-за этого:
    рост в кадре 69 px против 89 у ближних.

    Нормировка на разброс внутри видео чинит ПЕРВУЮ беду — разный контраст
    между съёмками. Это две разные починки, и нужны обе.
    """
    raw = raw_motion(frames)
    if body_frac is not None and len(body_frac) >= len(raw) + 1:
        frac = np.clip(np.asarray(body_frac, dtype=np.float64), 0.05, 1.0)
        area = (frac[:len(raw)] + frac[1:len(raw) + 1]) / 2.0
        raw = raw / area ** 2
        size_fix = "по росту в кадре из позы"
    else:
        size_fix = "нет: позы не было, дальние движения занижены"

    vals = smooth(raw, fps)
    floor = float(np.percentile(vals, FLOOR_PCT))
    active = vals[vals > floor]
    spread = float(active.std()) if active.size > 1 else 0.0
    if spread > 1e-9:
        scale, source = spread, "разброс"
    else:
        scale, source = 1.0, "нет"

    # Шум покоя по тихой половине огибающей. Медианное отклонение, а не
    # стандартное: одно настоящее движение задрало бы стандартное так, что
    # порог ушёл бы выше самого движения.
    quiet = vals[vals <= np.percentile(vals, QUIET_PCT)]
    noise = float(np.median(np.abs(quiet - np.median(quiet)))) * MAD_TO_SIGMA
    if noise <= 0.0:
        noise = max((float(vals.max()) - floor) * 0.01, 1e-12)

    norm = vals / scale
    nfloor = floor / scale
    nnoise = noise / scale
    strike_level = max(nfloor + STRIKE_FRAC * (float(norm.max()) - nfloor),
                       nfloor + STRIKE_SIGMA * nnoise)
    handling_level = nfloor + HANDLING_SIGMA * nnoise
    # Отсчёт разницы лежит между своими двумя кадрами, отсюда полкадра.
    times = np.arange(len(norm)) / fps + 0.5 / fps
    return Envelope(values=norm, times=times, fps=fps, floor=nfloor,
                    noise=nnoise, handling_level=handling_level,
                    strike_level=strike_level, scale=scale,
                    scale_source=source, size_fix=size_fix)
