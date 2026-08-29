"""Замеры готового файла: громкость, пик, окна кратковременной громкости."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


@dataclass(frozen=True)
class Loudness:
    integrated_lufs: float
    true_peak_dbtp: float
    lra: float


def _loudnorm_json(cmd: list[str], what: str) -> dict:
    result = subprocess.run(cmd, capture_output=True, text=True)
    match = _LOUDNORM_JSON.search(result.stderr)
    if not match:
        raise RuntimeError(f"loudnorm не вернул JSON при замере {what}:\n{result.stderr[-2000:]}")
    return json.loads(match.group(0))


def measure_loudness(path: str) -> Loudness:
    data = _loudnorm_json([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ], path)
    return Loudness(
        integrated_lufs=float(data["input_i"]),
        true_peak_dbtp=float(data["input_tp"]),
        lra=float(data["input_lra"]),
    )


def measure_window(path: str, start: float, end: float) -> float:
    """Интегральная громкость участка. Нужна для проверки сжатия динамики."""
    data = _loudnorm_json([
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ], f"{path} [{start:.1f}-{end:.1f}]")
    return float(data["input_i"])


def measure_duration(path: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ], capture_output=True, text=True)
    return float(result.stdout.strip())


def peak_db(path: str | Path) -> float:
    """Пик файла в dBFS через volumedetect.

    Живёт здесь, а не в сборщике счёта: замер готового файла — ровно то, для
    чего модуль существует, а теперь пик понадобился и сборщику подсказок,
    чтобы выставить уровень подложки.

    Приведение по ПИКУ, а не по громкости: у счёта числительные разной длины,
    и loudnorm сделал бы короткое «три» громче длинного «четыре», хотя в
    счёте они обязаны звучать одинаково.
    """
    done = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    if done.returncode:
        raise SystemExit("ffmpeg: %s" % done.stderr[-1500:])
    for line in done.stderr.splitlines():
        if "max_volume:" in line:
            return float(line.split("max_volume:")[1].split("dB")[0].strip())
    raise SystemExit("volumedetect не вернул пик для %s" % path)
