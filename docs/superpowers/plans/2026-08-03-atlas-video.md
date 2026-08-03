# Видеофон через Atlas Cloud — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить процедурный видеофон номера сгенерированными кадрами из Atlas Cloud, не тронув движок привязки к якорям, предохранитель и 107 существующих тестов.

**Architecture:** Atlas — поставщик файлов в `assets/video/base/`. Список кадров `scenario/shots.json` получает поля генерации (промпт, запреты, длительность, разрешение, референсы), новый `tools/atlas_gen.py` их читает, загружает референсы, отправляет задания, скачивает результат и пишет журнал расходов. Рендер `src/render_video.py` не знает про Atlas вообще: он видит только появившиеся файлы. Отдельно чинится дырка — заморозка на 55.2 останавливала процедурный фон, но не футаж.

**Tech Stack:** Python 3.12, numpy, FFmpeg, `requests` (новая зависимость, только для multipart-загрузки референсов), pytest. Модель `bytedance/seedance-2.0-mini/reference-to-video`, $0.056/с.

**Спека:** [2026-08-03-atlas-video-design.md](../specs/2026-08-03-atlas-video-design.md)

---

## Контракт API Atlas Cloud

Достан из `atlascloud.ai/docs/models/video` и `/docs/upload-files`. Не выдумывать поля — сверяться с этим блоком.

```
Загрузка референса
  POST https://api.atlascloud.ai/api/v1/model/uploadMedia
  Authorization: Bearer <ключ>
  multipart/form-data, файл в поле "file"
  Ответ: JSON, ссылка в "url". Файлы временные, чистятся периодически.

Отправка задания
  POST https://api.atlascloud.ai/api/v1/model/generateVideo
  Authorization: Bearer <ключ>
  JSON: {"model": "...", "prompt": "...", ...}
  Ответ: JSON, идентификатор в "id"

Опрос
  GET https://api.atlascloud.ai/api/v1/model/prediction/{id}
  Статусы: "completed" | "failed"
  Ссылка на результат: data["data"]["outputs"][0]
  Опрашивать раз в ~2 секунды, вебхуки не нужны
```

Формы модели, видимые в плейграунде: `Prompt`, `Reference Images` (максимум 9), `Reference Videos` (3), `Reference Audio` (3), `Duration` (4–15 с или −1), `Resolution` (`480p`, `720p`, `720p-SR`, `1080p-SR`, `1440p-SR`), `Aspect Ratio`, `Bitrate Mode`, `Generate Audio`, `Watermark`, `Return Last Frame`.

**Референсы адресуются внутри промпта токенами `@image1`, `@image2`** — их собственный пример: `Car 1 @image1 is speeding along the highway @image3`. Порядок токенов соответствует порядку загруженных файлов.

**Точные имена JSON-полей для всего, кроме `model`, `prompt` и `image_url`, в документации не приведены.** Их выясняет Задача 1, и до этого `atlas_gen.py` не запускается.

---

## Структура файлов

| файл | ответственность |
|---|---|
| `docs/atlas-api.md` | создаётся. Живой контракт API: точные имена полей, снятые со схемы модели. Единственное место, куда смотрит `atlas_gen.py` |
| `src/footage.py` | правится. `BaseShot` получает поля генерации; `FootageSource.base()` учится держать кадр при заморозке |
| `src/render_video.py:482` | правится. Одна строка: передать в `base()` замороженное время |
| `scenario/shots.json` | переписывается. С 4 слотов до 11, у каждого промпт и референсы |
| `tools/atlas_gen.py` | создаётся. Загрузить, отправить, дождаться, скачать, обеззвучить, записать в журнал |
| `docs/atlas-ledger.csv` | создаётся первым запуском |
| `tests/test_footage.py` | дополняется. Заморозка футажа, новые поля, целостность промптов |
| `requirements.txt` | правится. `requests` |
| `assets/screenshots/MANIFEST.md` | правится. Имена файлов после переименования в ASCII |

---

## Задача 1: Зафиксировать точные имена полей API

Без этого нельзя писать `atlas_gen.py`: спека прямо запрещает выдумывать поля, а два поля — `watermark` и `generate_audio` — при неверном имени молча испортят результат. Водяной знак локально не снять, он виден с любого места в зале.

**Файлы:**
- Создать: `docs/atlas-api.md`

- [ ] **Шаг 1: Снять схему модели**

Открыть <https://www.atlascloud.ai/models/bytedance/seedance-2.0-mini/reference-to-video>, нажать вкладку **Schema** (рядом с LLMs / Playground / API). Она отдаёт точные имена и типы полей запроса.

Если Schema требует входа — открыть вкладку **API**: там лежит готовый пример запроса с реальными именами полей. Второй источник — <https://www.atlascloud.ai/docs/openapi-index>.

- [ ] **Шаг 2: Записать контракт**

Создать `docs/atlas-api.md` и заполнить таблицу настоящими именами:

```markdown
# Контракт Atlas Cloud

Снято со вкладки Schema модели `bytedance/seedance-2.0-mini/reference-to-video`
3 августа 2026. Если Atlas поменяет схему, править здесь — `tools/atlas_gen.py`
читает имена полей только отсюда.

## Загрузка референса

POST https://api.atlascloud.ai/api/v1/model/uploadMedia
Authorization: Bearer <ключ>
multipart/form-data, файл в поле "file"
Ответ: {"url": "..."} — ссылка временная

## Отправка задания

POST https://api.atlascloud.ai/api/v1/model/generateVideo
Authorization: Bearer <ключ>

| наше значение | имя поля в API | тип | заметка |
|---|---|---|---|
| модель | `model` | string | подтверждено документацией |
| промпт | `prompt` | string | подтверждено документацией |
| референсы | ??? | ??? | список ссылок из uploadMedia |
| длительность | ??? | ??? | 4–15 или −1 |
| разрешение | ??? | ??? | 480p / 720p / 720p-SR / 1080p-SR / 1440p-SR |
| пропорции | ??? | ??? | 16:9 |
| генерировать звук | ??? | ??? | ВЫКЛЮЧИТЬ |
| водяной знак | ??? | ??? | ВЫКЛЮЧИТЬ |
| вернуть последний кадр | ??? | ??? | включить |

## Опрос

GET https://api.atlascloud.ai/api/v1/model/prediction/{id}
Статусы: "completed" | "failed"
Ссылка на результат: data["data"]["outputs"][0]
```

Заменить каждый `???` настоящим именем. **Ни одного `???` в файле остаться не должно** — это условие завершения задачи.

- [ ] **Шаг 3: Проверить, что вопросительных знаков не осталось**

Выполнить:

```bash
grep -c '???' docs/atlas-api.md
```

Ожидается: `0`

- [ ] **Шаг 4: Коммит**

```bash
git add docs/atlas-api.md
git commit -m "docs: контракт Atlas Cloud снят со схемы модели"
```

---

## Задача 2: Заморозка останавливает и футаж

`render_frame` отдаёт в `source.base()` настоящее время, а замороженное `t_anim` видят только процедурные рисовальщики. С реальным клипом на 55.2 исполнитель замирает, а экран продолжает ехать — против самого замысла заморозки.

**Файлы:**
- Изменить: `src/footage.py:322-355` (`FootageSource.base`), `src/footage.py:369-386` (`_offset`)
- Изменить: `src/render_video.py:482`
- Тест: `tests/test_footage.py`

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в конец `tests/test_footage.py`:

```python
# --- заморозка держит футаж ---------------------------------------------------


@pytest.fixture
def moving_clip(tmp_path):
    """Трёхсекундный клип, у которого каждый кадр отличается от соседнего.

    На клипе из одинаковых кадров тест на заморозку прошёл бы и на сломанном
    коде: держим мы кадр или читаем следующий, картинка была бы та же.
    """
    import subprocess
    (tmp_path / "base").mkdir()
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
        "-i", "testsrc=size=64x36:rate=30", "-t", "3",
        "-pix_fmt", "yuv420p", str(tmp_path / "base" / "c.mp4"),
    ], check=True)
    return tmp_path


def test_footage_holds_its_frame_while_time_is_frozen(moving_clip):
    """На 55.2 исполнитель держит позу, и шевелиться в зале не должно ничто."""
    from src.footage import FootageSource
    bases = [BaseShot(anchor="ice", clip="base/c.mp4", t=0.0, end=3.0)]
    source = FootageSource(bases, [], moving_clip, 64, 36, 30)
    try:
        moving = [source.base(i / 30.0, i / 30.0) for i in range(10)]
        held = [source.base(0.5 + i / 30.0, 0.5) for i in range(4)]
    finally:
        source.close()
    assert not np.array_equal(moving[0], moving[5]), "клип должен ехать"
    assert all(np.array_equal(held[0], frame) for frame in held[1:])


def test_footage_freeze_works_in_seek_mode_too(moving_clip):
    """Кадры-образцы идут вразнобой, поэтому держать последний прочитанный
    нельзя — надо перематывать на замороженный момент."""
    from src.footage import FootageSource
    bases = [BaseShot(anchor="ice", clip="base/c.mp4", t=0.0, end=3.0)]
    source = FootageSource(bases, [], moving_clip, 64, 36, 30, seek=True)
    try:
        frozen_early = source.base(1.0, 0.5)
        frozen_late = source.base(2.0, 0.5)
        running = source.base(2.0, 2.0)
    finally:
        source.close()
    assert np.array_equal(frozen_early, frozen_late)
    assert not np.array_equal(frozen_early, running)


def test_footage_runs_normally_when_time_is_not_frozen(moving_clip):
    """Заморозка не должна протечь на остальной номер."""
    from src.footage import FootageSource
    bases = [BaseShot(anchor="ice", clip="base/c.mp4", t=0.0, end=3.0)]
    source = FootageSource(bases, [], moving_clip, 64, 36, 30, seek=True)
    try:
        a = source.base(0.5, 0.5)
        b = source.base(1.5, 1.5)
    finally:
        source.close()
    assert not np.array_equal(a, b)
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Выполнить:

```bash
python -m pytest tests/test_footage.py -k freeze -v
```

Ожидается: FAIL, `TypeError: base() takes 2 positional arguments but 3 were given`

- [ ] **Шаг 3: Научить `base()` держать кадр**

В `src/footage.py` заменить подпись и тело `FootageSource.base` (строки 322–355) на:

```python
    def base(self, t: float, t_hold: float | None = None) -> np.ndarray | None:
        """Кадр фона на момент `t`.

        `t_hold` — момент, с которого берётся картинка. Обычно равен `t`, но на
        заморозке отстаёт: на 42.8 он получает удар и не реагирует, на 55.2
        держит позу до конца номера. Кусок при этом выбирается по настоящему
        времени, иначе после 55.2 мы бы уехали в предыдущий кадр списка.
        """
        hold = t_hold if t_hold is not None else t
        frozen = hold < t

        index, shot = -1, None
        for i, candidate in enumerate(self.bases):
            if candidate.t <= t < candidate.end:
                index, shot = i, candidate
                break
        if shot is None:
            return None
        path = self.assets / shot.clip
        if not path.exists():
            return None

        if self.seek:
            # Кадры-образцы идут вразнобой, держать последний прочитанный
            # нельзя — перематываем ровно на замороженный момент.
            frame = self._one_frame(path, self._offset(path, shot, hold), shot.speed)
        elif frozen and self._base_last is not None:
            # Потоковый режим: труба отдаёт следующий кадр на каждый вызов, и
            # никакое время её не остановит. Поэтому не читаем вовсе.
            frame = self._base_last
        else:
            if index != self._base_index:
                self._close_base()
                self._base_index = index
                self._base_last = None
                self._base_reader = ClipReader(
                    path, self.w, self.h, self.fps,
                    start_at=shot.start_at, speed=shot.speed, loop=shot.loop,
                )
            frame = self._base_reader.read() if self._base_reader else None
            if frame is None and not shot.loop:
                # Кадр-событие кончился — держим последний. Повторять его нельзя:
                # дверь вылетела бы во второй раз.
                frame = self._base_last
            elif frame is not None:
                self._base_last = frame
        if frame is None:
            return None
        tint = np.array(GRADES[shot.grade], dtype=np.float32) * shot.gain
        return frame[:, :, :3] * tint[None, None, :]
```

- [ ] **Шаг 4: Прогнать тесты заморозки**

```bash
python -m pytest tests/test_footage.py -k freeze -v
```

Ожидается: PASS, 3 теста

- [ ] **Шаг 5: Передать замороженное время из рендера**

В `src/render_video.py` заменить строку 482:

```python
    rgb = source.base(t) if source is not None else None
```

на:

```python
    rgb = source.base(t, t_anim) if source is not None else None
```

- [ ] **Шаг 6: Прогнать весь набор тестов**

```bash
python -m pytest -q
```

Ожидается: 110 passed (было 107, добавилось 3)

- [ ] **Шаг 7: Коммит**

```bash
git add src/footage.py src/render_video.py tests/test_footage.py
git commit -m "footage: заморозка останавливает и снятый материал, а не только рисованный"
```

---

## Задача 3: Поля генерации в списке кадров

Промпт живёт рядом со своим якорем — тот же принцип, что у таймкодов: один источник. `atlas_gen.py` читает тот же `shots.json`, что и рендер.

**Файлы:**
- Изменить: `src/footage.py:41-65` (`BaseShot`), `src/footage.py:89-111` (`load_shots`)
- Тест: `tests/test_footage.py`

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в `tests/test_footage.py` после блока разбора списка кадров:

```python
# --- поля генерации ----------------------------------------------------------


def test_generation_fields_are_empty_by_default(tmp_path):
    """Кадр со стока промпта не требует — поля необязательные."""
    path = _write(tmp_path, {"base": [{"anchor": "combat", "clip": "b.mp4"}]})
    shot = load_shots(path)[0][0]
    assert shot.prompt == "" and shot.negative == ""
    assert shot.duration == 0.0 and shot.resolution == ""
    assert shot.refs == ()


def test_generation_fields_are_read(tmp_path):
    path = _write(tmp_path, {"base": [{
        "anchor": "combat", "clip": "b.mp4",
        "prompt": "a dark hold @image1", "negative": "no text",
        "duration": 6, "resolution": "720p", "refs": ["room_wide.png"],
    }]})
    shot = load_shots(path)[0][0]
    assert shot.prompt == "a dark hold @image1"
    assert shot.negative == "no text"
    assert shot.duration == 6.0
    assert shot.resolution == "720p"
    assert shot.refs == ("room_wide.png",)


@pytest.mark.parametrize("duration", [3.9, 15.1, 0.5])
def test_shots_reject_duration_outside_the_model_range(duration, tmp_path):
    """Модель принимает 4–15 с. Задание за пределами вернёт ошибку через
    минуту ожидания, а не сразу, и это самая дорогая форма опечатки."""
    path = _write(tmp_path, {"base": [{
        "anchor": "combat", "clip": "b.mp4", "duration": duration}]})
    with pytest.raises(FootageError, match="duration"):
        load_shots(path)


def test_shots_reject_an_unknown_resolution(tmp_path):
    path = _write(tmp_path, {"base": [{
        "anchor": "combat", "clip": "b.mp4", "resolution": "4k"}]})
    with pytest.raises(FootageError, match="4k"):
        load_shots(path)


def test_shots_reject_a_prompt_token_without_its_reference(tmp_path):
    """@image3 при двух референсах — тихая ошибка: модель подставит не тот
    кадр, и разбираться придётся глазами по готовому клипу."""
    path = _write(tmp_path, {"base": [{
        "anchor": "combat", "clip": "b.mp4",
        "prompt": "@image1 and @image3", "refs": ["a.png", "b.png"],
    }]})
    with pytest.raises(FootageError, match="@image3"):
        load_shots(path)


def test_shots_accept_tokens_that_match_their_references(tmp_path):
    path = _write(tmp_path, {"base": [{
        "anchor": "combat", "clip": "b.mp4",
        "prompt": "@image2 behind @image1", "refs": ["a.png", "b.png"],
    }]})
    assert load_shots(path)[0][0].refs == ("a.png", "b.png")


def test_shots_reject_more_references_than_the_model_takes(tmp_path):
    path = _write(tmp_path, {"base": [{
        "anchor": "combat", "clip": "b.mp4",
        "refs": [f"{i}.png" for i in range(10)],
    }]})
    with pytest.raises(FootageError, match="9"):
        load_shots(path)
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

```bash
python -m pytest tests/test_footage.py -k generation -v
```

Ожидается: FAIL, `AttributeError: 'BaseShot' object has no attribute 'prompt'`

- [ ] **Шаг 3: Расширить `BaseShot`**

В `src/footage.py` добавить в конец полей `BaseShot`, перед `t` и `end`:

```python
    # Задание на генерацию. Пусто у кадров со стока: им промпт не нужен.
    # Референсы адресуются внутри промпта токенами @image1, @image2 — так их
    # принимает Seedance, порядок токенов соответствует порядку refs.
    prompt: str = ""
    negative: str = ""
    duration: float = 0.0
    resolution: str = ""
    refs: tuple[str, ...] = ()
    t: float = -1.0
    end: float = -1.0
```

- [ ] **Шаг 4: Добавить проверки в `load_shots`**

В `src/footage.py` перед строкой `import numpy as np` добавить:

```python
import re
```

После словаря `GRADES` добавить:

```python
# Разрешения, которые модель принимает. SR-варианты генерируют ниже и тянут
# апскейлером, поэтому они дешевле нативных, а не дороже.
RESOLUTIONS = ("480p", "720p", "720p-SR", "1080p-SR", "1440p-SR")

# Границы длительности у Seedance 2.0 Mini.
MIN_DURATION, MAX_DURATION = 4.0, 15.0

# Максимум референсных изображений на одно задание.
MAX_REFS = 9

_REF_TOKEN = re.compile(r"@image(\d+)")
```

В `load_shots`, внутри цикла по `raw.get("base", [])`, после проверки `speed` вставить:

```python
        duration = float(item.get("duration", 0.0))
        if duration and not (MIN_DURATION <= duration <= MAX_DURATION):
            raise FootageError(
                f"{item['anchor']}: duration={duration} вне диапазона модели "
                f"{MIN_DURATION}–{MAX_DURATION} с"
            )
        resolution = str(item.get("resolution", ""))
        if resolution and resolution not in RESOLUTIONS:
            raise FootageError(
                f"{item['anchor']}: неизвестное разрешение {resolution!r}, "
                f"допустимы {RESOLUTIONS}"
            )
        refs = tuple(str(r) for r in item.get("refs", []))
        if len(refs) > MAX_REFS:
            raise FootageError(
                f"{item['anchor']}: {len(refs)} референсов, модель принимает "
                f"не больше {MAX_REFS}"
            )
        prompt = str(item.get("prompt", ""))
        for token in _REF_TOKEN.finditer(prompt):
            number = int(token.group(1))
            if not 1 <= number <= len(refs):
                raise FootageError(
                    f"{item['anchor']}: промпт ссылается на @image{number}, "
                    f"а референсов {len(refs)}"
                )
```

И в конструктор `BaseShot(...)` добавить новые аргументы:

```python
            prompt=prompt, negative=str(item.get("negative", "")),
            duration=duration, resolution=resolution, refs=refs,
```

- [ ] **Шаг 5: Прогнать тесты**

```bash
python -m pytest tests/test_footage.py -k generation -v
```

Ожидается: PASS, 11 тестов

- [ ] **Шаг 6: Прогнать весь набор**

```bash
python -m pytest -q
```

Ожидается: 121 passed

- [ ] **Шаг 7: Коммит**

```bash
git add src/footage.py tests/test_footage.py
git commit -m "footage: задание на генерацию живёт рядом со своим якорем"
```

---

## Задача 4: Одиннадцать кадров с промптами

**Файлы:**
- Переименовать: 18 файлов в `assets/screenshots/`
- Изменить: `assets/screenshots/MANIFEST.md`
- Переписать: `scenario/shots.json`
- Тест: `tests/test_footage.py`

- [ ] **Шаг 1: Перевести имена референсов в ASCII**

Кириллица и пробелы в именах ломаются при любом выходе в оболочку — на этом проекте уже был `UnicodeEncodeError` на cp1252. Имена станут ещё и говорящими.

```bash
cd assets/screenshots
mv "1.png" room_wide.png
mv "2.png" revolver_temple.png
mv "3.png" backlit_silhouettes.png
mv "4.png" captive_from_below.png
mv "5.png" revolver_over_shoulder.png
mv "6.png" lohen_over_captive.png
mv "Источник света.png" room_light.png
mv "Враги.png" enemies.png
mv "Сражения и лёд.png" ice_burst.png
mv "Что-то похожее на сцену со льдом.png" ice_frozen_automaton.png
mv "Сражения и копьё.png" spear_fight_01.png
mv "Сражения и копьё2.png" spear_fight_02.png
mv "Сражения и копьё3.png" spear_fight_03.png
mv "Револьвер Пафосная сцена.png" revolver_at_camera.png
mv "Комната_проем_возможно_6.png" lohen_fullbody_green.png
mv "Комната_проем_возможно7.png" door_green.png
mv "Здесь ножик не знаю если это понадобится.png" knife_green.png
mv "Концевка и лого.png" logo_DO_NOT_USE.png
cd ../..
ls assets/screenshots
```

Ожидается: 22 файла с ASCII-именами плюс `MANIFEST.md`

- [ ] **Шаг 2: Обновить манифест**

В `assets/screenshots/MANIFEST.md` заменить старые имена на новые во всех таблицах. Соответствие ровно то, что в предыдущем шаге. Проверить, что кириллических имён файлов в манифесте не осталось:

```bash
grep -n '\.png' assets/screenshots/MANIFEST.md | grep -P '[А-Яа-я]'
```

Ожидается: пусто

- [ ] **Шаг 3: Написать падающий тест на комплектность**

Добавить в `tests/test_footage.py`:

```python
# --- реальный список кадров под генерацию ------------------------------------


def test_every_base_has_a_prompt_and_a_negative():
    """Кадр без промпта молча уедет в процедурный фолбэк, и это выяснится
    только на просмотре готового номера."""
    bases, _ = load_shots("scenario/shots.json")
    for shot in bases:
        assert shot.prompt.strip(), f"{shot.anchor}: пустой промпт"
        assert shot.negative.strip(), f"{shot.anchor}: пустые запреты"


def test_every_reference_file_exists():
    """Опечатка в имени референса выяснилась бы после загрузки, то есть уже
    за деньги."""
    from pathlib import Path
    bases, _ = load_shots("scenario/shots.json")
    for shot in bases:
        for ref in shot.refs:
            assert (Path("assets/screenshots") / ref).exists(), \
                f"{shot.anchor}: нет файла {ref}"


def test_the_logo_frame_is_never_used_as_a_reference():
    """Логотип на входе — прямой способ получить в генерации буквенный мусор,
    а читаемый текст стоит в запретах у каждого кадра."""
    bases, _ = load_shots("scenario/shots.json")
    for shot in bases:
        assert not any("logo" in ref for ref in shot.refs), shot.anchor


def test_every_base_is_at_least_as_long_as_its_window():
    """Клип короче своего куска закольцуется, и событие произойдёт дважды.
    Длиннее — обрежется по границе, и это нормально."""
    bases, _ = resolve(*load_shots("scenario/shots.json"), _real_plan())
    for shot in bases:
        assert shot.duration >= shot.end - shot.t - 1e-6, (
            f"{shot.anchor}: клип {shot.duration} с на куске "
            f"{shot.end - shot.t:.1f} с — закольцуется"
        )


def test_the_shot_list_covers_the_whole_number():
    bases, _ = resolve(*load_shots("scenario/shots.json"), _real_plan())
    assert len(bases) == 11
    assert bases[0].t == 0.0
    assert bases[-1].end == 60.0
    for earlier, later in zip(bases, bases[1:]):
        assert earlier.end == later.t, "в списке кадров дырка"


def test_only_one_shot_shows_his_face():
    """Второй Лоэн на экране перетягивает внимание с исполнителя. Лицо
    разрешено ровно один раз — вспышкой на 42.8."""
    bases, _ = resolve(*load_shots("scenario/shots.json"), _real_plan())
    with_face = [b.anchor for b in bases if "lohen_rage.png" in b.refs]
    assert with_face == ["hit_on_lohen"]
```

- [ ] **Шаг 4: Убедиться, что тесты падают**

```bash
python -m pytest tests/test_footage.py -k "prompt or reference or logo or window or covers or face" -v
```

Ожидается: FAIL — в текущем `shots.json` четыре кадра и ни одного промпта

- [ ] **Шаг 5: Переписать `scenario/shots.json`**

Полностью заменить содержимое файла:

```json
{
  "note": "Список кадров видеофона. Своих таймкодов здесь нет: каждый кадр висит на якоре — либо на имени состояния (interrogation, combat, ice), либо на идентификаторе события звука. Отсутствующий файл не ошибка: на его месте работает процедурный фон, и номер собирается целиком. Клипы кладутся в assets/video/base/, проверка комплекта — python src/render_video.py --check, генерация — python tools/atlas_gen.py",

  "главная задача экрана": "Не украшать, а объяснять. Зал видит одного человека и пустой стул; без экрана непонятно, что на 22.30 в комнату вломились вооружённые люди. Кадры подобраны по одному критерию: понятно ли из них, что происходит.",

  "камера": "База — субъективная камера. Ограничено не место камеры, а лицо: лицо Лоэна разрешено ровно один раз, вспышкой на 42.8, где уже стоят белая вспышка и заморозка. На 50.6 лица нет — реплику произносит исполнитель, второй рот дал бы рассинхрон. На 44.6 и 55.2 он появляется силуэтом: силуэт не может не совпасть с костюмом и не может разъехаться между шотами.",

  "референсы": "Адресуются внутри промпта токенами @image1, @image2 — так их принимает Seedance, порядок соответствует порядку в refs. Роли дублируются прозой в конце промпта: если токены модель не поймёт, проза останется. Разбор всех кадров — assets/screenshots/MANIFEST.md. В один пакет не кладутся конфликтующие палитры.",

  "модель": "bytedance/seedance-2.0-mini/reference-to-video, $0.056/с. Проба на 480p, продакшен на 720p. generate_audio и watermark выключены всегда: мастер-звук готов, а водяной знак виден с любого места в зале.",

  "base": [
    {
      "anchor": "interrogation",
      "clip": "base/01_interrogation.mp4",
      "grade": "cold",
      "gain": 0.85,
      "duration": 6,
      "resolution": "720p",
      "refs": ["room_wide.png", "room_light.png", "lohen_over_captive.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view of an interrogator standing over a captive inside a large dark cargo hold @image1: heavy wooden beams overhead, stacked crates, barrels and a workbench receding into blackness. On the RIGHT side of frame a huge trapezoidal hatch-window with heavy lattice bracing @image2 glows cold blue-white and throws one hard volumetric beam across a wet reflective floor. A bound man @image3 slumps on a chair on the LEFT third of frame, wrists tied behind the backrest, dark messy hair, brown coat, head hanging; he slowly lifts his head and looks up into the camera. The centre of frame stays empty dark floor. Environmental motion: dust drifting through the beam, faint breath steam. Camera: first person at standing eye height, extremely slow drift forward, only the faintest handheld sway. Timing: calm and unhurried across the whole clip, no event, no cut. Mood: cold, controlled, menacing, quiet, deep blue-black with one cold light source. Reference 1 defines the hold: beams, crates, workbench, floor. Reference 2 defines the lighting: the lattice hatch-window, the volumetric beam, the palette. Reference 3 defines the captive.",
      "negative": "no visible hands, no arms, no interrogator's body, no mirror or reflection of the camera, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no modern objects, no firearms, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no distorted faces",
      "почему так": "Двойная работа: сообщить залу, что мы в допросной, и установить окно-люк, которое вышибут на 22.30. Рук в кадре нет намеренно — руки артефакт номер один у всех видеомоделей, а присутствие человека продаёт не рука, а то, что пленник поднимает глаза в камеру. Пленник слева, окно справа, центр пустой: предохранитель гасит центральные 40% ширины, посади пленника по центру — утонет."
    },
    {
      "anchor": "footsteps_circling_1",
      "clip": "base/02_circling.mp4",
      "grade": "cold",
      "gain": 0.85,
      "duration": 11,
      "resolution": "720p",
      "refs": ["room_wide.png", "room_light.png", "lohen_over_captive.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view circling slowly around a captive tied to a chair inside a large dark cargo hold @image1. The huge trapezoidal lattice hatch-window @image2 glows cold blue-white and drifts across frame as the camera walks around the chair, its volumetric beam sweeping the wet floor. The bound man @image3 stays roughly on the left of frame, head low, following the camera with his eyes. Environmental motion: dust in the beam, shadows rotating slowly across crates and the workbench. Camera: first person at standing eye height, one continuous slow arc around the chair, unhurried, no cut. Timing: eleven seconds of steady circling, no event. Mood: cold, patient, in control. Reference 1 defines the hold. Reference 2 defines the lighting and palette. Reference 3 defines the captive.",
      "negative": "no visible hands, no arms, no interrogator's body, no mirror or reflection of the camera, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no modern objects, no firearms, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no distorted faces",
      "почему так": "Одиннадцать секунд под тихий диалог. Якорь называется footsteps_circling — в звуке он обходит стул, и камера делает то же самое. Движение медленное: любой рывок перетянет внимание с реплик."
    },
    {
      "anchor": "revolver_cylinder_spin",
      "clip": "base/03_revolver.mp4",
      "grade": "cold",
      "gain": 0.9,
      "duration": 7,
      "resolution": "720p",
      "refs": ["revolver_at_camera.png", "room_light.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. Extreme close view straight down the barrel of an ornate silver-and-blue revolver @image1 aimed directly at the camera, held in a black studded glove. The cylinder turns slowly, one chamber at a time. The shooter's face and body are lost in deep shadow behind the weapon, unreadable. Far behind, out of focus, the trapezoidal lattice hatch-window @image2 glows cold blue-white. Environmental motion: only the cylinder turning and a slow shift of the highlight along the barrel. Camera: locked off, dead level with the muzzle, no movement. Timing: the cylinder turns steadily through the whole clip. Mood: cold, intimate, threatening — the viewer is the one being aimed at. Reference 1 defines the revolver. Reference 2 defines the light behind.",
      "negative": "no visible face, no readable eyes, no character portrait, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no extra fingers, no second weapon",
      "почему так": "На 16.2 он говорит Six chambers. One bullet, на 21.15 взводит курок, на 21.7 щёлкает пустой. Ствол в зал делает зрителя пленником: он не смотрит допрос, он на стуле. Собственный револьвер остаётся реальным предметом в руке исполнителя, экран показывает его с другой стороны. Лицо в тени — правило про одно лицо за номер тратить здесь нельзя."
    },
    {
      "anchor": "combat",
      "clip": "base/04_breach.mp4",
      "grade": "hot",
      "gain": 1.0,
      "loop": false,
      "procedural": "breach",
      "duration": 7,
      "resolution": "720p",
      "refs": ["room_wide.png", "room_light.png", "enemies.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view inside the same large dark cargo hold @image1. The huge trapezoidal lattice hatch-window @image2 on the RIGHT of frame bursts inward off its mountings, splintering, and cold light floods in. Armed men @image3 pour through the opening one after another — four or five of them in long dark coats and wide-brimmed hats, one in a plain white mask — rushing toward the camera and fanning to the sides. They stay backlit: dark shapes against the light, faces not readable. Environmental motion: dust and splinters blast through the beam, shadows sweep the walls. Camera: first person at standing eye height, holds its ground, does not retreat, one small hard jolt at the instant of impact. Timing: the hatch bursts within the first half second; the men are inside and closing by the middle of the clip; the nearest fills the side of frame by the end. Mood: sudden, violent, overwhelming — but the camera is unafraid. Reference 1 defines the hold. Reference 2 defines the hatch-window and the light. Reference 3 defines the intruders: long coats, wide-brimmed hats, the white mask.",
      "negative": "no fantasy armour, no knights, no spears, no shields, no modern police or SWAT gear, no firearms, no visible hands, no arms, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no slow motion, no cut, no extra limbs, no distorted faces",
      "почему так": "САМЫЙ ВАЖНЫЙ КАДР. Шесть секунд, 22.30-28.50: вышибают люк, кричит охрана, лязгает оружие, он смеётся и говорит Finally, берёт копьё. Всё это время зал должен понимать, что в комнату вошли враги. Камера не отступает: он не пугается, вторжение его раззадоривает, и дёрнись камера назад — экран рассказал бы противоположное. loop false, потому что кадр-событие: закольцуйся он, люк вылетел бы дважды."
    },
    {
      "anchor": "burst1_whoosh",
      "clip": "base/05_burst1.mp4",
      "grade": "hot",
      "gain": 0.8,
      "duration": 5,
      "resolution": "720p",
      "refs": ["enemies.png", "spear_fight_01.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view in a red-lit underground hall: crimson floor, strings of small warm bulbs overhead, a wooden bar and overturned furniture in the haze. A man in a long dark coat and wide-brimmed hat @image1 lunges at the camera from the LEFT, swings, and is thrown backwards out of frame by an unseen impact; a pale blue slash of light @image2 cuts across the frame at the moment of the hit. Two more coated figures hesitate in the background. Environmental motion: dust and embers, the hanging bulbs swinging, red haze. Camera: first person, holds position, small sharp recoil on the impact. Timing: the lunge in the first second, the hit in the middle, the man gone by the end. Mood: fast, brutal, contemptuous. Reference 1 defines the enemies and the hall. Reference 2 defines the pale blue slash and the ice sparks.",
      "negative": "no fantasy armour, no knights, no shields, no modern police or SWAT gear, no firearms, no visible hands, no arms, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no slow motion, no cut, no extra limbs, no distorted faces",
      "почему так": "Начинается ровно на первом попадании: склейка с пролома на бой падает на удар, а не в пустоту."
    },
    {
      "anchor": "burst2_whoosh",
      "clip": "base/06_burst2.mp4",
      "grade": "hot",
      "gain": 0.8,
      "duration": 6,
      "resolution": "720p",
      "refs": ["enemies.png", "spear_fight_02.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view in the same red-lit underground hall, now from a lower angle near the floor. Two men in long dark coats and wide-brimmed hats @image1 close in from the RIGHT; the nearer one is knocked off his feet and slides toward the camera, the second is caught mid-turn by a heavy pale blue slash @image2 that throws four-pointed white star flares across the frame. Environmental motion: red haze, swinging bulbs, splinters skidding on the crimson floor. Camera: first person, low, tilts up slightly to follow the falling man, one sharp recoil. Timing: the approach in the first second, two hits in the middle, both men down by the end. Mood: heavier than before, the fight is escalating. Reference 1 defines the enemies and the hall. Reference 2 defines the slash and the star flares.",
      "negative": "no fantasy armour, no knights, no shields, no modern police or SWAT gear, no firearms, no visible hands, no arms, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no slow motion, no cut, no extra limbs, no distorted faces",
      "почему так": "Другой ракурс и другая сторона кадра: четыре одинаковых удара зал перестал бы различать уже на втором."
    },
    {
      "anchor": "burst3_impact_a",
      "clip": "base/07_burst3.mp4",
      "grade": "hot",
      "gain": 0.8,
      "duration": 5,
      "resolution": "720p",
      "refs": ["ice_frozen_automaton.png", "spear_fight_01.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view in the red-lit underground hall, looking up at a massive armoured mechanical figure @image1 — a hulking automaton with a plated head and long articulated arms — as it steps over wrecked furniture toward the camera and swings down. It is struck twice in quick succession by heavy pale blue slashes @image2; plates buckle, sparks and pale shards burst from the impacts, and it staggers. Environmental motion: red haze, debris thrown outward, bulbs torn from their wire. Camera: first person, low and tilted up, two hard recoils in a row. Timing: the step forward in the first second, two impacts back to back in the middle, the stagger at the end. Mood: the heaviest moment of the fight. Reference 1 defines the automaton. Reference 2 defines the slashes and the impact sparks.",
      "negative": "no fantasy armour on humans, no knights, no shields, no modern police or SWAT gear, no firearms, no visible hands, no arms, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no slow motion, no cut, no extra limbs, no distorted faces",
      "почему так": "Сильнейший удар боя, intensity 0.9. Бронированная машина даёт вес, которого группа бандитов не даёт."
    },
    {
      "anchor": "hit_on_lohen",
      "clip": "base/08_face.mp4",
      "grade": "hot",
      "gain": 1.0,
      "duration": 4,
      "resolution": "720p",
      "refs": ["lohen_rage.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. Tight close shot of a young man with pale grey-green hair and violet-red eyes @image1 in a navy and white coat with silver filigree, standing in a red-lit underground hall. He has just been hit: his head snaps back into frame and he breaks into a wide delighted grin, teeth showing, eyes bright — the blow pleased him. A pale blue spark of ice trails past his shoulder. Environmental motion: red haze behind him, hair still moving from the impact. Camera: locked off, chest-up framing, no movement. Timing: the head snaps into place in the first quarter of the clip and the grin holds. Mood: exhilarated, unhinged, delighted. Reference 1 defines his face, hair and coat.",
      "negative": "no speaking, no moving lips, no open-mouth dialogue, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no distorted faces, no second character",
      "почему так": "Единственное лицо во всём номере. Идёт обычным кадром базы, а не эффектом: генерация не отдаёт альфа-канал, накладывать лицо полупрозрачным слоем было бы нечем. Работу вспышки делают якоря, которые тут и так стоят — белая вспышка на два кадра и заморозка на 0.9 с. От кадра нужен только оскал. Губы не двигаются намеренно: на 43.6 в звуке смех, а не реплика."
    },
    {
      "anchor": "burst4_whoosh",
      "clip": "base/09_raise.mp4",
      "grade": "hot",
      "gain": 0.75,
      "duration": 4,
      "resolution": "720p",
      "refs": ["lohen_splash_art.png", "spear_full.png", "backlit_silhouettes.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. Wide shot of a lone figure @image1 seen as a dark backlit silhouette @image3 in the middle distance of a red-lit underground hall, long coat hanging, raising a long ornate polearm @image2 straight up above his head in one unhurried movement. Coated figures scatter backwards away from him into the haze, small and low in frame. He is a shape against the light, no facial detail. Environmental motion: red haze, dust, the last bulbs swinging. Camera: locked off, wide, slightly low, no movement. Timing: the polearm comes up steadily and stops at the top by the end of the clip. Mood: the fight is over and he knows it. Reference 1 defines his silhouette and proportions. Reference 2 defines the polearm shape and length. Reference 3 defines the backlit treatment.",
      "negative": "no visible face, no facial features, no readable eyes, no character portrait, no fantasy armour, no knights, no shields, no firearms, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no second weapon",
      "почему так": "Ты поднимаешь копьё на 45.9, силуэт на экране поднимает его одновременно. Два одинаковых движения в один момент сильнее, чем передача внимания. Силуэт не может не совпасть с костюмом и не может разъехаться между шотами. На 45.5 стоит якорь drain — цвет из кадра всё равно уйдёт, силуэт это переживёт."
    },
    {
      "anchor": "ice",
      "clip": "base/10_ice.mp4",
      "grade": "ice",
      "gain": 0.8,
      "duration": 9,
      "resolution": "720p",
      "refs": ["ice_burst.png", "ice_frozen_automaton.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. First-person point of view low over the floor of the underground hall as the red light drains out of it and everything turns deep blue. A wave of ice @image1 races away from the camera across the floor — long angular pale-cyan crystals with white glowing cores, throwing four-pointed white star flares — and climbs over wrecked furniture. Coated figures and a massive armoured automaton @image2 are caught mid-motion and locked in place, spikes of ice growing through and around them. Environmental motion: frost creeping outward, fine snow drifting down, crystals still growing at the far edge. Camera: first person, low, very slow push forward following the ice. Timing: the wave leaves the camera in the first second and reaches the far wall by the middle; the last seconds are the ice still spreading and slowing. Mood: cold, absolute, final. Reference 1 defines the ice: crystal shape, colour, the star flares. Reference 2 defines the frozen automaton.",
      "negative": "no visible hands, no arms, no visible face, no character portrait, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no fire, no warm light",
      "почему так": "Он бьёт копьём в пол, и лёд идёт ОТ него — то есть от камеры. Тринадцать секунд ледяного блока, из них этот кадр занимает восемь."
    },
    {
      "anchor": "ice_final_impact",
      "clip": "base/11_final.mp4",
      "grade": "ice",
      "gain": 0.8,
      "duration": 5,
      "resolution": "720p",
      "refs": ["lohen_splash_art.png", "lohen_spear_static.png", "spear_full.png"],
      "prompt": "Anime cinematic style, stylized like a modern Japanese game cutscene. Wide symmetrical shot of a lone figure @image1 standing dead still as a dark backlit silhouette in a frozen hall, long coat hanging motionless, a long ornate polearm @image2 @image3 driven point-down into the floor beside him, both hands resting on it. Around and behind him the floor is a field of long angular pale-cyan ice crystals with white glowing cores, and the frozen shapes of fallen men. He is a shape against the pale light, no facial detail. Environmental motion: fine snow drifting down, a slow travelling glint along the ice, nothing else. Camera: locked wide, an extremely slow pull back, no other movement. Timing: absolutely still throughout, only the snow and the glint. Mood: total, quiet dominance. Reference 1 defines his silhouette and proportions. References 2 and 3 define the polearm shape and length.",
      "negative": "no visible face, no facial features, no readable eyes, no character portrait, no speaking, no moving lips, no fantasy armour, no knights, no shields, no firearms, no readable text, no subtitles, no captions, no watermark, no logo, no user interface, no blood, no gore, no camera shake, no cut, no zoom, no extra limbs, no second weapon, no fire, no warm light",
      "почему так": "Пять секунд ты держишь позу, экран берёт слово — передача внимания. Трейлер называется Lohen: A Masterpiece, а реплика на 50.6 — They asked for a masterpiece. Consider it finished. Этот кадр рифмуется с трейлером намеренно. Заморозка на 55.2 останавливает и футаж (Задача 2), так что стоять он будет действительно неподвижно."
    }
  ],

  "fx": [],
  "почему fx пуст": "Рисованные слэши с альфа-каналом покупались на стоке. Генерация альфа-канала не отдаёт, поэтому удары теперь живут внутри базовых кадров, а процедурные вспышки на якорях flash остаются как были и работают поверх."
}
```

- [ ] **Шаг 6: Прогнать новые тесты**

```bash
python -m pytest tests/test_footage.py -v
```

Ожидается: PASS. Тесты `test_the_real_shot_list_resolves_against_the_real_scenario` и `test_the_breach_gets_its_own_shot_and_it_is_long_enough_to_read` придётся поправить: в первом список якорей теперь из одиннадцати имён и `len(fx) == 0`, во втором окно пролома стало 22.3–28.5 при том же условии на длину. Ожидания в них обновить, сами проверки оставить.

- [ ] **Шаг 7: Прогнать весь набор**

```bash
python -m pytest -q
```

Ожидается: 127 passed

- [ ] **Шаг 8: Проверить, что комплект виден рендеру**

```bash
python src/render_video.py --check
```

Ожидается: перечислены 11 отсутствующих файлов `base/*.mp4`, ошибок разбора нет

- [ ] **Шаг 9: Коммит**

```bash
git add assets/screenshots scenario/shots.json tests/test_footage.py
git commit -m "video: одиннадцать кадров с промптами, референсы переименованы в ASCII"
```

---

## Задача 5: `tools/atlas_gen.py`

**Файлы:**
- Создать: `tools/atlas_gen.py`
- Изменить: `requirements.txt`

- [ ] **Шаг 1: Добавить зависимость**

В `requirements.txt` перед блоком `# Тесты.` вставить:

```
# Загрузка референсов в Atlas Cloud идёт multipart/form-data. На urllib это
# двадцать строк ручной сборки границ, на requests — одна.
requests>=2.31
```

Установить:

```bash
python -m pip install -r requirements.txt
```

- [ ] **Шаг 2: Написать скрипт**

Создать `tools/atlas_gen.py`:

```python
"""Генерация кадров видеофона через Atlas Cloud.

Читает тот же scenario/shots.json, что и рендер: промпт живёт рядом со своим
якорем, и второго списка кадров в проекте нет.

Ключ берётся только из переменной окружения ATLASCLOUD_API_KEY и никуда не
печатается — ни в журнал, ни в сообщение об ошибке.

Точные имена полей запроса — в docs/atlas-api.md. Здесь они собраны в один
словарь FIELDS: Atlas поменяет схему, и правка будет в одном месте.

    $env:ATLASCLOUD_API_KEY="..."
    python tools/atlas_gen.py --only interrogation combat --resolution 480p
    python tools/atlas_gen.py --all
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.footage import BaseShot, load_shots  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.atlascloud.ai/api/v1/model"
MODEL = "bytedance/seedance-2.0-mini/reference-to-video"
RATE_PER_SECOND = {"480p": 0.056, "720p": 0.061}
LEDGER = ROOT / "docs" / "atlas-ledger.csv"
LEDGER_HEADER = ["timestamp", "shot", "model", "resolution", "duration",
                 "attempt", "cost_usd", "status", "file", "notes"]

# Имена полей запроса. Сверены со схемой модели — docs/atlas-api.md. Если
# какое-то имя окажется неверным, водяной знак или генерённый звук приедут
# молча, поэтому менять только вместе с документом.
FIELDS = {
    "model": "model",
    "prompt": "prompt",
    "negative": "negative_prompt",
    "refs": "reference_images",
    "duration": "duration",
    "resolution": "resolution",
    "aspect": "aspect_ratio",
    "audio": "generate_audio",
    "watermark": "watermark",
    "last_frame": "return_last_frame",
}


class AtlasError(RuntimeError):
    pass


def key() -> str:
    value = os.environ.get("ATLASCLOUD_API_KEY", "").strip()
    if not value:
        raise AtlasError(
            "нет переменной окружения ATLASCLOUD_API_KEY.\n"
            '  PowerShell:  $env:ATLASCLOUD_API_KEY="..."\n'
            "  bash:        export ATLASCLOUD_API_KEY=..."
        )
    return value


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {key()}"}


def upload(path: Path) -> str:
    """Заливает референс и возвращает временную ссылку на него."""
    with open(path, "rb") as fh:
        response = requests.post(f"{API}/uploadMedia", headers=headers(),
                                 files={"file": fh}, timeout=120)
    if response.status_code >= 400:
        raise AtlasError(f"загрузка {path.name} отклонена "
                         f"({response.status_code}): {response.text[:400]}")
    url = response.json().get("url")
    if not url:
        raise AtlasError(f"в ответе на загрузку {path.name} нет поля url: "
                         f"{response.text[:400]}")
    return url


def submit(shot: BaseShot, refs: list[str], resolution: str) -> str:
    body = {
        FIELDS["model"]: MODEL,
        FIELDS["prompt"]: shot.prompt,
        FIELDS["negative"]: shot.negative,
        FIELDS["refs"]: refs,
        FIELDS["duration"]: int(shot.duration),
        FIELDS["resolution"]: resolution,
        FIELDS["aspect"]: "16:9",
        # Мастер-звук готов и лежит в output/master_v2.wav. Генерённый звук нам
        # не нужен ни в каком виде, а водяной знак виден с любого места в зале.
        FIELDS["audio"]: False,
        FIELDS["watermark"]: False,
        FIELDS["last_frame"]: True,
    }
    response = requests.post(f"{API}/generateVideo", headers=headers(),
                             json=body, timeout=120)
    if response.status_code >= 400:
        raise AtlasError(f"задание отклонено ({response.status_code}): "
                         f"{response.text[:600]}")
    job = response.json().get("id")
    if not job:
        raise AtlasError(f"в ответе нет id задания: {response.text[:400]}")
    return job


def wait(job: str, timeout: float = 900.0) -> str:
    """Опрашивает задание раз в две секунды и возвращает ссылку на результат."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(f"{API}/prediction/{job}",
                                headers=headers(), timeout=60)
        if response.status_code >= 400:
            raise AtlasError(f"опрос {job} ({response.status_code}): "
                             f"{response.text[:400]}")
        payload = response.json()
        status = str(payload.get("status", payload.get("data", {}).get("status", "")))
        if status == "completed":
            outputs = payload.get("data", {}).get("outputs") or []
            if not outputs:
                raise AtlasError(f"задание {job} готово, но outputs пуст: "
                                 f"{str(payload)[:400]}")
            return outputs[0]
        if status == "failed":
            raise AtlasError(f"задание {job} провалилось: {str(payload)[:600]}")
        time.sleep(2.0)
    raise AtlasError(f"задание {job} не завершилось за {timeout:.0f} с")


def download(url: str, target: Path) -> None:
    """Скачивает во временный файл и обеззвучивает его при переносе на место.

    Звук снимается локально, а не только флагом в запросе: если имя поля
    generate_audio окажется неверным, флаг молча ничего не сделает, а
    сгенерированная дорожка поедет в монтаж под готовый мастер.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = target.with_suffix(".raw.mp4")
    with requests.get(url, stream=True, timeout=600) as response:
        if response.status_code >= 400:
            raise AtlasError(f"скачивание ({response.status_code}): {url}")
        with open(raw, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw),
                    "-an", "-c:v", "copy", str(target)], check=True)
    raw.unlink()


def note(row: dict) -> None:
    fresh = not LEDGER.exists()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        if fresh:
            writer.writeheader()
        writer.writerow(row)


def attempt_number(shot_anchor: str) -> int:
    if not LEDGER.exists():
        return 1
    with open(LEDGER, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["shot"] == shot_anchor]
    return len(rows) + 1


def generate(shot: BaseShot, resolution: str, stamp: str) -> None:
    attempt = attempt_number(shot.anchor)
    cost = RATE_PER_SECOND.get(resolution, 0.061) * shot.duration
    target = ROOT / "assets" / "video" / shot.clip
    print(f"[{shot.anchor}] попытка {attempt}, {shot.duration:g} с "
          f"{resolution}, ожидаемо ${cost:.2f}")

    row = {"timestamp": stamp, "shot": shot.anchor, "model": MODEL,
           "resolution": resolution, "duration": shot.duration,
           "attempt": attempt, "cost_usd": f"{cost:.4f}",
           "status": "", "file": shot.clip, "notes": ""}
    try:
        refs = [upload(ROOT / "assets" / "screenshots" / r) for r in shot.refs]
        url = wait(submit(shot, refs, resolution))
        download(url, target)
    except (AtlasError, subprocess.CalledProcessError) as error:
        row["status"] = "failed"
        row["notes"] = str(error).replace("\n", " ")[:300]
        note(row)
        raise
    row["status"] = "ok"
    note(row)
    print(f"[{shot.anchor}] готово: {target.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shots", default=str(ROOT / "scenario" / "shots.json"))
    ap.add_argument("--only", nargs="+", metavar="ЯКОРЬ",
                    help="сгенерировать только эти кадры")
    ap.add_argument("--all", action="store_true", help="все кадры списка")
    ap.add_argument("--resolution", default=None,
                    help="переопределить разрешение, например 480p для пробы")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать, что будет отправлено, и не отправлять")
    args = ap.parse_args()

    if not args.only and not args.all:
        ap.error("укажи --only ЯКОРЬ [ЯКОРЬ...] или --all")

    bases, _ = load_shots(args.shots)
    chosen = [b for b in bases if args.all or b.anchor in args.only]
    if args.only:
        unknown = set(args.only) - {b.anchor for b in bases}
        if unknown:
            ap.error(f"нет таких якорей: {', '.join(sorted(unknown))}. "
                     f"Есть: {', '.join(b.anchor for b in bases)}")

    total = sum(RATE_PER_SECOND.get(args.resolution or b.resolution, 0.061)
                * b.duration for b in chosen)
    print(f"кадров: {len(chosen)}, ожидаемая стоимость ${total:.2f}\n")

    if args.dry_run:
        for shot in chosen:
            resolution = args.resolution or shot.resolution
            print(f"--- {shot.anchor} | {shot.duration:g} с | {resolution} ---")
            print(f"референсы: {', '.join(shot.refs)}")
            print(f"промпт: {shot.prompt}\n")
            print(f"запреты: {shot.negative}\n")
        return 0

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    for shot in chosen:
        try:
            generate(shot, args.resolution or shot.resolution, stamp)
        except (AtlasError, subprocess.CalledProcessError) as error:
            print(f"[{shot.anchor}] ОШИБКА: {error}", file=sys.stderr)
            return 1
    print(f"\nжурнал: {LEDGER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Шаг 3: Заменить угаданные имена полей настоящими**

**Значения в словаре `FIELDS`, кроме `model` и `prompt`, — заглушки.** Они
выглядят правдоподобно (`negative_prompt`, `reference_images`, `generate_audio`),
но документацией не подтверждены, а спека прямо запрещает выдумывать поля API.

Открыть `docs/atlas-api.md` (Задача 1) и подставить в `FIELDS` имена из таблицы.
Два поля критичны:

- `watermark` — при неверном имени флаг молча не сработает, и водяной знак
  приедет в готовом клипе. Локально его не снять, а виден он с любого места
  в зале.
- `audio` — при неверном имени приедет сгенерированная дорожка. Это лечится
  локально: `download()` всё равно прогоняет файл через `ffmpeg -an`. Но знать
  об этом лучше сразу.

Сверить, что в `FIELDS` не осталось ни одного значения, которого нет в
`docs/atlas-api.md`:

```bash
python - <<'PY'
import re, pathlib
doc = pathlib.Path("docs/atlas-api.md").read_text(encoding="utf-8")
src = pathlib.Path("tools/atlas_gen.py").read_text(encoding="utf-8")
block = re.search(r"FIELDS = \{(.+?)\n\}", src, re.S).group(1)
names = re.findall(r':\s*"([^"]+)"', block)
missing = [n for n in names if n not in doc]
print("не подтверждены документацией:", missing or "нет, всё сходится")
PY
```

Ожидается: `не подтверждены документацией: нет, всё сходится`

- [ ] **Шаг 4: Проверить сухим прогоном, без сети и без ключа**

```bash
python tools/atlas_gen.py --only interrogation combat --resolution 480p --dry-run
```

Ожидается: два блока с промптами и строка `кадров: 2, ожидаемая стоимость $0.73`. Ключ не требуется, потому что сеть не трогается.

- [ ] **Шаг 5: Проверить, что неверный якорь ловится сразу**

```bash
python tools/atlas_gen.py --only no_such_anchor --dry-run
```

Ожидается: ошибка со списком настоящих якорей, код возврата 2

- [ ] **Шаг 6: Проверить, что без ключа скрипт объясняет, чего не хватает**

```bash
python tools/atlas_gen.py --only interrogation
```

Ожидается: `нет переменной окружения ATLASCLOUD_API_KEY` и подсказка для PowerShell. Ключ в вывод не попадает.

- [ ] **Шаг 7: Коммит**

```bash
git add tools/atlas_gen.py requirements.txt
git commit -m "tools: генерация кадров через Atlas Cloud, ключ только из окружения"
```

---

## Задача 6: Проба на двух кадрах

Цена $0.73 из тридцати. Дальше остальные девять кадров не запускаются, пока проба не просмотрена.

**Файлы:** ничего не правится, только читается результат.

- [ ] **Шаг 1: Подрезать референсы с полосой браузера**

У четырёх файлов посторонние элементы по краям — модель может воспроизвести их как часть кадра. Для пробы нужен только `lohen_splash_art.png`, но проще сделать все сразу.

```bash
cd assets/screenshots
for f in door_green.png spear_fight_03.png knife_green.png; do
  ffmpeg -v error -y -i "$f" -vf "crop=iw:ih-24:0:24" "tmp_$f" && mv "tmp_$f" "$f"
done
ffmpeg -v error -y -i lohen_splash_art.png -vf "crop=iw-80:ih-24:0:24" tmp.png && mv tmp.png lohen_splash_art.png
cd ../..
```

- [ ] **Шаг 2: Задать ключ в окружении**

```bash
export ATLASCLOUD_API_KEY=...
```

В PowerShell: `$env:ATLASCLOUD_API_KEY="..."`. В репозиторий, в файлы и в переписку ключ не попадает.

- [ ] **Шаг 3: Сгенерировать два кадра на 480p**

```bash
python tools/atlas_gen.py --only interrogation combat --resolution 480p
```

Ожидается: две строки `готово`, файлы `assets/video/base/01_interrogation.mp4` и `assets/video/base/04_breach.mp4`, новая строка в `docs/atlas-ledger.csv` на каждый кадр.

- [ ] **Шаг 4: Убедиться, что звука в клипах нет**

```bash
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 assets/video/base/01_interrogation.mp4
```

Ожидается: только `video`. Если появилась строка `audio` — поле `generate_audio` названо неверно, править `docs/atlas-api.md` и `FIELDS`.

- [ ] **Шаг 5: Прогнать через настоящий пайплайн**

```bash
python src/render_video.py --stills
```

Ожидается: кадры-образцы в `output/stills/`, включая `contact.png`. Это единственная честная проверка: клип смотрится с предохранителем и грейдингом, а не сам по себе.

- [ ] **Шаг 6: Просмотреть контактный лист по критериям приёмки**

Открыть `output/stills/contact.png` и проверить по списку:

1. Из кадра допроса понятно, что мы **стоим над пленником**, а не смотрим пустую комнату.
2. **Окно-люк видно и оно светится** — без установленного проёма ломать на 22.30 нечего.
3. Из кадра пролома понятно, что вломились **люди**, их **много** и они **вооружены**.
4. Водяного знака и читаемых надписей нет.
5. Комната в обоих кадрах одна и та же. Разъехалась — в продакшене сшивать через последний кадр.
6. Композиция читается **после предохранителя**: центральная полоса затемнена, и пленник с проёмом в неё не попали.
7. Затемнение центра не выглядит видимой вертикальной полосой на реальном футаже.

- [ ] **Шаг 7: Записать вывод и решение**

Создать `docs/status/2026-08-03-atlas-pilot.md`: что получилось, что нет, по каждому из семи пунктов, и решение — идём на остальные девять кадров или меняем композицию и референсы. Бюджет при провале **не увеличивается**: три попытки на кадр, дальше меняется постановка, а не сумма.

- [ ] **Шаг 8: Коммит**

```bash
git add docs/status/2026-08-03-atlas-pilot.md docs/atlas-ledger.csv
git commit -m "docs: результат пробной генерации двух кадров"
```

---

## Порядок и зависимости

Задача 1 блокирует Задачу 5: без точных имён полей `atlas_gen.py` писать нельзя.
Задача 3 блокирует Задачу 4: `shots.json` с промптами не загрузится, пока `load_shots` их не знает.
Задачи 2, 3 и 4 не требуют ни ключа, ни сети, ни денег — их можно закрыть целиком до первой генерации.
Задача 6 требует ключа от пользователя.

## Что этот план не делает

- Не отправляет письмо организаторам. Оно готово и не отправлено; револьвер и передний свет по-прежнему блокируют.
- Не покупает сток. Pexels и Pixabay остаются запасным вариантом.
- Не пересчитывает гейны. Значения в `shots.json` поставлены с запасом на тёмный исходник (0.75–1.0 против прежних 0.55–0.85), но настоящие числа берутся измерением по Rec.709 на 1920×1080 после появления реальных клипов — это отдельная работа после пробы.
- Не трогает мастер-звук.
