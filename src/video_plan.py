"""План картинки: состояния и якоря выводятся из сценария, а не задаются здесь.

Модуль ничего не знает ни про numpy, ни про FFmpeg — только про то, что и когда
происходит. Отдельно от рендерера по той же причине, по которой `models.py`
отделён от `render_audio.py`: разбор сценария можно проверить тестами, не
нарисовав ни одного кадра.

Единственный источник таймкодов — блоки `video` в `scenario/timeline.json`.
Если реплику передвинули, картинка едет за ней сама.
"""

from __future__ import annotations

from dataclasses import dataclass

STATES = ("interrogation", "combat", "ice")

# Сколько живёт эффект якоря, секунды. None означает «до конца своего
# состояния», а для freeze — до конца номера: он и задуман как точка, после
# которой не двигается ничего.
CUE_LENGTHS: dict[str, float | None] = {
    "state": 0.0,
    "flash": 0.22,
    "whiteflash": 0.90,
    "tighten": None,
    "drain": None,
    "freeze": None,
}


class VideoPlanError(Exception):
    """Блок video в сценарии не соответствует схеме."""


@dataclass(frozen=True)
class Segment:
    """Отрезок одного состояния палитры."""

    state: str
    start: float
    end: float

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class Cue:
    """Якорь: короткий эффект поверх состояния.

    source — идентификатор звукового события, из которого якорь взялся. Нужен
    только для сообщений об ошибках: без него непонятно, какую строку сценария
    править.
    """

    kind: str
    t: float
    end: float
    intensity: float
    source: str

    def phase(self, t: float) -> float | None:
        """0.0 в начале якоря, 1.0 в конце. Вне якоря — None."""
        if not (self.t <= t < self.end):
            return None
        span = self.end - self.t
        return 0.0 if span <= 0 else (t - self.t) / span


@dataclass(frozen=True)
class VideoPlan:
    segments: tuple[Segment, ...]
    cues: tuple[Cue, ...]
    total: float

    def state_at(self, t: float) -> str:
        for seg in self.segments:
            if seg.contains(t):
                return seg.state
        return self.segments[-1].state  # ровно на total_duration

    def segment_at(self, t: float) -> Segment:
        for seg in self.segments:
            if seg.contains(t):
                return seg
        return self.segments[-1]

    def active(self, t: float) -> tuple[Cue, ...]:
        return tuple(c for c in self.cues if c.phase(t) is not None)


def _anchors(raw_events: list[dict]) -> list[tuple[float, str, dict, str]]:
    found = []
    for e in raw_events:
        video = e.get("video")
        if video is None:
            continue
        source = str(e.get("id", "<без id>"))
        if "cue" not in video:
            raise VideoPlanError(f"{source}: в блоке video нет поля cue")
        found.append((float(e["t"]), str(video["cue"]), video, source))
    return sorted(found, key=lambda a: a[0])


def build_plan(raw_events: list[dict], total: float) -> VideoPlan:
    """Собирает состояния и якоря из сырых событий сценария.

    Проверок здесь больше, чем кажется нужным, ровно потому, что ошибка в блоке
    video не падает, а тихо рисует не то: пропущенный `state` в начале оставит
    первые секунды без палитры, а опечатка в имени якоря просто не сработает —
    и заметить это можно будет только на экране в зале.
    """
    anchors = _anchors(raw_events)
    if not anchors:
        raise VideoPlanError("в сценарии нет ни одного блока video")

    states = [a for a in anchors if a[1] == "state"]
    if not states:
        raise VideoPlanError("в сценарии нет ни одного якоря cue=state")
    if abs(states[0][0]) > 1e-9:
        raise VideoPlanError(
            f"первый якорь состояния стоит на {states[0][0]}, а должен на 0.0: "
            "иначе у начала номера нет палитры"
        )

    segments: list[Segment] = []
    for i, (t, _cue, video, source) in enumerate(states):
        state = str(video.get("state", ""))
        if state not in STATES:
            raise VideoPlanError(
                f"{source}: неизвестное состояние {state!r}, допустимы {STATES}"
            )
        end = states[i + 1][0] if i + 1 < len(states) else total
        if end <= t:
            raise VideoPlanError(
                f"{source}: состояние {state!r} начинается на {t} и кончается на "
                f"{end} — нулевая или отрицательная длина"
            )
        segments.append(Segment(state=state, start=t, end=end))

    cues: list[Cue] = []
    for t, kind, video, source in anchors:
        if kind == "state":
            continue
        if kind not in CUE_LENGTHS:
            raise VideoPlanError(
                f"{source}: неизвестный якорь {kind!r}, "
                f"допустимы {tuple(k for k in CUE_LENGTHS if k != 'state')}"
            )
        intensity = float(video.get("intensity", 1.0))
        if not 0.0 <= intensity <= 1.0:
            raise VideoPlanError(
                f"{source}: intensity={intensity} вне диапазона 0..1"
            )
        if t > total:
            raise VideoPlanError(f"{source}: якорь на {t} за концом номера ({total})")

        length = CUE_LENGTHS[kind]
        if length is not None:
            end = min(t + length, total)
        elif kind == "freeze":
            end = total
        else:
            # tighten и drain работают до смены палитры: оба готовят зал к
            # следующему состоянию, и обрывать их раньше нечем.
            seg = next((s for s in segments if s.contains(t)), segments[-1])
            end = seg.end
        if end <= t:
            raise VideoPlanError(
                f"{source}: якорь {kind!r} на {t} не успевает ничего сделать до {end}"
            )
        cues.append(Cue(kind=kind, t=t, end=end, intensity=intensity, source=source))

    return VideoPlan(segments=tuple(segments), cues=tuple(cues), total=float(total))
