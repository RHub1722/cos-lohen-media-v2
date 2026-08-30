"""Голосовые подсказки исполнителю: какое слово, когда и почему их меньше долей.

Задача, из которой это выросло: попадать ударами в звук. На сам удар реагировать
физически нельзя — реакция на звук 0.15–0.20 с, взмах копьём от покоя 0.3–0.6 с,
и к моменту контакта движение уже должно идти. Значит подсказка нужна не на
ударе, а на подготовке к нему.

Времена не выписываются здесь. Они берутся из долей `scenario/strikes.json`, у
которых уже есть и опорное событие, и смещение, и учёт пика внутри ассета
(`Beat.heard`). Сдвинулся удар в сценарии — подсказка уехала за ним.

Два рода дорожек, и разница между ними принципиальная, а не в громкости.

СЦЕНИЧЕСКИЕ идут в наушник исполнителя с телефона, который запускает рукой
ПОМОЩНИК за кулисами. Помощник, а не исполнитель: тот стоит спиной к экрану и
на нулевой секунде уже обходит стул. Телефон и зал — два независимых
источника; расхождение их хода за минуту меньше 3 мс, но момент нажатия даёт
промах, и он сдвигает все подсказки разом.

Промах складывается из двух частей разной природы, и они считаются ВРОЗЬ.
Якорь (`Anchor`) — время события в номере плюс реакция человека по
модальности: свойство номера, известно точно. Цепочка — нажатие плюс
радиоканал до наушника: свойство железа, одно число на все якоря, мерится
один раз. Постоянная часть вписывается в сдвиг и потому ничего не стоит;
настоящая ошибка — только разброс, ±0.02–0.08 с.

Чем помощник поймает старт, заранее неизвестно — это вопрос к площадке.
Поэтому дорожек три, по числу якорей в `ANCHORS`, и различаются они ТОЛЬКО
сдвигом: слова и отбор считаются до него и потому общие.

В каждую попадает только ПЕРВАЯ доля каждого действия. Подсказка «готовь» за
секунду до удара переживёт промах 0.15 с и останется полезной, а слово в точку
контакта при том же промахе превращается из помощи во вредительство. Момент
контакта несёт взмах в самом шоу — он звучит из зала, но он сэмпл-точен,
потому что он и есть шоу.

РЕПЕТИЦИОННАЯ идёт одним файлом в наушники дома, где никакого второго
источника нет и промаха старта не существует. В неё попадают все доли, какие
влезают.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# Роль доли -> слово. Слова короткие и разные на слух: в наушнике под музыку
# «готовь» и «держи» с одинаковым началом путались бы.
ROLE_WORDS: dict[str, str] = {
    "windup": "ready",      # готовь
    "swing": "go",          # пошёл
    "contact": "hit",       # бей
    "hold": "hold",         # держи
    "recover": "slow",      # медленно
}

# Все слова, включая те, что ставятся только через переопределение в доле.
WORDS: dict[str, str] = {
    "ready": "готовь",
    "go": "пошёл",
    "hit": "бей",
    "hold": "держи",
    "slow": "медленно",
    "wait": "жди",
    "head": "голова",
}

# Кто уступает место при наложении. Подготовка важнее контакта намеренно:
# контакт исполнитель и так слышит — в этот момент в дорожке играет сам удар, —
# а подготовку не слышит никто, кроме этой подсказки.
PRIORITY: dict[str, int] = {
    "windup": 0,
    "contact": 1,
    "hold": 2,
    "swing": 3,
    "recover": 4,
}

# Пауза между концом одного слова и началом следующего. Меньше — слова
# наезжают и оба перестают читаться.
MIN_GAP = 0.08

# Реакция человека на сигнал, по модальности. Слух на простой реакции быстрее
# и стабильнее зрения — отсюда и следует, что якорь на звуке точнее прочих.
# Числа книжные. Своих здесь и не будет: в записи реакцию от задержки железа
# не отделить, а складываются они всё равно в одно число.
REACTION_EAR = 0.16
REACTION_EYE = 0.20


class CueError(Exception):
    """Подсказку не из чего собрать."""


@dataclass(frozen=True)
class Anchor:
    """Чем помощник за кулисами ловит момент старта номера.

    t — когда якорь происходит в номере. Свойство НОМЕРА: известно точно, не
    мерится, от железа не зависит.

    reaction — задержка человека на этот вид сигнала. Свойство МОДАЛЬНОСТИ.

    Задержки цепочки здесь нет намеренно. Нажатие и радиоканал — свойство
    ЖЕЛЕЗА, одно на все три якоря, и приходит снаружи одним числом. Ради
    этого разделения всё и затевалось: замер делается один раз, а чинит все
    три дорожки. Склеенные, они требовали бы трёх замеров.
    """

    key: str
    t: float
    sense: str
    reaction: float
    catch: str

    def start_at(self, chain: float) -> float:
        """Время номера, в которое нажата кнопка, со всей цепочкой."""
        if chain < 0:
            raise CueError(f"chain={chain} отрицательный")
        return round(self.t + self.reaction + chain, 4)


# Три якоря. Больше и не будет: это всё, что помощник способен опознать в
# первые секунды, где на экране почти чёрная комната яркостью 0.074.
ANCHORS: dict[str, Anchor] = {
    "laugh": Anchor("laugh", 0.70, "ухо", REACTION_EAR,
                    "первый смех Лоэна"),
    "picture": Anchor("picture", 0.00, "глаз", REACTION_EYE,
                      "экран оживает: два синих пятна на боковых стенах"),
    "titles": Anchor("titles", 5.00, "глаз", REACTION_EYE,
                     "смена блока титров"),
}


def anchor_by(key: str) -> Anchor:
    if key not in ANCHORS:
        raise CueError(f"якорь {key!r} не из набора, есть {sorted(ANCHORS)}")
    return ANCHORS[key]


def track_plan(key: str | None, chain: float,
               start_at: float | None = None) -> list[tuple[Anchor, float]]:
    """Какие дорожки собирать и с каким сдвигом каждую.

    Живёт здесь, а не в main, потому что это и есть та политика, ради которой
    всё затевалось: якорь плюс цепочка. Проверять её надо тестом, а не глазами
    по выводу программы.

    start_at переопределяет всю сумму — им пользуются, когда сдвиг добыт
    замером на площадке и считать его заново не из чего.
    """
    if start_at is not None and key is None:
        raise CueError("start_at имеет смысл только с одним якорем: "
                       "иначе все дорожки вышли бы одинаковыми")
    keys = [key] if key else sorted(ANCHORS)
    out = []
    for k in keys:
        anchor = anchor_by(k)
        out.append((anchor, start_at if start_at is not None
                    else anchor.start_at(chain)))
    return out


@dataclass(frozen=True)
class Cue:
    """Одно слово в одну точку времени.

    t — время в дорожке номера, то есть когда слово должно быть УСЛЫШАНО.
    Файл слова обрезан от самой атаки, поэтому t это и начало файла тоже.
    """

    t: float
    word: str
    role: str
    strike: str
    what: str = ""

    @property
    def text(self) -> str:
        return WORDS[self.word]

    def asset(self) -> str:
        return f"cues/cue_{self.word}.wav"


def word_for(beat) -> str:
    """Слово доли: переопределение в сценарии, иначе по роли.

    Переопределение нужно там, где слово по роли врёт. У приёма удара роль
    contact, но бьёт не он, а его — «бей» было бы прямым обманом.
    """
    override = getattr(beat, "cue", "")
    word = override or ROLE_WORDS.get(beat.role, "")
    if not word:
        raise CueError(f"нет слова для роли {beat.role!r}")
    if word not in WORDS:
        raise CueError(
            f"слово {word!r} не из набора, есть {sorted(WORDS)}"
        )
    return word


def all_cues(strikes: Iterable) -> list[Cue]:
    """Подсказка на каждую долю каждого действия, без разбора наложений."""
    out: list[Cue] = []
    for strike in strikes:
        for beat in strike.beats:
            if beat.heard < 0:
                raise CueError(
                    f"{strike.id}/{beat.role}: доля без времени. "
                    "Сначала resolve_strikes, потом подсказки."
                )
            out.append(Cue(t=beat.heard, word=word_for(beat), role=beat.role,
                           strike=strike.id, what=beat.what))
    return sorted(out, key=lambda c: (c.t, PRIORITY[c.role]))


def first_cues(strikes: Iterable) -> list[Cue]:
    """По одной подсказке на действие — самая ранняя доля.

    Это и есть сценический набор. Одно слово на действие, за 0.3–1.3 с до
    первого контакта: столько, сколько дала постановка, а не сколько хотелось.
    """
    out: list[Cue] = []
    for strike in strikes:
        beats = [b for b in strike.beats if b.heard >= 0]
        if not beats:
            raise CueError(f"{strike.id}: ни одной доли со временем")
        first = min(beats, key=lambda b: b.heard)
        out.append(Cue(t=first.heard, word=word_for(first), role=first.role,
                       strike=strike.id, what=first.what))
    return sorted(out, key=lambda c: c.t)


def resolve_overlaps(cues: Sequence[Cue], lengths: dict[str, float],
                     min_gap: float = MIN_GAP) -> tuple[list[Cue], list[Cue]]:
    """Убирает наложения. Возвращает (что осталось, что снято).

    Снятое возвращается, а не выбрасывается молча: у первой же вспышки четыре
    доли укладываются в 1.47 с, а четыре слова занимают 1.8 с — что-то обязано
    уйти, и исполнитель должен знать, что именно, иначе он будет ждать слово,
    которого нет.

    При наложении остаётся доля с более важной ролью. Замена не может создать
    новое наложение с предыдущей оставленной: новая доля начинается позже
    заменённой, а заменённая уже не пересекалась с предыдущей.
    """
    for cue in cues:
        if cue.word not in lengths:
            raise CueError(f"не известна длина слова {cue.word!r}")

    kept: list[Cue] = []
    dropped: list[Cue] = []
    for cue in sorted(cues, key=lambda c: (c.t, PRIORITY[c.role])):
        if kept:
            last = kept[-1]
            busy_until = last.t + lengths[last.word] + min_gap
            if cue.t < busy_until:
                if PRIORITY[cue.role] < PRIORITY[last.role]:
                    dropped.append(last)
                    kept[-1] = cue
                else:
                    dropped.append(cue)
                continue
        kept.append(cue)
    return kept, sorted(dropped, key=lambda c: c.t)


def shift(cues: Sequence[Cue], start_at: float) -> list[Cue]:
    """Сдвиг под ручной старт телефона.

    start_at — время НОМЕРА, в которое нажат play. Всё, что было до этого
    момента, в файл не попадает: оно уже прошло.
    """
    if start_at < 0:
        raise CueError(f"start_at={start_at} отрицательный")
    return [Cue(t=round(c.t - start_at, 4), word=c.word, role=c.role,
                strike=c.strike, what=c.what)
            for c in cues if c.t - start_at >= 0]


def lengths_of(assets: str | Path, words: Iterable[str],
               probe) -> dict[str, float]:
    """Длины слов через переданный замерщик. Замерщик передаётся снаружи,
    чтобы логику подсказок можно было проверить без ffmpeg."""
    root = Path(assets)
    return {w: round(probe(root / f"cues/cue_{w}.wav"), 4) for w in set(words)}
