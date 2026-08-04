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
    """Один вход ffmpeg.

    При loop=True перед путём идут -stream_loop -1 и -t: ограничение по времени
    обязательно, иначе бесконечный вход не отдаёт EOF и ffmpeg висит после того,
    как всё уже сведено.
    """

    path: str
    loop: bool
    duration: float | None = None


# Форма провала музыки под ударом, в секундах. Атака начинается раньше самого
# удара намеренно: замах стоит за 0.30–0.45 с до него, и музыка должна уйти вниз
# уже под замахом, иначе слышно, как она дёргается посередине движения.
DUCK_ATTACK = 0.30
DUCK_HOLD = 0.30
DUCK_RELEASE = 0.50


def pan_gains(pan: float) -> tuple[float, float]:
    """Панорама постоянной мощности: -1 левый край, +1 правый, 0 центр."""
    angle = (pan + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def duck_expression(tl: Timeline) -> str:
    """Выражение для volume: единица везде, провал под каждым ударом.

    Пустая строка означает, что уводить нечего.

    Форма трапеция: линейный вход за DUCK_ATTACK до удара, полка DUCK_HOLD,
    линейный выход за DUCK_RELEASE. Резкая ступенька щёлкает, а плавная кривая
    здесь не нужна: под ударом всё равно грохот.

    Наложения берутся по максимуму, а не суммой. Два удара в 0.6 с друг от друга
    (38.60 и 39.20) сложились бы в провал вдвое глубже заказанного, и музыка
    пропала бы между ними совсем.
    """
    ducks = [e for e in tl.events if e.duck_db > 0]
    if not ducks:
        return ""

    terms = []
    for ev in sorted(ducks, key=lambda e: e.t):
        start = ev.t - DUCK_ATTACK
        end = ev.t + DUCK_HOLD + DUCK_RELEASE
        # Огибающая 0..1: нарастает, держится, спадает. Оба края уходят в
        # отрицательные значения за пределами окна, и max(0,...) их срезает.
        env = (f"max(0\\,min(1\\,min((t-{start:.4f})/{DUCK_ATTACK:.4f}\\,"
               f"({end:.4f}-t)/{DUCK_RELEASE:.4f})))")
        depth = 1.0 - 10.0 ** (-ev.duck_db / 20.0)
        terms.append(f"{depth:.6f}*{env}")

    deepest = terms[0]
    for term in terms[1:]:
        deepest = f"max({deepest}\\,{term})"
    return f"1-({deepest})"


def _event_chain(index: int, ev: Event, sample_rate: int) -> str:
    left, right = pan_gains(ev.pan)
    steps = [
        f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo",
    ]

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

    # Полки, а не колокола: вес и щелчок дают целые области спектра, а не одна
    # частота. Ставятся до volume, чтобы гейн события считался от готового тембра.
    if ev.bass_db:
        steps.append(f"bass=g={ev.bass_db:.6f}:f=110:w=0.7")
    if ev.treble_db:
        # 2500, а не 3500: полоса, в которой мерится запас, начинается с 2000 Гц,
        # и полка с 3500 подняла его всего на 1.9 dB из заказанных шести.
        steps.append(f"treble=g={ev.treble_db:.6f}:f=2500:w=0.7")

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

    # Провал считается по событиям ударов, но применяется к музыке. Поэтому
    # duck_expression получает весь таймлайн, а не события своего стема: вторых
    # таймкодов в проекте нет, и заводить их ради этого нельзя.
    duck = duck_expression(tl) if stem == "music" else ""
    ducking = f",volume=volume='{duck}':eval=frame" if duck else ""

    if not events:
        graph = (
            f"anullsrc=r={sr}:cl=stereo,"
            f"atrim=0:{total:.6f},asetpts=PTS-STARTPTS[out]"
        )
        return graph, []

    inputs = [
        GraphInput(path=ev.asset, loop=ev.loop, duration=ev.duration) for ev in events
    ]
    chains = [_event_chain(i, ev, sr) for i, ev in enumerate(events)]
    labels = "".join(f"[e{i}]" for i in range(len(events)))

    mix = (
        f"{labels}amix=inputs={len(events)}:normalize=0:dropout_transition=0"
        f"{ducking},"
        f"apad,atrim=0:{total:.6f},asetpts=PTS-STARTPTS[out]"
    )
    return ";".join(chains + [mix]), inputs


def ffmpeg_input_args(inputs: list[GraphInput]) -> list[str]:
    args: list[str] = []
    for item in inputs:
        if item.loop:
            args += ["-stream_loop", "-1", "-t", f"{item.duration:.6f}"]
        args += ["-i", item.path]
    return args
