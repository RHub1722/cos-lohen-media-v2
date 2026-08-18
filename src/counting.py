"""Непрерывный счёт как координата: где ты находишься в номере прямо сейчас.

Отличие от `src/cues.py` принципиальное. Слово подсказки стоит НА ДОЛЕ и
говорит, что делать. Цифра счёта стоит на РАВНОМЕРНОЙ сетке и говорит, где ты.
Первое молчит между действиями, второе не молчит никогда.

Шаг выбран замером, а не вкусом. Пульса в номере нет: автокорреляция огибающей
атак на бое даёт пик всего в 1.30 раза выше типичного значения в полосе, у
дорожки с метрономом это 5–20 раз. Значит сетка искусственная, и мерилом стало
другое — сколько долей склеивается в одну ячейку. На 0.333 с не склеивается ни
одна, на 0.5 с склеиваются три пары. Выбор в пользу 0.5 с сделан ухом по двум
пробам: сжатие речи падает с 1.665× до 1.110×, а якорь становится вдвое чаще.

Цикл ровно 5.000 с, за номер их укладывается ровно 12, поэтому «один» звучит на
каждой круглой пятёрке таймера. Фаза приколочена к нулю номера и не
подбирается: подбор дал бы 0.05 с точности и сломал бы якорь, а точность несёт
риз, а не цифра.
"""

from __future__ import annotations

from dataclasses import dataclass

# Числительные записаны одной фразой и нарезаны: см. tools/count_voice.py.
# «Один», а не «раз» — так заказал исполнитель.
WORDS: tuple[str, ...] = ("один", "два", "три", "четыре", "пять",
                          "шесть", "семь", "восемь", "девять", "десять")
CYCLE = len(WORDS)
STEP = 0.5

# Предельная длина нарастающего шума. Форма у всех ризов одна намеренно: она
# читается как один и тот же знак. А вот длина у двух из восьми меньше — там,
# где до предыдущего удара ближе, чем 1.2 с. Накрыть прошлый удар риз не имеет
# права: он перестал бы означать «сейчас будет следующий».
RISER = 1.2


class CountError(Exception):
    """Сетку не из чего построить или её просят о невозможном."""


@dataclass(frozen=True)
class Mark:
    """Одна цифра в одну точку времени номера."""

    t: float
    index: int

    @property
    def word(self) -> str:
        return WORDS[self.index]


def cell(t: float, step: float = STEP) -> int:
    """Номер ячейки сетки, БЛИЖАЙШЕЙ к моменту t.

    Округление, а не отбрасывание. Доля на 93% ячейки слышится как следующая
    цифра, и лист, называющий её текущей, врал бы в самом важном месте.
    """
    if t < 0:
        raise CountError(f"время {t} отрицательное: сетка начинается с нуля")
    return int(round(t / step))


def digit_at(t: float, step: float = STEP) -> tuple[str, float]:
    """Ближайшая цифра и промах до неё. Промах со знаком: плюс — доля позже."""
    k = cell(t, step)
    return WORDS[k % CYCLE], round(t - k * step, 6)


def grid(total: float, step: float = STEP) -> list[Mark]:
    """Все отметки от нуля до конца номера."""
    if total <= 0:
        raise CountError(f"длительность {total} не положительная")
    out, k = [], 0
    while k * step < total:
        out.append(Mark(t=round(k * step, 6), index=k % CYCLE))
        k += 1
    return out


def assign(strikes, step: float = STEP) -> list[dict]:
    """Цифра, промах и ячейка для каждой доли каждого приёма."""
    out = []
    for strike in strikes:
        for beat in strike.beats:
            if beat.heard < 0:
                raise CountError(
                    f"{strike.id}/{beat.role}: доля без времени. "
                    "Сначала resolve_strikes, потом счёт.")
            word, miss = digit_at(beat.heard, step)
            out.append({"t": beat.heard, "strike": strike.id,
                        "role": beat.role, "what": beat.what,
                        "word": word, "miss": miss,
                        "cell": cell(beat.heard, step)})
    return sorted(out, key=lambda r: r["t"])


def collisions(strikes, step: float = STEP) -> list[tuple[str, list[dict]]]:
    """Доли, которым досталась ОДНА И ТА ЖЕ отметка сетки.

    Именно одна отметка, а не одинаковое слово: 29.14 и 34.00 оба «девять», но
    они в разных циклах и разнесены на 4.86 с. Спутать можно только соседей.
    """
    cells: dict[int, list[dict]] = {}
    for row in assign(strikes, step):
        cells.setdefault(row["cell"], []).append(row)
    return [(rows[0]["word"], rows)
            for _, rows in sorted(cells.items()) if len(rows) > 1]


def repeated_digits(strikes, step: float = STEP) -> dict[str, list[float]]:
    """Слова, доставшиеся более чем одному КОНТАКТУ, с их временами."""
    seen: dict[str, list[float]] = {}
    for row in assign(strikes, step):
        if row["role"] == "contact":
            seen.setdefault(row["word"], []).append(row["t"])
    return {w: ts for w, ts in seen.items() if len(ts) > 1}


def risers(strikes, length: float = RISER) -> list[dict]:
    """Риз на КАЖДЫЙ контакт, вершина ровно в него.

    На контакт, а не на приём. У вспышки 2 и вспышки 3 по два попадания, и
    вторые оставались без риза вовсе: за 2.58 и 1.03 с до удара не звучало
    ничего, хотя бить надо ровно так же. Видно это стало на линейке тренажёра —
    36.58 оказался единственным контактом номера, у которого нет ни риза, ни
    тренировочного клипа.

    Начало подрезается ПРЕДЫДУЩИМ КОНТАКТОМ: риз, накрывший прошлый удар,
    перестаёт означать «сейчас будет следующий». Поэтому длина у ризов разная —
    у второго попадания вспышки 3 на неё остаётся всего 1.03 с.

    Долю можно исключить полем `riser: false` в сценарии. Исключение живёт
    рядом с долей, а не списком здесь: у встречного удара вспышки 4 замаха нет
    намеренно, и объявлять подготовку, которой не существует, значит врать о
    движении. Отсчёт «предыдущего контакта» при этом ведётся по ВСЕМ контактам,
    включая исключённые: удар звучит независимо от того, объявили его или нет.
    """
    contacts = []
    for strike in strikes:
        for beat in strike.beats:
            if beat.heard < 0:
                raise CountError(
                    f"{strike.id}/{beat.role}: доля без времени. "
                    "Сначала resolve_strikes, потом ризы.")
        found = [b for b in strike.beats if b.role == "contact"]
        if not found:
            raise CountError(
                f"{strike.id}: приём без контакта, ризу некуда целиться")
        contacts += [(b.heard, strike.id, getattr(b, "riser", True))
                     for b in found]

    out, prev = [], 0.0
    for peak, sid, wanted in sorted(contacts):
        if not wanted:
            prev = peak
            continue
        start = max(prev, peak - length)
        if start >= peak:
            raise CountError(
                f"{sid}: на риз не осталось места, контакт {peak:.2f} стоит "
                f"не позже предыдущего {prev:.2f}")
        out.append({"strike": sid, "start": round(start, 4),
                    "peak": round(peak, 4)})
        prev = peak
    return out
