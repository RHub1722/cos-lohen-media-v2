"""Построение filter_complex для одного стема.

Чистые функции: FFmpeg здесь не вызывается и файлы не читаются. Модуль вынесен
отдельно от render_audio именно потому, что это единственная сложная логика в
проекте, и ошибка в ней даёт не падение, а тихо неправильный звук.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.models import Event, Timeline


@dataclass(frozen=True)
class GraphInput:
    """Один вход ffmpeg: -i <path>, при loop=True перед ним идёт -stream_loop -1."""

    path: str
    loop: bool


def pan_gains(pan: float) -> tuple[float, float]:
    """Панорама постоянной мощности: -1 левый край, +1 правый, 0 центр."""
    angle = (pan + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _event_chain(index: int, ev: Event, sample_rate: int) -> str:
    left, right = pan_gains(ev.pan)
    steps = [
        f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo",
    ]

    # Обрезка нужна только петлям: -stream_loop -1 даёт бесконечный поток,
    # и без atrim граф никогда не закончится.
    if ev.duration is not None:
        steps.append(f"atrim=0:{ev.duration:.6f}")
        steps.append("asetpts=PTS-STARTPTS")

    if ev.fade_in > 0:
        steps.append(f"afade=t=in:st=0:d={ev.fade_in:.6f}")

    # Фейд на выходе ставится только там, где известна длина. У одиночных
    # эффектов её нет, и обрезать им естественный хвост нельзя.
    if ev.fade_out > 0 and ev.duration is not None:
        fade_start = max(0.0, ev.duration - ev.fade_out)
        steps.append(f"afade=t=out:st={fade_start:.6f}:d={ev.fade_out:.6f}")

    steps.append(f"volume={ev.gain_db:.6f}dB")
    steps.append(f"pan=stereo|c0={left:.6f}*c0|c1={right:.6f}*c1")

    delay_ms = int(round(ev.t * 1000))
    steps.append(f"adelay={delay_ms}|{delay_ms}")

    return f"[{index}:a]" + ",".join(steps) + f"[e{index}]"


def build_stem_graph(tl: Timeline, stem: str) -> tuple[str, list[GraphInput]]:
    """Строка filter_complex и список входов в порядке их индексов.

    Пустой стем возвращает граф из источника тишины и пустой список входов —
    такому вызову ffmpeg вообще не нужен -i.
    """
    events = tl.by_stem(stem)
    total = tl.total_duration
    sr = tl.sample_rate

    if not events:
        graph = (
            f"anullsrc=r={sr}:cl=stereo,"
            f"atrim=0:{total:.6f},asetpts=PTS-STARTPTS[out]"
        )
        return graph, []

    inputs = [GraphInput(path=ev.asset, loop=ev.duration is not None) for ev in events]
    chains = [_event_chain(i, ev, sr) for i, ev in enumerate(events)]
    labels = "".join(f"[e{i}]" for i in range(len(events)))

    mix = (
        f"{labels}amix=inputs={len(events)}:normalize=0:dropout_transition=0,"
        f"apad,atrim=0:{total:.6f},asetpts=PTS-STARTPTS[out]"
    )
    return ";".join(chains + [mix]), inputs


def ffmpeg_input_args(inputs: list[GraphInput]) -> list[str]:
    args: list[str] = []
    for item in inputs:
        if item.loop:
            args += ["-stream_loop", "-1"]
        args += ["-i", item.path]
    return args
