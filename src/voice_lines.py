"""Реплики номера и сколько секунд есть у каждой.

Один список реплик на все способы озвучки. У Seed Audio подача задаётся прозой
в поле `direction`, у ElevenLabs — разметкой в поле `tags`; текст реплики при
этом один и тот же. Разведи их по двум файлам, и однажды актёр прочитает одну
версию, а в сценарий встанет другая.

Бюджет секунд здесь не хранится: он считается из scenario/timeline.json. Два
списка одного и того же расходятся молча — этот проект уже платил за такое
расхождением movements.json и strikes.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.models import Timeline

ROOT = Path(__file__).resolve().parents[1]
LINES_PATH = ROOT / "scenario" / "voices_ru.json"


class LineError(Exception):
    """Список реплик не соответствует схеме или ссылается в пустоту."""


@dataclass(frozen=True)
class Line:
    """Реплика: что произносится и как это играть."""

    event: str
    line: str
    direction: str
    tags: str = ""
    # Та же подача словами для живого исполнителя, по-русски. Модель и актёр
    # читают указание по-разному, поэтому полей три, а намерение одно.
    play: str = ""
    note: str = ""
    # Жёсткий предел, когда стена не следующая реплика, а звук. У «...Серьёзно?»
    # до следующей реплики 2.00 с, но на 42.80 идёт удар по Лоэну, и фраза
    # обязана кончиться раньше. Без этого поля лист врал бы исполнителю.
    limit: float | None = None
    # Темп для конкретной реплики. Общий множитель на весь номер не годится:
    # крик охранника от замедления перестаёт быть криком, а у «...Серьёзно?»
    # до удара по Лоэну всего 1.20 с, и растягивать её некуда.
    speed: float | None = None

    @property
    def prompt(self) -> str:
        """Промпт для Seed Audio: ремарка прозой, реплика в лапках.

        Лапки — единственный маркер, отделяющий произносимое от указания. Без
        них модель читает ремарку вслух; проверяется длиной результата.
        """
        return f"{self.direction}: «{self.line}»"

    @property
    def tagged(self) -> str:
        """Текст для ElevenLabs: разметка перед репликой.

        У v3 разметка в квадратных скобках — указание, а не текст. На коротких
        репликах она иногда произносится вслух, и это тоже ловится длиной.
        """
        return f"{self.tags} {self.line}".strip() if self.tags else self.line


def load_lines(path: Path = LINES_PATH) -> list[Line]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: list[Line] = []
    seen: set[str] = set()
    for item in raw.get("lines", []):
        for field in ("event", "line", "direction"):
            if not str(item.get(field, "")).strip():
                raise LineError(f"реплика без поля {field!r}: {item}")
        event = str(item["event"])
        if event in seen:
            raise LineError(f"реплика {event!r} описана дважды")
        seen.add(event)
        speed = item.get("speed")
        limit = item.get("limit")
        out.append(Line(event=event, line=str(item["line"]),
                        direction=str(item["direction"]),
                        tags=str(item.get("tags", "")),
                        play=str(item.get("play", "")),
                        note=str(item.get("note", "")),
                        limit=float(limit) if limit is not None else None,
                        speed=float(speed) if speed is not None else None))
    if not out:
        raise LineError(f"в {path} нет ни одной реплики")
    return out


def budgets(tl: Timeline) -> dict[str, float]:
    """Сколько секунд есть у каждой реплики до следующей.

    Стена — следующая реплика: две реплики поверх друг друга недопустимы в
    любом случае, а удары и щелчки под речью идут штатно и стеной не являются.
    Там, где реплика обязана кончиться раньше из-за удара, это записано в
    поле note у самой реплики.
    """
    voices = sorted([e for e in tl.events if e.asset.startswith("voices/")],
                    key=lambda e: e.t)
    out: dict[str, float] = {}
    for i, event in enumerate(voices):
        nxt = voices[i + 1].t if i + 1 < len(voices) else tl.total_duration
        out[event.id] = round(nxt - event.t, 3)
    return out


# Запас на квантование и на попадание в ноль. Преобразование голоса даёт
# расхождение до 0.02 с на кадре mp3, но целиться в лимит вплотную значит
# однажды промахнуться на сотую и переписывать дубль из-за неё.
MARGIN = 0.15


def effective_budget(line: Line, room: dict[str, float]) -> float:
    """Настоящий предел реплики: меньшее из «до следующей» и жёсткого лимита."""
    budget = room[line.event]
    return min(budget, line.limit) if line.limit is not None else budget


def check_events(lines: list[Line], tl: Timeline) -> None:
    """Каждая реплика обязана иметь своё событие в сценарии.

    Иначе её некуда ставить, и обнаружилось бы это после генерации, то есть
    после траты.
    """
    known = {e.id for e in tl.events if e.asset.startswith("voices/")}
    missing = [line.event for line in lines if line.event not in known]
    if missing:
        raise LineError(
            f"нет таких событий в timeline.json: {missing} — репликам некуда "
            "встать")


TAKES = ROOT / "assets" / "voices" / "archive" / "takes"


def sheet(lines: list[Line], room: dict[str, float], tl: Timeline,
          out: Path | None = None, refs: dict[str, float] | None = None) -> Path:
    """Лист для записи голосом под преобразование голоса.

    Печатается из того же списка и тех же бюджетов, что уходят в генерацию.
    `refs` — длительности готовых генераций, они служат ориентиром по темпу:
    в эту длину реплика уже влезала.
    """
    out = out or ROOT / "output" / "voice_recording_sheet.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    by_id = {e.id: e for e in tl.events}
    refs = refs or {}

    ranked = sorted(lines, key=lambda ln: effective_budget(ln, room))
    tightest = ranked[0]

    body = [
        "# Лист записи: 13 реплик по-русски",
        "",
        "Порядок — как в номере. Самая тесная реплика — "
        f"**`{tightest.event}`**: на неё есть "
        f"{effective_budget(tightest, room) - MARGIN:.2f} с.",
        "",
        "## Главное про длину",
        "",
        "**Преобразование голоса сохраняет твой тайминг ровно.** Проверено:",
        "4.86 с записи дали 4.88 с на выходе. Модель меняет тембр, но не",
        "растягивает и не сжимает время. Значит секунды — требование, и попасть",
        "в них можешь только ты.",
        "",
        "У каждой реплики два числа:",
        "",
        "- **цель** — на это и целься. Тут уже учтён запас "
        f"{MARGIN:.2f} с и, где надо, удар, который наступает раньше следующей "
        "реплики.",
        "- **ориентир** — столько заняла готовая генерация тем же голосом. В неё",
        "  реплика точно влезает, и держать её в голове проще, чем предел.",
        "",
        "Длиннее цели — придётся переписывать: подрезать нечем, а растяжка темпа",
        "ломает ровно то, ради чего ты записываешь.",
        "",
        "## Как писать",
        "",
        "- **Не подражай тембру Лоэна.** Тембр будет заменён целиком, и попытка",
        "  его изобразить только зажмёт тебе игру. Играй своим голосом.",
        "- **Динамика переносится как есть.** Шёпот останется шёпотом, крик —",
        "  криком. Играй широко: что покажется перебором, на выходе станет ровно",
        "  тем, что нужно.",
        "- Микрофон на одном расстоянии от лица во всех дублях. Смена дистанции",
        "  посреди номера читается как смена человека.",
        "- **Не в перегруз.** В прошлой записи два дубля заключённого пришли с",
        "  пиком −1.1 и −0.0 dB — это на грани. Тихую запись вылечить можно,",
        "  перегруз нельзя ничем.",
        "- Тихая комната, никакой музыки в наушниках. Любой посторонний звук",
        "  уедет в тембр вместе с голосом.",
        "",
        "## Как разделять дубли",
        "",
        "Можно писать все дубли одной реплики в один файл — так и было в прошлый",
        "раз, — но тогда два правила обязательны, иначе нарезка ошибается:",
        "",
        "- **между дублями молчи не меньше 1.5 с**;",
        "- **внутри реплики не паузься дольше 0.4 с**.",
        "",
        "В прошлый файл `impressed` попало четыре дубля вместо трёх именно",
        "потому, что пауза внутри реплики была такой же, как между дублями.",
        "Номер дубля вслух не говори — он уедет в запись.",
        "",
        "## Куда положить",
        "",
        f"Папка `{TAKES.relative_to(ROOT).as_posix()}`, имя файла — **имя",
        "события**: `lohen_tongue.wav` для всех дублей одной реплики в одном",
        "файле, либо `lohen_tongue_1.wav`, `lohen_tongue_2.wav` по одному дублю",
        "на файл. wav лучше mp3, но mp3 тоже годится.",
        "",
        "## Реплики",
        "",
    ]
    for line in lines:
        budget = room.get(line.event)
        event = by_id.get(line.event)
        body.append(f"### {line.event}")
        body.append("")
        body.append(f"> **«{line.line}»**")
        body.append("")
        if budget is not None:
            hard = effective_budget(line, room)
            ref = refs.get(line.event)
            row = f"- **цель:** не больше **{hard - MARGIN:.2f} с**"
            if ref:
                row += f"   ·   **ориентир:** {ref:.2f} с"
            body.append(row)
            if line.limit is not None and line.limit < budget:
                body.append(
                    f"- **почему предел жёстче:** до следующей реплики "
                    f"{budget:.2f} с, но раньше наступает звук, и фраза обязана "
                    f"кончиться до него")
        if event is not None:
            body.append(f"- **место в номере:** {event.t:.2f} с")
        body.append(f"- **как играть:** {line.play or line.direction}")
        if line.note:
            body.append(f"- **контекст:** {line.note}")
        body.append("")

    body += [
        "## Чего в листе нет",
        "",
        "Трёх смехов Лоэна. Смех не переводится, английские файлы остаются как",
        "есть. Если решишь переиграть и их — пиши так же, отдельными файлами",
        "с именами `lohen_laugh_1`, `lohen_laugh_2`, `lohen_laugh_3`.",
        "",
        "Двое из тринадцати — не Лоэн: `prisoner_refuse` это заключённый,",
        "`guard_shout` это охранник. Их можно начитать тем же голосом, но играть",
        "надо другого человека, иначе три персонажа сольются в одного.",
        "",
    ]
    out.write_text("\n".join(body), encoding="utf-8")
    return out
