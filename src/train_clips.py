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
import re
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

# Идентификатор задания на сервере: тридцать два знака в шестнадцатеричном
# виде. По нему клип забирается обратно без повторной оплаты, и он же связывает
# принятую попытку со строкой в docs/atlas-ledger.csv.
PREDICTION = re.compile(r"^[0-9a-f]{32}$")


def attempt_name(cid: str, number: int) -> str:
    """Имя файла попытки в assets/train_clips/.

    Одно на проект: так называет файл tools/atlas_train.py при скачивании, и по
    этому же имени страница тренажёра находит принятую попытку. Рядом лежат
    отклонённые попытки с похожими именами, так что складывать это имя в двух
    местах нельзя — разойдётся, и на сайт уедет отклонённый клип.
    """
    return "%s_a%d.mp4" % (cid, number)


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
    beats: tuple[int, ...]     # номера долей удара, которые клип показывает
    attempt: int         # какая попытка признана годной
    prediction: str      # её задание на сервере, ключ к docs/atlas-ledger.csv
    watch: str           # что на клипе смотреть
    missing: tuple[str, ...]   # чего на клипе нет — это важнее того, что есть

    @property
    def refs(self) -> tuple[Path, ...]:
        """Всё, что уходит в reference_images, в порядке отправки."""
        return self.faces + self.panels

    @property
    def slow(self) -> float:
        return self.duration / self.real

    @property
    def accepted(self) -> str:
        """Имя файла принятой попытки в assets/train_clips/."""
        return attempt_name(self.id, self.attempt)


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


def caveat(path: Path | str = CLIPS) -> str:
    """Общая оговорка ко всем клипам: чего они не показывают в принципе.

    Лежит одной строкой на файл, а не копией в каждом клипе, по той же причине,
    по которой так лежит описание персонажа: семь копий разойдутся. На странице
    она стоит один раз в начале раздела.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    text = str(raw.get("общая оговорка", "")).strip()
    if not text:
        raise ClipError("в файле нет общей оговорки. Без неё раздел на сайте "
                        "выглядит как метроном, а доли внутри клипов стоят не "
                        "там, где их считает сценарий")
    return text


def load(strikes, path: Path | str = CLIPS,
         require_refs: bool = True) -> list[Clip]:
    """Задания вместе с подстановкой темпа из долей удара.

    `strikes` — уже разрешённые удары из src.strikes.resolve_strikes: времена
    берутся оттуда, потому что в самом сценарии они лежат смещениями от
    звуковых событий, а не абсолютными числами.

    `require_refs` — требовать, чтобы картинки входа лежали на диске. Для
    генерации это обязательно: за задание платят, и уехавшая молча поза дорога.
    Но и панели, и официальный арт производные или чужие, и обе папки в
    .gitignore, — а страница тренажёра собирается из свежего клона, где их нет,
    и никаких картинок на сервер не отправляет. Проверка защищает генерацию, а
    не сборку страницы, поэтому она выключаемая.
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
    if lost and require_refs:
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
        lost_panels = [p.name for p in panels if not p.exists()]
        if lost_panels and require_refs:
            raise ClipError(
                "клип %s: нет панелей %s в %s. Нарезать: python tools/cut_panels.py"
                % (cid, ", ".join(lost_panels), PANELS.relative_to(ROOT)))

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

        # Какая попытка признана годной. Рядом на диске лежат отклонённые —
        # копьё вверх ногами, наезд камеры, двухголовое оружие, — и отличаются
        # они от принятой одной цифрой в имени. Выбирать файл по последней
        # попытке нельзя: последняя не значит лучшая.
        pub = item.get("публикация") or {}
        attempt = int(pub.get("попытка", 0))
        if attempt < 1:
            raise ClipError(
                "клип %s не говорит, какая попытка принята. Рядом лежат "
                "отклонённые с похожими именами, и страница взяла бы любую" % cid)
        prediction = str(pub.get("prediction", "")).strip()
        if not PREDICTION.match(prediction):
            raise ClipError(
                "клип %s: prediction %r не похож на задание Atlas. По нему клип "
                "забирается обратно без повторной оплаты и сверяется со строкой "
                "в docs/atlas-ledger.csv" % (cid, prediction))
        watch = str(pub.get("смотреть", "")).strip()
        if not watch:
            raise ClipError("клип %s не говорит, что на нём смотреть. Без этого "
                            "раздел на сайте — просто семь плееров" % cid)
        # «Чего нет» обязательно у каждого клипа, и это не формальность: клип
        # показывает, КАК выглядит движение, но врёт про то, КОГДА оно
        # случается. Не написать этого рядом с плеером значит учить репетировать
        # под клип вместо звука.
        gaps = tuple(str(x).strip() for x in pub.get("чего нет", [])
                     if str(x).strip())
        if not gaps:
            raise ClipError(
                "клип %s не говорит, чего на нём нет. У каждого из семи есть что "
                "сказать: у финала нет переворота копья, у приёма удара корпус не "
                "замирает, у вспышки 3 весь оборот кончается на половине клипа" % cid)

        out.append(Clip(id=cid, strike=strike_id,
                        title=str(item.get("title", cid)),
                        duration=duration,
                        resolution=str(item.get("resolution", "480p")),
                        faces=faces, panels=panels,
                        prompt=prompt, negative=negative,
                        real=real, first=first, last=last,
                        beats=tuple(numbers),
                        attempt=attempt, prediction=prediction,
                        watch=watch, missing=gaps))

    if not out:
        raise ClipError("в файле нет ни одного клипа")
    return out
