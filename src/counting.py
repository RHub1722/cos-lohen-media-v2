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

# Длина нарастающего шума. 1.2 с — это самое тесное место в номере минус запас:
# у приёма удара от конца серии 3 до контакта 1.23 с. Единая длина у всех шести
# намеренно: риз одинаковой формы читается как один и тот же знак.
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
                        "role": beat.role, "what": getattr(beat, "what", ""),
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
    """По одному ризу на приём, вершина в первый контакт.

    Начало подрезается концом предыдущего приёма: риз, наехавший на прошлое
    действие, перестаёт означать «сейчас будет удар».
    """
    ordered = sorted(strikes, key=lambda s: min(b.heard for b in s.beats))
    out, prev_end = [], 0.0
    for strike in ordered:
        contacts = [b.heard for b in strike.beats if b.role == "contact"]
        if not contacts:
            raise CountError(
                f"{strike.id}: приём без контакта, ризу некуда целиться")
        peak = min(contacts)
        start = max(prev_end, peak - length)
        if start >= peak:
            raise CountError(
                f"{strike.id}: на риз не осталось места, контакт {peak:.2f} "
                f"стоит не позже конца прошлого приёма {prev_end:.2f}")
        out.append({"strike": strike.id, "start": round(start, 4),
                    "peak": round(peak, 4)})
        prev_end = max(b.heard for b in strike.beats)
    return out
