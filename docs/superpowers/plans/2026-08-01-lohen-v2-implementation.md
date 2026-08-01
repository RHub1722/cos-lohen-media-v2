# Лоэн v2 «Допрос» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать 60-секундную звуковую дорожку и видеофон к косплей-номеру Лоэна по спеке [2026-08-01-lohen-interrogation-scene-design.md](../specs/2026-08-01-lohen-interrogation-scene-design.md), со сдачей аудио 9 августа 2026.

**Architecture:** Единственный источник таймкодов — `scenario/timeline.json`. Его читают два независимых рендерера: `render_audio.py` собирает FFmpeg `filter_complex` по стемам и сводит мастер, `render_video.py` рисует процедурный фон по тем же событиям. Расхождение звука и картинки становится физически невозможным. Чистые функции (разбор сценария, валидация, построение графа фильтров) покрыты тестами; звук и картинка проверяются замерами через `ffprobe`/`loudnorm`, а не юнит-тестами.

**Tech Stack:** Python 3.12, FFmpeg 8.1 (`subprocess`, без pydub), pytest, ElevenLabs MCP для генерации голосов, SFX и музыки.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `src/models.py` | Схема `Event` и `Timeline`, разбор JSON, значения по умолчанию. Ничего не знает про FFmpeg |
| `src/probe.py` | Обёртка над `ffprobe`: длительность, частота, каналы файла. Кэширует результаты |
| `src/validator.py` | Проверки сценария до рендера. Возвращает список проблем, не бросает исключений |
| `src/filtergraph.py` | Построение строки `filter_complex` из событий. Чистая функция, полностью тестируема |
| `src/render_audio.py` | Вызовы FFmpeg: стемы, сумма, двухпроходная нормализация, mp3 |
| `src/measure.py` | Замеры готового мастера: LUFS, True Peak, длительность, окна кратковременной громкости |
| `src/render_video.py` | Процедурный видеофон по событиям с блоком `video` |
| `src/build.py` | Точка входа и CLI. Склеивает всё вышеперечисленное |
| `scenario/timeline.json` | Все таймкоды номера |
| `tests/` | Тесты на `models`, `validator`, `filtergraph` |

Модули разделены так, чтобы каждый держался в голове целиком. `filtergraph` вынесен из `render_audio` отдельно именно потому, что это единственная сложная логика в проекте, и её надо тестировать без запуска FFmpeg.

---

## Task 1: Каркас проекта

**Files:**
- Create: `requirements.txt`, `README.md`, `pytest.ini`, `output/.gitignore`

- [ ] **Step 1: Создать `requirements.txt`**

```text
# Проекту не нужны библиотеки для работы со звуком: всю обработку делает FFmpeg,
# Python только строит команды. Здесь только то, что нужно для тестов.
pytest>=8.0
```

- [ ] **Step 2: Создать `pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- [ ] **Step 3: Создать `output/.gitignore`**

```text
# Всё в этой папке воспроизводится командой `python src/build.py`.
*
!.gitignore
```

- [ ] **Step 4: Создать `README.md`** с разделами: что это, как запустить, структура, требования (Python 3.12+, FFmpeg в PATH).

- [ ] **Step 5: Коммит**

```bash
git add -A && git commit -m "Каркас проекта: зависимости, pytest, README"
```

---

## Task 2: `src/models.py` — схема события

**Files:**
- Create: `src/models.py`, `tests/test_models.py`

- [ ] **Step 1: Написать падающий тест**

```python
import pytest
from src.models import Event, Timeline, ScenarioError


def test_event_defaults():
    ev = Event.from_dict({"id": "click", "t": 18.0, "asset": "sfx/click.wav", "stem": "sfx"})
    assert ev.gain_db == 0.0
    assert ev.pan == 0.0
    assert ev.duration is None
    assert ev.fade_in == 0.01
    assert ev.fade_out == 0.01
    assert ev.video is None


def test_event_rejects_unknown_stem():
    with pytest.raises(ScenarioError, match="stem"):
        Event.from_dict({"id": "x", "t": 0.0, "asset": "a.wav", "stem": "drums"})


def test_event_rejects_pan_out_of_range():
    with pytest.raises(ScenarioError, match="pan"):
        Event.from_dict({"id": "x", "t": 0.0, "asset": "a.wav", "stem": "sfx", "pan": 1.5})


def test_timeline_parses_events_and_meta():
    tl = Timeline.from_dict({
        "version": "v2",
        "total_duration": 60.0,
        "events": [{"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"}],
    })
    assert tl.total_duration == 60.0
    assert tl.sample_rate == 48000
    assert len(tl.events) == 1


def test_timeline_events_sorted_by_time():
    tl = Timeline.from_dict({
        "total_duration": 60.0,
        "events": [
            {"id": "b", "t": 5.0, "asset": "b.wav", "stem": "sfx"},
            {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"},
        ],
    })
    assert [e.id for e in tl.events] == ["a", "b"]
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.models'`

- [ ] **Step 3: Реализовать `src/models.py`**

```python
"""Схема сценария. Ничего не знает про FFmpeg и файловую систему."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STEMS = ("voices", "sfx", "music", "ambience")


class ScenarioError(Exception):
    """Сценарий не соответствует схеме."""


@dataclass(frozen=True)
class Event:
    id: str
    t: float
    asset: str
    stem: str
    gain_db: float = 0.0
    pan: float = 0.0
    duration: float | None = None
    fade_in: float = 0.01
    fade_out: float = 0.01
    video: dict | None = None
    note: str = ""

    @staticmethod
    def from_dict(raw: dict) -> "Event":
        for key in ("id", "t", "asset", "stem"):
            if key not in raw:
                raise ScenarioError(f"событие без обязательного поля {key!r}: {raw}")

        stem = raw["stem"]
        if stem not in STEMS:
            raise ScenarioError(f"{raw['id']}: неизвестный stem {stem!r}, допустимы {STEMS}")

        pan = float(raw.get("pan", 0.0))
        if not -1.0 <= pan <= 1.0:
            raise ScenarioError(f"{raw['id']}: pan={pan} вне диапазона -1..1")

        t = float(raw["t"])
        if t < 0:
            raise ScenarioError(f"{raw['id']}: отрицательное время {t}")

        duration = raw.get("duration")
        return Event(
            id=str(raw["id"]),
            t=t,
            asset=str(raw["asset"]),
            stem=stem,
            gain_db=float(raw.get("gain_db", 0.0)),
            pan=pan,
            duration=None if duration is None else float(duration),
            fade_in=float(raw.get("fade_in", 0.01)),
            fade_out=float(raw.get("fade_out", 0.01)),
            video=raw.get("video"),
            note=str(raw.get("note", "")),
        )


@dataclass(frozen=True)
class Timeline:
    total_duration: float
    events: tuple[Event, ...]
    version: str = "v2"
    sample_rate: int = 48000
    target_lufs: float = -16.0
    target_tp: float = -1.5

    @staticmethod
    def from_dict(raw: dict) -> "Timeline":
        if "total_duration" not in raw:
            raise ScenarioError("в сценарии нет total_duration")
        events = tuple(sorted(
            (Event.from_dict(e) for e in raw.get("events", [])),
            key=lambda e: e.t,
        ))
        return Timeline(
            total_duration=float(raw["total_duration"]),
            events=events,
            version=str(raw.get("version", "v2")),
            sample_rate=int(raw.get("sample_rate", 48000)),
            target_lufs=float(raw.get("target_lufs", -16.0)),
            target_tp=float(raw.get("target_tp", -1.5)),
        )

    @staticmethod
    def load(path: str | Path) -> "Timeline":
        with open(path, encoding="utf-8") as fh:
            return Timeline.from_dict(json.load(fh))

    def by_stem(self, stem: str) -> tuple[Event, ...]:
        return tuple(e for e in self.events if e.stem == stem)
```

- [ ] **Step 4: Запустить тесты**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 5: Коммит**

```bash
git add src/models.py tests/test_models.py && git commit -m "models: схема события и сценария с разбором JSON"
```

---

## Task 3: `src/probe.py` — обёртка над ffprobe

**Files:**
- Create: `src/probe.py`

Тестами не покрывается: это тонкая обёртка над внешним процессом, и осмысленный тест потребовал бы настоящих WAV-файлов. Корректность проверяется тем, что валидатор на настоящих ассетах выводит правдоподобные цифры.

- [ ] **Step 1: Реализовать**

```python
"""Чтение параметров аудиофайла через ffprobe."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class AudioInfo:
    path: str
    duration: float
    sample_rate: int
    channels: int


class ProbeError(Exception):
    pass


@lru_cache(maxsize=512)
def probe(path: str | Path) -> AudioInfo:
    path = str(path)
    if not Path(path).is_file():
        raise ProbeError(f"файл не найден: {path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels:format=duration",
        "-of", "json", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProbeError(f"ffprobe не смог прочитать {path}: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise ProbeError(f"в файле нет аудиопотока: {path}")

    stream = data["streams"][0]
    return AudioInfo(
        path=path,
        duration=float(data["format"]["duration"]),
        sample_rate=int(stream["sample_rate"]),
        channels=int(stream["channels"]),
    )
```

- [ ] **Step 2: Проверить на настоящем файле**

Run: `python -c "from src.probe import probe; print(probe('C:/Cosplay/audio-project/assets/ice/ice_final_impact.wav'))"`
Expected: строка `AudioInfo(...)` с ненулевой длительностью

- [ ] **Step 3: Коммит**

```bash
git add src/probe.py && git commit -m "probe: чтение длительности, частоты и каналов через ffprobe"
```

---

## Task 4: `src/validator.py` — проверки до рендера

**Files:**
- Create: `src/validator.py`, `tests/test_validator.py`

- [ ] **Step 1: Написать падающий тест**

```python
from src.models import Timeline
from src.validator import Problem, check_timeline


def _tl(events, total=60.0):
    return Timeline.from_dict({"total_duration": total, "events": events})


def test_clean_timeline_has_no_structural_problems():
    tl = _tl([{"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert [p for p in problems if p.level == "error"] == []


def test_duplicate_ids_are_an_error():
    tl = _tl([
        {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"},
        {"id": "a", "t": 2.0, "asset": "b.wav", "stem": "sfx"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert any(p.level == "error" and "дубл" in p.message for p in problems)


def test_event_starting_past_total_duration_is_an_error():
    tl = _tl([{"id": "late", "t": 61.0, "asset": "a.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert any(p.level == "error" and "late" in p.message for p in problems)


def test_event_overrunning_the_end_is_a_warning():
    tl = _tl([{"id": "tail", "t": 59.0, "asset": "a.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 5.0)
    assert any(p.level == "warning" and "tail" in p.message for p in problems)


def test_missing_asset_is_an_error():
    def missing(path):
        raise FileNotFoundError(path)

    tl = _tl([{"id": "gone", "t": 1.0, "asset": "nope.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=missing)
    assert any(p.level == "error" and "gone" in p.message for p in problems)


def test_empty_stem_is_a_warning():
    tl = _tl([{"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"}])
    problems = check_timeline(tl, probe_fn=lambda p: 0.5)
    assert any(p.level == "warning" and "voices" in p.message for p in problems)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `python -m pytest tests/test_validator.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.validator'`

- [ ] **Step 3: Реализовать `src/validator.py`**

```python
"""Проверки сценария до рендера. Ничего не бросает — возвращает список проблем."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

from src.models import STEMS, Timeline


@dataclass(frozen=True)
class Problem:
    level: str  # "error" | "warning"
    message: str


def check_timeline(tl: Timeline, probe_fn: Callable[[str], float]) -> list[Problem]:
    """probe_fn получает путь к ассету и возвращает его длительность в секундах."""
    problems: list[Problem] = []

    counts = Counter(e.id for e in tl.events)
    for event_id, n in counts.items():
        if n > 1:
            problems.append(Problem("error", f"дублирующийся id {event_id!r}: {n} события"))

    if not tl.events:
        problems.append(Problem("error", "в сценарии нет событий"))

    for ev in tl.events:
        if ev.t >= tl.total_duration:
            problems.append(Problem(
                "error",
                f"{ev.id}: начинается на {ev.t:.3f}, за границей {tl.total_duration:.3f}",
            ))
            continue

        try:
            source_len = probe_fn(ev.asset)
        except Exception as exc:
            problems.append(Problem("error", f"{ev.id}: ассет недоступен — {exc}"))
            continue

        length = ev.duration if ev.duration is not None else source_len
        end = ev.t + length
        if end > tl.total_duration + 1e-6:
            problems.append(Problem(
                "warning",
                f"{ev.id}: кончается на {end:.3f}, будет обрезан по {tl.total_duration:.3f}",
            ))

        if ev.duration is not None and ev.duration > source_len + 1e-6:
            problems.append(Problem(
                "warning",
                f"{ev.id}: duration={ev.duration:.3f} длиннее файла {source_len:.3f}, пойдёт петлёй",
            ))

    used = {e.stem for e in tl.events}
    for stem in STEMS:
        if stem not in used:
            problems.append(Problem("warning", f"стем {stem} пуст, будет собран как тишина"))

    return problems


def format_problems(problems: list[Problem]) -> str:
    if not problems:
        return "Проверки пройдены, замечаний нет."
    lines = []
    for level in ("error", "warning"):
        chunk = [p for p in problems if p.level == level]
        if chunk:
            title = "ОШИБКИ" if level == "error" else "предупреждения"
            lines.append(f"{title} ({len(chunk)}):")
            lines.extend(f"  - {p.message}" for p in chunk)
    return "\n".join(lines)


def has_errors(problems: list[Problem]) -> bool:
    return any(p.level == "error" for p in problems)
```

- [ ] **Step 4: Запустить тесты**

Run: `python -m pytest tests/test_validator.py -v`
Expected: PASS, 6 тестов

- [ ] **Step 5: Коммит**

```bash
git add src/validator.py tests/test_validator.py && git commit -m "validator: проверки сценария до рендера"
```

---

## Task 5: `src/filtergraph.py` — построение filter_complex

Самое сложное место проекта и единственное, где ошибка тихая: неверный граф даёт не падение, а неправильный звук. Поэтому строится отдельным модулем и покрывается тестами целиком.

**Files:**
- Create: `src/filtergraph.py`, `tests/test_filtergraph.py`

- [ ] **Step 1: Написать падающий тест**

```python
from src.models import Timeline
from src.filtergraph import build_stem_graph, pan_gains


def _tl(events, total=60.0):
    return Timeline.from_dict({"total_duration": total, "events": events})


def test_pan_gains_centre_is_equal_and_constant_power():
    left, right = pan_gains(0.0)
    assert abs(left - right) < 1e-9
    assert abs(left**2 + right**2 - 1.0) < 1e-9


def test_pan_gains_hard_left_silences_right():
    left, right = pan_gains(-1.0)
    assert abs(left - 1.0) < 1e-9
    assert abs(right) < 1e-9


def test_graph_has_one_chain_per_event_and_one_amix():
    tl = _tl([
        {"id": "a", "t": 1.0, "asset": "a.wav", "stem": "sfx"},
        {"id": "b", "t": 2.0, "asset": "b.wav", "stem": "sfx"},
    ])
    graph, inputs = build_stem_graph(tl, "sfx")
    assert len(inputs) == 2
    assert graph.count("adelay") == 2
    assert graph.count("amix=inputs=2") == 1


def test_delay_is_expressed_in_milliseconds():
    tl = _tl([{"id": "a", "t": 12.4, "asset": "a.wav", "stem": "sfx"}])
    graph, _ = build_stem_graph(tl, "sfx")
    assert "adelay=12400|12400" in graph


def test_zero_delay_event_still_gets_a_chain():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}])
    graph, inputs = build_stem_graph(tl, "sfx")
    assert len(inputs) == 1
    assert "adelay=0|0" in graph


def test_gain_is_applied_in_decibels():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx", "gain_db": -8.5}])
    graph, _ = build_stem_graph(tl, "sfx")
    assert "volume=-8.500000dB" in graph


def test_looped_event_declares_stream_loop_on_its_input():
    tl = _tl([{"id": "room", "t": 0.0, "asset": "r.wav", "stem": "ambience", "duration": 18.6}])
    _, inputs = build_stem_graph(tl, "ambience")
    assert inputs[0].loop is True
    assert "atrim=0:18.600000" in build_stem_graph(tl, "ambience")[0]


def test_empty_stem_produces_silence_graph():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}])
    graph, inputs = build_stem_graph(tl, "music")
    assert inputs == []
    assert "anullsrc" in graph


def test_output_is_padded_and_trimmed_to_total_duration():
    tl = _tl([{"id": "a", "t": 0.0, "asset": "a.wav", "stem": "sfx"}], total=60.0)
    graph, _ = build_stem_graph(tl, "sfx")
    assert "apad" in graph
    assert "atrim=0:60.000000" in graph
    assert graph.rstrip().endswith("[out]")
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `python -m pytest tests/test_filtergraph.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.filtergraph'`

- [ ] **Step 3: Реализовать `src/filtergraph.py`**

```python
"""Построение filter_complex для одного стема. Чистые функции, FFmpeg не вызывается."""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.models import Event, Timeline


@dataclass(frozen=True)
class GraphInput:
    """Один вход ffmpeg: -i <path>, при loop=True перед ним идёт -stream_loop -1."""
    path: str
    loop: bool


def pan_gains(pan: float) -> tuple[float, float]:
    """Постоянная мощность: pan -1 это левый край, +1 правый, 0 центр."""
    angle = (pan + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _event_chain(index: int, ev: Event, sample_rate: int) -> str:
    left, right = pan_gains(ev.pan)
    steps = [
        f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo",
    ]

    if ev.duration is not None:
        steps.append(f"atrim=0:{ev.duration:.6f}")
        steps.append("asetpts=PTS-STARTPTS")

    if ev.fade_in > 0:
        steps.append(f"afade=t=in:st=0:d={ev.fade_in:.6f}")

    if ev.fade_out > 0 and ev.duration is not None:
        fade_start = max(0.0, ev.duration - ev.fade_out)
        steps.append(f"afade=t=out:st={fade_start:.6f}:d={ev.fade_out:.6f}")

    steps.append(f"volume={ev.gain_db:.6f}dB")
    steps.append(f"pan=stereo|c0={left:.6f}*c0|c1={right:.6f}*c1")

    delay_ms = int(round(ev.t * 1000))
    steps.append(f"adelay={delay_ms}|{delay_ms}")

    return f"[{index}:a]" + ",".join(steps) + f"[e{index}]"


def build_stem_graph(tl: Timeline, stem: str) -> tuple[str, list[GraphInput]]:
    """Возвращает строку filter_complex и список входов в порядке их индексов."""
    events = tl.by_stem(stem)
    total = tl.total_duration
    sr = tl.sample_rate

    if not events:
        graph = (
            f"anullsrc=r={sr}:cl=stereo,"
            f"atrim=0:{total:.6f},asetpts=PTS-STARTPTS[out]"
        )
        return graph, []

    inputs = [GraphInput(path=ev.asset, loop=ev.duration is not None) for ev in events]
    chains = [_event_chain(i, ev, sr) for i, ev in enumerate(events)]
    labels = "".join(f"[e{i}]" for i in range(len(events)))

    mix = (
        f"{labels}amix=inputs={len(events)}:normalize=0:dropout_transition=0,"
        f"apad,atrim=0:{total:.6f},asetpts=PTS-STARTPTS[out]"
    )
    return ";".join(chains + [mix]), inputs


def ffmpeg_input_args(inputs: list[GraphInput]) -> list[str]:
    args: list[str] = []
    for item in inputs:
        if item.loop:
            args += ["-stream_loop", "-1"]
        args += ["-i", item.path]
    return args
```

- [ ] **Step 4: Запустить тесты**

Run: `python -m pytest tests/test_filtergraph.py -v`
Expected: PASS, 9 тестов

- [ ] **Step 5: Коммит**

```bash
git add src/filtergraph.py tests/test_filtergraph.py && git commit -m "filtergraph: построение filter_complex по стемам"
```

---

## Task 6: `src/measure.py` — замеры мастера

**Files:**
- Create: `src/measure.py`

- [ ] **Step 1: Реализовать**

```python
"""Замеры готового файла: интегральная громкость, пик, окна кратковременной громкости."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Loudness:
    integrated_lufs: float
    true_peak_dbtp: float
    lra: float


def measure_loudness(path: str) -> Loudness:
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
    if not match:
        raise RuntimeError(f"loudnorm не вернул JSON для {path}:\n{result.stderr[-2000:]}")
    data = json.loads(match.group(0))
    return Loudness(
        integrated_lufs=float(data["input_i"]),
        true_peak_dbtp=float(data["input_tp"]),
        lra=float(data["input_lra"]),
    )


def measure_window(path: str, start: float, end: float) -> float:
    """Интегральная громкость участка. Нужна для проверки сжатия динамики."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
    if not match:
        raise RuntimeError(f"не удалось замерить окно {start}-{end} в {path}")
    return float(json.loads(match.group(0))["input_i"])


def measure_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ]
    return float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
```

- [ ] **Step 2: Проверить на существующем мастере предыдущего проекта**

Run: `python -c "from src.measure import measure_loudness; print(measure_loudness('C:/Cosplay/audio-project/output/master_v3.wav'))"`
Expected: LUFS около −16, True Peak ниже −1.5. Если файла нет — взять любой WAV из `assets`.

- [ ] **Step 3: Коммит**

```bash
git add src/measure.py && git commit -m "measure: замеры LUFS, True Peak и окон громкости"
```

---

## Task 7: `src/render_audio.py` — сборка стемов и мастера

**Files:**
- Create: `src/render_audio.py`

Порядок сборки: каждый стем рендерится отдельным файлом → четыре стема суммируются в предмастер → двухпроходный `loudnorm` даёт мастер. Так стемы и мастер гарантированно согласованы, а не собраны разными путями.

- [ ] **Step 1: Реализовать**

```python
"""Сборка стемов, суммы и нормализованного мастера через FFmpeg."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from src.filtergraph import build_stem_graph, ffmpeg_input_args
from src.models import STEMS, Timeline


class RenderError(Exception):
    pass


def _run(cmd: list[str], what: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"{what} упал:\n{' '.join(cmd)}\n\n{result.stderr[-4000:]}")
    return result.stderr


def render_stem(tl: Timeline, stem: str, assets_root: Path, out_path: Path) -> list[str]:
    graph, inputs = build_stem_graph(tl, stem)
    resolved = [
        type(item)(path=str(assets_root / item.path), loop=item.loop) for item in inputs
    ]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    if not resolved:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r={tl.sample_rate}:cl=stereo"]
        graph = f"[0:a]atrim=0:{tl.total_duration:.6f},asetpts=PTS-STARTPTS[out]"
    cmd += ffmpeg_input_args(resolved)
    cmd += [
        "-filter_complex", graph,
        "-map", "[out]",
        "-ar", str(tl.sample_rate), "-ac", "2", "-c:a", "pcm_s24le",
        str(out_path),
    ]
    _run(cmd, f"рендер стема {stem}")
    return cmd


def sum_stems(stem_paths: list[Path], tl: Timeline, out_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    for path in stem_paths:
        cmd += ["-i", str(path)]
    labels = "".join(f"[{i}:a]" for i in range(len(stem_paths)))
    graph = (
        f"{labels}amix=inputs={len(stem_paths)}:normalize=0:dropout_transition=0,"
        f"apad,atrim=0:{tl.total_duration:.6f},asetpts=PTS-STARTPTS[out]"
    )
    cmd += [
        "-filter_complex", graph, "-map", "[out]",
        "-ar", str(tl.sample_rate), "-ac", "2", "-c:a", "pcm_s24le",
        str(out_path),
    ]
    _run(cmd, "сумма стемов")


def _loudnorm_pass1(path: Path, tl: Timeline) -> dict:
    stderr = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"loudnorm=I={tl.target_lufs}:TP={tl.target_tp}:LRA=11:print_format=json",
        "-f", "null", "-",
    ], "loudnorm, первый проход")
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not match:
        raise RenderError("loudnorm не вернул измерения на первом проходе")
    return json.loads(match.group(0))


def normalize(premaster: Path, tl: Timeline, out_path: Path) -> dict:
    m = _loudnorm_pass1(premaster, tl)
    af = (
        f"loudnorm=I={tl.target_lufs}:TP={tl.target_tp}:LRA=11"
        f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}:linear=true:print_format=summary,"
        f"aresample={tl.sample_rate}:resampler=soxr:precision=28,"
        f"apad,atrim=0:{tl.total_duration:.6f},asetpts=PTS-STARTPTS"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", str(premaster), "-af", af,
        "-ar", str(tl.sample_rate), "-ac", "2", "-c:a", "pcm_s24le",
        str(out_path),
    ], "loudnorm, второй проход")
    return m


def to_mp3(wav_path: Path, mp3_path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", str(wav_path), "-c:a", "libmp3lame", "-b:a", "320k",
        str(mp3_path),
    ], "экспорт mp3")


def render_all(tl: Timeline, assets_root: Path, out_dir: Path, suffix: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem_paths = []
    commands = {}
    for stem in STEMS:
        path = out_dir / f"{stem}_{suffix}.wav"
        commands[stem] = render_stem(tl, stem, assets_root, path)
        stem_paths.append(path)

    premaster = out_dir / f"premaster_{suffix}.wav"
    sum_stems(stem_paths, tl, premaster)

    master = out_dir / f"master_{suffix}.wav"
    measured = normalize(premaster, tl, master)
    to_mp3(master, out_dir / f"master_{suffix}.mp3")

    return {"master": master, "stems": stem_paths, "premaster_measured": measured,
            "commands": commands}
```

- [ ] **Step 2: Коммит**

```bash
git add src/render_audio.py && git commit -m "render_audio: стемы, сумма, двухпроходная нормализация, mp3"
```

---

## Task 8: `src/build.py` — точка входа

**Files:**
- Create: `src/build.py`, `build.ps1`

- [ ] **Step 1: Реализовать `src/build.py`**

```python
"""Точка входа сборки. python src/build.py [--scenario ...] [--suffix ...]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.measure import measure_duration, measure_loudness, measure_window  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.probe import probe  # noqa: E402
from src.render_audio import render_all  # noqa: E402
from src.validator import check_timeline, format_problems, has_errors  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(ROOT / "scenario" / "timeline.json"))
    ap.add_argument("--suffix", default="v2")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    tl = Timeline.load(args.scenario)
    assets = ROOT / "assets"
    print(f"Сценарий: {args.scenario}")
    print(f"Событий: {len(tl.events)}, длительность {tl.total_duration:.3f} с\n")

    problems = check_timeline(tl, probe_fn=lambda p: probe(assets / p).duration)
    print(format_problems(problems), "\n")
    if has_errors(problems):
        print("Сборка остановлена: есть ошибки.")
        return 1
    if args.check_only:
        return 0

    result = render_all(tl, assets, ROOT / "output", args.suffix)
    master = result["master"]

    duration = measure_duration(str(master))
    loud = measure_loudness(str(master))
    quiet_block = measure_window(str(master), 0.0, 18.6)
    fight_block = measure_window(str(master), 20.6, 44.0)
    spread = fight_block - quiet_block

    report = {
        "master": str(master),
        "duration": duration,
        "integrated_lufs": loud.integrated_lufs,
        "true_peak_dbtp": loud.true_peak_dbtp,
        "lra": loud.lra,
        "interrogation_lufs": quiet_block,
        "combat_lufs": fight_block,
        "dynamic_spread_lu": spread,
        "events": len(tl.events),
    }
    (ROOT / "output" / f"render-report-{args.suffix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Мастер:       {master}")
    print(f"Длительность: {duration:.3f} с (цель {tl.total_duration:.3f})")
    print(f"LUFS:         {loud.integrated_lufs:.2f} (цель {tl.target_lufs})")
    print(f"True Peak:    {loud.true_peak_dbtp:.2f} dBTP (потолок {tl.target_tp})")
    print(f"Допрос:       {quiet_block:.2f} LUFS")
    print(f"Бой:          {fight_block:.2f} LUFS")
    print(f"Разброс:      {spread:.2f} LU (норма по спеке не больше 8)")
    if spread > 8.0:
        print("  ВНИМАНИЕ: динамика шире нормы, допрос потеряется в шумном зале.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Реализовать `build.ps1`** — обёртка, вызывающая `python src/build.py @args`. Сохранить с UTF-8 BOM.

- [ ] **Step 3: Проверить, что CLI работает вхолостую**

Run: `python src/build.py --check-only`
Expected: список ошибок про отсутствующие ассеты — на этом этапе это правильный результат.

- [ ] **Step 4: Коммит**

```bash
git add src/build.py build.ps1 && git commit -m "build: точка входа с проверками и замерами"
```

---

## Task 9: `scenario/timeline.json` — сценарий

**Files:**
- Create: `scenario/timeline.json`

Все таймкоды берутся из спеки, разделы 5–7 и 11. Уровни `gain_db` ставятся стартовыми по иерархии из раздела 12 и уточняются после первого замера.

- [ ] **Step 1: Записать сценарий** — 45 событий по четырём стемам: 17 `voices`, 21 `sfx`, 3 `music`, 4 `ambience`. Блок `video` — у 11 событий-якорей: три смены состояния и восемь вспышек.

- [ ] **Step 2: Проверить, что он разбирается**

Run: `python -c "from src.models import Timeline; tl=Timeline.load('scenario/timeline.json'); print(len(tl.events), tl.total_duration)"`
Expected: `45 60.0`

- [ ] **Step 3: Коммит**

```bash
git add scenario/timeline.json && git commit -m "scenario: полный таймлайн номера на 60 секунд"
```

---

## Task 10: Перенос проверенных ассетов

**Files:**
- Copy: семь файлов из `C:\Cosplay\audio-project\assets`

- [ ] **Step 1: Скопировать** `spear_whoosh_fast`, `spear_whoosh_heavy`, `spear_staff_impact`, `spear_armor_impact` в `assets/sfx/`, `freeze_spreading`, `ice_final_impact`, `ice_resonance_tail` в `assets/sfx/`.

- [ ] **Step 2: Проверить параметры каждого**

Run: `python -c "from src.probe import probe; import glob; [print(probe(p)) for p in glob.glob('assets/sfx/*.wav')]"`
Expected: 48000 Гц у всех, ненулевая длительность

- [ ] **Step 3: Коммит**

```bash
git add assets/sfx && git commit -m "assets: семь проверенных SFX перенесены из предыдущего проекта"
```

---

## Task 11: Подбор голоса Лоэна

Первая задача по генерации и самая рискованная: **голос обязан уметь смеяться.** Три смеха в дорожке несут смысл, а синтезированный смех — самое ненадёжное в TTS.

- [ ] **Step 1: Найти кандидатов** в библиотеке ElevenLabs: молодой мужской, английский, лёгкий, способный на смех и издёвку.
- [ ] **Step 2: Сгенерировать одну и ту же пробу** на каждом кандидате: короткий смех плюс реплика `Oh. Cat got your tongue?`. Смех — самая трудная проба, отсеет большинство.
- [ ] **Step 3: Сложить кандидатов** в `assets/voices/archive/` с именами `candidate_<voice>_probe.wav`.
- [ ] **Step 4: Записать список кандидатов** в `docs/voice-candidates.md` с id голоса, настройками и что слышно в пробе.
- [ ] **Step 5: Коммит**

```bash
git add docs/voice-candidates.md && git commit -m "voices: пробы кандидатов на голос Лоэна"
```

---

## Task 12: Генерация реплик

- [ ] **Step 1: Сгенерировать 14 событий Лоэна** по таблице из раздела 9 спеки в `assets/voices/`.
- [ ] **Step 2: Сгенерировать пленника**: дыхание петлёй и сломанную реплику на 0:07.3.
- [ ] **Step 3: Сгенерировать выкрик охраны** на 0:18.9.
- [ ] **Step 4: Замерить фактические длительности** и сверить с таблицей.

Run: `python -c "from src.probe import probe; import glob; [print(f'{p}: {probe(p).duration:.3f}') for p in sorted(glob.glob('assets/voices/*.wav'))]"`

- [ ] **Step 5: Подогнать таймкоды** в `scenario/timeline.json` под фактические длительности. Речь не ускорять и не сжимать — двигать события.
- [ ] **Step 6: Коммит**

```bash
git add assets/voices scenario/timeline.json && git commit -m "voices: все реплики сгенерированы, таймкоды выровнены по факту"
```

---

## Task 13: Генерация SFX

- [ ] **Step 1: Комната и допрос** — тон бетонной допросной, дыхание пленника, скрип стула, шаги, прокрут барабана, взвод курка, сухой щелчок.
- [ ] **Step 2: Вторжение** — вышибленная дверь, сапоги, лязг оружия.
- [ ] **Step 3: Бой** — копьё с опоры, глухой удар по Лоэну без крика и стона, отступающие шаги, брошенное оружие.
- [ ] **Step 4: Лёд** — подъём воздуха, ледяной разряд, замёрзшая комната.
- [ ] **Step 5: Проверить формат** каждого: 48 кГц. Всё, что пришло в другой частоте, пересчитать через `aresample=48000:resampler=soxr:precision=28` в новый файл, исходник оставить в `archive/`.
- [ ] **Step 6: Коммит**

```bash
git add assets/sfx assets/ambience && git commit -m "sfx: комната, револьвер, вторжение, бой, лёд"
```

---

## Task 14: Генерация музыки

- [ ] **Step 1: Низкий тик** — 6.2 с, низкая пульсация в ровном темпе, без мелодии.
- [ ] **Step 2: Боевой слой** — 26.4 с, с местом для прореживания к концу.
- [ ] **Step 3: Ледяной дрон** — 12.6 с, низкая холодная подложка без движения.
- [ ] **Step 4: Коммит**

```bash
git add assets/music && git commit -m "music: тик допроса, боевой слой, ледяной дрон"
```

---

## Task 15: Первая сборка и правка уровней

- [ ] **Step 1: Собрать**

Run: `python src/build.py`
Expected: мастер создан, длительность 60.000, LUFS около −16, True Peak ниже −1.5

- [ ] **Step 2: Проверить разброс динамики.** Если больше 8 LU — поднять `gain_db` событий блока допроса и опустить взлом двери, пересобрать.
- [ ] **Step 3: Проверить, что клиппинга нет** — True Peak строго ниже −1.5 dBTP.
- [ ] **Step 4: Коммит**

```bash
git add scenario/timeline.json && git commit -m "levels: уровни выставлены по замеру, динамика в пределах 8 LU"
```

---

## Task 16: Письмо организаторам

**Files:**
- Create: `docs/organizer-letter.md`

- [ ] **Step 1: Написать письмо** по восьми вопросам из раздела 16 спеки. Первыми — револьвер и передний свет: они блокируют работу.
- [ ] **Step 2: Коммит**

```bash
git add docs/organizer-letter.md && git commit -m "docs: письмо организаторам, готово к отправке"
```

---

## Task 17: `src/render_video.py`

Начинается только после заморозки аудио 9 августа. До этого таймкоды могут двигаться, и видео придётся переделывать.

- [ ] **Step 1: Три состояния палитры** по спеке, раздел 13.
- [ ] **Step 2: Якоря синхронизации** из блоков `video` в сценарии.
- [ ] **Step 3: Предохранитель** — затемнение центральной вертикальной полосы во всех состояниях.
- [ ] **Step 4: Мукс со звуком** в `output/final.mp4`.
- [ ] **Step 5: Коммит**

---

## Task 18: Точка состояния

- [ ] **Step 1: Создать** `docs/status/2026-08-XX-v2a.md`: что собрано, замеры, что перепроверить, открытые вопросы.
- [ ] **Step 2: Создать** `docs/status/INDEX.md` с таблицей точек.
- [ ] **Step 3: Коммит**

---

## Порядок и зависимости

Задачи 1–8 — код, идут подряд и ни от чего не зависят. Задача 9 нужна до любого рендера. Задачи 10–14 — ассеты, могут идти параллельно между собой, но задача 11 обязана быть первой из них: если голос не найдётся, весь блок реплик придётся переделывать. Задача 15 требует всего предыдущего. Задача 16 не зависит ни от чего и должна быть сделана в первый день. Задача 17 начинается после сдачи аудио.
