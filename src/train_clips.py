"""Тренировочные клипы: задания на генерацию видео по панелям листов движений.

Читает scenario/train_clips.json, но своих чисел про время не имеет ни одного:
длину движения и множитель замедления считает из scenario/strikes.json и
подставляет в промпт вместо {real} и {slow}. Сдвинется доля в сценарии —
поедет и промпт, а не разойдётся с ним молча.

Проверок здесь больше, чем кода, и все они про то, что дороже опечатки: за
каждое задание платят деньги, а понять по готовому видео, что промпт врал про
темп или что одна поза не уехала на сервер, нельзя.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIPS = ROOT / "scenario/train_clips.json"
PANELS = ROOT / "assets/sheets/panels"

# Длительности, которые принимает модель. Список из схемы, docs/atlas-api.md:
# -1 значит «сколько выйдет», и нам он не нужен — длина клипа задаёт замедление.
DURATIONS = tuple(range(4, 16))

# Больше девяти референсов поле reference_images не берёт.
MAX_REFS = 9

PLACEHOLDERS = ("{real}", "{slow}")


class ClipError(Exception):
    pass


@dataclass(frozen=True)
class Clip:
    """Одно задание на генерацию."""

    id: str
    strike: str
    title: str
    duration: int
    resolution: str
    panels: tuple[Path, ...]
    prompt: str
    negative: str
    real: float          # сколько длится движение на самом деле, секунды
    first: float         # время первой доли клипа
    last: float          # время последней

    @property
    def slow(self) -> float:
        return self.duration / self.real


def _fmt_slow(value: float) -> str:
    """Множитель замедления словами модели: «4x», а не «4.09090909x»."""
    return "%.1fx" % value if value < 10 else "%.0fx" % value


def load(strikes, path: Path | str = CLIPS) -> list[Clip]:
    """Задания вместе с подстановкой темпа из долей удара.

    `strikes` — уже разрешённые удары из src.strikes.resolve_strikes: времена
    берутся оттуда, потому что в самом сценарии они лежат смещениями от
    звуковых событий, а не абсолютными числами.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    negative = str(raw.get("общий запрет", "")).strip()
    if not negative:
        raise ClipError("в файле нет общего запрета — модель не имеет "
                        "отдельного поля запретов, и без него в кадр уедет текст")

    by_id = {s.id: s for s in strikes}
    out: list[Clip] = []
    seen: set[str] = set()

    for item in raw.get("clips", []):
        cid = str(item.get("id", "")).strip()
        if not cid:
            raise ClipError("клип без id: %s" % item)
        if cid in seen:
            raise ClipError("клип %s объявлен дважды" % cid)
        seen.add(cid)

        strike_id = str(item.get("strike", "")).strip()
        strike = by_id.get(strike_id)
        if strike is None:
            raise ClipError("клип %s ссылается на удар %r, которого нет в "
                            "strikes.json. Есть: %s"
                            % (cid, strike_id, ", ".join(by_id)))

        # Предел на референсы проверяется ПЕРВЫМ: это свойство самого запроса,
        # а не долей. Иначе клип с одиннадцатью панелями падал бы на порядке
        # долей, и сообщение уводило бы от настоящей причины.
        panels = tuple(PANELS / str(name) for name in item.get("panels", []))
        if not panels:
            raise ClipError("клип %s без панелей" % cid)
        if len(panels) > MAX_REFS:
            raise ClipError("клип %s: панелей %d, модель берёт не больше %d"
                            % (cid, len(panels), MAX_REFS))

        numbers = [int(n) for n in item.get("beats", [])]
        if not numbers:
            raise ClipError("клип %s не говорит, какие доли он показывает" % cid)
        bad = [n for n in numbers if not 1 <= n <= len(strike.beats)]
        if bad:
            raise ClipError("клип %s: у удара %s всего %d долей, а просят %s"
                            % (cid, strike_id, len(strike.beats), bad))
        if numbers != sorted(numbers):
            raise ClipError("клип %s: доли идут не по порядку: %s" % (cid, numbers))
        beats = [strike.beats[n - 1] for n in numbers]

        if len(panels) != len(beats):
            raise ClipError(
                "клип %s: долей %d, а панелей %d. Одна поза уехала бы на сервер "
                "молча, и на готовом видео этого не увидеть"
                % (cid, len(beats), len(panels)))
        missing = [p.name for p in panels if not p.exists()]
        if missing:
            raise ClipError(
                "клип %s: нет панелей %s в %s. Нарезать: python tools/cut_panels.py"
                % (cid, ", ".join(missing), PANELS.relative_to(ROOT)))

        duration = int(item.get("duration", 0))
        if duration not in DURATIONS:
            raise ClipError("клип %s: длина %s, а модель принимает только %s"
                            % (cid, duration, ", ".join(map(str, DURATIONS))))

        first, last = beats[0].heard, beats[-1].heard
        real = round(last - first, 2)
        if real <= 0:
            raise ClipError("клип %s: доли с %.2f по %.2f, длина движения не "
                            "положительная" % (cid, first, last))

        template = str(item.get("prompt", ""))
        for mark in PLACEHOLDERS:
            if mark not in template:
                raise ClipError(
                    "клип %s: в промпте нет %s. Темп обязан подставляться из "
                    "долей, иначе он разойдётся со сценарием молча" % (cid, mark))
        prompt = (template
                  .replace("{real}", "%.2f" % real)
                  .replace("{slow}", _fmt_slow(duration / real)))
        left = [c for c in "{}" if c in prompt]
        if left:
            raise ClipError("клип %s: в промпте осталась незакрытая подстановка "
                            "— на сервер уехали бы фигурные скобки" % cid)

        out.append(Clip(id=cid, strike=strike_id,
                        title=str(item.get("title", cid)),
                        duration=duration,
                        resolution=str(item.get("resolution", "480p")),
                        panels=panels, prompt=prompt, negative=negative,
                        real=real, first=first, last=last))

    if not out:
        raise ClipError("в файле нет ни одного клипа")
    return out
