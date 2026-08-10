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
# Референсы внешности — официальный арт, а не наши листы: на листах персонаж
# уехал в русого в тёмно-синем сюртуке, и брать облик оттуда нельзя.
FACES = ROOT / "assets/screenshots"

# Длительности, которые принимает модель. Список из схемы, docs/atlas-api.md:
# -1 значит «сколько выйдет», и нам он не нужен — длина клипа задаёт замедление.
DURATIONS = tuple(range(4, 16))

# Больше девяти референсов поле reference_images не берёт.
MAX_REFS = 9

PLACEHOLDERS = ("{who}", "{shot}", "{char}", "{poses}", "{real}", "{slow}")

# Панелей на клип. Замер первого захода: при шести панелях против двух
# референсов внешности персонаж уехал в русого с листов на две секунды, при
# трёх-четырёх выстоял. Неверная внешность на входе побеждает, когда её втрое
# больше — см. docs/status/2026-08-10-train-clips.md.
MAX_PANELS = 4


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
    faces: tuple[Path, ...]   # референсы внешности, уходят ПЕРВЫМИ
    panels: tuple[Path, ...]  # позы, уходят после них
    prompt: str
    negative: str
    real: float          # сколько длится движение на самом деле, секунды
    first: float         # время первой доли клипа
    last: float          # время последней

    @property
    def refs(self) -> tuple[Path, ...]:
        """Всё, что уходит в reference_images, в порядке отправки."""
        return self.faces + self.panels

    @property
    def slow(self) -> float:
        return self.duration / self.real


def _fmt_slow(value: float) -> str:
    """Множитель замедления словами модели: «4x», а не «4.09090909x»."""
    return "%.1fx" % value if value < 10 else "%.0fx" % value


def _span(first: int, last: int) -> str:
    """Как назвать модели диапазон картинок: она адресует их словом image N."""
    if first == last:
        return "image %d" % first
    if last == first + 1:
        return "images %d and %d" % (first, last)
    return "images %d-%d" % (first, last)


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

    # Внешность описана ОДИН раз на весь файл. Шесть копий уже расходились —
    # так у листов движений персонаж и превратился из Лоэна в русого.
    character = raw.get("character") or {}
    who = str(character.get("описание", "")).strip()
    if not who:
        raise ClipError("в файле нет описания персонажа. Без него модель возьмёт "
                        "облик с панелей, а там он неверный")
    shot = str(raw.get("кадр", "")).strip()
    if not shot:
        raise ClipError("в файле нет правил кадра. Без них камера уезжает сама: "
                        "у вспышки 4 она наехала и тело вышло из кадра")
    faces = tuple(FACES / str(name) for name in character.get("refs", []))
    if not faces:
        raise ClipError("в файле нет референсов внешности. Одного описания "
                        "словами мало: проверено на листах, персонаж уезжает")
    lost = [p.name for p in faces if not p.exists()]
    if lost:
        raise ClipError("нет референсов внешности %s в %s"
                        % (", ".join(lost), FACES.relative_to(ROOT)))

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
        if len(panels) > MAX_PANELS:
            raise ClipError(
                "клип %s: панелей %d, а больше %d держать нельзя — при шести "
                "персонаж уезжает в русого с листов. Разбей клип на части, как "
                "burst_3a и burst_3b" % (cid, len(panels), MAX_PANELS))
        if len(faces) + len(panels) > MAX_REFS:
            raise ClipError(
                "клип %s: референсов %d (внешность %d + позы %d), модель берёт "
                "не больше %d" % (cid, len(faces) + len(panels), len(faces),
                                  len(panels), MAX_REFS))

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
        # Номера картинок считаются из фактического порядка отправки: сначала
        # внешность, потом позы. Руками их писать нельзя — добавится референс,
        # и промпт начнёт показывать модели не на те картинки.
        prompt = (template
                  .replace("{who}", who)
                  .replace("{shot}", shot)
                  .replace("{char}", _span(1, len(faces)))
                  .replace("{poses}", _span(len(faces) + 1,
                                            len(faces) + len(panels)))
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
                        faces=faces, panels=panels,
                        prompt=prompt, negative=negative,
                        real=real, first=first, last=last))

    if not out:
        raise ClipError("в файле нет ни одного клипа")
    return out
