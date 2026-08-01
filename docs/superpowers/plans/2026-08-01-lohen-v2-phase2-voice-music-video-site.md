# Лоэн v2, вторая очередь: голос, музыка, видео, репетиционный сайт

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести все реплики Лоэна на голос Lo Mod v2, заменить музыку на гибрид трейлерной оркестровки с тяжёлым басом, собрать видеофон для LED-экрана и репетиционный сайт с описанием движений.

**Architecture:** Единственный источник таймкодов остаётся `scenario/timeline.json`. К нему добавляется второй источник — `scenario/movements.json` с описанием движений исполнителя; движения привязаны к событиям звука по `id`, и валидатор запрещает ссылку на несуществующее событие. Три потребителя читают эти два файла и ничего не знают друг о друге: `render_audio.py` собирает дорожку, `render_video.py` рисует фон, `render_rehearsal.py` печатает самодостаточную HTML-страницу с вшитыми данными.

**Tech Stack:** Python 3.12, FFmpeg 8.1, pytest, ElevenLabs MCP. Сайт — один HTML-файл без библиотек и без интернета, открывается двойным щелчком.

---

## Разбиение на очереди

Три фазы независимы и каждая даёт работающий результат. Их можно выполнять как три отдельные сессии.

| Фаза | Что даёт | Когда |
|---|---|---|
| **1. Голос и музыка** | пересобранный мастер, готовый к сдаче | **до 9 августа, блокирует всё** |
| **2. Репетиционный сайт** | страница для постановки хореографии | можно начинать сразу, не ждёт заморозки |
| **3. Видео на LED** | `final.mp4` со звуком внутри | только после заморозки аудио |

Фаза 3 идёт последней намеренно: пока таймкоды могут двигаться, видео придётся переделывать.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `scenario/movements.json` | описание движений: что делать, с какой скоростью, насколько мощно |
| `src/movements.py` | схема движения, загрузка, привязка к событиям звука |
| `src/render_rehearsal.py` | генератор самодостаточной HTML-страницы с вшитыми данными |
| `src/render_video.py` | процедурный видеофон по событиям с блоком `video` |
| `src/validator.py` | расширяется: наложение реплик и висячие ссылки движений |
| `tests/test_movements.py` | схема движений |
| `tests/test_validator.py` | дополняется двумя проверками |

---

# ФАЗА 1. Голос и музыка

## Task 1: Перегенерация реплик Лоэна голосом Lo Mod v2

Голос: `Lo Mod v2`, id `5L1KqcuIYxrRg4k4opVX`, модель `eleven_v3`.

**Пленник и охрана не трогаются.** Если они зазвучат голосом Лоэна, зал не поймёт, что в комнате три человека, и пустой стул перестанет читаться как пленник.

**Files:**
- Create: 14 файлов в `assets/voices/archive/lomod2/`
- Modify: `assets/asset-manifest.json`, `assets/voices/*.wav`

- [ ] **Step 1: Сгенерировать 14 реплик** через `mcp__ElevenLabs__text_to_speech`, каждый вызов с `voice_id=5L1KqcuIYxrRg4k4opVX`, `model_id=eleven_v3`, `output_format=mp3_44100_192`, `output_directory=C:/Cosplay/audio-project-v2/assets/voices/archive/lomod2`.

| Файл | Текст | stability | style |
|---|---|---|---|
| `lohen_laugh_1` | `Heh. [laughs]` | 0.35 | 0.50 |
| `lohen_impressed` | `Still awake? I'm impressed.` | 0.40 | 0.35 |
| `lohen_security` | `One more time. Where's the security posted?` | 0.55 | 0.20 |
| `lohen_tongue` | `Oh. Cat got your tongue?` | 0.35 | 0.45 |
| `lohen_game` | `Then let's play a little game.` | 0.35 | 0.45 |
| `lohen_chambers` | `Six chambers. One bullet.` | 0.45 | 0.30 |
| `lohen_count` | `Three... two...` | 0.50 | 0.30 |
| `lohen_laugh_2` | `Hah. [laughs]` | 0.30 | 0.55 |
| `lohen_finally` | `Finally.` | 0.40 | 0.40 |
| `lohen_feel` | `Didn't even feel it.` | 0.40 | 0.40 |
| `lohen_thatall` | `Is that all you brought?` | 0.45 | 0.35 |
| `lohen_really` | `...Really?` | 0.50 | 0.30 |
| `lohen_laugh_3` | `Hm. [laughs]` | 0.30 | 0.55 |
| `lohen_final` | `They asked for a masterpiece. Consider it finished.` | 0.55 | 0.30 |

Три реплики уже сгенерированы этим голосом при сравнении версий и переиспользуются: `lohen_laugh_1`, `lohen_impressed`, `lohen_tongue`, `lohen_game`, `lohen_final`.

- [ ] **Step 2: Прописать новые имена файлов в `assets/asset-manifest.json`**, заменив пути в блоке `map.voices` на файлы из `lomod2/`. Записать в блок `voice_lohen` новый id и имя. Старые записи не удалять — перенести в блок `voice_lohen_previous`, чтобы был след, чем озвучивалась первая сборка.

- [ ] **Step 3: Перенести и привести к формату проекта**

Run: `python src/import_assets.py`
Expected: строка `Перенесено файлов: 36`, у всех реплик Лоэна новые длительности

- [ ] **Step 4: Коммит**

```bash
git add assets scenario && git commit -m "voices: все реплики Лоэна перегенерированы голосом Lo Mod v2"
```

---

## Task 2: Валидатор ловит наложение реплик

Перегенерация меняет длительности, и две реплики могут наехать друг на друга. Сейчас валидатор этого не видит: он проверяет только выход за границу дорожки. Наложение двух голосов — тихий дефект, слышный только при прослушивании.

**Files:**
- Modify: `src/validator.py`, `tests/test_validator.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_overlapping_voice_events_are_an_error():
    tl = _full([
        {"id": "line_a", "t": 1.0, "asset": "a.wav", "stem": "voices"},
        {"id": "line_b", "t": 2.0, "asset": "b.wav", "stem": "voices"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 3.0)
    assert any(p.level == "error" and "line_a" in p.message and "line_b" in p.message
               for p in problems)


def test_adjacent_voice_events_are_fine():
    tl = _full([
        {"id": "line_a", "t": 1.0, "asset": "a.wav", "stem": "voices"},
        {"id": "line_b", "t": 5.0, "asset": "b.wav", "stem": "voices"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 2.0)
    assert not any("line_a" in p.message and "line_b" in p.message for p in problems)


def test_overlapping_sfx_events_are_allowed():
    """Взмах и попадание накладываются намеренно — это не дефект."""
    tl = _full([
        {"id": "whoosh", "t": 1.0, "asset": "w.wav", "stem": "sfx"},
        {"id": "impact", "t": 1.3, "asset": "i.wav", "stem": "sfx"},
    ])
    problems = check_timeline(tl, probe_fn=lambda p: 1.0)
    assert not any(p.level == "error" for p in problems)
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `python -m pytest tests/test_validator.py -k overlap -v`
Expected: FAIL, ошибка про наложение не находится

- [ ] **Step 3: Дописать проверку в `src/validator.py`**, сразу перед блоком с пустыми стемами

```python
    # Наложение реплик — тихий дефект: два голоса звучат одновременно, и это
    # слышно только на прослушивании. У sfx наложение штатное: взмах и
    # попадание намеренно перекрываются.
    voices = sorted(tl.by_stem("voices"), key=lambda e: e.t)
    for earlier, later in zip(voices, voices[1:]):
        try:
            length = earlier.duration or probe_fn(earlier.asset)
        except Exception:
            continue
        overlap = (earlier.t + length) - later.t
        if overlap > 1e-3:
            problems.append(Problem(
                "error",
                f"{earlier.id} и {later.id} накладываются на {overlap:.3f} с — "
                f"два голоса зазвучат одновременно",
            ))
```

- [ ] **Step 4: Запустить все тесты**

Run: `python -m pytest -q`
Expected: PASS, 39 тестов

- [ ] **Step 5: Проверить на настоящем сценарии**

Run: `python src/build.py --check-only`
Expected: если после перегенерации реплики наехали — список пар с величиной наложения

- [ ] **Step 6: Развести наложения**, двигая события в `scenario/timeline.json`. Речь не ускорять и не сжимать. Опорные точки, которые двигать нельзя: щелчок 21.7, дверь 22.3, удар копья 47.0, финальный удар 55.2.

- [ ] **Step 7: Коммит**

```bash
git add src/validator.py tests/test_validator.py scenario/timeline.json && git commit -m "validator: наложение реплик стало ошибкой; таймкоды разведены"
```

---

## Task 3: Новая музыка — четыре слоя вместо трёх

Жанр: **гибрид трейлерной оркестровки с тяжёлым электронным басом.** Оркестр даёт эпичность и связь с первоисточником, бас и дроп — ощущение, что Лоэну весело. Чистый дабстеп увёл бы номер от персонажа, чистая оркестровка не дала бы драйва.

Сейчас в музыке дыра **22.3–26.9**: дверь вышибли, а музыки нет до момента, когда он берёт копьё. Туда встаёт новый слой — раскрутка, которая разрешается дропом.

| Слой | Живёт | Роль |
|---|---|---|
| `music_interrogation` | 0.0–16.2 | низкий гул под допросом, почти на пороге слышимости |
| `music_tick` | 16.2–22.3 | существующий, отсчёт игры, умирает на щелчке |
| `music_riser` | 22.3–26.9 | **новый**: раскрутка от вышибленной двери к дропу |
| `music_combat` | 26.9–47.0 | **перегенерировать**: дроп на первой доле, дальше драйв |
| `music_ice_drone` | 47.4–60.0 | существующий, холодная подложка |

Обрыв музыки на 47.0 сохраняется без изменений — на нём держится весь ледяной финал.

**Files:**
- Create: 3 файла в `assets/music/archive/`
- Modify: `assets/asset-manifest.json`, `scenario/timeline.json`

- [ ] **Step 1: Сгенерировать подложку допроса** через `mcp__ElevenLabs__compose_music`, `force_instrumental=true`, `music_length_ms=20000`, `output_directory=C:/Cosplay/audio-project-v2/assets/music/archive`

```text
A very low, dark ambient drone for a concrete interrogation room. Deep sub-bass
foundation with faint metallic resonance far above it. Tense and patient,
holding still. No melody, no chords, no percussion, no build, no resolution.
Should sit almost below the threshold of hearing.
```

- [ ] **Step 2: Сгенерировать раскрутку** — `music_length_ms=8000`

```text
A short aggressive riser building tension toward a drop. Starts the instant a
steel door is kicked in: low distorted bass swell, rising filtered noise,
orchestral strings climbing, and a hard snare build accelerating to the very
end. It must end at maximum tension without resolving — the drop lands after
this clip, not inside it.
```

- [ ] **Step 3: Сгенерировать боевой слой** — `music_length_ms=26000`

```text
Hybrid trailer music with heavy electronic bass. It opens on the drop itself,
full force from the very first beat: massive distorted sub-bass, aggressive
syncopated bass design, hard drums, and epic orchestral strings and brass
riding on top. The energy is exhilarated rather than grim — this is a fighter
who is enjoying himself, not a villain. Keeps driving for most of its length,
then strips down over the final six seconds to bass and pulse alone. No vocals,
no fade to silence at the end.
```

- [ ] **Step 4: Прописать в манифест** блоки с вырезкой окна. Длина у генераций плавает, поэтому окно задаётся явно:

```json
"music__<новый файл 1>.mp3": {
  "file": "music_interrogation.wav", "start": 2.0, "duration": 18.0,
  "why": "Пропускаем первые две секунды: у генераций часто медленный вход."
},
"music__<новый файл 2>.mp3": {
  "file": "music_riser.wav", "start": 0.0, "duration": 5.0,
  "why": "Берём хвост раскрутки: пик напряжения должен прийтись на 26.9."
},
"music__<новый файл 3>.mp3": {
  "file": "music_combat.wav", "start": 0.0, "duration": 22.0,
  "why": "Дроп на первой доле, начало берём как есть."
}
```

- [ ] **Step 5: Перенести**

Run: `python src/import_assets.py`
Expected: три новых файла в `assets/music/` с заданными длительностями

- [ ] **Step 6: Проверить, что раскрутка растёт, а дроп начинается сразу**

Run: `python src/check_music.py`

Скрипт создаётся здесь же, `src/check_music.py`:

```python
"""Уровень музыкальных слоёв по секундам. Раскрутка обязана расти, дроп — начинаться сразу."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]

for name in ("music_interrogation", "music_riser", "music_combat", "music_ice_drone"):
    path = ROOT / "assets/music" / f"{name}.wav"
    if not path.is_file():
        print(f"{name}: нет файла")
        continue
    total = float(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], capture_output=True, text=True).stdout.strip())
    marks = []
    step = max(1.0, total / 6)
    t = 0.0
    while t < total - 0.5:
        end = min(t + step, total)
        out = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-to", f"{end:.2f}",
            "-i", str(path), "-af", "volumedetect", "-f", "null", "-",
        ], capture_output=True, text=True).stderr
        m = re.search(r"mean_volume: (-?[\d.]+)", out)
        marks.append(f"{t:4.1f}с {m.group(1):>6}" if m else f"{t:4.1f}с      ?")
        t = end
    print(f"{name:20} " + "  ".join(marks))
```

Expected: у `music_riser` уровень растёт от первой метки к последней; у `music_combat` первая метка не тише остальных.

- [ ] **Step 7: Добавить два события в `scenario/timeline.json`**

```json
{
  "id": "music_interrogation",
  "t": 0.0, "asset": "music/music_interrogation.wav", "stem": "music",
  "duration": 16.2, "gain_db": -26.0, "fade_in": 1.5, "fade_out": 0.8,
  "note": "Подложка допроса на пороге слышимости. Уходит, когда входит тик."
},
{
  "id": "music_riser",
  "t": 22.3, "asset": "music/music_riser.wav", "stem": "music",
  "duration": 4.6, "gain_db": -13.0, "fade_in": 0.05, "fade_out": 0.05,
  "note": "От вышибленной двери до дропа. Кончается ровно на 26.9, где входит боевой слой."
}
```

- [ ] **Step 8: Коммит**

```bash
git add assets scenario src/check_music.py && git commit -m "music: подложка допроса, раскрутка к дропу, боевой слой в гибридном жанре"
```

---

## Task 4: Пересборка и правка уровней

**Files:**
- Modify: `scenario/timeline.json`

- [ ] **Step 1: Собрать**

Run: `python src/build.py`
Expected: 60.000 с, LUFS около −16, True Peak ниже −1.5, предупреждений нет

- [ ] **Step 2: Проверить иерархию акцентов по предмастеру**, не по мастеру

Run: `python src/check_levels.py`

Скрипт создаётся здесь же, `src/check_levels.py`:

```python
"""Пики акцентов в предмастере. В мастере лимитер сводит верхушки в один
потолок, и по нему иерархию не увидеть."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
PREMASTER = ROOT / "output/premaster_v2.wav"

ACCENTS = [
    ("дверь", 22.3, 23.2),
    ("вспышка 1", 28.4, 29.9),
    ("вспышка 3", 38.5, 39.9),
    ("удар по нему", 42.7, 44.0),
    ("копьё в пол", 46.9, 47.8),
    ("ФИНАЛЬНЫЙ УДАР", 55.1, 56.3),
]

rows = []
for label, start, end in ACCENTS:
    out = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start}", "-to", f"{end}",
        "-i", str(PREMASTER), "-af", "volumedetect", "-f", "null", "-",
    ], capture_output=True, text=True).stderr
    m = re.search(r"max_volume: (-?[\d.]+)", out)
    rows.append((label, float(m.group(1)) if m else 0.0))

for label, peak in rows:
    print(f"  {label:18} {peak:6.1f} dB")

loudest = max(rows, key=lambda r: r[1])
if loudest[0] != "ФИНАЛЬНЫЙ УДАР":
    print(f"\n  ВНИМАНИЕ: главный акцент номера перекрыт — громче всех «{loudest[0]}».")
else:
    print("\n  Иерархия в порядке: финальный удар — абсолютный пик.")
```

Expected: строка «Иерархия в порядке»

- [ ] **Step 3: Если иерархия перевёрнута** — опустить перекрывающую группу на 3–5 дБ в `scenario/timeline.json` и пересобрать. Финальный удар не поднимать: он уже на 0.0 дБ.

- [ ] **Step 4: Проверить разброс динамики.** В выводе `build.py` строка «Разброс». Норма — не больше 8 LU.

- [ ] **Step 5: Коммит**

```bash
git add scenario/timeline.json && git commit -m "levels: уровни выставлены по замеру после смены голоса и музыки"
```

---

## Task 5: Точка состояния и обновление сценария

**Files:**
- Create: `docs/status/2026-08-XX-v2b.md`
- Modify: `docs/status/INDEX.md`, `scenario/SCENARIO_V2_60S.md`

- [ ] **Step 1: Создать точку состояния** по образцу `2026-08-01-v2a.md`: замеры, что изменилось, что перепроверить на слух, открытые вопросы.
- [ ] **Step 2: Дописать строку в `docs/status/INDEX.md`.**
- [ ] **Step 3: Обновить в `scenario/SCENARIO_V2_60S.md`** таблицу длительностей реплик (§9), раскладку музыки (§11 проектного решения переносится в §10 сценария) и идентификатор голоса.
- [ ] **Step 4: Коммит**

```bash
git add docs scenario && git commit -m "docs: точка состояния v2b, сценарий синхронизирован"
```

---

# ФАЗА 2. Репетиционный сайт

## Task 6: `scenario/movements.json` — данные движений

Главное содержимое сайта. Каждое движение привязано к событию звука по `id`, поэтому таймкод не дублируется и не может разойтись.

Шкалы `speed` и `power` — от 1 до 5. Это не физика, а язык для постановки: 1 — медленно и мягко, 5 — резко и во всю силу.

**Files:**
- Create: `scenario/movements.json`

- [ ] **Step 1: Записать файл**

```json
{
  "note": "Движения исполнителя. Таймкод берётся из события звука по trigger_event и здесь не дублируется. speed и power — шкала 1..5: 1 медленно и мягко, 5 резко и во всю силу.",
  "movements": [
    {
      "id": "circling",
      "trigger_event": "room_interrogation",
      "name": "Обход стула",
      "what": "Медленно обходишь пустой стул. Шаг неторопливый, руки свободны. Ты не допрашиваешь — ты убиваешь время.",
      "speed": 1, "power": 1, "duration": 11.0,
      "hold": "Держишь до наклона. Ни одного резкого движения."
    },
    {
      "id": "lean_in",
      "trigger_event": "lohen_tongue",
      "name": "Наклон к стулу",
      "what": "Наклоняешься вплотную к пустому стулу, лицом на уровень сидящего. Одна рука на спинке.",
      "speed": 2, "power": 2, "duration": 1.2,
      "hold": "Задержаться внизу до конца реплики, потом выпрямиться на счёт музыки."
    },
    {
      "id": "revolver_up",
      "trigger_event": "revolver_cylinder_spin",
      "name": "Револьвер вверх, прокрут барабана",
      "what": "Поднимаешь револьвер на уровень головы и крутишь барабан. Держи высоко — это должно быть видно с последнего ряда.",
      "speed": 3, "power": 2, "duration": 1.6,
      "hold": "Рука остаётся поднятой, пока говоришь про шесть камор."
    },
    {
      "id": "pull_trigger",
      "trigger_event": "revolver_dry_click",
      "name": "Спуск, глядя в зал",
      "what": "Наводишь на стул НЕ ГЛЯДЯ — голова повёрнута в зал. Жмёшь спуск. Осечка. Пожимаешь плечом.",
      "speed": 2, "power": 3, "duration": 1.0,
      "hold": "Главный кадр блока. Не смотри на стул ни в какой момент."
    },
    {
      "id": "head_turn",
      "trigger_event": "door_breach",
      "name": "Голова на звук двери",
      "what": "Только голова поворачивается к двери. Корпус не двигается.",
      "speed": 4, "power": 2, "duration": 0.5,
      "hold": "Пауза, пока кричит охрана."
    },
    {
      "id": "straighten_grin",
      "trigger_event": "lohen_laugh_2",
      "name": "Выпрямиться и улыбнуться",
      "what": "Разворачиваешься корпусом, выпрямляешься. Не испуг — радость. Наконец-то что-то интересное.",
      "speed": 2, "power": 3, "duration": 1.5,
      "hold": "Держать до взрыва музыки."
    },
    {
      "id": "take_spear",
      "trigger_event": "music_combat",
      "name": "Оставить револьвер, взять копьё",
      "what": "Демонстративно бросаешь револьвер на сиденье стула и снимаешь копьё с опоры. Одно слитное движение.",
      "speed": 4, "power": 3, "duration": 1.5,
      "hold": "Самое узкое место постановки: на всё две с половиной секунды."
    },
    {
      "id": "burst_1",
      "trigger_event": "burst1_whoosh",
      "name": "Вспышка 1: горизонтальный взмах",
      "what": "Быстрый горизонтальный взмах слева направо с попаданием древком.",
      "speed": 5, "power": 4, "duration": 1.3,
      "hold": "После — медленный обход, разворот к новой стороне. НЕ стойка."
    },
    {
      "id": "burst_2",
      "trigger_event": "burst2_whoosh",
      "name": "Вспышка 2: разворот с выпадом",
      "what": "Тяжёлый взмах через разворот, заканчивается выпадом с ударом по броне.",
      "speed": 5, "power": 5, "duration": 1.5,
      "hold": "Дальше прогулочный шаг, смена направления."
    },
    {
      "id": "burst_3",
      "trigger_event": "burst3_whoosh",
      "name": "Вспышка 3: полный оборот в низкий выпад",
      "what": "Полный оборот с копьём, два попадания подряд, финиш в низком выпаде. Самое крупное движение боя.",
      "speed": 5, "power": 5, "duration": 2.4,
      "hold": "Медленно распрямляешься. Не спеши."
    },
    {
      "id": "take_the_hit",
      "trigger_event": "hit_on_lohen",
      "name": "Принять удар",
      "what": "Голова резко дёргается вбок, как от попадания. Корпус НЕ уходит. Пауза. Потом медленно поворачиваешь голову обратно и смеёшься.",
      "speed": 5, "power": 2, "duration": 1.2,
      "hold": "Самое ценное место номера. Пауза после рывка обязательна — без неё не читается."
    },
    {
      "id": "burst_4",
      "trigger_event": "burst4_whoosh",
      "name": "Вспышка 4: встречный удар",
      "what": "Один короткий встречный удар. Коротко и без замаха.",
      "speed": 5, "power": 4, "duration": 1.2,
      "hold": "После — стоишь. Бой кончился."
    },
    {
      "id": "spear_down",
      "trigger_event": "ice_burst",
      "name": "КОПЬЁ В ПОЛ",
      "what": "Замах вверх на подъёме воздуха, затем удар копьём в пол в точку метки. Руки уходят с древка, копьё остаётся стоять само.",
      "speed": 5, "power": 5, "duration": 1.0,
      "hold": "Не держи древко после удара. Копьё стоит, ты стоишь свободно."
    },
    {
      "id": "power_pose",
      "trigger_event": "lohen_final",
      "name": "Поза силы",
      "what": "Прямая спина, ровный подбородок, раскрытая расслабленная кисть вдоль тела. НЕ боевая стойка. Ты уже победил.",
      "speed": 1, "power": 1, "duration": 3.8,
      "hold": "Ни одного движения, пока говоришь."
    },
    {
      "id": "final_pose",
      "trigger_event": "ice_final_impact",
      "name": "Финальная поза",
      "what": "Подбородок на волос выше. Больше ничего не меняется.",
      "speed": 2, "power": 3, "duration": 0.6,
      "hold": "Держать 4.8 секунды до конца дорожки. Это самая длинная неподвижность номера."
    }
  ]
}
```

- [ ] **Step 2: Коммит**

```bash
git add scenario/movements.json && git commit -m "scenario: пятнадцать движений с описанием скорости и силы"
```

---

## Task 7: `src/movements.py` — схема и привязка

**Files:**
- Create: `src/movements.py`, `tests/test_movements.py`

- [ ] **Step 1: Написать падающий тест**

```python
import pytest

from src.models import Timeline
from src.movements import Movement, MovementError, load_movements, resolve_times


def _tl():
    return Timeline.from_dict({
        "total_duration": 60.0,
        "events": [
            {"id": "ice_burst", "t": 47.0, "asset": "a.wav", "stem": "sfx"},
            {"id": "lohen_final", "t": 51.0, "asset": "b.wav", "stem": "voices"},
        ],
    })


def test_movement_parses_required_fields():
    m = Movement.from_dict({
        "id": "spear_down", "trigger_event": "ice_burst", "name": "Копьё в пол",
        "what": "Удар в пол.", "speed": 5, "power": 5, "duration": 1.0,
    })
    assert m.speed == 5
    assert m.hold == ""


def test_movement_rejects_scale_out_of_range():
    with pytest.raises(MovementError, match="speed"):
        Movement.from_dict({
            "id": "x", "trigger_event": "ice_burst", "name": "n", "what": "w",
            "speed": 7, "power": 3, "duration": 1.0,
        })


def test_resolve_times_takes_time_from_the_triggering_event():
    movements = [Movement.from_dict({
        "id": "spear_down", "trigger_event": "ice_burst", "name": "n", "what": "w",
        "speed": 5, "power": 5, "duration": 1.0,
    })]
    resolved = resolve_times(movements, _tl())
    assert resolved[0].t == 47.0


def test_resolve_times_rejects_a_dangling_trigger():
    movements = [Movement.from_dict({
        "id": "ghost", "trigger_event": "no_such_event", "name": "n", "what": "w",
        "speed": 1, "power": 1, "duration": 1.0,
    })]
    with pytest.raises(MovementError, match="no_such_event"):
        resolve_times(movements, _tl())


def test_resolved_movements_are_sorted_by_time():
    movements = [
        Movement.from_dict({"id": "b", "trigger_event": "lohen_final", "name": "n",
                            "what": "w", "speed": 1, "power": 1, "duration": 1.0}),
        Movement.from_dict({"id": "a", "trigger_event": "ice_burst", "name": "n",
                            "what": "w", "speed": 1, "power": 1, "duration": 1.0}),
    ]
    assert [m.id for m in resolve_times(movements, _tl())] == ["a", "b"]
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `python -m pytest tests/test_movements.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.movements'`

- [ ] **Step 3: Реализовать `src/movements.py`**

```python
"""Движения исполнителя. Таймкод не хранится, а берётся из события звука.

Так постановка и дорожка не могут разойтись: если событие переименовали или
убрали, привязка ломается на валидации, а не на репетиции.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from src.models import Timeline


class MovementError(Exception):
    pass


@dataclass(frozen=True)
class Movement:
    id: str
    trigger_event: str
    name: str
    what: str
    speed: int
    power: int
    duration: float
    hold: str = ""
    t: float = -1.0  # проставляется в resolve_times

    @staticmethod
    def from_dict(raw: dict) -> "Movement":
        for key in ("id", "trigger_event", "name", "what", "speed", "power", "duration"):
            if key not in raw:
                raise MovementError(f"движение без обязательного поля {key!r}: {raw}")
        for scale in ("speed", "power"):
            value = int(raw[scale])
            if not 1 <= value <= 5:
                raise MovementError(
                    f"{raw['id']}: {scale}={value} вне шкалы 1..5"
                )
        return Movement(
            id=str(raw["id"]),
            trigger_event=str(raw["trigger_event"]),
            name=str(raw["name"]),
            what=str(raw["what"]),
            speed=int(raw["speed"]),
            power=int(raw["power"]),
            duration=float(raw["duration"]),
            hold=str(raw.get("hold", "")),
        )


def load_movements(path: str | Path) -> list[Movement]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return [Movement.from_dict(m) for m in raw.get("movements", [])]


def resolve_times(movements: list[Movement], tl: Timeline) -> list[Movement]:
    by_id = {e.id: e for e in tl.events}
    resolved = []
    for m in movements:
        event = by_id.get(m.trigger_event)
        if event is None:
            raise MovementError(
                f"{m.id}: движение ссылается на событие {m.trigger_event!r}, "
                f"которого нет в сценарии"
            )
        resolved.append(replace(m, t=event.t))
    return sorted(resolved, key=lambda m: m.t)
```

- [ ] **Step 4: Запустить тесты**

Run: `python -m pytest tests/test_movements.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 5: Проверить на настоящих данных**

Run: `python -c "from src.models import Timeline; from src.movements import load_movements, resolve_times; tl=Timeline.load('scenario/timeline.json'); ms=resolve_times(load_movements('scenario/movements.json'), tl); print(len(ms)); [print(f'{m.t:6.2f} {m.name}') for m in ms]"`
Expected: 15 движений, времена по возрастанию, ни одной висячей ссылки

- [ ] **Step 6: Коммит**

```bash
git add src/movements.py tests/test_movements.py && git commit -m "movements: схема движений с привязкой к событиям звука"
```

---

## Task 8: `src/render_rehearsal.py` — генератор страницы

Страница самодостаточная: данные вшиваются в HTML при генерации, потому что из `file://` подгрузить JSON браузер не даст. Дорожка подключается отдельным файлом, который пользователь выбирает сам, — так страницу можно переслать без 17 мегабайт звука.

**Files:**
- Create: `src/render_rehearsal.py`
- Modify: `scenario/timeline.json`

- [ ] **Step 1: Добавить полю `text` в шестнадцать голосовых событий `scenario/timeline.json`**

Сейчас текст реплики пришлось бы вытаскивать из `note`, а там режиссёрский комментарий вперемешку с самой репликой — на экране была бы каша. Заводим отдельное поле. `models.Event` его подхватит без изменений: неизвестные ключи он игнорирует, а читать будет генератор страницы напрямую из JSON.

| Событие | `text` |
|---|---|
| `lohen_laugh_1` | `(смех)` |
| `lohen_impressed` | `Still awake? I'm impressed.` |
| `lohen_security` | `One more time. Where's the security posted?` |
| `prisoner_refuse` | `I can't— they'll kill me—` |
| `lohen_tongue` | `Oh. Cat got your tongue?` |
| `lohen_game` | `Then let's play a little game.` |
| `lohen_chambers` | `Six chambers. One bullet.` |
| `lohen_count` | `Three... two...` |
| `guard_shout` | `There! Take him!` |
| `lohen_laugh_2` | `(смех, голоднее)` |
| `lohen_finally` | `Finally.` |
| `lohen_feel` | `Didn't even feel it.` |
| `lohen_thatall` | `Is that all you brought?` |
| `lohen_really` | `...Really?` |
| `lohen_laugh_3` | `(смех после удара)` |
| `lohen_final` | `They asked for a masterpiece. Consider it finished.` |

- [ ] **Step 2: Реализовать**

```python
"""Генератор самодостаточной репетиционной страницы.

Данные вшиваются в HTML при генерации: из file:// браузер не даст подгрузить
внешний JSON. Дорожку пользователь выбирает сам через файловый диалог, чтобы
страницу можно было переслать без 17 мегабайт звука.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/rehearsal_template.html"


# Названия сцен. Границы сцен не задаются отдельно: они выводятся из якорей
# video.state, которые уже стоят в сценарии для видеорендерера. Один источник
# на две подсистемы — сцены на странице не могут разойтись с картинкой.
SCENE_NAMES = {
    "interrogation": "Допрос",
    "combat": "Бой",
    "ice": "Лёд",
}


def build_scenes(raw_events: list[dict], total: float) -> list[dict]:
    starts = sorted(
        (e["t"], e["video"]["state"])
        for e in raw_events
        if e.get("video", {}).get("cue") == "state"
    )
    scenes = []
    for i, (t, state) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else total
        scenes.append({
            "key": state,
            "name": SCENE_NAMES.get(state, state),
            "t": t,
            "end": end,
        })
    return scenes


def build_payload(tl: Timeline, movements, raw: dict) -> dict:
    by_id = {e["id"]: e for e in raw["events"]}
    lines = [
        {"t": e.t, "id": e.id, "text": by_id[e.id].get("text", e.id)}
        for e in tl.by_stem("voices")
    ]
    return {
        "total": tl.total_duration,
        "scenes": build_scenes(raw["events"], tl.total_duration),
        "movements": [
            {"id": m.id, "t": m.t, "name": m.name, "what": m.what,
             "speed": m.speed, "power": m.power, "duration": m.duration,
             "hold": m.hold, "trigger": m.trigger_event}
            for m in movements
        ],
        "lines": sorted(lines, key=lambda x: x["t"]),
    }


def main() -> int:
    scenario = ROOT / "scenario/timeline.json"
    tl = Timeline.load(scenario)
    with open(scenario, encoding="utf-8") as fh:
        raw = json.load(fh)
    movements = resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl
    )
    payload = build_payload(tl, movements, raw)

    html = TEMPLATE.read_text(encoding="utf-8")
    marker = "/*__DATA__*/"
    if marker not in html:
        raise SystemExit(f"в шаблоне нет маркера {marker}")
    html = html.replace(marker, json.dumps(payload, ensure_ascii=False))

    out = ROOT / "output/rehearsal.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Готово: {out}")
    print(f"  сцен: {len(payload['scenes'])}, движений: {len(payload['movements'])}, "
          f"реплик: {len(payload['lines'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Коммит** (шаблона ещё нет, генератор упадёт — это нормально, шаблон в следующей задаче)

```bash
git add src/render_rehearsal.py && git commit -m "rehearsal: генератор страницы"
```

---

## Task 9: `src/rehearsal_template.html` — сама страница

**Files:**
- Create: `src/rehearsal_template.html`

- [ ] **Step 1: Написать шаблон**

Требования к странице, все обязательные:

| Блок | Что показывает |
|---|---|
| **Панель движения** | самый крупный элемент экрана: название, что делать, шкалы скорости и силы, что удерживать |
| **Сцены** | три плашки — Допрос, Бой, Лёд. Текущая подсвечена, клик перематывает на её начало |
| **Следующее движение** | название и через сколько секунд |
| **Следующая сцена** | название и через сколько секунд |
| **Реплика** | текст того, что звучит сейчас |
| **Шкала времени** | полоса на 60 с с метками всех движений, кликабельная |
| **Плеер** | выбор файла дорожки, пуск и пауза, текущее время |
| **Навигация** | стрелки — движения, `1` `2` `3` — сцены, пробел — пуск и пауза |

```html
<!doctype html>
<meta charset="utf-8">
<title>Лоэн v2 — репетиция</title>
<style>
  :root { --bg:#121316; --fg:#e9e7e2; --dim:#8a8781; --line:#2a2c31; --hot:#d8663a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; }
  .wrap { max-width: 960px; margin: 0 auto; padding: 20px; }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap;
         padding:12px; border:1px solid var(--line); border-radius:10px; }
  button { background:#1d1f24; color:var(--fg); border:1px solid var(--line);
           border-radius:8px; padding:8px 14px; font-size:15px; cursor:pointer; }
  button:hover { border-color:#4a4d55; }
  .clock { font-variant-numeric: tabular-nums; font-size:22px; min-width:120px; }
  .track { position:relative; height:44px; margin:18px 0; background:#1a1c20;
           border:1px solid var(--line); border-radius:8px; cursor:pointer; }
  .mark { position:absolute; top:0; bottom:0; width:2px; background:#575a62; }
  .mark.on { background:var(--hot); width:3px; }
  .play { position:absolute; top:0; bottom:0; width:2px; background:#fff; }
  .now { margin:18px 0; padding:22px; border:1px solid var(--line);
         border-radius:12px; background:#171a1f; }
  .now h1 { margin:0 0 6px; font-size:30px; line-height:1.2; }
  .now .what { font-size:19px; margin:10px 0 16px; }
  .now .hold { color:var(--dim); font-size:15px; border-left:3px solid var(--line);
               padding-left:12px; }
  .scales { display:flex; gap:28px; margin:14px 0; }
  .scale span { color:var(--dim); font-size:13px; display:block; margin-bottom:4px; }
  .pips { display:flex; gap:5px; }
  .pip { width:26px; height:12px; border-radius:3px; background:#2a2c31; }
  .pip.on { background:var(--hot); }
  .scenes { display:flex; gap:8px; margin:14px 0; }
  .sc { flex:1; padding:10px 12px; border:1px solid var(--line); border-radius:8px;
        background:#15171b; cursor:pointer; }
  .sc.on { border-color:var(--hot); background:#221a16; }
  .sc b { display:block; font-weight:400; font-size:18px; }
  .sc span { color:var(--dim); font-size:13px; font-variant-numeric:tabular-nums; }
  .side { display:flex; gap:14px; flex-wrap:wrap; }
  .card { flex:1 1 220px; padding:14px; border:1px solid var(--line);
          border-radius:10px; background:#15171b; }
  .card b { color:var(--dim); font-weight:400; font-size:13px; display:block;
            margin-bottom:6px; }
  .line { font-size:18px; min-height:28px; }
</style>
<div class="wrap">
  <div class="bar">
    <input type="file" id="file" accept="audio/*">
    <button id="toggle">Пуск</button>
    <button id="prev">← пред.</button>
    <button id="next">след. →</button>
    <span class="clock" id="clock">0.00 / 60.00</span>
  </div>

  <div class="scenes" id="scenes"></div>

  <div class="track" id="track"><div class="play" id="play" style="left:0"></div></div>

  <div class="now">
    <h1 id="mname">—</h1>
    <div class="what" id="mwhat">Выбери файл дорожки и нажми пуск.</div>
    <div class="scales">
      <div class="scale"><span>скорость</span><div class="pips" id="speed"></div></div>
      <div class="scale"><span>сила</span><div class="pips" id="power"></div></div>
    </div>
    <div class="hold" id="mhold"></div>
  </div>

  <div class="side">
    <div class="card"><b>Сейчас звучит</b><div class="line" id="line">—</div></div>
    <div class="card"><b>Следующее движение</b><div class="line" id="nextm">—</div></div>
    <div class="card"><b>Следующая сцена</b><div class="line" id="nexts">—</div></div>
  </div>
</div>
<audio id="audio"></audio>
<script>
const DATA = /*__DATA__*/;
const $ = id => document.getElementById(id);
const audio = $("audio");

DATA.movements.forEach((m, i) => {
  const el = document.createElement("div");
  el.className = "mark";
  el.style.left = (m.t / DATA.total * 100) + "%";
  el.dataset.i = i;
  $("track").appendChild(el);
});
const marks = [...document.querySelectorAll(".mark")];

DATA.scenes.forEach((s, i) => {
  const el = document.createElement("div");
  el.className = "sc";
  el.innerHTML = "<b>" + s.name + "</b><span>" + s.t.toFixed(1) + "–"
                 + s.end.toFixed(1) + " с</span>";
  el.addEventListener("click", () => { audio.currentTime = s.t; });
  $("scenes").appendChild(el);
});
const sceneEls = [...document.querySelectorAll(".sc")];

function activeScene(t) {
  let idx = 0;
  DATA.scenes.forEach((s, i) => { if (t >= s.t - 0.05) idx = i; });
  return idx;
}

function pips(node, n) {
  node.innerHTML = "";
  for (let i = 1; i <= 5; i++) {
    const d = document.createElement("div");
    d.className = "pip" + (i <= n ? " on" : "");
    node.appendChild(d);
  }
}

function activeIndex(t) {
  let idx = -1;
  DATA.movements.forEach((m, i) => { if (t >= m.t - 0.05) idx = i; });
  return idx;
}

function currentLine(t) {
  let text = "—";
  DATA.lines.forEach(l => { if (t >= l.t - 0.05 && t < l.t + 4.0) text = l.text; });
  return text;
}

function render() {
  const t = audio.currentTime || 0;
  $("clock").textContent = t.toFixed(2) + " / " + DATA.total.toFixed(2);
  $("play").style.left = (t / DATA.total * 100) + "%";

  const i = activeIndex(t);
  marks.forEach((el, j) => el.classList.toggle("on", j === i));

  if (i >= 0) {
    const m = DATA.movements[i];
    $("mname").textContent = m.name;
    $("mwhat").textContent = m.what;
    $("mhold").textContent = m.hold;
    pips($("speed"), m.speed);
    pips($("power"), m.power);
  }

  const s = activeScene(t);
  sceneEls.forEach((el, j) => el.classList.toggle("on", j === s));

  const nxt = DATA.movements[i + 1];
  $("nextm").textContent = nxt
    ? nxt.name + "  —  через " + Math.max(0, nxt.t - t).toFixed(1) + " с"
    : "конец номера";

  const nxs = DATA.scenes[s + 1];
  $("nexts").textContent = nxs
    ? nxs.name + "  —  через " + Math.max(0, nxs.t - t).toFixed(1) + " с"
    : "последняя сцена";

  $("line").textContent = currentLine(t);

  requestAnimationFrame(render);
}

$("file").addEventListener("change", e => {
  const f = e.target.files[0];
  if (f) { audio.src = URL.createObjectURL(f); }
});
$("toggle").addEventListener("click", () => {
  if (audio.paused) { audio.play(); $("toggle").textContent = "Пауза"; }
  else { audio.pause(); $("toggle").textContent = "Пуск"; }
});
$("prev").addEventListener("click", () => {
  const i = activeIndex(audio.currentTime || 0);
  const target = DATA.movements[Math.max(0, i - 1)];
  if (target) audio.currentTime = target.t;
});
$("next").addEventListener("click", () => {
  const i = activeIndex(audio.currentTime || 0);
  const target = DATA.movements[Math.min(DATA.movements.length - 1, i + 1)];
  if (target) audio.currentTime = target.t;
});
$("track").addEventListener("click", e => {
  const r = e.currentTarget.getBoundingClientRect();
  audio.currentTime = (e.clientX - r.left) / r.width * DATA.total;
});
document.addEventListener("keydown", e => {
  if (e.code === "Space") { e.preventDefault(); $("toggle").click(); }
  if (e.code === "ArrowRight") $("next").click();
  if (e.code === "ArrowLeft") $("prev").click();
  const scene = { Digit1: 0, Digit2: 1, Digit3: 2 }[e.code];
  if (scene !== undefined && DATA.scenes[scene]) {
    audio.currentTime = DATA.scenes[scene].t;
  }
});

pips($("speed"), 0);
pips($("power"), 0);
render();
</script>
```

- [ ] **Step 2: Сгенерировать**

Run: `python src/render_rehearsal.py`
Expected: `Готово: ...output/rehearsal.html`, `сцен: 3, движений: 15, реплик: 16`

- [ ] **Step 3: Проверить, что данные подставились, а маркер исчез**

Run: `python -c "h=open('output/rehearsal.html',encoding='utf-8').read(); assert '/*__DATA__*/' not in h; assert 'spear_down' in h; assert 'Допрос' in h; print('ок,', len(h), 'символов')"`
Expected: `ок, <число> символов`

- [ ] **Step 4: Открыть в браузере**, выбрать `output/master_v2.mp3`, прогнать номер целиком. Проверить по списку: панель движения меняется в срок; подсветка сцены переключается на 22.3 и 47.0; оба отсчёта «через сколько» уменьшаются; клик по плашке сцены и по шкале перематывает; пробел ставит на паузу; клавиши `1` `2` `3` прыгают по сценам.

- [ ] **Step 5: Коммит**

```bash
git add src/rehearsal_template.html && git commit -m "rehearsal: страница с панелью движения, шкалами скорости и силы"
```

---

# ФАЗА 3. Видео на LED-экран

Начинать **только после заморозки аудио**. Пока таймкоды двигаются, видео придётся переделывать.

## Task 10: `src/render_video.py` — три состояния и якоря

**Files:**
- Create: `src/render_video.py`

Три состояния палитры и одиннадцать якорей уже лежат в `scenario/timeline.json` в блоках `video`. Рендерер их читает и ничего не придумывает сам.

| Состояние | Когда | Картинка |
|---|---|---|
| `interrogation` | 0.0–22.3 | холодный синий, почти статично, медленный дрейф, пыль в луче |
| `combat` | 22.3–47.0 | красный, следы движения, вспышки по якорям |
| `ice` | 47.0–60.0 | льдисто-белый, трещины от нижнего центра, остановка кадра |

| Тип якоря | Что делает |
|---|---|
| `state` | смена палитры |
| `flash` | короткая вспышка, яркость по `intensity` |
| `whiteflash` | один-два белых кадра |
| `tighten` | сжатие кадра к центру |
| `drain` | спад насыщенности |
| `freeze` | остановка движения до конца |

- [ ] **Step 1: Реализовать генератор кадров.** Разрешение до ответа организаторов взять 1920×1080, 30 кадров в секунду. Кадры писать в `output/frames/`, затем собирать `ffmpeg -framerate 30 -i output/frames/%05d.png`.

- [ ] **Step 2: Предохранитель.** Центральная вертикальная полоса кадра шириной 40% затемняется всегда, множителем не выше 0.35, во всех трёх состояниях. Без переднего света экран превращает исполнителя в силуэт, а костюм — главный критерий судей. Критичнее всего в ледяном блоке: кадр белый, а исполнитель стоит неподвижно последние тринадцать секунд.

- [ ] **Step 3: Мукс со звуком**

```bash
ffmpeg -y -framerate 30 -i output/frames/%05d.png -i output/master_v2.wav \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 320k -shortest output/final_v2.mp4
```

- [ ] **Step 4: Проверить длительность и синхронность**

Run: `python -c "from src.measure import measure_duration; print(measure_duration('output/final_v2.mp4'))"`
Expected: `60.0`

- [ ] **Step 5: Коммит**

```bash
git add src/render_video.py && git commit -m "video: три состояния палитры, якоря из сценария, предохранитель"
```

---

## Task 11: Финальная точка состояния

- [ ] **Step 1: Создать** `docs/status/2026-08-XX-v2c.md`: что вошло в сдачу, замеры мастера, параметры видео, что осталось открытым.
- [ ] **Step 2: Дописать строку в INDEX.**
- [ ] **Step 3: Коммит.**

---

## Порядок и зависимости

Фаза 1 блокирует всё: до 9 августа. Внутри неё задачи строго последовательны, кроме Task 2, который можно делать параллельно с генерацией.

Фаза 2 ни от чего не зависит и полезна сразу: страницу можно открыть на текущем мастере и начать ставить хореографию, не дожидаясь новой музыки. Единственное следствие Фазы 1 для неё — при смене таймкодов надо перезапустить `python src/render_rehearsal.py`.

Фаза 3 начинается после сдачи аудио и требует ответа организаторов по разрешению экрана и формату файла. Если ответа не будет, брать 1920×1080 и H.264.
