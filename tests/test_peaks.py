import struct
import wave

import pytest

from src.peaks import PeakError, peak_offset, peak_offsets

SR = 48000


def _wav(path, spike_at: float, length: float = 1.0):
    """Тишина с одним щелчком в известном месте."""
    frames = bytearray()
    spike = int(spike_at * SR)
    for i in range(int(length * SR)):
        value = 30000 if i == spike else 0
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(bytes(frames))


def test_peak_offset_finds_a_known_peak(tmp_path):
    path = tmp_path / "click.wav"
    _wav(path, 0.4)
    assert peak_offset(path) == pytest.approx(0.4, abs=0.001)


def test_peak_offset_of_a_peak_at_the_very_start_is_zero(tmp_path):
    path = tmp_path / "hit.wav"
    _wav(path, 0.0)
    assert peak_offset(path) == pytest.approx(0.0, abs=0.001)


def test_peak_offsets_keys_are_the_paths_from_the_scenario(tmp_path):
    (tmp_path / "sfx").mkdir()
    _wav(tmp_path / "sfx" / "a.wav", 0.25)
    _wav(tmp_path / "sfx" / "b.wav", 0.75)
    out = peak_offsets(tmp_path, ["sfx/a.wav", "sfx/b.wav", "sfx/a.wav"])
    assert sorted(out) == ["sfx/a.wav", "sfx/b.wav"]
    assert out["sfx/a.wav"] == pytest.approx(0.25, abs=0.001)


def test_peak_offset_complains_loudly_about_a_missing_file(tmp_path):
    """Молчаливый ноль здесь опаснее падения: он поставил бы удар на начало
    файла, и промах в треть секунды никто бы не заметил."""
    with pytest.raises(PeakError):
        peak_offset(tmp_path / "no_such.wav")


def test_the_real_whoosh_peaks_late_and_the_real_impact_peaks_at_once():
    """Ловушка проекта: у быстрого взмаха пик на 0.376 с, у удара — сразу.
    Если эти числа поменяются после перегенерации ассета, вся боевая сетка
    тренажёра уедет, и узнать об этом надо здесь, а не на репетиции."""
    got = peak_offsets("assets", ["sfx/spear_whoosh_fast.wav",
                                  "sfx/spear_staff_impact.wav",
                                  "sfx/spear_armor_impact.wav"])
    assert got["sfx/spear_whoosh_fast.wav"] == pytest.approx(0.376, abs=0.01)
    assert got["sfx/spear_staff_impact.wav"] < 0.05
    assert got["sfx/spear_armor_impact.wav"] < 0.06
