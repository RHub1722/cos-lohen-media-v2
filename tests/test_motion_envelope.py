"""Тесты 1-4 приёмки: огибающая движения.

Тесты 2 и 3 существуют потому, что ровно на этих двух местах проба и
сломалась: автоэкспозиция красила кадр целиком, а модель фона проваливалась,
когда исполнитель не покидал кадр.
"""

import numpy as np
import pytest

from motion import envelope, video
from tests import motion_clips


def build(path, width=160):
    clip = video.probe(path)
    frames = video.gray_frames(clip, width=width)
    return envelope.build(frames, clip.fps), clip


def test_1_peak_lands_on_the_known_moment(tmp_path):
    """Всплеск в известный момент: пик огибающей попадает в него."""
    fps, total, a, b = 30, 120, 30, 60
    path = motion_clips.sweep(tmp_path / "s.mp4", fps=fps, total=total, a=a, b=b)
    env, _ = build(path)
    want = (a + 0.5 * (b - a)) / fps
    got = float(env.times[int(np.argmax(env.values))])
    assert abs(got - want) <= 2.0 / fps, f"пик на {got:.3f}, ждали {want:.3f}"


def test_1b_a_hard_stop_reads_shorter_than_its_windup(tmp_path):
    """`stop` действительно мерит, чем останавливают палку.

    Долгий разгон и резкая остановка (rise=0.85) должны дать торможение
    короче замаха. Если метрика этого не различает, она бесполезна.
    """
    fps = 30
    path = motion_clips.sweep(tmp_path / "s.mp4", fps=fps, total=120,
                              a=30, b=75, rise=0.85)
    env, _ = build(path)
    peak = int(np.argmax(env.values))
    level = env.level_for(float(env.values[peak]))
    left = peak
    while left > 0 and env.values[left] > level:
        left -= 1
    right = peak
    while right < len(env.values) - 1 and env.values[right] > level:
        right += 1
    windup = (peak - left) / fps
    stop = (right - peak) / fps
    assert stop < windup, f"торможение {stop:.3f} не короче замаха {windup:.3f}"


# Уровень покоя на настоящих тренировочных видео, замер пробой: v1 0.00443,
# v2 0.00142, v3 0.00739. Остаток от подавленного скачка обязан быть ниже
# самого тихого из них, иначе на настоящем материале он читался бы как движение.
REAL_REST_LEVEL = 0.00142


def test_2_a_global_brightness_step_is_not_motion(tmp_path):
    """Автоэкспозиция: вся яркость разом выросла, движения нет.

    Проверяется не абсолютный остаток, а во сколько раз починка его подавила.
    Относительный порог здесь не годится: на синтетике неподвижные кадры
    воспроизводятся бит в бит, медиана разницы РОВНО ноль, и «в четыре раза
    выше медианы» вырождается в произвольное число.

    Второе утверждение важнее первого: остаток должен лежать ниже уровня
    покоя настоящих видео. Иначе подавление есть, а толку нет.
    """
    fps, total, at = 30, 120, 60
    path = motion_clips.bright_step(tmp_path / "b.mp4", fps=fps,
                                    total=total, at=at)
    clip = video.probe(path)
    frames = video.gray_frames(clip, width=160)
    window = slice(max(at - 3, 0), at + 3)

    # Без починки: разница кадров как есть.
    naive = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    fixed = envelope.raw_motion(frames)

    assert naive[window].max() > 0.10, (
        f"стенд не воспроизвёл скачок яркости: всего "
        f"{naive[window].max():.4f}")
    suppression = naive[window].max() / max(float(fixed[window].max()), 1e-12)
    assert suppression > 20.0, f"подавление всего {suppression:.1f}x"

    # Остаток от скачка — одиночный кадр. Классифицирует не он, а сглаженная
    # огибающая, и одиночный выброс это ровно то, для чего сглаживание стоит.
    smoothed = float(envelope.smooth(fixed, clip.fps)[window].max())
    assert smoothed < REAL_REST_LEVEL, (
        f"сглаженный остаток {smoothed:.5f} не ниже уровня покоя настоящих "
        f"видео {REAL_REST_LEVEL} (запас {REAL_REST_LEVEL / max(smoothed, 1e-12):.2f}x)")


def test_3_works_when_the_subject_never_leaves_the_frame(tmp_path):
    """Модели фона нет вовсе, поэтому объект может быть в кадре всегда.

    На настоящем материале медианный фон оказывался самим исполнителем, когда
    он стоял на месте, и маска ловила почти ничего.
    """
    fps = 30
    path = motion_clips.sweep(tmp_path / "s.mp4", fps=fps, total=120, a=30, b=60)
    env, _ = build(path)
    assert env.values.max() > env.strike_level, "всплеск не нашёлся"
    assert env.values[:20].mean() < env.strike_level, "покой принят за удар"


def test_4_the_same_motion_at_two_contrasts_normalises_together(tmp_path):
    """Порог не переносится между съёмками: v1 максимум 0.029, v2 — 0.014 при
    том же движении. После нормировки огибающие должны совпасть."""
    fps = 30
    strong, _ = build(motion_clips.sweep(tmp_path / "hi.mp4", fps=fps,
                                         total=120, a=30, b=60, contrast=1.0))
    weak, _ = build(motion_clips.sweep(tmp_path / "lo.mp4", fps=fps,
                                       total=120, a=30, b=60, contrast=0.35))
    n = min(len(strong.values), len(weak.values))
    ratio = strong.values[:n].max() / weak.values[:n].max()
    assert 0.9 <= ratio <= 1.1, f"после нормировки расходятся в {ratio:.2f} раза"


def test_scale_source_is_always_named(tmp_path):
    """Отчёт обязан сказать, какая нормировка применена, иначе числа между
    видео сравнивать нельзя."""
    env, _ = build(motion_clips.sweep(tmp_path / "s.mp4", fps=30,
                                      total=120, a=30, b=60))
    assert env.scale_source in {"поза", "разброс", "нет"}
    assert env.size_fix
