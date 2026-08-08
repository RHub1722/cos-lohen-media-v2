"""Сверка звука страницы с фонограммой номера.

Главный тест здесь — подменённая середина. Именно так и разошлось в жизни:
допрос и финал совпадали, а бой в середине был переделан целиком, и среднее по
файлу это бы спрятало.
"""

import struct
import wave

import numpy as np
import pytest

from src.soundcheck import SoundcheckError, check, match_windows

SR = 16000


def _wav(path, seed: int, seconds: float = 15.0, swap=None):
    """Шум с известным зерном. swap=(t0, t1) — кусок из другого зерна."""
    rng = np.random.default_rng(seed)
    samples = (rng.standard_normal(int(seconds * SR)) * 8000).astype(np.int16)
    if swap:
        other = np.random.default_rng(seed + 1000)
        i0, i1 = int(swap[0] * SR), int(swap[1] * SR)
        samples[i0:i1] = (other.standard_normal(i1 - i0) * 8000).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def test_the_same_soundtrack_matches_everywhere(tmp_path):
    a = _wav(tmp_path / "a.wav", seed=1)
    windows = check(a, a)
    assert len(windows) == 3
    assert all(corr > 0.99 for _, corr in windows)


def test_a_different_soundtrack_is_caught(tmp_path):
    a = _wav(tmp_path / "a.wav", seed=1)
    b = _wav(tmp_path / "b.wav", seed=2)
    with pytest.raises(SoundcheckError):
        check(a, b)


def test_a_substituted_middle_is_caught(tmp_path):
    """Ровно наш случай: края совпадают, середина переделана.

    Среднее по файлу здесь остаётся высоким, и одним числом на весь файл такую
    подмену не увидеть. Поэтому окнами.
    """
    master = _wav(tmp_path / "master.wav", seed=7)
    video = _wav(tmp_path / "video.wav", seed=7, swap=(5.0, 10.0))

    windows = match_windows(video, master)
    assert windows[0][1] > 0.99, "первое окно должно совпадать"
    assert windows[2][1] > 0.99, "последнее окно должно совпадать"
    assert windows[1][1] < 0.2, "подменённое окно должно провалиться"

    with pytest.raises(SoundcheckError) as exc:
        check(video, master)
    # Ошибка обязана называть, ГДЕ не совпало: «не совпало» без места — это
    # повод гадать, а гадать тут не о чем.
    assert "5.0" in str(exc.value)


def test_a_missing_file_is_loud(tmp_path):
    """Молчаливое «совпадает» здесь опаснее падения: страница уехала бы на
    планшет с чужим звуком, и заметить это можно было бы только ушами."""
    a = _wav(tmp_path / "a.wav", seed=1)
    with pytest.raises(SoundcheckError):
        check(tmp_path / "no_such.mp4", a)


def test_a_file_without_a_soundtrack_is_loud(tmp_path):
    silent = tmp_path / "empty.wav"
    with wave.open(str(silent), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(b"")
    with pytest.raises(SoundcheckError):
        check(silent, _wav(tmp_path / "a.wav", seed=1))
