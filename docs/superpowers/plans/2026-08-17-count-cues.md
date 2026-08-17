# Дорожка счёта и ризов: план внедрения

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать третью дорожку подсказок — непрерывный счёт два раза в секунду и нарастающий шум перед каждым приёмом, всё в правое ухо, поверх приглушённого на 9 dB номера — плюс печатный лист «какой удар на какой цифре» и переключатель в тренажёре.

**Architecture:** Логика отделена от сборки. `src/counting.py` — чистые функции: сетка, назначение цифры доле по правилу «ближайшая», поиск столкновений, размещение ризов. Ни ffmpeg, ни файлов, ни ввода-вывода, поэтому проверяется тестами целиком. `src/render_count.py` — всё, что трогает диск: нарезка десяти числительных из готового заказа, синтез ризов, сведение через FFmpeg, печать листа. Времена берутся из `scenario/strikes.json` — того же источника, что у тренажёра и книжки.

**Tech Stack:** Python 3, FFmpeg (весь звук), numpy (только замеры в тестах), pytest.

**Спека:** [docs/superpowers/specs/2026-08-17-count-cues-design.md](../specs/2026-08-17-count-cues-design.md)

---

## Что уже сделано

`tools/count_voice.py` написан, счёт заказан, числительные померены. Заказ лежит в `assets/cues/archive/count_take1_speed100.mp3` (вне гита, как все исходники озвучки). Границы слов первого цикла замерены и перечислены в Задаче 4 — переизмерять не нужно.

## Структура файлов

| файл | ответственность |
|---|---|
| `src/counting.py` | сетка счёта, цифра доли, столкновения, ризы. Без ввода-вывода |
| `src/render_count.py` | нарезка числительных, синтез ризов, сведение, лист |
| `tests/test_counting.py` | проверки логики: сетка, якорь, ближайшая цифра, столкновения |
| `tests/test_render_count.py` | проверки собранного файла: каналы, длительность, приглушение |
| `assets/cues/count_01.wav` … `count_10.wav` | десять числительных, в гите |
| `output/count_cues.wav` | готовая дорожка, 60.000 с |
| `output/count_sheet.md` | лист ориентиров |
| `site/count_cues.m4a` | сжатая копия для страницы |
| `src/render_training.py` | правка: имя дорожки в данные, сжатие в `--site` |
| `src/training_template.html` | правка: переключатель и звуковой элемент |

---

## Задача 1: сетка счёта и якорь

**Files:**
- Create: `src/counting.py`
- Test: `tests/test_counting.py`

- [ ] **Шаг 1: написать падающий тест**

```python
"""Сетка счёта: две отметки в секунду, цикл из десяти, якорь на круглых пятёрках."""

import pytest

from src.counting import CYCLE, STEP, WORDS, CountError, digit_at, grid


def test_the_grid_covers_the_number_exactly():
    marks = grid(60.0)
    assert len(marks) == 120
    assert marks[0].t == 0.0
    assert marks[0].word == "один"
    assert marks[-1].t == 59.5
    assert marks[-1].word == "десять"


def test_one_lands_on_every_round_five():
    """Якорь, ради которого выбран шаг 0.5 с. Цикл ровно 5.000 с, значит счёт
    и таймер видео не разъезжаются: на любой круглой пятёрке звучит «один»."""
    for t in (0.0, 5.0, 10.0, 30.0, 45.0, 55.0):
        assert digit_at(t)[0] == "один", t


def test_the_cycle_is_ten_words_and_five_seconds():
    assert len(WORDS) == CYCLE == 10
    assert CYCLE * STEP == 5.0


def test_the_digit_is_the_nearest_one_not_the_containing_one():
    """Доля на 93% пятёрки слышится как шестёрка. Называть её пятой значит
    врать: исполнитель услышит «шесть» ровно в момент удара."""
    word, miss = digit_at(1.47)   # 94% ячейки «три», k=3
    assert word == "четыре"
    assert miss == pytest.approx(-0.03, abs=1e-9)
    word, miss = digit_at(1.53)
    assert word == "четыре"
    assert miss == pytest.approx(0.03, abs=1e-9)


def test_a_negative_time_is_refused():
    with pytest.raises(CountError):
        digit_at(-0.1)
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_counting.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.counting'`

- [ ] **Шаг 3: написать реализацию**

```python
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
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Run: `python -m pytest tests/test_counting.py -v`
Expected: PASS, 5 тестов

- [ ] **Шаг 5: коммит**

```bash
git add src/counting.py tests/test_counting.py
git commit -m "count: сетка счёта и якорь на круглых пятёрках"
```

---

## Задача 2: цифра для каждой доли и поиск столкновений

**Files:**
- Modify: `src/counting.py`
- Test: `tests/test_counting.py`

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/test_counting.py`:

```python
from src.counting import assign, collisions, repeated_digits


class FakeBeat:
    def __init__(self, role, heard):
        self.role, self.heard, self.what = role, heard, ""


class FakeStrike:
    def __init__(self, sid, beats):
        self.id, self.beats = sid, tuple(beats)


def _burst_1():
    return FakeStrike("burst_1", [
        FakeBeat("windup", 28.50), FakeBeat("swing", 28.88),
        FakeBeat("contact", 29.14), FakeBeat("recover", 29.60)])


def test_every_beat_gets_a_digit_and_a_signed_miss():
    rows = assign([_burst_1()])
    assert [r["word"] for r in rows] == ["восемь", "девять", "девять", "десять"]
    assert rows[2]["strike"] == "burst_1"
    assert rows[2]["role"] == "contact"
    assert rows[2]["miss"] == pytest.approx(0.14, abs=0.001)


def test_two_beats_in_one_cell_are_reported_not_hidden():
    """Взмах и контакт серии 1 стоят в 0.26 с, а шаг 0.5 с. Счёт их не
    различает, и это цена выбранного темпа. Молчать о ней нельзя: исполнитель
    будет ждать вторую цифру, которой не будет."""
    found = collisions([_burst_1()])
    assert len(found) == 1
    word, beats = found[0]
    assert word == "девять"
    assert [b["role"] for b in beats] == ["swing", "contact"]


def test_the_same_digit_on_two_different_strikes_is_not_a_collision():
    """29.14 и 34.00 оба зовутся «девять», но между ними 4.86 с — целый цикл, и
    у каждого свой риз. Путаницы нет, но в листе это оговаривается."""
    second = FakeStrike("burst_2", [FakeBeat("contact", 34.00)])
    assert collisions([_burst_1(), second]) == collisions([_burst_1()])
    repeats = repeated_digits([_burst_1(), second])
    assert repeats["девять"] == [29.14, 34.00]
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_counting.py -v`
Expected: FAIL, `ImportError: cannot import name 'assign'`

- [ ] **Шаг 3: написать реализацию**

Дописать в `src/counting.py`:

```python
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
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Run: `python -m pytest tests/test_counting.py -v`
Expected: PASS, 8 тестов

- [ ] **Шаг 5: коммит**

```bash
git add src/counting.py tests/test_counting.py
git commit -m "count: цифра доли по правилу ближайшей и поиск столкновений"
```

---

## Задача 3: ризы

**Files:**
- Modify: `src/counting.py`
- Test: `tests/test_counting.py`

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/test_counting.py`:

```python
from src.counting import RISER, risers


def test_a_riser_peaks_exactly_on_the_first_contact():
    rows = risers([_burst_1()])
    assert len(rows) == 1
    assert rows[0]["strike"] == "burst_1"
    assert rows[0]["peak"] == pytest.approx(29.14)
    assert rows[0]["start"] == pytest.approx(29.14 - RISER)


def test_a_riser_never_starts_before_the_previous_strike_ended():
    """У приёма удара место самое тесное: 1.23 с от конца серии 3 до контакта.
    Риз длиннее наехал бы на предыдущий приём и перестал бы что-либо значить."""
    early = FakeStrike("burst_3", [FakeBeat("contact", 40.95),
                                   FakeBeat("recover", 41.60)])
    late = FakeStrike("take_the_hit", [FakeBeat("hold", 42.40),
                                       FakeBeat("contact", 42.83)])
    rows = risers([early, late])
    assert rows[1]["start"] >= 41.60
    assert rows[1]["peak"] == pytest.approx(42.83)


def test_a_strike_without_a_contact_is_refused():
    with pytest.raises(CountError):
        risers([FakeStrike("empty", [FakeBeat("hold", 10.0)])])
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_counting.py -v`
Expected: FAIL, `ImportError: cannot import name 'risers'`

- [ ] **Шаг 3: написать реализацию**

Дописать в `src/counting.py`:

```python
# Длина нарастающего шума. 1.2 с — это самое тесное место в номере минус запас:
# у приёма удара от конца серии 3 до контакта 1.23 с. Единая длина у всех шести
# намеренно: риз одинаковой формы читается как один и тот же знак.
RISER = 1.2


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
```

- [ ] **Шаг 4: убедиться, что тест проходит**

Run: `python -m pytest tests/test_counting.py -v`
Expected: PASS, 11 тестов

- [ ] **Шаг 5: коммит**

```bash
git add src/counting.py tests/test_counting.py
git commit -m "count: ризы с вершиной в первый контакт"
```

---

## Задача 4: нарезка десяти числительных

**Files:**
- Create: `src/render_count.py`
- Test: `tests/test_render_count.py`

Границы замерены `tools/count_voice.py` по первому циклу заказа. Разброс со вторым циклом не больше 0.030 с.

- [ ] **Шаг 1: написать падающий тест**

```python
"""Сборка дорожки счёта. Дорогое здесь — FFmpeg, поэтому нарезка и сведение
проверяются на уже собранных файлах, а не пересобираются под каждый тест."""

import subprocess

import pytest

from src.counting import STEP, WORDS
from src.render_count import NUMERALS, OUT_DIR, TAKE


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    return float(out)


def test_there_are_ten_numerals_and_their_bounds_are_written_down():
    assert len(NUMERALS) == len(WORDS) == 10
    for word, (a, b) in zip(WORDS, NUMERALS):
        assert 0.0 <= a < b, word


def test_every_numeral_fits_the_step_after_compression():
    """Иначе цифры наедут друг на друга и счёт превратится в кашу. Самое
    длинное — «четыре», 0.555 с, отсюда общий множитель 1.110×."""
    for i, word in enumerate(WORDS):
        path = OUT_DIR / ("count_%02d.wav" % (i + 1))
        if not path.exists():
            pytest.skip("числительные не нарезаны: python src/render_count.py --cut")
        assert probe(path) <= STEP + 0.001, word


def test_the_source_take_is_named_even_though_it_is_not_in_git():
    """Заказ лежит в assets/cues/archive/, который под .gitignore. Имя должно
    быть записано в коде: без него нарезку не повторить."""
    assert TAKE.name == "count_take1_speed100.mp3"
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_render_count.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.render_count'`

- [ ] **Шаг 3: написать реализацию**

```python
"""Дорожка счёта и ризов плюс печатный лист ориентиров.

    python src/render_count.py --cut     # заново нарезать числительные
    python src/render_count.py           # собрать дорожку и лист

Третий инструмент рядом с двумя от 5 августа, и задача у него другая. Слово
подсказки стоит на доле и говорит, ЧТО делать. Цифра счёта идёт равномерно и
говорит, ГДЕ ты. Совместить их в одном файле нельзя: на шаге 0.5 с между двумя
цифрами слову «готовь» негде поместиться.

Всё, что подсказка, идёт в ПРАВЫЙ канал. Левое ухо остаётся чистым монитором
номера: вынул правый наушник — слышишь выступление без единой подсказки. Это то
же разделение, на котором построена сценическая дорожка, — она моно и идёт в
один наушник, потому что второе ухо обязано слышать зал.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.counting import RISER, STEP, WORDS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Заказ ElevenLabs, голос cgSgspJ2msm6clMCkdW9, eleven_multilingual_v2,
# stability 0.85 — тот же, которым записаны «готовь» и «бей». Лежит вне гита:
# assets/cues/archive под .gitignore, как все исходники озвучки.
TAKE = ROOT / "assets/cues/archive/count_take1_speed100.mp3"
OUT_DIR = ROOT / "assets/cues"

# Границы первого цикла, замерены tools/count_voice.py по провалам тишины.
# Разброс между двумя произнесениями одного числительного не больше 0.030 с.
NUMERALS: tuple[tuple[float, float], ...] = (
    (0.030, 0.505),   # один
    (0.725, 1.130),   # два
    (1.490, 1.780),   # три
    (2.050, 2.605),   # четыре
    (2.980, 3.305),   # пять
    (3.615, 4.090),   # шесть
    (4.465, 4.895),   # семь
    (5.295, 5.835),   # восемь
    (6.160, 6.680),   # девять
    (7.085, 7.635),   # десять
)

# Запас перед атакой и скосы от щелчков — как у семи слов подсказок.
LEAD = 0.010
FADE = 0.006
PEAK_DB = -6.0


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit("ffmpeg: %s" % done.stderr[-1500:])
    return done.stderr


def peak_db(path: Path) -> float:
    """Пик файла в dBFS. Нужен, чтобы привести все десять к одному уровню.

    Приведение по ПИКУ, а не по громкости: числительные разной длины, и
    loudnorm сделал бы короткое «три» громче длинного «четыре», хотя в счёте
    они обязаны звучать одинаково.
    """
    err = run(["ffmpeg", "-v", "info", "-i", str(path),
               "-af", "volumedetect", "-f", "null", "-"])
    for line in err.splitlines():
        if "max_volume:" in line:
            return float(line.split("max_volume:")[1].split("dB")[0].strip())
    raise SystemExit("volumedetect не вернул пик для %s" % path)


def factor() -> float:
    """Один множитель на все десять.

    Свой на каждое слово дал бы счёт, у которого цифры произносятся с разной
    скоростью, и он читался бы как сбой темпа, а не как счёт.
    """
    return max(b - a for a, b in NUMERALS) / STEP


def cut_numerals() -> list[Path]:
    if not TAKE.exists():
        raise SystemExit(
            "нет заказа %s. Он вне гита: заказать заново — "
            "python tools/count_voice.py --order" % TAKE)
    k = factor()
    print("самое длинное числительное %.3f с, шаг %.3f с → сжатие %.3f× на все"
          % (max(b - a for a, b in NUMERALS), STEP, k))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for i, ((a, b), word) in enumerate(zip(NUMERALS, WORDS), start=1):
        path = OUT_DIR / ("count_%02d.wav" % i)
        raw = path.with_suffix(".raw.wav")
        length = (b - a) / k
        # Первый проход: вырезать, сжать, скосить щелчки.
        run(["ffmpeg", "-v", "error", "-y",
             "-ss", "%.4f" % max(0.0, a - LEAD), "-t", "%.4f" % (b - a + LEAD),
             "-i", str(TAKE),
             "-af", "atempo=%.5f,afade=t=in:d=%.3f,afade=t=out:st=%.4f:d=%.3f"
                    % (k, FADE, max(0.0, length - FADE), FADE),
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(raw)])
        # Второй проход: один линейный гейн до общего пика. Замер, а не
        # угадывание: числительные приходят с разбросом громкости до 4 dB.
        gain = PEAK_DB - peak_db(raw)
        run(["ffmpeg", "-v", "error", "-y", "-i", str(raw),
             "-af", "volume=%.2fdB" % gain,
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(path)])
        raw.unlink()
        print("  %-9s %.3f с, гейн %+.2f dB → %s"
              % (word, length, gain, path.name))
        out.append(path)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cut", action="store_true",
                    help="заново нарезать числительные из заказа")
    args = ap.parse_args()
    if args.cut:
        cut_numerals()
        return 0
    ap.error("сборка дорожки появится в следующей задаче")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
```

- [ ] **Шаг 4: нарезать и проверить**

Run: `python src/render_count.py --cut`
Expected: множитель 1.110 и десять строк вида
`один 0.428 с, гейн +3.10 dB → count_01.wav`

Run: `python -m pytest tests/test_render_count.py -v`
Expected: PASS, 3 теста

- [ ] **Шаг 5: коммит**

```bash
git add src/render_count.py tests/test_render_count.py assets/cues/count_*.wav
git commit -m "count: десять числительных нарезаны из заказа"
```

---

## Задача 5: сборка дорожки

**Files:**
- Modify: `src/render_count.py`
- Test: `tests/test_render_count.py`

Сборка идёт слоями, а не одной командой на 133 входа. Цикл из десяти цифр длится ровно 5.000 с и повторяется ровно 12 раз, поэтому счёт собирается один раз и зацикливается.

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/test_render_count.py`:

```python
import numpy as np

from src.render_count import DUCK_DB, OUT_TRACK, SOUNDTRACK


def channels(path, t0, t1, sr=16000):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "%.4f" % t0, "-t", "%.4f" % (t1 - t0),
         "-i", str(path), "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    return x[:, 0], x[:, 1]


@pytest.fixture(scope="module")
def track():
    if not OUT_TRACK.exists():
        pytest.skip("нет %s: python src/render_count.py" % OUT_TRACK.name)
    return OUT_TRACK


def test_the_track_is_exactly_the_length_of_the_number(track):
    assert probe(track) == pytest.approx(60.0, abs=0.002)


def test_the_left_ear_carries_the_number_and_nothing_else(track):
    """Главная проверка каналов. Вынув правый наушник, исполнитель обязан
    услышать выступление без единой подсказки — значит левый канал должен
    совпадать с приглушённым номером, а не просто «быть похожим»."""
    for t0 in (5.0, 29.0, 42.5, 47.0):
        left, _ = channels(track, t0, t0 + 1.0)
        ref_l, _ = channels(SOUNDTRACK, t0, t0 + 1.0)
        ref_l = ref_l * (10.0 ** (-DUCK_DB / 20.0))
        n = min(len(left), len(ref_l))
        assert np.abs(left[:n] - ref_l[:n]).max() < 2e-3, t0


def test_the_right_ear_is_louder_than_the_left_where_the_count_runs(track):
    for t0 in (5.0, 29.0, 42.5):
        left, right = channels(track, t0, t0 + 1.0)
        assert np.abs(right).max() > np.abs(left).max() * 1.5, t0


def test_the_number_is_ducked_by_exactly_nine_decibels(track):
    """Ровный гейн, а не трапеции: под непрерывным счётом трапеция всё время в
    нижней точке, так что это просто гейн, и он обязан быть ровно тем."""
    left, _ = channels(track, 10.0, 20.0)
    ref, _ = channels(SOUNDTRACK, 10.0, 20.0)
    n = min(len(left), len(ref))
    got = 20 * np.log10(np.sqrt((left[:n] ** 2).mean())
                        / np.sqrt((ref[:n] ** 2).mean()))
    assert got == pytest.approx(-DUCK_DB, abs=0.15)


def test_the_track_keeps_headroom(track):
    left, right = channels(track, 0.0, 60.0)
    peak = 20 * np.log10(max(np.abs(left).max(), np.abs(right).max()))
    assert peak < -1.0, "%.2f dBTP — нет запаса, счёт надо опустить" % peak
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_render_count.py -v`
Expected: FAIL, `ImportError: cannot import name 'OUT_TRACK'`

- [ ] **Шаг 3: написать реализацию**

Дописать в `src/render_count.py` (константы — рядом с существующими):

```python
# Фонограмма номера, а не наш мастер: с 8 августа звучит ручное сведение из
# монтажки. Кладём то, подо что выступают.
SOUNDTRACK = ROOT / "output/master_ru_fx.wav"
OUT_TRACK = ROOT / "output/count_cues.wav"
TOTAL = 60.0

# Насколько уходит вниз номер. Девять, а не четырнадцать как в репетиционной
# дорожке: глубже — и пропадает сам звук удара, по которому проверяется
# попадание, то есть дорожка отменяет собственную задачу.
DUCK_DB = 9.0
RISER_DB = -9.0
```

И функции:

```python
def build_cycle(work: Path) -> Path:
    """Один цикл счёта длиной ровно CYCLE*STEP секунд.

    Цикл собирается отдельно и потом зацикливается: 60 с делятся на 5.000 с
    ровно 12 раз, поэтому склейка попадает точно в границу, а входов у FFmpeg
    остаётся десять вместо ста двадцати.
    """
    parts, labels, inputs = [], [], []
    for i in range(len(WORDS)):
        inputs += ["-i", str(OUT_DIR / ("count_%02d.wav" % (i + 1)))]
        ms = int(round(i * STEP * 1000))
        parts.append("[%d:a]adelay=%d[c%d]" % (i, ms, i))
        labels.append("[c%d]" % i)
    parts.append("".join(labels) + "amix=inputs=%d:normalize=0:"
                 "dropout_transition=0[m]" % len(labels))
    parts.append("[m]atrim=0:%.4f,asetpts=N/SR/TB[out]" % (len(WORDS) * STEP))
    out = work / "cycle.wav"
    run(["ffmpeg", "-v", "error", "-y"] + inputs
        + ["-filter_complex", ";".join(parts), "-map", "[out]",
           "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)])
    return out


def build_count(work: Path) -> Path:
    """Счёт на весь номер: цикл, повторённый нужное число раз."""
    cycle = build_cycle(work)
    times = int(round(TOTAL / (len(WORDS) * STEP)))
    if abs(times * len(WORDS) * STEP - TOTAL) > 1e-6:
        raise SystemExit(
            "цикл %.3f с не укладывается в %.3f с целое число раз — "
            "склейка попадёт внутрь цифры" % (len(WORDS) * STEP, TOTAL))
    out = work / "count.wav"
    run(["ffmpeg", "-v", "error", "-y", "-stream_loop", str(times - 1),
         "-i", str(cycle), "-t", "%.4f" % TOTAL,
         "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)])
    return out


def build_risers(work: Path, rows: list[dict]) -> Path:
    """Шесть нарастающих шумов: чирп плюс розовый шум под общей огибающей.

    Синтез целиком на FFmpeg: библиотек для звука в проекте нет, весь звук
    делает он. Огибающая степенная, а не линейная — линейная слышится как
    ровная полка и вершину не обозначает.
    """
    inputs, parts, labels = [], [], []
    for j, row in enumerate(rows):
        length = row["peak"] - row["start"]
        inputs += ["-f", "lavfi", "-i",
                   "aevalsrc=sin(2*PI*(180*t+380*t*t)):d=%.4f:s=48000" % length,
                   "-f", "lavfi", "-i",
                   "anoisesrc=d=%.4f:c=pink:r=48000:a=0.35" % length]
        ms = int(round(row["start"] * 1000))
        for idx in (2 * j, 2 * j + 1):
            parts.append("[%d:a]volume='pow(t/%.4f\\,2.2)':eval=frame,"
                         "adelay=%d,volume=%.1fdB[r%d]"
                         % (idx, length, ms, RISER_DB, idx))
            labels.append("[r%d]" % idx)
    parts.append("".join(labels) + "amix=inputs=%d:normalize=0:"
                 "dropout_transition=0[m]" % len(labels))
    parts.append("[m]apad,atrim=0:%.4f,asetpts=N/SR/TB[out]" % TOTAL)
    out = work / "risers.wav"
    run(["ffmpeg", "-v", "error", "-y"] + inputs
        + ["-filter_complex", ";".join(parts), "-map", "[out]",
           "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)])
    return out


def build_track(work: Path, rows: list[dict]) -> Path:
    """Сведение: номер стерео вниз на 9 dB, подсказки моно жёстко вправо.

    Ограничителя нет намеренно. С ним левый канал перестал бы совпадать с
    приглушённым номером бит в бит, а это единственная проверка, которая
    доказывает, что в левое ухо не попала ни одна подсказка. Запас проверяется
    замером, и если его не хватит, вниз идёт один линейный гейн на подсказки —
    так же, как сделан запас у мастера 8 августа.
    """
    count = build_count(work)
    risers_wav = build_risers(work, rows)
    run(["ffmpeg", "-v", "error", "-y",
         "-i", str(SOUNDTRACK), "-i", str(count), "-i", str(risers_wav),
         "-filter_complex",
         "[0:a]volume=-%.1fdB,atrim=0:%.4f[bed];"
         "[1:a][2:a]amix=inputs=2:normalize=0:dropout_transition=0,"
         "pan=stereo|c0=0*c0|c1=c0[cue];"
         "[bed][cue]amix=inputs=2:normalize=0:dropout_transition=0,"
         "atrim=0:%.4f,asetpts=N/SR/TB[out]" % (DUCK_DB, TOTAL, TOTAL),
         "-map", "[out]", "-ar", "48000", "-ac", "2",
         "-c:a", "pcm_s24le", str(OUT_TRACK)])
    return OUT_TRACK
```

Заменить ветку в `main`:

```python
    if args.cut:
        cut_numerals()
        return 0

    tl = Timeline.load(ROOT / "scenario/timeline.json")
    assets = ROOT / "assets"
    peaks = peak_offsets(assets, sorted({e.asset for e in tl.events
                                         if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    strikes = resolve_strikes(
        load_strikes(ROOT / "scenario/strikes.json"), tl, peaks, moves)

    if not SOUNDTRACK.exists():
        raise SystemExit("нет фонограммы %s" % SOUNDTRACK)
    if not (OUT_DIR / "count_01.wav").exists():
        raise SystemExit("числительные не нарезаны: "
                         "python src/render_count.py --cut")

    rows = risers(strikes)
    work = ROOT / "output" / "count_work"
    work.mkdir(parents=True, exist_ok=True)
    build_track(work, rows)
    print("%s  %.3f с" % (OUT_TRACK, TOTAL))
    for row in rows:
        print("  риз %-13s %.2f → %.2f" % (row["strike"], row["start"],
                                           row["peak"]))
    return 0
```

И импорты вверху рядом с `from src.counting import`:

```python
from src.counting import RISER, STEP, WORDS, risers  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402
```

- [ ] **Шаг 4: собрать и проверить**

Run: `python src/render_count.py`
Expected: `output/count_cues.wav  60.000 с` и шесть строк с ризами

Run: `python -m pytest tests/test_render_count.py -v`
Expected: PASS, 8 тестов

Если `test_the_track_keeps_headroom` падает — опустить подсказки одним гейном: добавить `,volume=-2dB` в цепочку `[cue]` и пересобрать. Множитель подбирается по числу из сообщения теста, а не наугад.

- [ ] **Шаг 5: коммит**

```bash
git add src/render_count.py tests/test_render_count.py
git commit -m "count: дорожка собрана, подсказки в правый канал"
```

---

## Задача 6: лист «какой удар на какой цифре»

**Files:**
- Modify: `src/render_count.py`
- Test: `tests/test_render_count.py`

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/test_render_count.py`:

```python
from src.render_count import SHEET, sheet


@pytest.fixture(scope="module")
def sheet_text():
    if not SHEET.exists():
        pytest.skip("нет %s: python src/render_count.py" % SHEET.name)
    return SHEET.read_text(encoding="utf-8")


def test_the_sheet_names_all_eight_contacts(sheet_text):
    for t in ("29.14", "34.00", "36.58", "39.92",
              "40.95", "42.83", "44.98", "47.03"):
        assert t in sheet_text, t


def test_the_sheet_confesses_the_three_collisions(sheet_text):
    """Цена выбранного темпа перечислена поимённо. Если однажды столкновений
    станет больше, лист обязан назвать и их — иначе исполнитель будет ждать
    цифру, которой не будет."""
    assert "делят одну цифру" in sheet_text
    for t in ("28.88", "43.13", "46.19"):
        assert t in sheet_text, t


def test_the_sheet_warns_that_one_digit_serves_two_strikes(sheet_text):
    assert "«девять»" in sheet_text and "«один»" in sheet_text
    assert "разных цикла" in sheet_text


def test_the_sheet_explains_the_anchor(sheet_text):
    assert "круглой пятёрке" in sheet_text
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_render_count.py -v`
Expected: FAIL, `ImportError: cannot import name 'SHEET'`

- [ ] **Шаг 3: написать реализацию**

Дописать константу рядом с `OUT_TRACK`:

```python
SHEET = ROOT / "output/count_sheet.md"
```

И функцию:

```python
def sheet(strikes) -> str:
    """Печатный лист. Пишется здесь, а не в шаблоне: он весь из чисел."""
    rows = assign(strikes)
    lines = [
        "# Лист счёта: какой удар на какой цифре",
        "",
        "Собран `python src/render_count.py`. Времена — из долей",
        "`scenario/strikes.json`, то есть из того же источника, что тренажёр.",
        "Руками здесь править нечего: сдвинется удар в сценарии — уедет и лист.",
        "",
        "## Как этим пользоваться",
        "",
        "Счёт идёт два раза в секунду и не замолкает. Цикл из десяти цифр",
        "длится ровно пять секунд, поэтому **«один» приходится на каждой",
        "круглой пятёрке** таймера: 0, 5, 10 и так далее. Потерялся — дождись",
        "«один» и посмотри на таймер.",
        "",
        "Счёт говорит, ГДЕ ты. Точный момент удара говорит нарастающий шум:",
        "его вершина стоит ровно в контакт. Цифра — координата, риз — попадание.",
        "",
        "Всё это звучит только в правом ухе. Левое слышит номер чистым.",
        "",
        "## Восемь ударов",
        "",
        "| время | приём | цифра | промах |",
        "|---|---|---|---|",
    ]
    for row in rows:
        if row["role"] == "contact":
            lines.append("| %.2f | %s | **«%s»** | %+.3f с |"
                         % (row["t"], row["strike"], row["word"], row["miss"]))

    repeats = repeated_digits(strikes)
    if repeats:
        lines += [
            "",
            "### Одна цифра на два удара",
            "",
            "Это не ошибка: удары стоят в разных циклах, между ними целых пять",
            "секунд, и у каждого свой риз. Но знать стоит.",
            "",
        ]
        for word, times in sorted(repeats.items()):
            lines.append("- **«%s»** — это и %s"
                         % (word, ", и ".join("%.2f" % t for t in times)))

    hits = collisions(strikes)
    lines += [
        "",
        "## Доли, которые делят одну цифру",
        "",
        "Цена темпа два раза в секунду. Самые тесные доли номера стоят в 0.21 с",
        "друг от друга, а шаг счёта 0.5 с — значит счёт их не различает.",
        "Перечислены все, чтобы не ждать цифру, которой не будет.",
        "",
        "| цифра | доли |",
        "|---|---|",
    ]
    for word, beats in hits:
        what = ", ".join("%.2f %s/%s" % (b["t"], b["strike"], b["role"])
                         for b in beats)
        lines.append("| «%s» | %s |" % (word, what))

    lines += [
        "",
        "## Все двадцать шесть долей",
        "",
        "| время | приём | роль | цифра | промах |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| %.2f | %s | %s | «%s» | %+.3f с |"
                     % (row["t"], row["strike"], row["role"],
                        row["word"], row["miss"]))

    lines += [
        "",
        "## Чего этот лист не заменяет",
        "",
        "Прогон под запись. Подготовительные доли в `strikes.json` поставлены",
        "по книжным 0.3–0.6 с на взмах. Твои числа могут отличаться вдвое, и",
        "тогда сдвигать надо доли: цифры и ризы пересчитаются сами.",
        "",
    ]
    return "\n".join(lines)
```

Дописать импорт: `from src.counting import assign, collisions, repeated_digits, ...`

И в `main`, после `build_track(...)`:

```python
    SHEET.write_text(sheet(strikes), encoding="utf-8")
    print("%s" % SHEET)
    for word, beats in collisions(strikes):
        print("  делят «%s»: %s" % (word, ", ".join(
            "%.2f %s" % (b["t"], b["role"]) for b in beats)))
```

- [ ] **Шаг 4: собрать и проверить**

Run: `python src/render_count.py`
Expected: строка `output/count_sheet.md` и три строки «делят …»

Run: `python -m pytest tests/test_render_count.py -v`
Expected: PASS, 12 тестов

- [ ] **Шаг 5: коммит**

```bash
git add src/render_count.py tests/test_render_count.py output/count_sheet.md
git commit -m "count: лист какой удар на какой цифре"
```

---

## Задача 7: переключатель в тренажёре

**Files:**
- Modify: `src/render_count.py` (сжатая копия для страницы)
- Modify: `src/render_training.py:222-282` (данные) и рядом с `SITE_VIDEO`
- Modify: `src/training_template.html:556` и `:1374`
- Test: `tests/test_render_training.py`

Второго видео не собирается. Страница играет то же видео с выключенным звуком и ведёт рядом `<audio>` по часам — та же техника, которой в виде «Пульт» синхронизированы ролик номера и клип приёма.

- [ ] **Шаг 1: написать падающий тест**

Дописать в `tests/test_render_training.py`:

```python
def test_the_page_knows_where_the_count_track_lies(payload):
    assert payload["count"] == "count_cues.m4a"


def test_the_count_track_is_published_next_to_the_page():
    track = SITE_DIR / "count_cues.m4a"
    assert track.exists(), "нет site/count_cues.m4a: python src/render_count.py --site"
    megabytes = track.stat().st_size / 1024 / 1024
    assert megabytes < 2.0, (
        "%.1f МБ — многовато для мобильной связи" % megabytes)


def test_the_page_carries_the_count_switch():
    """Переключатель обязан быть и в разметке, и в скрипте: кнопка без
    обработчика выглядит рабочей и не делает ничего."""
    html = (ROOT / "src/training_template.html").read_text(encoding="utf-8")
    assert 'id="countTrack"' in html
    assert 'id="countBtn"' in html
    assert "countBtn" in html.split("const VIEWS")[1]
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `python -m pytest tests/test_render_training.py -k count -v`
Expected: FAIL, `KeyError: 'count'`

- [ ] **Шаг 3: написать реализацию**

В `src/render_count.py` добавить константу и ветку:

```python
SITE_TRACK = ROOT / "site/count_cues.m4a"
SITE_BITRATE = "96k"


def publish() -> Path:
    """Сжатая копия для страницы. Второго видео не собирается: ещё один mp4 —
    это около шести мегабайт в гит, а звук в m4a — около одного."""
    if not OUT_TRACK.exists():
        raise SystemExit("нет %s: сначала python src/render_count.py" % OUT_TRACK)
    SITE_TRACK.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(OUT_TRACK),
         "-c:a", "aac", "-b:a", SITE_BITRATE, str(SITE_TRACK)])
    print("%s  %.1f МБ" % (SITE_TRACK, SITE_TRACK.stat().st_size / 1e6))
    return SITE_TRACK
```

Добавить флаг в `main`: `ap.add_argument("--site", action="store_true")`, и после записи листа:

```python
    if args.site:
        publish()
```

В `src/render_training.py` рядом с `SITE_VIDEO`:

```python
# Дорожка счёта: тот же номер, но приглушённый на 9 dB, а поверх него в правом
# канале счёт и ризы. Собирается src/render_count.py; страница только
# переключает звук, второго видео для этого не нужно.
SITE_COUNT = "count_cues.m4a"
```

В `build_payload`, в возвращаемый словарь, рядом с `"clips_fallback"`:

```python
        "count": SITE_COUNT,
```

В `src/training_template.html` после строки 556 (`<video id="video" …>`):

```html
    <audio id="countTrack" preload="none"></audio>
```

В `src/training_template.html` после `setRate(1);` (строка 1374):

```javascript
// Счёт идёт отдельной дорожкой поверх того же видео: второго ролика для этого
// не нужно, и в гит не едет ещё шесть мегабайт. Звук видео выключается, а
// <audio> ведётся часами видео — так же, как клип приёма в виде «Пульт».
const countTrack = $("countTrack");
const COUNT_DRIFT = 0.15;
let countOn = false;
function syncCount() {
  if (!countOn) return;
  if (countTrack.playbackRate !== video.playbackRate) {
    countTrack.playbackRate = video.playbackRate;
  }
  if (Math.abs(countTrack.currentTime - video.currentTime) > COUNT_DRIFT) {
    countTrack.currentTime = video.currentTime;
  }
  if (video.paused && !countTrack.paused) countTrack.pause();
  if (!video.paused && countTrack.paused) countTrack.play().catch(() => {});
}
function setCount(on) {
  countOn = on;
  video.muted = on;
  $("countBtn").classList.toggle("on", on);
  if (on) {
    if (!countTrack.src) countTrack.src = DATA.count;
    countTrack.currentTime = video.currentTime;
    if (!video.paused) countTrack.play().catch(() => {});
  } else {
    countTrack.pause();
  }
}
(() => {
  const b = el("button", "btn", "счёт");
  b.type = "button";
  b.id = "countBtn";
  b.title = "Счёт два раза в секунду и ризы — в правое ухо, номер тише на 9 dB";
  b.addEventListener("click", () => setCount(!countOn));
  $("rates").appendChild(b);
})();
video.addEventListener("seeked", syncCount);
video.addEventListener("play", syncCount);
video.addEventListener("pause", syncCount);
```

Найти в шаблоне цикл покадрового обновления (тот, что вызывает `requestAnimationFrame`) и добавить в него вызов `syncCount();`.

- [ ] **Шаг 4: собрать и проверить**

Run: `python src/render_count.py --site`
Expected: `site/count_cues.m4a  0.7 МБ`

Run: `python src/render_training.py --site`
Expected: сборка страницы без ошибок

Run: `python -m pytest tests/test_render_training.py -v`
Expected: PASS, все тесты включая три новых

- [ ] **Шаг 5: проверить глазами в браузере**

Открыть `site/index.html` через `http://127.0.0.1:PORT` (не `file://`: там `window.innerWidth === 0` и замер вёрстки бессмыслен). Нажать «счёт», проиграть 28–48 с, убедиться, что счёт слышен справа, номер тише, и что при перемотке дорожка не отстаёт.

- [ ] **Шаг 6: коммит**

```bash
git add src/render_count.py src/render_training.py src/training_template.html tests/test_render_training.py site/count_cues.m4a site/index.html
git commit -m "count: переключатель счёта в тренажёре"
```

---

## Задача 8: точка состояния и запись в манифест

**Files:**
- Create: `docs/status/2026-08-17-count-cues.md`
- Modify: `docs/status/INDEX.md:20-22`
- Modify: `assets/asset-manifest.json`

- [ ] **Шаг 1: записать генерацию в манифест**

В массив генераций `assets/asset-manifest.json` добавить:

```json
{
  "file": "assets/cues/count_01.wav … count_10.wav (десять числительных)",
  "date": "2026-08-17",
  "why": "Непрерывный счёт как координата: цифра говорит, ГДЕ исполнитель в номере. Слова подсказок от 5 августа говорят, ЧТО делать, и совместить их нельзя — на шаге 0.5 с между цифрами слову негде поместиться.",
  "one_take": "Десять числительных заказаны ОДНОЙ фразой в двух циклах и нарезаны скриптом. Десять отдельных вызовов дали бы десять чуть разных тембров. Два цикла — чтобы увидеть разброс: он не больше 0.030 с.",
  "trim": "Границы замерены tools/count_voice.py по провалам тишины. Сжатие 1.110×, ОДИН множитель на все десять: разный дал бы счёт с разной скоростью цифр. Запас 10 мс перед атакой, скосы по 6 мс, пик -6 dB.",
  "voice": "cgSgspJ2msm6clMCkdW9, eleven_multilingual_v2, stability 0.85. Тот же голос, что у семи слов подсказок: два разных голоса читались бы в ухе как два разных человека.",
  "rejected": "Скорость 1.2 даёт верный темп (цикл 3.350 с против 3.3333), но числительные слипаются в непрерывную речь, и разрезать её не удалось.",
  "raw": "assets/cues/archive/",
  "doc": "docs/status/2026-08-17-count-cues.md"
}
```

- [ ] **Шаг 2: написать точку состояния**

`docs/status/2026-08-17-count-cues.md` — по образцу `docs/status/2026-08-05-voice-cues.md`. Обязательно записать:

- замер, который выбрал шаг: пульса нет (пик автокорреляции в 1.30 раза выше типичного значения полосы), доли не ложатся ни на какую сетку (0.65–0.87 от случайного), поэтому мерилом стало число склеенных долей;
- почему выбран 0.5 с, а не 0.333 с: замер был за 0.333, выбор сделан ухом по двум пробам, и это правильный порядок;
- цену: три пары долей делят цифру, из них плохая одна — взмах и контакт серии 1 в 0.26 с;
- выгоду: якорь вдвое чаще (цикл ровно 5.000 с), сжатие речи 1.110× вместо 1.665×;
- правый канал и проверку, которая это доказывает (левый канал совпадает с приглушённым номером);
- два отрицательных результата: скорость 1.2 и разбор слитой речи по энергии;
- итоговое число тестов.

- [ ] **Шаг 3: дописать строку в INDEX.md**

Новая строка добавляется ПЕРВОЙ в таблицу (новые точки сверху):

```markdown
| [2026-08-17-count-cues](2026-08-17-count-cues.md) | не тронут | третья дорожка подсказок: непрерывный счёт два раза в секунду и шесть ризов, всё в правое ухо, номер тише на 9 dB. Шаг выбран не вкусом: пульса в номере нет, доли не ложатся ни на какую сетку, поэтому мерилом стало число склеенных долей. Замер был за три в секунду, ухо выбрало два — взамен якорь вдвое чаще (цикл ровно 5.000 с, «один» на каждой круглой пятёрке) и сжатие речи 1.110× вместо 1.665×. Цена названа поимённо: три пары долей делят цифру. Левое ухо слышит номер чистым, и это проверяется отсчётами |
```

- [ ] **Шаг 4: прогнать все тесты**

Run: `python -m pytest -q`
Expected: PASS, все тесты

- [ ] **Шаг 5: коммит и пуш**

```bash
git add docs/status/2026-08-17-count-cues.md docs/status/INDEX.md assets/asset-manifest.json
git commit -m "count: точка состояния и запись генерации в манифест"
git push origin main
```

---

## Самопроверка плана

**Покрытие спеки.** Сверено по разделам:

| требование спеки | задача |
|---|---|
| сетка 120 отметок, шаг 0.5 с | 1 |
| «один» на каждой круглой пятёрке | 1 |
| ближайшая цифра, а не содержащая | 1 |
| три пары долей делят цифру, и ровно эти три | 2, 6 |
| одна цифра на два удара — оговорено | 2, 6 |
| риз на каждый приём, вершина в первый контакт | 3 |
| риз не начинается раньше конца прошлого приёма | 3 |
| числительные одной фразой, один множитель сжатия | 4 |
| ни одно числительное не длиннее шага | 4 |
| подсказки жёстко вправо, номер стерео | 5 |
| в левом канале нет подсказок — замер отсчётами | 5 |
| номер приглушён ровно на 9.0 dB | 5 |
| дорожка ровно 60.000 с | 5 |
| запас по пикам | 5 |
| лист «какой удар на какой цифре» | 6 |
| переключатель в тренажёре, второго видео нет | 7 |
| сжатая копия для страницы | 7 |
| отрицательные результаты записаны | 8 |

**Не покрыто намеренно:** проверка `src/soundcheck.py` на `master_ru_fx.wav`. Дорожка счёта строится ИЗ `master_ru_fx.wav` напрямую — сверять файл сам с собой незачем. Тест `test_the_left_ear_carries_the_number_and_nothing_else` доказывает то же самое строже: левый канал совпадает с приглушённой фонограммой по отсчётам.

**Согласованность имён.** `STEP`, `WORDS`, `CYCLE`, `RISER`, `cell`, `digit_at`, `grid`, `assign`, `collisions`, `repeated_digits`, `risers` объявлены в Задачах 1–3 и используются в 4–6 под теми же именами. `OUT_TRACK`, `SHEET`, `SITE_TRACK`, `DUCK_DB`, `SOUNDTRACK`, `NUMERALS`, `TAKE`, `OUT_DIR` объявлены в Задачах 4–7 и там же используются.

**Что может пойти не так и что тогда делать.** Единственное место с настоящей неопределённостью — запас по пикам в Задаче 5: сумма приглушённого номера, счёта и риза в правом канале может подойти к потолку. Тест это ловит, а лечение записано прямо в шаге: один линейный гейн на слой подсказок, число берётся из сообщения теста. Ограничитель ставить нельзя — он сломает проверку левого канала.
