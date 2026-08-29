# Три якоря синхронизации дорожки подсказок — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать три сценические дорожки подсказок под три разных якоря старта, чтобы помощник за кулисами мог выбрать на площадке, чем ловить начало номера, и чтобы одного замера задержки цепочки хватало на все три.

**Architecture:** Якорь и задержка цепочки разъезжаются в две независимые величины. Якорь (`Anchor` в `src/cues.py`) — время события в номере плюс реакция человека по модальности: свойство номера, известно точно. Цепочка (`--chain`) — нажатие плюс радиоканал: свойство железа, одно число на все якоря. `start_at = anchor.t + anchor.reaction + chain`. Дорожки различаются только сдвигом: слова, отбор и снятые при наложении подсказки считаются до сдвига и потому общие.

**Tech Stack:** Python 3.12, ffmpeg/ffprobe, pytest. Без новых зависимостей.

**Спецификация:** [2026-08-30-cue-sync-anchors-design.md](../specs/2026-08-30-cue-sync-anchors-design.md)

---

## Структура файлов

| файл | ответственность | что с ним |
|---|---|---|
| `src/measure.py` | замеры готового файла: громкость, пик, окна | **правится:** принимает `peak_db` |
| `src/render_count.py` | сборка счёта и ризов | **правится:** отдаёт `peak_db`, дальше импортирует |
| `src/cues.py` | логика подсказок без ffmpeg: слова, наложения, сдвиг, якоря | **правится:** `Anchor`, `ANCHORS`, `anchor_by`, `track_plan` |
| `src/render_cues.py` | сборка дорожек, подложка, щелчок, лист, публикация | **правится:** три якоря, `--chain`, подложка, щелчок, m4a |
| `tests/test_cue_anchors.py` | якоря и всё, что от них зависит | **создаётся** |
| `tests/test_cues.py` | слова, наложения, сдвиг | **не трогается** — это и есть проверка совместимости |
| `README.md` | точка входа | **правится:** блок про сценические дорожки |
| `docs/status/2026-08-30-cue-anchors.md` | запись о сделанном | **создаётся** |

Два решения по границам, которые стоит назвать вслух.

**`peak_db` переезжает в `src/measure.py`.** Его докстринг уже обещает пик
(«Замеры готового файла: громкость, **пик**, окна»), а понадобился он теперь
второму инструменту. Оставить его в `render_count.py` значило бы тянуть сборщик
счёта в сборщик слов ради одной функции.

**Политика «какие дорожки собирать» уезжает из `main` в `src/cues.py`.** Это
ровно то, ради чего всё затевалось, и проверять это надо тестом, а не глазами
по выводу программы. В `main` остаётся цикл по готовому списку.

---

### Task 1: `peak_db` переезжает в `src/measure.py`

Чистый перенос без смены поведения. Нужен, потому что подложка в Task 4 ставит
уровень замером, а не верой в параметр генератора.

**Files:**
- Modify: `src/measure.py`
- Modify: `src/render_count.py:151-171`
- Test: `tests/test_render_count.py` (существующий, не правится)

- [ ] **Step 1: Убедиться, что тесты сейчас зелёные**

Run: `python -m pytest tests/test_render_count.py -q`
Expected: PASS. Это точка отсчёта: перенос обязан оставить то же число.

- [ ] **Step 2: Добавить `peak_db` в `src/measure.py`**

В шапку `src/measure.py`, к существующим импортам:

```python
from pathlib import Path
```

В конец `src/measure.py`:

```python
def peak_db(path: str | Path) -> float:
    """Пик файла в dBFS через volumedetect.

    Живёт здесь, а не в сборщике счёта: замер готового файла — ровно то, для
    чего модуль существует, а теперь пик понадобился и сборщику подсказок,
    чтобы выставить уровень подложки.

    Приведение по ПИКУ, а не по громкости: у счёта числительные разной длины,
    и loudnorm сделал бы короткое «три» громче длинного «четыре», хотя в
    счёте они обязаны звучать одинаково.
    """
    done = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    if done.returncode:
        raise SystemExit("ffmpeg: %s" % done.stderr[-1500:])
    for line in done.stderr.splitlines():
        if "max_volume:" in line:
            return float(line.split("max_volume:")[1].split("dB")[0].strip())
    raise SystemExit("volumedetect не вернул пик для %s" % path)
```

- [ ] **Step 3: Убрать `peak_db` из `src/render_count.py` и импортировать**

Удалить целиком функцию `peak_db` — от строки `def peak_db(path: Path) -> float:`
до строки `raise SystemExit("volumedetect не вернул пик для %s" % path)`
включительно.

Функцию `run` **оставить на месте**: её зовут ещё девять раз в этом же файле.

Рядом с существующими импортами `src.*` в `src/render_count.py` добавить:

```python
from src.measure import peak_db  # noqa: E402
```

- [ ] **Step 4: Проверить, что ничего не отвалилось**

Run: `python -m pytest tests/test_render_count.py -q`
Expected: PASS, столько же тестов, сколько в Step 1.

Run: `python -c "from src.render_count import peak_db; print(peak_db.__module__)"`
Expected: `src.measure`

- [ ] **Step 5: Коммит**

```bash
git add src/measure.py src/render_count.py
git commit -m "measure: peak_db переезжает туда, где его обещает докстринг"
```

---

### Task 2: якорь как объект

**Files:**
- Modify: `src/cues.py`
- Create: `tests/test_cue_anchors.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_cue_anchors.py`:

```python
"""Якоря синхронизации: чем помощник ловит старт номера и как это считается.

Имя файла выбрано в стороне от `tests/test_sync_budget.py`: тот про совсем
другое — сколько вызовов play и перемоток тренажёр заказывает у планшета.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cues import ANCHORS, CueError, anchor_by, first_cues, shift
from src.models import Timeline
from src.movements import load_movements, resolve_times
from src.peaks import peak_offsets
from src.strikes import load_strikes, resolve_strikes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real():
    """Настоящие действия из сценария: якоря обязаны работать на них."""
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    assets = ROOT / "assets"
    peaks = peak_offsets(assets, sorted({e.asset for e in tl.events
                                         if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    return resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"),
                           tl, peaks, moves)


# --- арифметика якоря --------------------------------------------------------


def test_each_anchor_adds_its_own_time_and_reaction():
    """Якорь знает две вещи: когда он в номере и чем его ловят."""
    assert anchor_by("picture").start_at(0.25) == 0.45
    assert anchor_by("laugh").start_at(0.25) == 1.11
    assert anchor_by("titles").start_at(0.25) == 5.45


def test_the_chain_moves_every_anchor_by_the_same_amount():
    """Ради этого якорь и цепочка и разъезжались: замер один, дорожек три."""
    before = {k: a.start_at(0.20) for k, a in ANCHORS.items()}
    after = {k: a.start_at(0.30) for k, a in ANCHORS.items()}
    assert sorted(before) == sorted(after)
    assert all(round(after[k] - before[k], 4) == 0.10 for k in before)


def test_the_ear_reacts_faster_than_the_eye():
    """Не украшение: отсюда и следует, что якорь на звуке точнее прочих."""
    assert anchor_by("laugh").reaction < anchor_by("picture").reaction
    assert anchor_by("picture").reaction == anchor_by("titles").reaction


def test_an_unknown_anchor_is_refused():
    with pytest.raises(CueError, match="не из набора"):
        anchor_by("subtitles")


def test_a_negative_chain_is_refused():
    """Отрицательная задержка означала бы нажатие до сигнала."""
    with pytest.raises(CueError, match="отрицательный"):
        anchor_by("laugh").start_at(-0.1)


def test_every_anchor_says_what_to_catch():
    """Строка уезжает в лист ориентиров: без неё якорь — голое число."""
    for anchor in ANCHORS.values():
        assert anchor.catch.strip()
        assert anchor.sense in ("ухо", "глаз")


# --- на настоящих действиях --------------------------------------------------


def test_all_anchors_carry_the_same_words(real):
    """Якорь двигает дорожку, но не отбирает: отбор идёт ДО сдвига."""
    first = first_cues(real)
    words = {k: tuple(c.word for c in shift(first, a.start_at(0.25)))
             for k, a in ANCHORS.items()}
    assert len(set(words.values())) == 1, words


def test_the_latest_anchor_still_keeps_every_word(real):
    """Титры на 5.00 — самый поздний якорь. Резал бы он слова, это был бы уже
    другой инструмент, а не та же дорожка под другой старт."""
    first = first_cues(real)
    assert len(shift(first, anchor_by("titles").start_at(0.25))) == len(first)


def test_no_cue_lands_before_its_file_starts(real):
    first = first_cues(real)
    for anchor in ANCHORS.values():
        for cue in shift(first, anchor.start_at(0.25)):
            assert cue.t >= 0
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `python -m pytest tests/test_cue_anchors.py -q`
Expected: FAIL на сборе — `ImportError: cannot import name 'ANCHORS' from 'src.cues'`

- [ ] **Step 3: Реализовать в `src/cues.py`**

Сразу после константы `MIN_GAP` и перед `class CueError`:

```python
# Реакция человека на сигнал, по модальности. Слух на простой реакции быстрее
# и стабильнее зрения — отсюда и следует, что якорь на звуке точнее прочих.
# Числа книжные. Своих здесь и не будет: в записи реакцию от задержки железа
# не отделить, а складываются они всё равно в одно число.
REACTION_EAR = 0.16
REACTION_EYE = 0.20
```

После `class CueError` — ему нужен `CueError` для проверки в `start_at`:

```python
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
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `python -m pytest tests/test_cue_anchors.py -q`
Expected: PASS, 9 тестов.

Run: `python -m pytest tests/test_cues.py -q`
Expected: PASS — старые тесты не тронуты.

- [ ] **Step 5: Коммит**

```bash
git add src/cues.py tests/test_cue_anchors.py
git commit -m "cues: якорь стал объектом — время номера и реакция врозь от цепочки"
```

---

### Task 3: какие дорожки собирать

Политика выносится из `main` отдельной функцией, чтобы её можно было проверить
тестом. В `main` останется цикл по готовому списку.

**Files:**
- Modify: `src/cues.py`
- Test: `tests/test_cue_anchors.py`

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_cue_anchors.py` после блока арифметики:

```python
# --- какие дорожки собирать --------------------------------------------------


def test_without_an_anchor_every_track_is_built():
    """По умолчанию собираются все три: чем ловить — вопрос к площадке."""
    plan = track_plan(None, 0.25)
    assert [a.key for a, _ in plan] == ["laugh", "picture", "titles"]
    assert [s for _, s in plan] == [1.11, 0.45, 5.45]


def test_one_anchor_builds_one_track():
    assert [a.key for a, _ in track_plan("titles", 0.25)] == ["titles"]


def test_an_explicit_start_overrides_the_whole_sum():
    """Число, добытое замером на площадке, важнее любого расчёта."""
    (anchor, start), = track_plan("laugh", 0.25, start_at=0.95)
    assert anchor.key == "laugh"
    assert start == 0.95


def test_an_explicit_start_without_an_anchor_is_refused():
    """Три дорожки с одним сдвигом — это три одинаковых файла."""
    with pytest.raises(CueError, match="только с одним якорем"):
        track_plan(None, 0.25, start_at=0.95)
```

И расширить импорт в шапке файла:

```python
from src.cues import (ANCHORS, CueError, anchor_by, first_cues, shift,
                      track_plan)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `python -m pytest tests/test_cue_anchors.py -q`
Expected: FAIL на сборе — `ImportError: cannot import name 'track_plan'`

- [ ] **Step 3: Реализовать в `src/cues.py`**

После функции `anchor_by`:

```python
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
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `python -m pytest tests/test_cue_anchors.py -q`
Expected: PASS, 13 тестов.

- [ ] **Step 5: Коммит**

```bash
git add src/cues.py tests/test_cue_anchors.py
git commit -m "cues: план дорожек отдельной функцией — политику проверяет тест"
```

---

### Task 4: три дорожки и лист под них

**Files:**
- Modify: `src/render_cues.py` — докстринг, константы, `sheet`, `main`

- [ ] **Step 1: Переписать докстринг модуля**

Заменить верх `src/render_cues.py` (до `from __future__`):

```python
"""Дорожки голосовых подсказок и печатный лист ориентиров.

    python src/render_cues.py                    # все три якоря
    python src/render_cues.py --chain 0.31       # свой замер цепочки
    python src/render_cues.py --anchor laugh     # только один якорь

Что получается:

    output/rehearsal_cues_v2.wav    номер + голос поверх, для репетиции дома
    output/stage_cues_laugh.wav     в наушник, ловить первый смех
    output/stage_cues_picture.wav   в наушник, ловить появление картинки
    output/stage_cues_titles.wav    в наушник, ловить смену титров
    output/cue_sheet.md             печатный лист: что слышно и за сколько

Три дорожки, потому что play жмёт помощник за кулисами, а не исполнитель, и
чем он поймает старт — вопрос к площадке, а не к расчёту. Различаются только
сдвигом: слова и отбор считаются ДО него и потому общие.

Почему сценическая дорожка не содержит слова в точку контакта — в docstring
`src/cues.py`. Коротко: старт нажимается рукой, и слово в точку при промахе
вредит.
"""
```

- [ ] **Step 2: Заменить константы**

Удалить:

```python
# Куда упирается ручной старт. По умолчанию исполнитель жмёт play на первом
# звуке номера — смех на 0.70, — и человеческая реакция добавляет ещё 0.25 с.
# Оба числа заглушки: настоящее даёт один замер, описанный в листе ориентиров.
SYNC_ON = 0.70
REACTION = 0.25
```

Вписать вместо них:

```python
# Задержка ЦЕПОЧКИ: нажатие кнопки плюс радиоканал до наушника. Свойство
# железа, одно на все три якоря, и потому отдельное от них.
#
# Заглушка: нажатие около 0.05 плюс Bluetooth, который по кодеку даёт
# 0.15-0.30 (SBC 0.15-0.25, AAC 0.15-0.20, aptX 0.08-0.15). Настоящее число
# даёт один замер, порядок в листе ориентиров.
CHAIN = 0.25
```

- [ ] **Step 3: Расширить импорт из `src.cues`**

```python
from src.cues import (ANCHORS, Cue, all_cues, first_cues,  # noqa: E402
                      lengths_of, resolve_overlaps, shift, track_plan)
```

- [ ] **Step 4: Переписать `sheet` под три якоря**

Заменить функцию `sheet` целиком:

```python
def sheet(kept: list[Cue], dropped: list[Cue], first: list[Cue],
          chain: float, strikes) -> str:
    """Печатный лист. Пишется здесь, а не в шаблоне: он весь из чисел."""
    contacts = {}
    for strike in strikes:
        earliest = min((b.heard for b in strike.beats if b.role == "contact"),
                       default=None)
        if earliest is not None:
            contacts[strike.id] = earliest

    lines = [
        "# Лист ориентиров: когда наносить удары",
        "",
        "Сгенерирован `python src/render_cues.py`. Времена — из долей",
        "`scenario/strikes.json`, то есть из того же источника, что тренажёр.",
        "Руками здесь править нечего: сдвинется удар в сценарии — уедет и лист.",
        "",
        "## Главное правило",
        "",
        "На удар реагировать нельзя. Реакция на звук 0.15–0.20 с, взмах копьём",
        "от покоя 0.3–0.6 с: к моменту контакта движение уже должно идти.",
        "Поэтому ориентир всегда стоит на подготовке, а не на попадании.",
        "",
        "## Три дорожки: чем ловить старт",
        "",
        "Play жмёт помощник за кулисами, а не исполнитель. Чем он поймает",
        "начало номера — вопрос к площадке, поэтому собраны все три, а выбор",
        "делается на месте и ДО выхода.",
        "",
        "| файл | ловить | чем | в номере | сдвиг |",
        "|---|---|---|---|---|",
    ]
    for anchor, start_at in track_plan(None, chain):
        lines.append(f"| `stage_cues_{anchor.key}.wav` | {anchor.catch} | "
                     f"{anchor.sense} | {anchor.t:.2f} | {start_at:.2f} |")

    lines += [
        "",
        f"Сдвиг = время якоря + реакция (ухо 0.16, глаз 0.20) + цепочка "
        f"{chain:.2f}.",
        "",
        "Слова в точку контакта нет ни в одной намеренно: старт нажимается",
        "рукой, и слово в точку при промахе вредит. Контакт несёт сам номер.",
        "",
        "**Рабочее окно старта — ±0.2 с.** При опоздании на 0.2 с у «пошёл»",
        "остаётся 0.18 с опережения: подсказка сжимается, но помогает. При",
        "0.38 с слово ложится ровно в контакт и начинает вредить.",
        "",
        "В начале каждой дорожки стоит щелчок. Услышал — канал жив и часы",
        "пошли. Не услышал — Bluetooth оборвался, и подсказок не будет вовсе.",
        "",
        "## Слова и опережение",
        "",
        "| слово | в номере | действие | до первого контакта |",
        "|---|---|---|---|",
    ]
    for cue in first:
        c = contacts.get(cue.strike)
        gap = f"{c - cue.t:.2f} с" if c is not None else "—"
        lines.append(f"| **{cue.text}** | {cue.t:.2f} | {cue.strike} | {gap} |")

    lines += [
        "",
        "## Репетиционная дорожка: все доли, какие влезли",
        "",
        "`output/rehearsal_cues_v2.wav` — номер плюс голос поверх. Только для",
        "репетиции: старта на сцене здесь нет, промаха нет, слова стоят точно.",
        "",
        "| время | слово | роль | действие |",
        "|---|---|---|---|",
    ]
    for cue in kept:
        lines.append(f"| {cue.t:.2f} | **{cue.text}** | {cue.role} | "
                     f"{cue.strike} |")

    if dropped:
        lines += [
            "",
            "### Что снято и почему",
            "",
            "Доли идут плотнее, чем произносятся слова: у первой вспышки четыре",
            "доли укладываются в 1.47 с, а четыре слова занимают 1.8 с. Снятое",
            "перечислено, чтобы не ждать слова, которого не будет. При наложении",
            "остаётся более важная роль, и подготовка важнее контакта: контакт",
            "слышен сам — в этот момент играет удар, — а подготовку не слышит",
            "никто, кроме подсказки.",
            "",
            "| время | слово | роль | действие |",
            "|---|---|---|---|",
        ]
        for cue in dropped:
            lines.append(f"| {cue.t:.2f} | {cue.text} | {cue.role} | "
                         f"{cue.strike} |")

    lines += [
        "",
        "## Как замерить задержку цепочки",
        "",
        "Замер ОДИН на все три дорожки: мерится цепочка — нажатие плюс",
        "радиоканал, — а она от якоря не зависит. В этом весь смысл того, что",
        "якорь и цепочка считаются врозь.",
        "",
        "1. Включи номер в зале или на колонках, телефон помощника — в руке.",
        "2. Возьми любую из трёх дорожек и жми play на её якоре.",
        "3. Пиши на диктофон второго устройства сразу и зал, и наушник",
        "   (наушник поднеси к микрофону).",
        "4. В записи найди якорь и ЩЕЛЧОК в начале дорожки. Разница минус",
        "   время якоря минус реакция и есть цепочка.",
        "5. Пересобери с ней: `python src/render_cues.py --chain ЧИСЛО`.",
        "",
        "Готовый инструмент для того же замера уже есть у дорожки ризов:",
        "`output/cues/lohen_cues_riser_sync.m4a` кладёт номер тихим фоном, и",
        "расхождение двух копий одного звука слышно как хлопок. Ею ловятся и",
        "промах пуска, и задержка наушника разом.",
        "",
        f"Сейчас цепочка стоит на заглушке {chain:.2f} с.",
        "",
        "Задержка меняется при переподключении наушника: кодек",
        "перевыбирается, и число становится другим. Мерить надо перед самым",
        "выходом и после этого наушник не трогать.",
        "",
        "## Чего эти дорожки не заменяют",
        "",
        "Прогон под запись. Все подготовительные точки в `strikes.json`",
        "поставлены по книжным 0.3–0.6 с на взмах. Твои числа могут отличаться",
        "вдвое, и тогда сдвигать надо доли, а не подсказки: подсказки",
        "пересчитаются сами.",
        "",
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Переписать аргументы `main`**

Заменить строку с `--start-at`:

```python
    ap.add_argument("--anchor", choices=sorted(ANCHORS), default=None,
                    help="чем ловить старт; без него собираются все три")
    ap.add_argument("--chain", type=float, default=CHAIN,
                    help="задержка цепочки: нажатие плюс радиоканал")
    ap.add_argument("--start-at", type=float, default=None,
                    help="прямое переопределение суммы, в обход якоря и цепочки")
```

- [ ] **Step 6: Переписать сборку в `main`**

Заменить блок от `every = all_cues(strikes)` до `return 0`:

```python
    every = all_cues(strikes)
    lengths = lengths_of(assets, [c.word for c in every], ffprobe_duration)
    kept, dropped = resolve_overlaps(every, lengths)
    first = first_cues(strikes)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"действий {len(strikes)}, долей {len(every)}, "
          f"подсказок в репетиционной {len(kept)}, снято {len(dropped)}")
    for cue in kept:
        print(f"  {cue.t:6.2f}  {cue.text:9} {cue.role:8} {cue.strike}")
    if dropped:
        print("снято из-за наложения:")
        for cue in dropped:
            print(f"  {cue.t:6.2f}  {cue.text:9} {cue.role:8} {cue.strike}")

    master = Path(args.master)
    if not master.exists():
        raise SystemExit(f"нет мастера {master}. Сначала python src/build.py")
    render(kept, out / "rehearsal_cues_v2.wav", tl.total_duration, assets,
           master)

    made: list[Path] = []
    for anchor, start_at in track_plan(args.anchor, args.chain, args.start_at):
        stage = shift(first, start_at)
        path = out / f"stage_cues_{anchor.key}.wav"
        print(f"\n{anchor.key}: ловить {anchor.catch} ({anchor.sense}), "
              f"сдвиг {start_at:.2f} с, {len(stage)} слов")
        for cue in stage:
            print(f"  файл {cue.t:6.2f}  номер {cue.t + start_at:6.2f}  "
                  f"{cue.text:9} {cue.strike}")
        render(stage, path, tl.total_duration - start_at, assets, None,
               channels=1)
        made.append(path)

    text = sheet(kept, dropped, first, args.chain, strikes)
    (out / "cue_sheet.md").write_text(text, encoding="utf-8")

    for path in [out / "rehearsal_cues_v2.wav"] + made:
        print(f"\n{path}  {ffprobe_duration(path):.3f} с, "
              f"{path.stat().st_size / 1e6:.1f} МБ")
    print(f"{out / 'cue_sheet.md'}")
    return 0
```

`track_plan` сам поднимет `CueError`, если `--start-at` дан без `--anchor` —
отдельной проверки в `main` не нужно.

- [ ] **Step 7: Собрать и посмотреть**

Run: `python src/render_cues.py`
Expected: три блока — `laugh`, `picture`, `titles` — со сдвигами 1.11, 0.45,
5.45; в `output/` появились три `stage_cues_*.wav`.

Run: `python src/render_cues.py --start-at 0.95`
Expected: FAIL с текстом «start_at имеет смысл только с одним якорем».

Run: `head -30 output/cue_sheet.md`
Expected: таблица из трёх строк со сдвигами 1.11, 0.45, 5.45.

- [ ] **Step 8: Прогнать все тесты**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Коммит**

```bash
git add src/render_cues.py
git commit -m "cues: три дорожки под три якоря, цепочка отдельным числом"
```

`output/cue_sheet.md` в коммит НЕ идёт: вся папка `output/` не версионируется как
воспроизводимая, и лист там никогда не отслеживался.

---

### Task 5: подложка против сна наушника

Перенос готового решения из `src/render_count.py`, где то же самое сделано для
ризов. Дорожка слов собрана 5 августа под проводной наушник и про Bluetooth не
знает.

**Files:**
- Modify: `src/render_cues.py` — импорты, константы, `render`, `main`
- Test: `tests/test_cue_anchors.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_cue_anchors.py`:

```python
# --- собранные файлы ---------------------------------------------------------

import subprocess  # noqa: E402

from src.measure import peak_db  # noqa: E402

OUT = ROOT / "output"
STAGE = [OUT / f"stage_cues_{k}.wav" for k in ("laugh", "picture", "titles")]
BUILT = pytest.mark.skipif(not all(p.exists() for p in STAGE),
                           reason="сначала python src/render_cues.py")


def _mean_db(path: Path, start: float, length: float) -> float:
    """Средний уровень окна. Цифровая тишина даёт около -91 dB и ниже."""
    done = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", f"{start:.4f}", "-t", f"{length:.4f}",
         "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in done.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0].strip())
    raise AssertionError(f"volumedetect не дал средний уровень для {path}")


@BUILT
@pytest.mark.parametrize("path", STAGE, ids=lambda p: p.stem)
def test_the_silence_between_words_is_not_digital_silence(path):
    """Наушник на цифровой тишине уходит в энергосбережение, и первое слово
    после паузы приходит обрезанным. Между шестью словами паузы по 4-10 с."""
    assert _mean_db(path, 8.0, 4.0) > -85.0


@BUILT
@pytest.mark.parametrize("path", STAGE, ids=lambda p: p.stem)
def test_the_floor_stays_far_under_the_words(path):
    """Подложка обязана быть неслышной: она страховка, а не звук."""
    assert peak_db(path) - _mean_db(path, 8.0, 4.0) > 50.0
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `python -m pytest tests/test_cue_anchors.py -q -k silence`
Expected: FAIL — окно 8–12 с сейчас цифровая тишина, `mean_volume` около
`-91 dB`.

- [ ] **Step 3: Добавить импорты в `src/render_cues.py`**

К импортам стандартной библиотеки:

```python
import tempfile
```

К импортам `src.*`:

```python
from src.measure import peak_db  # noqa: E402
```

- [ ] **Step 4: Добавить константы**

После `CHAIN`:

```python
# Подложка под тишиной. Перенесено из src/render_count.py, где то же сделано
# для дорожки ризов: «наушники на тишине уходят в энергосбережение — первый
# риз пришёл бы обрезанным или не пришёл бы вовсе». Здесь между шестью словами
# паузы по 4-10 секунд, то есть болезнь та же.
#
# Оговорка оттуда переносится вместе с решением: это страховка, а не
# доказанное лечение, и проверяется только на его наушнике.
FLOOR_DB = -60.0

# Амплитуда генератора до приведения. Уровень ставится ЗАМЕРОМ, а не верой в
# этот параметр: цветной фильтр anoisesrc меняет пик непредсказуемо, и -60
# «на глаз» может оказаться и -48, и -72.
FLOOR_AMPLITUDE = 0.35
```

- [ ] **Step 5: Реализовать генератор подложки**

Перед `def render(`:

```python
def floor_track(work: Path, total: float) -> tuple[Path, float]:
    """Розовый шум подо всей дорожкой и усиление до FLOOR_DB.

    Возвращает файл и то, на сколько его поднять. Отдельным файлом, а не
    фильтром на лету, потому что уровень выставляется замером пика, а
    замерить можно только записанное.
    """
    path = work / "floor.wav"
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"anoisesrc=d={total:.4f}:c=pink:r=48000:a={FLOOR_AMPLITUDE}",
         "-ac", "1", "-c:a", "pcm_s24le", str(path)],
        capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"ffmpeg подложка: {done.stderr[-1500:]}")
    return path, FLOOR_DB - peak_db(path)
```

- [ ] **Step 6: Подключить подложку в `render`**

Заменить сигнатуру и докстринг:

```python
def render(cues: list[Cue], out: Path, total: float, assets: Path,
           bed: Path | None, channels: int = 2, floor: bool = False) -> None:
    """Собирает дорожку: слова через adelay, при наличии — поверх номера.

    channels=1 для сценической: она едет в один наушник, второе ухо обязано
    слышать зал. Моно и вдвое меньше файл на телефоне.

    floor=True тоже только для сценической: подложка нужна там, где дорожка
    идёт по Bluetooth и подолгу молчит. У репетиционной под словами играет
    номер, тишины нет вовсе, и подложка была бы мусором в файле.
    """
```

Заменить всё от `lengths = lengths_of(...)` до конца функции:

```python
    lengths = lengths_of(assets, [c.word for c in cues], ffprobe_duration)

    with tempfile.TemporaryDirectory(prefix="cues_") as tmp:
        work = Path(tmp)
        inputs: list[str] = []
        if bed is not None:
            inputs += ["-i", str(bed)]
        for cue in cues:
            inputs += ["-i", str(assets / f"cues/cue_{cue.word}.wav")]

        base = 1 if bed is not None else 0
        parts = []
        labels = []
        for i, cue in enumerate(cues):
            ms = int(round(cue.t * 1000.0))
            parts.append(f"[{base + i}:a]adelay={ms}|{ms},"
                         f"volume={CUE_GAIN_DB}dB[c{i}]")
            labels.append(f"[c{i}]")

        if bed is not None:
            expr = duck_expression(cues, lengths)
            parts.append(f"[0:a]volume='{expr}':eval=frame[bed]")
            labels.insert(0, "[bed]")

        if floor:
            path, gain = floor_track(work, total)
            inputs += ["-i", str(path)]
            parts.append(f"[{base + len(cues)}:a]volume={gain:.2f}dB[floor]")
            labels.append("[floor]")

        n = len(labels)
        parts.append("".join(labels) + f"amix=inputs={n}:normalize=0:"
                     f"dropout_transition=0[mix]")
        # Обрезка по длине номера обязательна: adelay продлевает поток, и
        # последнее слово вытянуло бы файл за 60 с.
        parts.append(f"[mix]atrim=0:{total:.4f},asetpts=N/SR/TB[out]")

        cmd = (["ffmpeg", "-v", "error", "-y"] + inputs
               + ["-filter_complex", ";".join(parts), "-map", "[out]"]
               + ["-ar", "48000", "-ac", str(channels),
                  "-c:a", "pcm_s24le", str(out)])
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode:
            raise SystemExit(f"ffmpeg: {done.stderr[-1500:]}")
```

- [ ] **Step 7: Включить у сценических дорожек**

В `main`, в вызове внутри цикла по якорям:

```python
        render(stage, path, tl.total_duration - start_at, assets, None,
               channels=1, floor=True)
```

- [ ] **Step 8: Пересобрать и прогнать**

Run: `python src/render_cues.py`
Expected: три файла собираются без ошибок.

Run: `python -m pytest tests/test_cue_anchors.py -q`
Expected: PASS, 19 тестов.

- [ ] **Step 9: Коммит**

```bash
git add src/render_cues.py tests/test_cue_anchors.py
git commit -m "cues: подложка -60 dBFS — наушник больше не засыпает между словами"
```

---

### Task 6: щелчок в начале

**Files:**
- Modify: `src/render_cues.py` — константы, `render`, `main`
- Test: `tests/test_cue_anchors.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_cue_anchors.py`:

```python
@BUILT
@pytest.mark.parametrize("path", STAGE, ids=lambda p: p.stem)
def test_a_click_confirms_the_channel_is_alive(path):
    """Помощник нажал — исполнитель обязан услышать, что часы пошли. Без
    этого о разорванном Bluetooth станет известно на 28.50, посреди номера.

    Щелчок стоит не в нуле: первые ~0.2 с съедает пробуждение канала, и в
    нуле его срезало бы вместе с ними."""
    quiet = _mean_db(path, 0.05, 0.15)
    click = _mean_db(path, 0.25, 0.20)
    assert click - quiet > 20.0, f"тихо {quiet:.1f}, щелчок {click:.1f}"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `python -m pytest tests/test_cue_anchors.py -q -k click`
Expected: FAIL — в окне 0.25–0.45 с сейчас только подложка, разница около 0 dB.

- [ ] **Step 3: Добавить константы**

После блока подложки:

```python
# Щелчок в начале дорожки. Помощник нажал — исполнитель услышал и знает, что
# канал жив и часы пошли. Обрыв Bluetooth на дальности в дорожке не лечится,
# но его можно сделать заметным сразу, а не на первом пропущенном слове.
#
# Не в нуле: первые ~0.2 с съедает пробуждение канала. На 0.30 щелчок звучит
# ПОСЛЕ пробуждения и тем доказывает, что оно случилось.
CLICK_AT = 0.30
CLICK_HZ = 1000
CLICK_LEN = 0.015
CLICK_DB = -12.0
```

- [ ] **Step 4: Подключить щелчок в `render`**

Расширить сигнатуру и дописать в докстринг:

```python
def render(cues: list[Cue], out: Path, total: float, assets: Path,
           bed: Path | None, channels: int = 2, floor: bool = False,
           click: bool = False) -> None:
```

В докстринг, последней строкой:

```
    click=True тоже только для сценической: дома по проводу канал не рвётся,
    и подтверждать нечего.
```

Сразу после блока `if floor:` добавить:

```python
        if click:
            inputs += ["-f", "lavfi", "-i",
                       f"sine=frequency={CLICK_HZ}:duration={CLICK_LEN}"
                       f":sample_rate=48000"]
            idx = base + len(cues) + (1 if floor else 0)
            ms = int(round(CLICK_AT * 1000.0))
            # Фейды по 2 мс: без них у щелчка появятся собственные щелчки на
            # обрыве синуса, и он выйдет грязнее того, что обозначает.
            parts.append(f"[{idx}:a]afade=t=in:d=0.002,"
                         f"afade=t=out:st={CLICK_LEN - 0.002:.4f}:d=0.002,"
                         f"adelay={ms}|{ms},volume={CLICK_DB}dB[click]")
            labels.append("[click]")
```

- [ ] **Step 5: Включить у сценических дорожек**

В `main`:

```python
        render(stage, path, tl.total_duration - start_at, assets, None,
               channels=1, floor=True, click=True)
```

- [ ] **Step 6: Пересобрать и прогнать**

Run: `python src/render_cues.py`
Run: `python -m pytest tests/test_cue_anchors.py -q`
Expected: PASS, 22 теста.

- [ ] **Step 7: Коммит**

```bash
git add src/render_cues.py tests/test_cue_anchors.py
git commit -m "cues: щелчок на 0.30 — обрыв канала виден сразу, а не на 28.50"
```

---

### Task 7: публикация в телефон

Папка `output/cues/` уже есть и целиком копируется в телефон — там лежат ризы.
Слова едут туда же, под своим префиксом.

**Files:**
- Modify: `src/render_cues.py` — константы, `publish`, `main`

- [ ] **Step 1: Добавить константы**

После блока щелчка:

```python
# Та же папка, что у ризов: она целиком копируется в телефон, и держать две
# было бы приглашением взять на площадку не ту. Префикс разный намеренно — в
# одной папке должно быть видно, что это разные инструменты, а не варианты
# одного. Константы продублированы, а не импортированы: тянуть сборщик счёта
# в сборщик слов ради двух строк дороже, чем повторить их.
CUES_DIR = ROOT / "output" / "cues"
CUES_BITRATE = "128k"
```

- [ ] **Step 2: Реализовать публикацию**

Перед `def main(`:

```python
def publish(made: list[Path]) -> list[Path]:
    """m4a в папку телефона. Несжатых там быть не должно: три файла по 5 МБ
    в телефоне ни к чему, а разницы в наушнике на 128k нет.
    """
    CUES_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for src in made:
        key = src.stem.replace("stage_cues_", "")
        dst = CUES_DIR / f"lohen_words_{key}.m4a"
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-c:a", "aac", "-b:a", CUES_BITRATE, "-ac", "1", str(dst)],
            capture_output=True, text=True)
        if done.returncode:
            raise SystemExit(f"ffmpeg m4a: {done.stderr[-1500:]}")
        out.append(dst)
    return out
```

- [ ] **Step 3: Позвать из `main`**

После цикла по якорям, перед сборкой листа:

```python
    print("\nв телефон помощнику:")
    for path in publish(made):
        print(f"  {path.name}  {path.stat().st_size / 1e6:.2f} МБ")
    print(f"  лежат в {CUES_DIR}")
```

- [ ] **Step 4: Собрать и проверить**

Run: `python src/render_cues.py`
Run: `ls output/cues/`
Expected: рядом с `lohen_cues_riser*.m4a` появились `lohen_words_laugh.m4a`,
`lohen_words_picture.m4a`, `lohen_words_titles.m4a`.

- [ ] **Step 5: Коммит**

```bash
git add src/render_cues.py
git commit -m "cues: три дорожки слов едут в телефон рядом с ризами"
```

---

### Task 8: README и точка состояния

**Files:**
- Modify: `README.md:111-127`
- Create: `docs/status/2026-08-30-cue-anchors.md`
- Modify: `docs/status/INDEX.md`

- [ ] **Step 1: Переписать блок в `README.md`**

Заменить абзац от «Голосовые подсказки — две дорожки…» до строки с
`--start-at 0.95` включительно на:

````markdown
Голосовые подсказки — репетиционная дорожка и три сценические под три якоря
старта. Времена берутся из долей `scenario/strikes.json`, то есть из того же
источника, что тренажёр:

```bash
python src/render_cues.py
```

`output/rehearsal_cues_v2.wav` — номер плюс голос поверх, для репетиции дома.

Три сценические — моно, только подсказки, в наушник исполнителя с телефона
помощника за кулисами. Различаются тем, чем ловить старт номера:

| файл | ловить | в номере |
|---|---|---|
| `stage_cues_picture.wav` | экран оживает: два синих пятна | 0.00 |
| `stage_cues_laugh.wav` | первый смех Лоэна | 0.70 |
| `stage_cues_titles.wav` | смена блока титров | 5.00 |

Копии m4a едут в `output/cues/` — папку, которая целиком копируется в телефон.

`output/cue_sheet.md` — лист: чем ловить каждый якорь, за сколько до удара
слышно слово, что снято из-за наложения и как замерить задержку цепочки. Замер
один на все три: мерится нажатие плюс радиоканал, а они от якоря не зависят.
Замерил — пересобери своим числом:

```bash
python src/render_cues.py --chain 0.31
```
````

- [ ] **Step 2: Написать точку состояния**

Создать `docs/status/2026-08-30-cue-anchors.md`:

```markdown
# Три якоря синхронизации: чем ловить старт номера

30 августа 2026. Дорожка номера, видео и счёт не тронуты.

Заказ: «нам нужно синхронизироваться на чём-то. Я предлагаю синхронизироваться
после того, как исчезают первые субтитры за моим авторством».

## Что переставило вопрос

Play жмёт **помощник за кулисами**, а не исполнитель. Помощник видит экран —
значит зрительные якоря доступны, чего у исполнителя не было: он стоит спиной
к экрану и на 0.00 уже обходит стул. Но телефон у помощника, а наушник
Bluetooth — значит в цепочку встроился радиоканал через всю сцену.

## Три якоря, а не один

| якорь | ловить | в номере | разброс | сдвиг при цепочке 0.25 |
|---|---|---|---|---|
| `picture` | экран оживает | 0.00 | ±0.03–0.05 | 0.45 |
| `laugh` | первый смех | 0.70 | ±0.02–0.04 | 1.11 |
| `titles` | смена титров | 5.00 | ±0.05–0.08 | 5.45 |

Против самой тесной подсказки — «пошёл» с опережением 0.38 с — рабочие все
три. Точнее прочих оказался слуховой: на простой реакции ухо стабильнее глаза,
а предугадывание проигрывает им обоим.

Заказ исходил из обратного — что заранее видимое событие точнее внезапного.
Это верно как ощущение и неверно как расчёт: постоянная задержка вписывается в
сдвиг и потому ничего не стоит, а разброс у предугаданного нажатия больше, чем
у реакции.

## Якорь и цепочка разъехались

Было одно число `--start-at 0.95` = `SYNC_ON 0.70 + REACTION 0.25`. Стало:

    start_at = anchor.t + anchor.reaction + chain

Якорь — свойство номера, реакция — свойство модальности, цепочка — свойство
железа. **Замер делается один раз и чинит все три дорожки**; склеенные, они
требовали бы трёх замеров.

## Что взято готовым, а не написано заново

`CUES_FLOOR_DB = -60.0` из `src/render_count.py`: розовый шум подо всей
дорожкой против сна Bluetooth-наушника на цифровой тишине. У ризов это стоит с
17 августа, у слов не стояло — дорожка собрана 5 августа под провод.

Оговорка оттуда перенесена вместе с решением: страховка, а не доказанное
лечение, проверяется только на его наушнике.

Замер задержки тоже не изобретался: сверочная копия ризов
`lohen_cues_riser_sync.m4a` кладёт номер тихим фоном, и расхождение двух копий
одного звука слышно как хлопок. Ею ловятся и промах пуска, и задержка разом.

## Что добавлено

**Щелчок на 0.30 с.** Обрыв радиоканала в дорожке не лечится, но его можно
сделать заметным сразу. Не в нуле: первые ~0.2 с съедает пробуждение канала, и
щелчок в нуле срезало бы вместе с ними.

## Чего это не заменяет

Замер цепочки, прогон под запись, техническую репетицию. Какой из трёх якорей
виден и слышен с места помощника — вопрос к площадке, а не к расчёту.

## Вариант `titles` условный

Титры идут только в публикационную копию; в файле организаторам их нет. Чтобы
якорь существовал на площадке, надо вернуть титры в сценический рендер,
отменить решение «подпись с именем на сцене неуместна» и успеть заменить
видеофайл — срок сдачи видео у организаторов не выяснен. Дорожка собрана
заранее и ничего не блокирует.
```

- [ ] **Step 3: Дописать строку в `docs/status/INDEX.md`**

Добавить в таблицу, по образцу соседних строк:

```markdown
| [2026-08-30-cue-anchors](2026-08-30-cue-anchors.md) | не тронут | три якоря синхронизации сценической дорожки: `picture` 0.00, `laugh` 0.70, `titles` 5.00. Якорь и задержка цепочки считаются врозь — замер один на все три. Подложка −60 dBFS против сна Bluetooth-наушника перенесена от ризов, добавлен щелчок на 0.30 |
```

- [ ] **Step 4: Прогнать всё**

Run: `python -m pytest -q`
Expected: PASS, **497** тестов (475 было до начала работы плюс 22 новых).
Прогон занимает около шести минут — внутри задач гонять только целевой файл.

- [ ] **Step 5: Коммит**

```bash
git add README.md docs/status/
git commit -m "docs: точка состояния по якорям синхронизации, README про три дорожки"
```

---

## Самопроверка плана

**Покрытие спецификации.** §3 три якоря → Task 2. §5 разъезд якоря и цепочки →
Task 2 и 3. §6 подложка → Task 5, щелчок → Task 6. §8 три файла и лист →
Task 4, публикация в телефон → Task 7. §9 проверки → тесты в Task 2–6.
§7 гейт варианта `titles` — внешнее решение, кода не требует, назван в Task 8.

**Не покрыто намеренно:** §11 «запасной режим на случай плохого замера».
Спецификация прямо говорит, что это решение принимается по числу после замера,
а не заранее.

**Согласованность имён.** `Anchor.start_at(chain)` заведена в Task 2, зовётся в
Task 3 и 4. `anchor_by` — Task 2, зовётся в Task 3. `track_plan(key, chain,
start_at)` — Task 3, зовётся в Task 4 дважды: в `main` и в `sheet`. `floor` и
`click` — параметры `render`, заведены в Task 5 и 6, включаются в `main` там же.
`publish` и `CUES_DIR` — Task 7. `peak_db` — Task 1, зовётся в Task 5 и в тесте
Task 5. Хелпер `_mean_db` и метка `BUILT` заведены в Task 5, переиспользуются в
Task 6.

**Порядок задач.** Task 5 обязана идти после Task 4: её тесты читают собранные
`stage_cues_*.wav`, которых до Task 4 не существует. Метка `BUILT` пропустит их,
если файлов нет, — но тогда падение в Step 2 не случится, и TDD выродится.
