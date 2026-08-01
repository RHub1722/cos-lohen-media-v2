"""Чтение параметров аудиофайла через ffprobe."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class AudioInfo:
    path: str
    duration: float
    sample_rate: int
    channels: int


class ProbeError(Exception):
    pass


@lru_cache(maxsize=512)
def probe(path: str | Path) -> AudioInfo:
    path = str(path)
    if not Path(path).is_file():
        raise ProbeError(f"файл не найден: {path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels:format=duration",
        "-of", "json", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProbeError(f"ffprobe не смог прочитать {path}: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise ProbeError(f"в файле нет аудиопотока: {path}")

    stream = data["streams"][0]
    return AudioInfo(
        path=path,
        duration=float(data["format"]["duration"]),
        sample_rate=int(stream["sample_rate"]),
        channels=int(stream["channels"]),
    )
