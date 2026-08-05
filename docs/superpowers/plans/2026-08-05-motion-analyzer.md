# Анализатор движений: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Пакет `motion/`, который по видео тренировки замеряет время, ритм, торможение и переходы между ударами, сверяет их с требованиями номера и складывает разбор с кадрами в `train/reports/<дата>/`.

**Architecture:** Кадры и звук читаются через FFmpeg (`src.footage.ClipReader` переиспользуется как есть). Огибающая движения строится по разнице соседних кадров с четырьмя починками, которые нашла проба на настоящем материале: подавление автоэкспозиции, сглаживание, нормировка на масштаб, три режима вместо одного порога. Модели фона нет вовсе — проба показала, что она проваливается трижды. Слой позы необязателен: без него анализатор отдаёт время и ритм, с ним — ещё и углы тела.

**Tech Stack:** Python 3.12, numpy, scipy, Pillow, FFmpeg, pytest. Опционально mediapipe 0.10.35 (уже установлен) плюс файл модели, который в пакет не входит.

**Проектное решение:** [docs/superpowers/specs/2026-08-05-motion-analyzer-design.md](../specs/2026-08-05-motion-analyzer-design.md). Все ссылки на «пробу» ниже — это п. 2 того документа.

---

## Структура файлов

| файл | ответственность |
|---|---|
| `motion/__init__.py` | пусто, пакет |
| `motion/video.py` | **ввод:** ffprobe, серые кадры, полоса звука, один кадр полного размера |
| `motion/envelope.py` | огибающая движения и её пороги. Четыре починки из пробы живут здесь |
| `motion/segment.py` | покой / владение / удар, доли удара, обрезка возни с камерой |
| `motion/pose.py` | **необязательный слой:** суставы, рост в кадре, кинетическая цепь |
| `motion/frames.py` | **вывод картинок:** полосы кадров и обзорный лист |
| `motion/requirements.py` | **единственный модуль, знающий о номере:** читает `scenario/` |
| `motion/compare.py` | сверка замеров с требованиями. Слова `burst_3` не содержит |
| `motion/session.py` | один прогон в один словарь |
| `motion/report.py` | `report.md` и `measurements.json` |
| `motion/analyze.py` | точка входа |
| `motion/README.md` | что это, как запустить, что означают числа |
| `tests/motion_clips.py` | генератор синтетических клипов для тестов |
| `tests/test_motion_video.py` | ввод |
| `tests/test_motion_envelope.py` | тесты 1–4 из приёмки |
| `tests/test_motion_segment.py` | тесты 5–6 |
| `tests/test_motion_compare.py` | тесты 7–8 |
| `requirements.txt` | добавить mediapipe с оговоркой |
| `.gitignore` | добавить `motion/models/` |
| `README.md` | раздел про анализатор |

**Порядок зависимостей:** `video` → `envelope` → `segment` → (`pose`, `frames`) → (`requirements`, `compare`) → `session` → `report` → `analyze`. Каждая задача ниже опирается только на предыдущие.

---

## Задача 1: Пакет и чтение видео

**Files:**
- Create: `motion/__init__.py`
- Create: `motion/video.py`
- Create: `tests/motion_clips.py`
- Test: `tests/test_motion_video.py`

- [ ] **Шаг 1: Генератор синтетических клипов**

Создать `tests/motion_clips.py`. Это фундамент тестов 1–6: настоящие видео в тестах использовать нельзя, они медленные и не воспроизводимы.

```python
"""Синтетические клипы с известным ответом.

Тот же приём, что в tools/make_test_clips.py: кадры рисует numpy, кодирует
FFmpeg. Настоящие тренировочные видео в тестах не используются — они медленные,
и на них нет известного правильного ответа.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

W, H = 320, 180


def encode(path: Path, frames: np.ndarray, fps: int) -> Path:
    """Массив (n, H, W) в 0..1 -> mp4 без потерь качества для замера."""
    raw = (np.clip(frames, 0.0, 1.0) * 255).astype(np.uint8)
    rgb = np.repeat(raw[:, :, :, None], 3, axis=3)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{frames.shape[2]}x{frames.shape[1]}", "-framerate", str(fps),
         "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
         str(path)],
        input=rgb.tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg не собрал клип: {proc.stderr.decode(errors='replace')}")
    return path


def scene(n: int, contrast: float = 1.0) -> np.ndarray:
    """Неподвижный фон: горизонтальные полосы. Ничем не отличается от кадра
    к кадру, поэтому вся разница в клипе будет от того, что мы нарисуем сверху."""
    base = np.zeros((H, W), dtype=np.float32) + 0.35
    base[::8, :] = 0.5
    return np.repeat(base[None, :, :], n, axis=0) * contrast


def bar(frames: np.ndarray, i: int, x: float, contrast: float = 1.0) -> None:
    """Вертикальная полоса шириной 10 px с центром в x. Это «палка»."""
    x0 = int(np.clip(x - 5, 0, frames.shape[2] - 1))
    x1 = int(np.clip(x + 5, 1, frames.shape[2]))
    frames[i, 20:160, x0:x1] = np.clip(0.35 + 0.6 * contrast, 0.0, 1.0)


def sweep(path: Path, fps: int, total: int, a: int, b: int,
          rise: float = 0.5, contrast: float = 1.0) -> Path:
    """Полоса стоит, потом проходит кадр и снова стоит.

    Скорость идёт по треугольнику: разгон до кадра a + rise*(b-a), потом
    торможение. Пик скорости и есть известный ответ. rise=0.5 — симметрично;
    rise=0.85 — долгий замах и резкая остановка, то есть «палку остановили».
    """
    frames = scene(total, contrast)
    peak = a + rise * (b - a)
    speed = np.zeros(total)
    for i in range(a, b):
        speed[i] = (i - a) / max(peak - a, 1e-9) if i <= peak \
            else (b - i) / max(b - peak, 1e-9)
    pos = 40 + np.cumsum(np.clip(speed, 0.0, None))
    pos *= (W - 80) / max(pos[-1] - pos[0], 1e-9) if pos[-1] > pos[0] else 1.0
    pos = pos - pos[0] + 40
    for i in range(total):
        bar(frames, i, float(pos[min(i, total - 1)]), contrast)
    encode(path, frames, fps)
    return path


def still(path: Path, fps: int, total: int) -> Path:
    """Ничего не двигается вовсе."""
    frames = scene(total)
    for i in range(total):
        bar(frames, i, 160.0)
    return encode(path, frames, fps)


def bright_step(path: Path, fps: int, total: int, at: int,
                step: float = 0.18) -> Path:
    """Ничего не двигается, но на кадре `at` вся яркость разом растёт.

    Это автоэкспозиция телефона. На настоящем материале она красила кадр
    целиком и читалась как движение."""
    frames = scene(total)
    for i in range(total):
        bar(frames, i, 160.0)
    frames[at:] += step
    return encode(path, frames, fps)


def two_sweeps(path: Path, fps: int, dead: bool) -> Path:
    """Два смаха. dead=True — между ними полная остановка; False — медленный
    переход, полоса продолжает ползти."""
    total = fps * 4
    frames = scene(total)
    a1, b1 = int(fps * 0.4), int(fps * 1.0)
    a2, b2 = int(fps * 2.6), int(fps * 3.2)
    pos = np.full(total, 40.0)
    pos[a1:b1] = np.linspace(40, 150, b1 - a1)
    pos[b1:a2] = 150.0 if dead else np.linspace(150, 170, a2 - b1)
    pos[a2:b2] = np.linspace(pos[a2 - 1], 280, b2 - a2)
    pos[b2:] = 280.0
    for i in range(total):
        bar(frames, i, float(pos[i]))
    return encode(path, frames, fps)
```

- [ ] **Шаг 2: Написать падающий тест на чтение**

Создать `tests/test_motion_video.py`:

```python
"""Ввод: сколько кадров, какой формы, и падает ли внятно на плохом файле."""

import numpy as np
import pytest

from motion import video
from tests import motion_clips


def test_probe_reads_size_and_fps(tmp_path):
    path = motion_clips.still(tmp_path / "a.mp4", fps=30, total=90)
    clip = video.probe(path)
    assert (clip.width, clip.height) == (motion_clips.W, motion_clips.H)
    assert clip.fps == 30
    assert clip.duration == pytest.approx(3.0, abs=0.2)


def test_gray_frames_shape_and_range(tmp_path):
    path = motion_clips.still(tmp_path / "a.mp4", fps=30, total=90)
    frames = video.gray_frames(video.probe(path), width=160)
    assert frames.ndim == 3
    assert frames.shape[2] == 160
    assert frames.shape[1] == 90          # пропорции 320x180 сохранены
    assert frames.dtype == np.float32
    assert 0.0 <= frames.min() and frames.max() <= 1.0
    assert len(frames) >= 88              # кодек может отдать на кадр меньше


def test_short_clip_is_refused(tmp_path):
    path = motion_clips.still(tmp_path / "a.mp4", fps=30, total=30)
    with pytest.raises(video.VideoError, match="от 2 с"):
        video.probe(path)


def test_missing_file_names_itself(tmp_path):
    with pytest.raises(video.VideoError, match="нет.mp4"):
        video.probe(tmp_path / "нет.mp4")
```

- [ ] **Шаг 3: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_video.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'motion'`

- [ ] **Шаг 4: Написать `motion/__init__.py` и `motion/video.py`**

`motion/__init__.py` — пустой файл.

```python
"""Ввод: кадры и звук через FFmpeg. Своих алгоритмов здесь нет.

Кадры читает src.footage.ClipReader — он уже приводит клип любого разрешения
к нужному размеру через трубу и падает с внятной ошибкой, называя файл и
команду. Своей копии нет намеренно.

fill=False, чтобы кадр никогда не обрезался: у сегодняшних видео пропорции
совпадают с целевыми и разницы нет, но вертикальное видео с телефона на
следующем заходе обрезалось бы молча, а pad при совпадающих пропорциях не
делает ничего.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.footage import ClipReader

# Веса яркости BT.709 — те же, по которым живёт видеорендер проекта.
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

MIN_DURATION = 2.0


class VideoError(Exception):
    """Видео не читается или не годится для разбора."""


@dataclass(frozen=True)
class Clip:
    path: Path
    width: int
    height: int
    fps: int
    duration: float


def probe(path: str | Path) -> Clip:
    """Размер, частота и длина. Частота округляется до целой.

    Округление намеренное: ClipReader всё равно приводит поток к целой частоте
    фильтром fps, и время в замере считается по той же целой. Для 30000/1001
    это расхождение 0.1% и полная внутренняя согласованность вместо точности,
    которой в кадрах всё равно нет.
    """
    path = Path(path)
    if not path.exists():
        raise VideoError(f"{path.name}: файла нет ({path})")
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoError(f"{path.name}: ffprobe вернул {proc.returncode}.\n"
                         f"{proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    stream = next((s for s in data.get("streams", [])
                   if s.get("codec_type") == "video"), None)
    if stream is None:
        raise VideoError(f"{path.name}: в файле нет видеодорожки")
    num, _, den = str(stream.get("r_frame_rate", "0/1")).partition("/")
    fps = int(round(float(num) / float(den or 1))) or 1
    duration = float(data.get("format", {}).get("duration", 0.0))
    if duration < MIN_DURATION:
        raise VideoError(f"{path.name}: длина {duration:.2f} с, разбирать нечего "
                         f"(нужно от {MIN_DURATION:g} с)")
    return Clip(path=path, width=int(stream["width"]),
                height=int(stream["height"]), fps=fps, duration=duration)


def gray_frames(clip: Clip, width: int = 320) -> np.ndarray:
    """Все кадры серыми, (n, h, w) float32 в 0..1.

    Мелкое разрешение для сигнала: 3139 кадров в полном размере это около 6 ГБ,
    в 320x180 — 180 МБ.
    """
    height = max(2, int(round(width * clip.height / clip.width / 2)) * 2)
    reader = ClipReader(clip.path, width, height, clip.fps, fill=False)
    out: list[np.ndarray] = []
    try:
        while True:
            frame = reader.read()
            if frame is None:
                break
            out.append(frame[:, :, :3] @ LUMA)
    finally:
        reader.close()
    if not out:
        raise VideoError(f"{clip.path.name}: FFmpeg не отдал ни одного кадра")
    return np.stack(out)


def band_envelope(clip: Clip, hz: float = 2000.0) -> np.ndarray:
    """Пиковая огибающая полосы выше hz, по отсчёту на кадр видео.

    Нужна ровно для одного: найти возню с камерой в начале и в конце. Проба
    показала, что палка на этих скоростях не свистит вовсе, и как источник
    тайминга звук не годится. Дорожки может не быть — тогда пустой массив.
    """
    sr = 48000
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(clip.path),
         "-af", f"highpass=f={hz:g}", "-ac", "1", "-ar", str(sr),
         "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(proc.stdout, dtype=np.float32)
    hop = max(1, int(round(sr / clip.fps)))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.abs(x[:n * hop].reshape(n, hop)).max(axis=1)


def still_rgb(clip: Clip, t: float) -> np.ndarray:
    """Один кадр полного размера, (h, w, 3) uint8. Для картинок отчёта."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(clip.path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    need = clip.width * clip.height * 3
    if len(proc.stdout) < need:
        raise VideoError(f"{clip.path.name}: кадр на {t:.2f} с не прочитался")
    return np.frombuffer(proc.stdout[:need], np.uint8).reshape(
        clip.height, clip.width, 3)
```

- [ ] **Шаг 5: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_video.py -v`
Expected: PASS, 4 passed

- [ ] **Шаг 6: Коммит**

```bash
git add motion/__init__.py motion/video.py tests/motion_clips.py tests/test_motion_video.py && git commit -m "motion: чтение видео и синтетика для тестов"
```

---

## Задача 2: Огибающая движения — четыре починки из пробы

**Files:**
- Create: `motion/envelope.py`
- Test: `tests/test_motion_envelope.py`

- [ ] **Шаг 1: Написать падающие тесты 1–4**

Создать `tests/test_motion_envelope.py`. Каждый тест существует потому, что без него замер соврал на настоящем материале.

```python
"""Тесты 1-4 приёмки: огибающая движения.

Тесты 2 и 3 существуют потому, что ровно на этих двух местах проба и
сломалась: автоэкспозиция красила кадр целиком, а модель фона проваливалась,
когда исполнитель не покидал кадр.
"""

import numpy as np
import pytest

from motion import envelope, video
from tests import motion_clips


def build(path, width=160):
    clip = video.probe(path)
    frames = video.gray_frames(clip, width=width)
    return envelope.build(frames, clip.fps), clip


def test_1_peak_lands_on_the_known_moment(tmp_path):
    """Всплеск в известный момент: пик огибающей попадает в него."""
    fps, total, a, b = 30, 120, 30, 60
    path = motion_clips.sweep(tmp_path / "s.mp4", fps=fps, total=total, a=a, b=b)
    env, _ = build(path)
    want = (a + 0.5 * (b - a)) / fps
    got = float(env.times[int(np.argmax(env.values))])
    assert abs(got - want) <= 2.0 / fps, f"пик на {got:.3f}, ждали {want:.3f}"


def test_1b_a_hard_stop_reads_shorter_than_its_windup(tmp_path):
    """`stop` действительно мерит, чем останавливают палку.

    Долгий разгон и резкая остановка (rise=0.85) должны дать торможение
    короче замаха. Если метрика этого не различает, она бесполезна.
    """
    fps = 30
    path = motion_clips.sweep(tmp_path / "s.mp4", fps=fps, total=120,
                              a=30, b=75, rise=0.85)
    env, _ = build(path)
    peak = int(np.argmax(env.values))
    level = env.floor + 0.10 * (env.values[peak] - env.floor)
    left = peak
    while left > 0 and env.values[left] > level:
        left -= 1
    right = peak
    while right < len(env.values) - 1 and env.values[right] > level:
        right += 1
    windup = (peak - left) / fps
    stop = (right - peak) / fps
    assert stop < windup, f"торможение {stop:.3f} не короче замаха {windup:.3f}"


def test_2_a_global_brightness_step_is_not_motion(tmp_path):
    """Автоэкспозиция: вся яркость разом выросла, движения нет.

    Замеряется raw_motion, а не нормированная огибающая: в клипе без движения
    нормировать не на что, и делить на разброс шума значило бы проверять шум.
    """
    fps, total, at = 30, 120, 60
    path = motion_clips.bright_step(tmp_path / "b.mp4", fps=fps,
                                    total=total, at=at)
    clip = video.probe(path)
    raw = envelope.raw_motion(video.gray_frames(clip, width=160))
    median = float(np.median(raw))
    at_step = float(raw[max(at - 3, 0):at + 3].max())
    assert at_step <= max(median * 4.0, 1e-4), (
        f"скачок яркости дал {at_step:.6f} при медиане {median:.6f}")


def test_3_works_when_the_subject_never_leaves_the_frame(tmp_path):
    """Модели фона нет вовсе, поэтому объект может быть в кадре всегда.

    На настоящем материале медианный фон оказывался самим исполнителем, когда
    он стоял на месте, и маска ловила почти ничего.
    """
    fps = 30
    path = motion_clips.sweep(tmp_path / "s.mp4", fps=fps, total=120, a=30, b=60)
    env, _ = build(path)
    assert env.values.max() > env.strike_level, "всплеск не нашёлся"
    assert env.values[:20].mean() < env.strike_level, "покой принят за удар"


def test_4_the_same_motion_at_two_contrasts_normalises_together(tmp_path):
    """Порог не переносится между съёмками: v1 максимум 0.029, v2 — 0.014 при
    том же движении. После нормировки огибающие должны совпасть."""
    fps = 30
    strong, _ = build(motion_clips.sweep(tmp_path / "hi.mp4", fps=fps,
                                         total=120, a=30, b=60, contrast=1.0))
    weak, _ = build(motion_clips.sweep(tmp_path / "lo.mp4", fps=fps,
                                       total=120, a=30, b=60, contrast=0.35))
    n = min(len(strong.values), len(weak.values))
    ratio = strong.values[:n].max() / weak.values[:n].max()
    assert 0.9 <= ratio <= 1.1, f"после нормировки расходятся в {ratio:.2f} раза"


def test_scale_source_is_always_named(tmp_path):
    """Отчёт обязан сказать, какая нормировка применена, иначе числа между
    видео сравнивать нельзя."""
    env, _ = build(motion_clips.sweep(tmp_path / "s.mp4", fps=30,
                                      total=120, a=30, b=60))
    assert env.scale_source in {"поза", "разброс", "нет"}
    assert env.size_fix
```

- [ ] **Шаг 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_envelope.py -v`
Expected: FAIL — `ImportError: cannot import name 'envelope' from 'motion'`

- [ ] **Шаг 3: Написать `motion/envelope.py`**

```python
"""Огибающая движения и её пороги.

Четыре починки здесь существуют не для аккуратности, а потому что без каждой
из них замер соврал на настоящем материале. Что именно ломалось — в
docs/superpowers/specs/2026-08-05-motion-analyzer-design.md, п. 2.

Модели фона нет вовсе. Она проваливалась трижды: медиана по времени оказывалась
самим исполнителем, когда он стоял на месте; автоэкспозиция красила кадр
целиком; эрозия назначала палкой торс. Разница соседних кадров ни одного из
этих провалов не имеет.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FLOOR_PCT = 20.0        # дно (уровень покоя) — 20-я процентиль
STRIKE_FRAC = 0.35      # порог удара — дно + 0.35 * (максимум - дно)
SMOOTH_S = 0.08         # окно сглаживания
LEVEL_FRAC = 0.10       # уровень, по которому мерятся замах и торможение

# 0.35 взят из пробы и подлежит настройке на трёх настоящих видео по одному
# критерию: найденные всплески должны совпадать с тем, что видно на контактном
# листе. Проба с 0.35 БЕЗ нормировки пропустила дальние смахи.


@dataclass(frozen=True)
class Envelope:
    values: np.ndarray      # сглаженная и нормированная, отсчёт на пару кадров
    times: np.ndarray       # время каждого отсчёта, с
    fps: int
    floor: float            # уровень покоя, в тех же единицах что values
    strike_level: float     # порог удара
    scale: float            # на что поделили
    scale_source: str       # "поза" | "разброс" | "нет"
    size_fix: str           # чем починен масштаб внутри видео

    def level_for(self, peak: float) -> float:
        """Уровень 10%, от которого мерятся замах и торможение."""
        return self.floor + LEVEL_FRAC * (peak - self.floor)


def raw_motion(frames: np.ndarray) -> np.ndarray:
    """Разница соседних кадров с подавлением автоэкспозиции.

    Вычитание собственного среднего каждого кадра ДО разницы — вся починка, и
    она одна строка. Без неё скачок экспозиции телефона отличается сразу в
    каждой точке и читается как движение: на настоящем материале он красил в
    маску весь навес, деревья и плитку.
    """
    levelled = frames - frames.mean(axis=(1, 2), keepdims=True)
    return np.abs(np.diff(levelled, axis=0)).mean(axis=(1, 2))


def smooth(values: np.ndarray, fps: int, window_s: float = SMOOTH_S) -> np.ndarray:
    """Скользящее среднее. Один кадр при 60 fps не бывает замахом.

    Без сглаживания проба выдавала подъём и спад по 0.017 с, то есть по одному
    кадру, — это артефакт спайкового сигнала, а не замер.
    """
    width = max(1, int(round(window_s * fps)))
    values = np.asarray(values, dtype=np.float64)
    if width < 2 or len(values) < width:
        return values
    return np.convolve(values, np.ones(width) / width, mode="same")


def build(frames: np.ndarray, fps: int,
          body_frac: np.ndarray | None = None) -> Envelope:
    """Огибающая из кадров.

    body_frac — рост исполнителя долей высоты кадра, по кадру, из позы. Если
    он есть, чинится ВТОРАЯ беда масштаба: один и тот же смах вблизи и вдалеке
    даёт разную энергию, потому что она растёт как площадь, то есть как
    квадрат роста в кадре. Проба пропустила дальние смахи ровно из-за этого:
    рост в кадре 69 px против 89 у ближних.

    Нормировка на разброс внутри видео чинит ПЕРВУЮ беду — разный контраст
    между съёмками. Это две разные починки, и нужны обе.
    """
    raw = raw_motion(frames)
    if body_frac is not None and len(body_frac) >= len(raw) + 1:
        frac = np.clip(np.asarray(body_frac, dtype=np.float64), 0.05, 1.0)
        area = (frac[:len(raw)] + frac[1:len(raw) + 1]) / 2.0
        raw = raw / area ** 2
        size_fix = "по росту в кадре из позы"
    else:
        size_fix = "нет: позы не было, дальние движения занижены"

    vals = smooth(raw, fps)
    floor = float(np.percentile(vals, FLOOR_PCT))
    active = vals[vals > floor]
    spread = float(active.std()) if active.size > 1 else 0.0
    if spread > 1e-9:
        scale, source = spread, "разброс"
    else:
        scale, source = 1.0, "нет"

    norm = vals / scale
    nfloor = floor / scale
    strike_level = nfloor + STRIKE_FRAC * (float(norm.max()) - nfloor)
    # Отсчёт разницы лежит между своими двумя кадрами, отсюда полкадра.
    times = np.arange(len(norm)) / fps + 0.5 / fps
    return Envelope(values=norm, times=times, fps=fps, floor=nfloor,
                    strike_level=strike_level, scale=scale,
                    scale_source=source, size_fix=size_fix)
```

- [ ] **Шаг 4: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_envelope.py -v`
Expected: PASS, 6 passed

- [ ] **Шаг 5: Коммит**

```bash
git add motion/envelope.py tests/test_motion_envelope.py && git commit -m "motion: огибающая движения, четыре починки из пробы"
```

---

## Задача 3: Режимы, удары и обрезка возни с камерой

**Files:**
- Create: `motion/segment.py`
- Test: `tests/test_motion_segment.py`

- [ ] **Шаг 1: Написать падающие тесты 5–6**

Создать `tests/test_motion_segment.py`:

```python
"""Тесты 5-6 приёмки: режимы и переходы."""

import numpy as np
import pytest

from motion import envelope, segment, video
from tests import motion_clips


def analyse(path):
    clip = video.probe(path)
    frames = video.gray_frames(clip, width=160)
    env = envelope.build(frames, clip.fps)
    band = video.band_envelope(clip)
    trim = segment.camera_trim(band, clip.fps, clip.duration)
    return env, trim, clip


def test_5_a_static_clip_is_one_long_rest(tmp_path):
    """Неподвижный клип: один отрезок покоя, ноль ударов."""
    env, trim, clip = analyse(motion_clips.still(tmp_path / "s.mp4",
                                                 fps=30, total=120))
    hits = segment.strikes(env, trim)
    parts = segment.segments(env, trim)
    assert hits == []
    assert [p.role for p in parts] == ["покой"]
    assert parts[0].end - parts[0].start > 3.0


def test_6_dead_stop_between_strikes_is_detected(tmp_path):
    """Два всплеска с полной остановкой между ними."""
    env, trim, _ = analyse(motion_clips.two_sweeps(tmp_path / "d.mp4",
                                                   fps=30, dead=True))
    hits = segment.strikes(env, trim)
    assert len(hits) == 2, [round(h.t_peak, 2) for h in hits]
    assert hits[0].dead_stop_before is None, "у первого удара нет предыдущего"
    assert hits[1].dead_stop_before is True


def test_6b_a_continuous_transition_is_not_a_dead_stop(tmp_path):
    """Те же два всплеска, но между ними движение не прекращается."""
    env, trim, _ = analyse(motion_clips.two_sweeps(tmp_path / "c.mp4",
                                                   fps=30, dead=False))
    hits = segment.strikes(env, trim)
    assert len(hits) == 2, [round(h.t_peak, 2) for h in hits]
    assert hits[1].dead_stop_before is False


def test_strike_carries_windup_and_stop(tmp_path):
    env, trim, _ = analyse(motion_clips.sweep(tmp_path / "s.mp4", fps=30,
                                              total=120, a=30, b=60))
    hits = segment.strikes(env, trim)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.windup > 0 and hit.stop > 0
    assert hit.windup + hit.stop <= (60 - 30) / 30 * 1.6
    assert hit.gap_before is None


def test_trim_names_itself_even_when_nothing_is_cut(tmp_path):
    """Обрезанное окно всегда попадает в отчёт, даже если резать нечего."""
    _, trim, clip = analyse(motion_clips.still(tmp_path / "s.mp4",
                                               fps=30, total=120))
    assert trim.start == 0.0
    assert trim.end == pytest.approx(clip.duration, abs=0.3)
    assert trim.reason


def test_trim_without_audio_says_so(tmp_path):
    trim = segment.camera_trim(np.zeros(0), fps=30, duration=4.0)
    assert trim.start == 0.0 and trim.end == 4.0
    assert "дорожки" in trim.reason
```

- [ ] **Шаг 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_segment.py -v`
Expected: FAIL — `ImportError: cannot import name 'segment' from 'motion'`

- [ ] **Шаг 3: Написать `motion/segment.py`**

```python
"""Три режима, удары и обрезка возни с камерой.

Один порог на всё не годится: проба показала, что все 19 секунд медленного
владения в v3 лежат ниже порога удара, и детектор пиков их не видит вовсе.
Медленная работа и удар — разные вещи, и мерятся разными правилами.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motion.envelope import Envelope

HANDLING_MIN_S = 0.5      # владение короче этого — не режим, а дрожание
MIN_GAP_S = 0.35          # два пика ближе этого — один удар
DEAD_STOP_FACTOR = 1.5    # дно паузы ниже 1.5 x покоя — мёртвая остановка
TRIM_DB = 12.0            # всплеск полосы выше медианы на столько — камера
TRIM_EDGE_S = 5.0         # искать только в первых и последних секундах


@dataclass(frozen=True)
class Segment:
    role: str               # "покой" | "владение" | "удар"
    start: float
    end: float


@dataclass(frozen=True)
class Strike:
    t_peak: float
    peak: float
    windup: float           # от 10% до пика
    stop: float             # от пика до 10% — чем останавливают палку
    gap_before: float | None
    floor_before: float | None
    dead_stop_before: bool | None


@dataclass(frozen=True)
class Trim:
    start: float
    end: float
    reason: str


def camera_trim(band: np.ndarray, fps: int, duration: float,
                edge_s: float = TRIM_EDGE_S, db: float = TRIM_DB) -> Trim:
    """Отрезать возню с камерой по звуку.

    Проба: верхняя полоса стоит на -60 dB и подскакивает до -30...-47 только
    когда трогают камеру. Палка на этих скоростях не свистит, поэтому всплеск
    в первых или последних секундах — это руки на телефоне, а не движение.

    Обрезанное окно возвращается всегда, даже когда резать нечего: отчёт обязан
    его назвать.
    """
    if band.size == 0:
        return Trim(0.0, duration, "звуковой дорожки нет, обрезка не делалась")
    level = 20.0 * np.log10(np.maximum(band, 1e-9))
    median = float(np.median(level))
    loud = level > median + db
    edge = max(1, int(round(edge_s * fps)))

    start, end = 0.0, duration
    parts = []
    head = np.flatnonzero(loud[:edge])
    if head.size:
        start = min((head.max() + 1) / fps, duration * 0.5)
        parts.append(f"в начале срезано {start:.2f} с")
    tail = np.flatnonzero(loud[max(len(loud) - edge, 0):])
    if tail.size:
        first = max(len(loud) - edge, 0) + int(tail.min())
        end = max(first / fps, duration * 0.5)
        parts.append(f"в конце срезано {duration - end:.2f} с")
    reason = ("возня с камерой по звуку: " + ", ".join(parts)) if parts \
        else f"резать нечего: всплесков громче медианы на {db:g} dB у краёв нет"
    return Trim(start, end, reason)


def _inside(env: Envelope, trim: Trim) -> np.ndarray:
    return (env.times >= trim.start) & (env.times <= trim.end)


def segments(env: Envelope, trim: Trim) -> list[Segment]:
    """Разметка на покой, владение и удар. Владение короче 0.5 с не режим."""
    mask = _inside(env, trim)
    times, vals = env.times[mask], env.values[mask]
    if len(vals) == 0:
        return []

    roles = np.where(vals > env.strike_level, "удар",
                     np.where(vals > env.floor, "владение", "покой"))
    out: list[Segment] = []
    i = 0
    while i < len(roles):
        j = i
        while j + 1 < len(roles) and roles[j + 1] == roles[i]:
            j += 1
        out.append(Segment(role=str(roles[i]), start=float(times[i]),
                           end=float(times[j])))
        i = j + 1

    # Короткое владение — не режим. Приклеивается к покою, чтобы дрожание
    # камеры не выглядело работой с оружием.
    fixed = [s if not (s.role == "владение"
                       and s.end - s.start < HANDLING_MIN_S)
             else Segment("покой", s.start, s.end) for s in out]
    merged: list[Segment] = []
    for part in fixed:
        if merged and merged[-1].role == part.role:
            merged[-1] = Segment(part.role, merged[-1].start, part.end)
        else:
            merged.append(part)
    return merged


def strikes(env: Envelope, trim: Trim) -> list[Strike]:
    """Удары: локальные максимумы выше порога, не ближе 0.35 с друг к другу."""
    mask = _inside(env, trim)
    idx = np.flatnonzero(mask)
    if idx.size < 3:
        return []
    times, vals = env.times[mask], env.values[mask]

    peaks: list[int] = []
    for i in range(1, len(vals) - 1):
        if vals[i] <= env.strike_level:
            continue
        if vals[i] < vals[i - 1] or vals[i] < vals[i + 1]:
            continue
        if peaks and times[i] - times[peaks[-1]] <= MIN_GAP_S:
            if vals[i] > vals[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)

    out: list[Strike] = []
    for k, i in enumerate(peaks):
        level = env.level_for(float(vals[i]))
        left = i
        while left > 0 and vals[left] > level:
            left -= 1
        right = i
        while right < len(vals) - 1 and vals[right] > level:
            right += 1
        gap = floor_before = None
        dead = None
        if k:
            prev = peaks[k - 1]
            gap = float(times[i] - times[prev])
            floor_before = float(vals[prev:i].min())
            dead = bool(floor_before < env.floor * DEAD_STOP_FACTOR)
        out.append(Strike(
            t_peak=float(times[i]), peak=float(vals[i]),
            windup=float(times[i] - times[left]),
            stop=float(times[right] - times[i]),
            gap_before=gap, floor_before=floor_before, dead_stop_before=dead))
    return out


def longest(parts: list[Segment], roles: tuple[str, ...]) -> float:
    """Самый длинный непрерывный отрезок из перечисленных режимов.

    Нужно для двух требований номера сразу: burst_3 просит 2.4 с непрерывного
    действия, финальная поза — 4.8 с неподвижности.
    """
    best = run = 0.0
    for part in parts:
        if part.role in roles:
            run += part.end - part.start
            best = max(best, run)
        else:
            run = 0.0
    return best
```

- [ ] **Шаг 4: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_segment.py -v`
Expected: PASS, 6 passed

- [ ] **Шаг 5: Коммит**

```bash
git add motion/segment.py tests/test_motion_segment.py && git commit -m "motion: три режима, удары и обрезка возни с камерой"
```

---

## Задача 4: Требования номера и сверка

**Files:**
- Create: `motion/requirements.py`
- Create: `motion/compare.py`
- Test: `tests/test_motion_compare.py`

- [ ] **Шаг 1: Написать падающий тест 7**

Создать `tests/test_motion_compare.py`:

```python
"""Тест 7 приёмки: сверка с требованиями, и что требования читаются из сценария."""

import pytest

from motion import compare, requirements

STUB = {
    "actions": [
        {"id": "a_long", "name": "оборот", "duration": 2.4, "contacts": 2,
         "no_stance": True, "hold": "НЕ стойка"},
        {"id": "a_short", "name": "встречный", "duration": 1.2, "contacts": 1,
         "no_stance": False, "hold": "стоишь"},
    ],
    "longest_stillness": 4.8,
}


def test_7_a_short_session_fails_the_long_action():
    measured = {"longest_action": 1.0, "longest_stillness": 6.0,
                "strikes": 3, "dead_stops": 0, "transitions": 2}
    verdicts = {f.what: f.verdict for f in compare.compare(measured, STUB)}
    assert verdicts["оборот 2.4 с"] == "нет"
    assert verdicts["встречный 1.2 с"] == "нет"
    assert verdicts["неподвижность 4.8 с"] == "есть"


def test_7b_a_long_session_passes_both():
    measured = {"longest_action": 2.6, "longest_stillness": 2.0,
                "strikes": 5, "dead_stops": 0, "transitions": 4}
    verdicts = {f.what: f.verdict for f in compare.compare(measured, STUB)}
    assert verdicts["оборот 2.4 с"] == "есть"
    assert verdicts["встречный 1.2 с"] == "есть"
    assert verdicts["неподвижность 4.8 с"] == "нет"


def test_7c_dead_stops_break_the_no_stance_requirement():
    measured = {"longest_action": 3.0, "longest_stillness": 5.0,
                "strikes": 4, "dead_stops": 3, "transitions": 3}
    findings = {f.what: f for f in compare.compare(measured, STUB)}
    stance = findings["переходы без стойки"]
    assert stance.verdict == "нет"
    assert "3 из 3" in stance.detail


def test_7d_no_transitions_is_not_a_failure():
    """Один удар за прогон — переходов нет, и приговора по ним тоже."""
    measured = {"longest_action": 3.0, "longest_stillness": 5.0,
                "strikes": 1, "dead_stops": 0, "transitions": 0}
    stance = {f.what: f for f in compare.compare(measured, STUB)}[
        "переходы без стойки"]
    assert stance.verdict == "нечего проверять"


def test_requirements_come_from_the_real_scenario():
    """Требования читаются из scenario/, а не из копии в анализаторе."""
    reqs = requirements.from_scenario()
    ids = {a["id"] for a in reqs["actions"]}
    assert {"burst_1", "burst_2", "burst_3", "burst_4", "spear_down"} <= ids
    burst_3 = next(a for a in reqs["actions"] if a["id"] == "burst_3")
    assert burst_3["duration"] == pytest.approx(2.4)
    assert burst_3["contacts"] >= 2, "у burst_3 в сценарии два попадания"
    assert reqs["longest_stillness"] >= 4.0
    assert any(a["no_stance"] for a in reqs["actions"]), (
        "хотя бы у одного действия в hold написано НЕ стойка")
```

- [ ] **Шаг 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_compare.py -v`
Expected: FAIL — `ImportError: cannot import name 'compare' from 'motion'`

- [ ] **Шаг 3: Написать `motion/requirements.py`**

```python
"""ЕДИНСТВЕННЫЙ модуль, знающий о номере.

Заказчик выбрал не разделять пакет и номер, и цена решения названа: в другом
проекте анализатор придётся разбирать. Чтобы цена осталась низкой, всё знание
живёт здесь. Остальные восемь модулей слова burst_3 не содержат.

Требования собираются из scenario/ каждый раз заново. Файла с копией
длительностей нет и не будет: в проекте правило — ни один таймкод не
дублируется, а копия разошлась бы с timeline.json молча.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOVEMENTS = ROOT / "scenario" / "movements.json"
STRIKES = ROOT / "scenario" / "strikes.json"

# Хореография пишет запрет прямым текстом: «после — медленный обход, разворот
# к новой стороне, НЕ стойка». Ищем эту фразу, а не догадываемся.
NO_STANCE = "НЕ стойка"

# Финальная неподвижность записана в hold текстом, а не числом. Держать её
# нужно 4.8 с — это остаток дорожки после ice_final_impact.
STILLNESS_FALLBACK = 4.8


def from_scenario(root: Path | None = None) -> dict:
    """Требования номера как обычный словарь.

    Боевые действия — те, у которых в strikes.json есть разбор по долям: у них
    номер требует конкретной длительности и конкретного числа попаданий.
    """
    base = root or ROOT
    movements = json.loads((base / "scenario" / "movements.json")
                           .read_text(encoding="utf-8"))["movements"]
    strikes = json.loads((base / "scenario" / "strikes.json")
                         .read_text(encoding="utf-8"))["strikes"]

    contacts: dict[str, int] = {}
    for strike in strikes:
        move = str(strike.get("movement", ""))
        contacts[move] = sum(1 for b in strike.get("beats", [])
                             if b.get("role") == "contact")

    actions = []
    for move in movements:
        move_id = str(move["id"])
        if move_id not in contacts:
            continue
        hold = str(move.get("hold", ""))
        actions.append({
            "id": move_id,
            "name": str(move.get("name", move_id)),
            "duration": float(move.get("duration", 0.0)),
            "contacts": int(contacts[move_id]),
            "hold": hold,
            "no_stance": NO_STANCE in hold,
        })

    stillness = STILLNESS_FALLBACK
    for move in movements:
        if move.get("id") == "final_pose":
            hold = str(move.get("hold", ""))
            for token in hold.replace(",", " ").split():
                token = token.replace("Держать", "")
                try:
                    value = float(token)
                except ValueError:
                    continue
                if 1.0 <= value <= 30.0:
                    stillness = value
                    break
    return {"actions": actions, "longest_stillness": stillness}
```

- [ ] **Шаг 4: Написать `motion/compare.py`**

```python
"""Сверка замеров с требованиями. О номере не знает ничего.

Требования приходят словарём, и слова burst_3 здесь нет: этот модуль одинаково
работает для любого номера с любым оружием.
"""

from __future__ import annotations

from dataclasses import dataclass

CLOSE = 0.85    # 85% требуемой длительности — «близко», а не «нет»


@dataclass(frozen=True)
class Finding:
    what: str
    verdict: str        # "есть" | "близко" | "нет" | "нечего проверять"
    detail: str


def compare(measured: dict, reqs: dict) -> list[Finding]:
    """Что из требований номера в этом заходе есть, а чего нет."""
    out: list[Finding] = []

    longest = float(measured.get("longest_action", 0.0))
    for action in reqs.get("actions", []):
        need = float(action["duration"])
        if longest >= need:
            verdict = "есть"
        elif longest >= need * CLOSE:
            verdict = "близко"
        else:
            verdict = "нет"
        contacts = int(action.get("contacts", 0))
        tail = f", попаданий нужно {contacts}" if contacts > 1 else ""
        out.append(Finding(
            what=f"{action['name']} {need:g} с",
            verdict=verdict,
            detail=(f"самое длинное непрерывное действие захода "
                    f"{longest:.2f} с против {need:g} с{tail}")))

    need_still = float(reqs.get("longest_stillness", 0.0))
    still = float(measured.get("longest_stillness", 0.0))
    out.append(Finding(
        what=f"неподвижность {need_still:g} с",
        verdict="есть" if still >= need_still else "нет",
        detail=f"самая длинная неподвижность захода {still:.2f} с"))

    transitions = int(measured.get("transitions", 0))
    dead = int(measured.get("dead_stops", 0))
    named = [a["name"] for a in reqs.get("actions", []) if a.get("no_stance")]
    if transitions == 0:
        verdict, detail = "нечего проверять", "переходов в заходе нет"
    elif dead == 0:
        verdict = "есть"
        detail = f"мёртвых остановок нет, переходов {transitions}"
    else:
        verdict = "нет"
        detail = (f"мёртвых остановок {dead} из {transitions}. "
                  f"Хореография запрещает стойку после: {', '.join(named)}"
                  if named else
                  f"мёртвых остановок {dead} из {transitions}")
    out.append(Finding(what="переходы без стойки", verdict=verdict,
                       detail=detail))
    return out
```

- [ ] **Шаг 5: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_compare.py -v`
Expected: PASS, 5 passed

- [ ] **Шаг 6: Коммит**

```bash
git add motion/requirements.py motion/compare.py tests/test_motion_compare.py && git commit -m "motion: требования из сценария и сверка с ними"
```

---

## Задача 5: Картинки отчёта

**Files:**
- Create: `motion/frames.py`
- Test: дополнить `tests/test_motion_video.py`

- [ ] **Шаг 1: Написать падающий тест**

Дописать в конец `tests/test_motion_video.py`:

```python
def test_strike_strip_has_four_columns(tmp_path):
    from motion import frames as mframes
    from motion.segment import Strike

    clip = video.probe(motion_clips.sweep(tmp_path / "s.mp4", fps=30,
                                          total=120, a=30, b=60))
    hit = Strike(t_peak=1.5, peak=3.0, windup=0.4, stop=0.3, gap_before=None,
                 floor_before=None, dead_stop_before=None)
    out = mframes.strike_strip(clip, hit, tmp_path / "strip.png")
    assert out.exists()
    from PIL import Image
    with Image.open(out) as img:
        assert img.width > img.height * 3, "четыре кадра в ряд"


def test_overview_sheet_is_written(tmp_path):
    from motion import frames as mframes
    clip = video.probe(motion_clips.still(tmp_path / "s.mp4", fps=30, total=120))
    out = mframes.overview_sheet(clip, tmp_path / "sheet.png")
    assert out.exists() and out.stat().st_size > 1000
```

- [ ] **Шаг 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_video.py -k strip -v`
Expected: FAIL — `ImportError: cannot import name 'frames' from 'motion'`

- [ ] **Шаг 3: Написать `motion/frames.py`**

```python
"""Картинки отчёта: полосы кадров и обзорный лист.

Прожжённое время обязательно. Без него нельзя сослаться на момент, а весь
разбор ошибок по кадрам состоит из таких ссылок.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from motion.video import Clip, still_rgb
from motion.segment import Segment, Strike

THUMB_W = 480
FONT_BOX = (0, 0, 118, 26)


def _stamp(img: Image.Image, text: str) -> Image.Image:
    """Время в углу. Шрифт по умолчанию, чтобы не тащить файл шрифта."""
    draw = ImageDraw.Draw(img)
    draw.rectangle(FONT_BOX, fill=(0, 0, 0))
    draw.text((6, 7), text, fill=(255, 220, 0))
    return img


def _thumb(clip: Clip, t: float) -> Image.Image:
    rgb = still_rgb(clip, t)
    img = Image.fromarray(rgb)
    height = max(2, round(THUMB_W * clip.height / clip.width))
    img = img.resize((THUMB_W, height))
    return _stamp(img, f"{t:6.2f}s")


def _row(images: list[Image.Image], out_path: Path) -> Path:
    width = sum(i.width for i in images)
    height = max(i.height for i in images)
    sheet = Image.new("RGB", (width, height), (0, 0, 0))
    x = 0
    for img in images:
        sheet.paste(img, (x, 0))
        x += img.width
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def strike_strip(clip: Clip, strike: Strike, out_path: Path) -> Path:
    """Четыре кадра удара: начало замаха, пик, остановка, и через 0.3 с после."""
    times = [
        max(0.0, strike.t_peak - strike.windup),
        strike.t_peak,
        min(clip.duration - 0.05, strike.t_peak + strike.stop),
        min(clip.duration - 0.05, strike.t_peak + strike.stop + 0.30),
    ]
    return _row([_thumb(clip, t) for t in times], out_path)


def handling_strip(clip: Clip, part: Segment, out_path: Path,
                   every: float = 2.0) -> Path:
    """Медленное владение: кадр каждые две секунды."""
    times = list(np.arange(part.start, min(part.end, clip.duration - 0.05),
                           every))
    if not times:
        times = [part.start]
    return _row([_thumb(clip, float(t)) for t in times[:8]], out_path)


def overview_sheet(clip: Clip, out_path: Path, columns: int = 4,
                   rows: int = 4) -> Path:
    """Обзорный лист: весь заход равномерно, чтобы видеть его целиком."""
    count = columns * rows
    step = clip.duration / (count + 1)
    thumbs = [_thumb(clip, step * (i + 1)) for i in range(count)]
    width = thumbs[0].width * columns
    height = thumbs[0].height * rows
    sheet = Image.new("RGB", (width, height), (0, 0, 0))
    for i, img in enumerate(thumbs):
        sheet.paste(img, ((i % columns) * img.width,
                          (i // columns) * img.height))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
```

- [ ] **Шаг 4: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_video.py -v`
Expected: PASS, 6 passed

- [ ] **Шаг 5: Коммит**

```bash
git add motion/frames.py tests/test_motion_video.py && git commit -m "motion: полосы кадров и обзорный лист"
```

---

## Задача 6: Слой позы

> **Эта задача требует файла модели, которого нет в пакете.** `mediapipe` 1.0.0 выкинул старый API `mp.solutions`, а 0.10.35 не содержит ни одного файла модели: проверено, `**/*.tflite`, `**/*.binarypb`, `**/*.task` — по нулю. Модель качается отдельно.
>
> **Если скачивание не согласовано — задача пропускается целиком.** Задачи 1–5 и 7–9 от неё не зависят: `session.py` вызывает `pose.available()`, получает отказ с причиной, и отчёт пишет, что слоя не было. Разбор остаётся полным, тело сужу по кадрам глазом.

**Files:**
- Create: `motion/pose.py`
- Modify: `.gitignore`
- Modify: `requirements.txt`
- Test: `tests/test_motion_pose.py`

- [ ] **Шаг 1: Получить модель**

Файл: `pose_landmarker_full.task`, около 9 МБ, источник — `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task`, официальное хранилище моделей MediaPipe от Google. Положить в `motion/models/pose_landmarker_full.task`.

- [ ] **Шаг 2: Исключить модель из гита**

Дописать в `.gitignore`:

```
# Модель позы MediaPipe: 9 МБ чужого бинарника, который скачивается одной
# командой из официального хранилища Google. В репозиторий ему не место по той
# же причине, по которой там нет купленного видео. Как получить — motion/README.md.
motion/models/
```

- [ ] **Шаг 3: Написать падающий тест**

Создать `tests/test_motion_pose.py`. Тест 8 приёмки: набор обязан быть зелёным и без модели.

```python
"""Тест 8 приёмки: слой позы необязателен, и его отсутствие не ломает набор."""

import numpy as np
import pytest

from motion import pose


def test_available_always_answers_with_a_reason():
    ok, why = pose.available()
    assert isinstance(ok, bool)
    assert why, "причина обязательна и когда всё есть, и когда нет"


def test_track_returns_none_when_the_layer_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(pose, "available", lambda: (False, "выключено в тесте"))
    from motion import video
    from tests import motion_clips
    clip = video.probe(motion_clips.still(tmp_path / "s.mp4", fps=30, total=90))
    assert pose.track(clip) is None


def test_hip_lead_reads_the_sign_correctly():
    """Бёдра раньше кистей — плюс. Позже — минус. Это весь смысл метрики."""
    fps = 30
    hips = np.zeros(60)
    wrists = np.zeros(60)
    hips[20] = 1.0          # бёдра включились на 20-м кадре
    wrists[26] = 1.0        # кисти на 26-м, то есть на 0.2 с позже
    assert pose.hip_lead(hips, wrists, fps) == pytest.approx(0.2, abs=1e-6)
    assert pose.hip_lead(wrists, hips, fps) == pytest.approx(-0.2, abs=1e-6)


@pytest.mark.skipif(not pose.available()[0], reason="модели позы нет")
def test_real_track_has_coverage_and_body_height(tmp_path):
    from motion import video
    from tests import motion_clips
    clip = video.probe(motion_clips.still(tmp_path / "s.mp4", fps=30, total=90))
    track = pose.track(clip)
    assert track is not None
    assert 0.0 <= track.coverage <= 1.0
    assert len(track.body_frac) > 0
```

- [ ] **Шаг 4: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_pose.py -v`
Expected: FAIL — `ImportError: cannot import name 'pose' from 'motion'`

- [ ] **Шаг 5: Написать `motion/pose.py`**

```python
"""Необязательный слой: суставы, рост в кадре и кинетическая цепь.

Он существует потому, что проба доказала: геометрию тела по этому материалу
арифметикой не взять. Вычитание фона проваливается трижды — медиана оказывается
самим исполнителем, автоэкспозиция красит кадр целиком, эрозия назначает палкой
торс. Поза не зависит ни от фона, ни от экспозиции.

Дисциплина покрытия. Если суставы нашлись меньше чем на 60% кадров, выводы о
теле подавляются, а покрытие называется. Это прямое следствие уже сделанной в
проекте ошибки: в shots.json моей же рукой было записано, что первый удар серии
3 совпадает с картинкой, потому что на кадре видны ледяные шипы. Шипы там
нарисованы с первого кадра. Несколько удачных кадров — не основание для вывода
обо всём прогоне.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from motion.video import Clip, still_rgb

MODEL = Path(__file__).resolve().parent / "models" / "pose_landmarker_full.task"
MIN_COVERAGE = 0.60
EVERY = 2               # каждый второй кадр: 30 замеров в секунду хватает

# Точки MediaPipe Pose, на которых держатся все замеры тела.
L_SHOULDER, R_SHOULDER = 11, 12
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_ANKLE, R_ANKLE = 27, 28


@dataclass(frozen=True)
class PoseTrack:
    times: np.ndarray           # время каждого замера
    body_frac: np.ndarray       # рост в кадре, доля высоты
    shoulder_deg: np.ndarray    # угол линии плеч
    hip_deg: np.ndarray         # угол линии бёдер
    wrist_speed: np.ndarray     # скорость середины между кистями
    hip_speed: np.ndarray       # угловая скорость линии бёдер
    stance: np.ndarray          # ширина стойки в плечах
    grip: np.ndarray            # расстояние между кистями в плечах
    coverage: float             # доля кадров, где суставы нашлись

    @property
    def trustworthy(self) -> bool:
        return self.coverage >= MIN_COVERAGE


def available() -> tuple[bool, str]:
    """Есть ли слой позы, и если нет — почему. Причина обязательна всегда."""
    try:
        import mediapipe  # noqa: F401
    except Exception as exc:
        return False, f"mediapipe не импортируется: {exc}"
    try:
        from mediapipe.tasks.python import vision  # noqa: F401
    except Exception as exc:
        return False, f"в mediapipe нет tasks.vision: {exc}"
    if not MODEL.exists():
        return False, (f"файла модели нет: {MODEL}. Как получить — "
                       "motion/README.md")
    return True, f"mediapipe и модель на месте ({MODEL.name})"


def hip_lead(hip_speed: np.ndarray, wrist_speed: np.ndarray,
             fps: float) -> float:
    """На сколько секунд бёдра опередили кисти.

    Плюс — цепь правильная: корпус разгоняет оружие. Минус или ноль — машешь
    руками, и сила идёт не из корпуса. Это и есть числовой ответ на «откуда
    идёт сила».
    """
    if hip_speed.size == 0 or wrist_speed.size == 0:
        return 0.0
    return float((int(np.argmax(wrist_speed)) - int(np.argmax(hip_speed))) / fps)


def _angle(ax, ay, bx, by) -> np.ndarray:
    return np.degrees(np.arctan2(by - ay, bx - ax))


def track(clip: Clip, every: int = EVERY) -> PoseTrack | None:
    """Суставы по всему клипу. None, если слоя нет."""
    ok, _ = available()
    if not ok:
        return None

    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision

    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_poses=1)

    step = every / clip.fps
    stamps = np.arange(0.0, max(clip.duration - 0.02, step), step)
    rows: list[list[float] | None] = []
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        for t in stamps:
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=still_rgb(clip, float(t)))
            result = landmarker.detect_for_video(image, int(t * 1000))
            if not result.pose_landmarks:
                rows.append(None)
                continue
            lm = result.pose_landmarks[0]
            rows.append([lm[i].x for i in range(33)] + [lm[i].y for i in range(33)])

    found = [r for r in rows if r is not None]
    coverage = len(found) / max(len(rows), 1)
    if not found:
        # У PoseTrack семь массивов после times, потом coverage.
        return PoseTrack(stamps, *(np.zeros(0) for _ in range(7)), 0.0)

    # Пропуски заполняются последним известным: дырка в середине замаха иначе
    # даёт разрыв скорости, которого в движении не было.
    filled: list[list[float]] = []
    last = found[0]
    for row in rows:
        last = row if row is not None else last
        filled.append(last)
    arr = np.array(filled, dtype=np.float64)
    x, y = arr[:, :33], arr[:, 33:]

    shoulder = _angle(x[:, L_SHOULDER], y[:, L_SHOULDER],
                      x[:, R_SHOULDER], y[:, R_SHOULDER])
    hip = _angle(x[:, L_HIP], y[:, L_HIP], x[:, R_HIP], y[:, R_HIP])
    shoulder_w = np.hypot(x[:, L_SHOULDER] - x[:, R_SHOULDER],
                          y[:, L_SHOULDER] - y[:, R_SHOULDER])
    shoulder_w = np.maximum(shoulder_w, 1e-6)

    top = np.minimum(y[:, L_SHOULDER], y[:, R_SHOULDER])
    bottom = np.maximum(y[:, L_ANKLE], y[:, R_ANKLE])
    body_frac = np.clip(np.abs(bottom - top) / 0.8, 0.05, 1.0)

    wrist_mid_x = (x[:, L_WRIST] + x[:, R_WRIST]) / 2.0
    wrist_mid_y = (y[:, L_WRIST] + y[:, R_WRIST]) / 2.0
    wrist_speed = np.abs(np.gradient(np.hypot(wrist_mid_x, wrist_mid_y)))
    hip_speed = np.abs(np.gradient(np.unwrap(np.radians(hip))))

    return PoseTrack(
        times=stamps[:len(arr)],
        body_frac=body_frac,
        shoulder_deg=shoulder,
        hip_deg=hip,
        wrist_speed=wrist_speed,
        hip_speed=hip_speed,
        stance=np.hypot(x[:, L_ANKLE] - x[:, R_ANKLE],
                        y[:, L_ANKLE] - y[:, R_ANKLE]) / shoulder_w,
        grip=np.hypot(x[:, L_WRIST] - x[:, R_WRIST],
                      y[:, L_WRIST] - y[:, R_WRIST]) / shoulder_w,
        coverage=coverage)
```

- [ ] **Шаг 6: Дописать `requirements.txt`**

Добавить в конец файла:

```
# Замер тренировок по видео (motion/). mediapipe нужен ТОЛЬКО слою позы: без
# него анализатор работает и отдаёт время, ритм и торможение, но не углы тела.
# Файла модели в пакете нет — как его получить, написано в motion/README.md.
# opencv-contrib-python приезжает прицепом к mediapipe и напрямую не
# используется: кадры читает FFmpeg.
mediapipe>=0.10.35
```

- [ ] **Шаг 7: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_pose.py -v`
Expected: PASS, 4 passed — либо 3 passed 1 skipped, если модели нет

- [ ] **Шаг 8: Коммит**

```bash
git add motion/pose.py tests/test_motion_pose.py requirements.txt .gitignore && git commit -m "motion: необязательный слой позы и дисциплина покрытия"
```

---

## Задача 7: Сборка прогона и отчёт

**Files:**
- Create: `motion/session.py`
- Create: `motion/report.py`
- Create: `motion/analyze.py`
- Test: `tests/test_motion_report.py`

- [ ] **Шаг 1: Написать падающий тест насквозь**

Создать `tests/test_motion_report.py`:

```python
"""Прогон насквозь на синтетике: от файла до report.md."""

import json

from motion import report, session
from tests import motion_clips


def test_session_measures_a_synthetic_clip(tmp_path):
    path = motion_clips.two_sweeps(tmp_path / "d.mp4", fps=30, dead=True)
    data = session.measure(path)
    assert data["strikes"] == 2
    assert data["transitions"] == 1
    assert data["dead_stops"] == 1
    assert data["scale_source"] in {"поза", "разброс", "нет"}
    assert data["trim"]["reason"]
    assert data["pose"]["used"] in {True, False}
    assert data["pose"]["why"]


def test_report_writes_both_files_and_names_its_limits(tmp_path):
    path = motion_clips.two_sweeps(tmp_path / "d.mp4", fps=30, dead=True)
    data = session.measure(path)
    out = report.write([data], tmp_path / "out")
    text = out.read_text(encoding="utf-8")
    assert (tmp_path / "out" / "measurements.json").exists()
    saved = json.loads((tmp_path / "out" / "measurements.json")
                       .read_text(encoding="utf-8"))
    assert saved[0]["strikes"] == 2
    # Три вещи, без которых числам верить нельзя.
    assert "нормировк" in text.lower()
    assert "обрезан" in text.lower() or "срезано" in text.lower()
    assert "поза" in text.lower()


def test_report_says_so_when_no_strikes_were_found(tmp_path):
    path = motion_clips.still(tmp_path / "s.mp4", fps=30, total=120)
    data = session.measure(path)
    assert data["strikes"] == 0
    out = report.write([data], tmp_path / "out")
    text = out.read_text(encoding="utf-8")
    assert "ударов не найдено" in text.lower()
```

- [ ] **Шаг 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_motion_report.py -v`
Expected: FAIL — `ImportError: cannot import name 'session' from 'motion'`

- [ ] **Шаг 3: Написать `motion/session.py`**

```python
"""Один прогон в один словарь. Вся склейка модулей здесь и только здесь."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from motion import envelope, frames as mframes, pose, segment, video


def measure(path: str | Path, out_frames: Path | None = None,
            pose_on: bool = True) -> dict:
    """Замерить видео целиком. Картинки пишутся, если задан out_frames."""
    clip = video.probe(path)
    gray = video.gray_frames(clip)

    track = pose.track(clip) if pose_on else None
    ok, why = pose.available()
    if not pose_on:
        why = "слой отключён ключом --no-pose"
    body = None
    if track is not None and track.trustworthy and len(track.times) > 1:
        # Поза замеряется каждый второй кадр, а огибающая живёт на кадровой
        # сетке. Без растяжения длина не сойдётся, и починка масштаба МОЛЧА
        # не применится — а именно она чинит пропуск дальних движений.
        grid = np.arange(len(gray)) / clip.fps
        body = np.interp(grid, track.times, track.body_frac)
    if track is not None and not track.trustworthy:
        why = (f"суставы нашлись на {track.coverage:.0%} кадров, порог "
               f"{pose.MIN_COVERAGE:.0%} — выводы о теле подавлены")

    env = envelope.build(gray, clip.fps, body_frac=body)
    trim = segment.camera_trim(video.band_envelope(clip), clip.fps,
                              clip.duration)
    parts = segment.segments(env, trim)
    hits = segment.strikes(env, trim)

    dead = [h for h in hits if h.dead_stop_before is True]
    pictures: dict[str, str] = {}
    if out_frames is not None:
        stem = clip.path.stem
        pictures["обзор"] = str(mframes.overview_sheet(
            clip, out_frames / f"{stem}-обзор.png").name)
        for i, hit in enumerate(hits, 1):
            name = mframes.strike_strip(
                clip, hit, out_frames / f"{stem}-удар-{i:02d}.png").name
            pictures[f"удар {i}"] = str(name)
        for i, part in enumerate([p for p in parts if p.role == "владение"], 1):
            if part.end - part.start < 2.0:
                continue
            name = mframes.handling_strip(
                clip, part, out_frames / f"{stem}-владение-{i:02d}.png").name
            pictures[f"владение {i}"] = str(name)

    return {
        "file": clip.path.name,
        "duration": round(clip.duration, 3),
        "fps": clip.fps,
        "trim": {"start": round(trim.start, 3), "end": round(trim.end, 3),
                 "reason": trim.reason},
        "scale_source": env.scale_source,
        "size_fix": env.size_fix,
        "floor": round(env.floor, 4),
        "strike_level": round(env.strike_level, 4),
        "strikes": len(hits),
        "transitions": max(len(hits) - 1, 0),
        "dead_stops": len(dead),
        "longest_action": round(segment.longest(parts, ("удар", "владение")), 3),
        "longest_stillness": round(segment.longest(parts, ("покой",)), 3),
        "windup_median": round(float(np.median([h.windup for h in hits])), 3)
                         if hits else None,
        "stop_median": round(float(np.median([h.stop for h in hits])), 3)
                       if hits else None,
        "pose": {
            "used": bool(body is not None),
            "why": why,
            "coverage": round(track.coverage, 3) if track else None,
            "hip_lead": round(pose.hip_lead(track.hip_speed,
                                            track.wrist_speed, clip.fps / 2),
                              3) if (track and track.trustworthy) else None,
            "stance_median": round(float(np.median(track.stance)), 2)
                             if (track and track.trustworthy) else None,
            "grip_median": round(float(np.median(track.grip)), 2)
                           if (track and track.trustworthy) else None,
        },
        "hits": [
            {"t_peak": round(h.t_peak, 3), "peak": round(h.peak, 3),
             "windup": round(h.windup, 3), "stop": round(h.stop, 3),
             "gap_before": round(h.gap_before, 3) if h.gap_before else None,
             "dead_stop_before": h.dead_stop_before}
            for h in hits
        ],
        "segments": [{"role": p.role, "start": round(p.start, 3),
                      "end": round(p.end, 3)} for p in parts],
        "pictures": pictures,
    }
```

- [ ] **Шаг 4: Написать `motion/report.py`**

```python
"""report.md и measurements.json.

Отчёт обязан назвать три вещи: обрезанное окно, источник нормировки и покрытие
позой. Это не украшение, а условие, при котором его числам можно верить.
"""

from __future__ import annotations

import json
from pathlib import Path

from motion import compare as mcompare
from motion import requirements


def _session_block(data: dict) -> list[str]:
    out = [f"## {data['file']}", ""]
    out += [
        f"Длина {data['duration']:.2f} с, {data['fps']} fps. "
        f"Разбирается окно {data['trim']['start']:.2f}–{data['trim']['end']:.2f} с.",
        "",
        f"- **Обрезка:** {data['trim']['reason']}",
        f"- **Нормировка:** {data['scale_source']}; масштаб внутри видео — "
        f"{data['size_fix']}",
        f"- **Поза:** {data['pose']['why']}",
        "",
    ]
    if not data["strikes"]:
        out += [
            "**Ударов не найдено.** Это не ошибка чтения: дно огибающей "
            f"{data['floor']:.3f}, порог удара {data['strike_level']:.3f}, "
            f"самое длинное непрерывное действие {data['longest_action']:.2f} с. "
            "Всё движение в этом заходе идёт ниже порога удара.",
            "",
        ]
        return out

    out += [
        f"Ударов {data['strikes']}, переходов {data['transitions']}, из них "
        f"**мёртвых остановок {data['dead_stops']}**.",
        f"Медиана замаха {data['windup_median']:.3f} с, медиана торможения "
        f"{data['stop_median']:.3f} с.",
        f"Самое длинное непрерывное действие {data['longest_action']:.2f} с, "
        f"самая длинная неподвижность {data['longest_stillness']:.2f} с.",
        "",
        "| № | пик, с | замах | торможение | пауза до | мёртвая остановка |",
        "|---|---|---|---|---|---|",
    ]
    for i, hit in enumerate(data["hits"], 1):
        gap = f"{hit['gap_before']:.2f}" if hit["gap_before"] else "—"
        dead = {True: "да", False: "нет", None: "—"}[hit["dead_stop_before"]]
        out.append(f"| {i} | {hit['t_peak']:.2f} | {hit['windup']:.3f} | "
                   f"{hit['stop']:.3f} | {gap} | {dead} |")
    out.append("")

    if data["pose"]["used"]:
        out += [
            f"- Бёдра опережают кисти на **{data['pose']['hip_lead']:+.3f} с** "
            "(минус — ведут руки, сила не из корпуса)",
            f"- Стойка {data['pose']['stance_median']:.2f} плеча, хват "
            f"{data['pose']['grip_median']:.2f} плеча",
            "",
        ]
    for name, file in data.get("pictures", {}).items():
        out.append(f"![{name}](frames/{file})")
    out.append("")
    return out


def write(sessions: list[dict], out_dir: Path,
          reqs: dict | None = None) -> Path:
    """Записать report.md и measurements.json. Возвращает путь к отчёту."""
    out_dir = Path(out_dir)
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    (out_dir / "measurements.json").write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")

    reqs = reqs if reqs is not None else requirements.from_scenario()
    lines = ["# Разбор тренировки", "",
             "Числа собраны `motion/analyze.py`. Метод и то, почему он такой, — "
             "в [проектном решении]"
             "(../../../docs/superpowers/specs/2026-08-05-motion-analyzer-design.md).",
             ""]
    for data in sessions:
        lines += _session_block(data)

    total = {
        "longest_action": max((s["longest_action"] for s in sessions),
                              default=0.0),
        "longest_stillness": max((s["longest_stillness"] for s in sessions),
                                 default=0.0),
        "strikes": sum(s["strikes"] for s in sessions),
        "transitions": sum(s["transitions"] for s in sessions),
        "dead_stops": sum(s["dead_stops"] for s in sessions),
    }
    lines += ["## Годность к прогону номера", "",
              "| требование | есть | замер |", "|---|---|---|"]
    for finding in mcompare.compare(total, reqs):
        lines.append(f"| {finding.what} | **{finding.verdict}** | "
                     f"{finding.detail} |")
    lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
```

- [ ] **Шаг 5: Написать `motion/analyze.py`**

```python
"""Точка входа.

    python motion/analyze.py                       всё новое в train/
    python motion/analyze.py --only train/a.mp4    одно видео
    python motion/analyze.py --out <папка>          куда положить
    python motion/analyze.py --no-pose             без слоя позы

Заход, для которого отчёт уже есть, не пересчитывается: следующий раз — одна
команда без аргументов.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from motion import pose, report, session, video

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "train"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Разбор тренировки по видео")
    parser.add_argument("--only", type=Path, action="append", default=None,
                        help="разобрать только эти файлы")
    parser.add_argument("--out", type=Path, default=None,
                        help="куда положить отчёт")
    parser.add_argument("--no-pose", action="store_true",
                        help="не использовать слой позы")
    parser.add_argument("--force", action="store_true",
                        help="пересчитать, даже если отчёт уже есть")
    args = parser.parse_args(argv)

    videos = sorted(args.only) if args.only else sorted(
        p for p in TRAIN.glob("*.mp4") if p.is_file())
    if not videos:
        print(f"в {TRAIN} нет ни одного mp4", file=sys.stderr)
        return 1

    out_dir = args.out or (TRAIN / "reports" / date.today().isoformat())
    if out_dir.exists() and not args.force and (out_dir / "report.md").exists():
        print(f"отчёт уже есть: {out_dir / 'report.md'}\n"
              f"пересчитать — добавить --force")
        return 0

    ok, why = pose.available()
    print(f"слой позы: {'есть' if ok and not args.no_pose else 'нет'} — {why}")

    sessions = []
    for path in videos:
        print(f"замер {path.name} ...", flush=True)
        try:
            sessions.append(session.measure(
                path, out_frames=out_dir / "frames",
                pose_on=not args.no_pose))
        except video.VideoError as exc:
            print(f"  пропущено: {exc}", file=sys.stderr)
    if not sessions:
        print("ни одно видео не прочиталось", file=sys.stderr)
        return 1

    path = report.write(sessions, out_dir)
    print(f"\nготово: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Шаг 6: Прогнать, убедиться что проходит**

Run: `python -m pytest tests/test_motion_report.py -v`
Expected: PASS, 3 passed

- [ ] **Шаг 7: Прогнать весь набор проекта**

Run: `python -m pytest -q`
Expected: PASS — 221 прежних теста плюс новые, ни одного упавшего

- [ ] **Шаг 8: Коммит**

```bash
git add motion/session.py motion/report.py motion/analyze.py tests/test_motion_report.py && git commit -m "motion: сборка прогона, отчёт и точка входа"
```

---

## Задача 8: Прогон на трёх настоящих видео и настройка порогов

**Files:**
- Create: `train/reports/2026-08-05/report.md` (генерируется)
- Create: `train/reports/2026-08-05/measurements.json` (генерируется)
- Create: `train/reports/2026-08-05/frames/*.png` (генерируется)
- Modify: `motion/envelope.py` (только если порог не сойдётся)

- [ ] **Шаг 1: Прогнать анализатор**

Run: `python motion/analyze.py`
Expected: три строки «замер ... », затем «готово: train/reports/2026-08-05/report.md»

- [ ] **Шаг 2: Сверить найденные всплески с контактным листом**

Открыть `train/reports/2026-08-05/frames/*-обзор.png` и таблицу ударов в `report.md`.

Критерий один: **найденные всплески должны совпадать с тем, что видно на обзорном листе.** Проба с порогом 0.35 без нормировки пропустила смахи в интервале 13–22 с у `video_2026-08-05_16-15-26.mp4` — там рост в кадре 69 px против 89 у ближних. Если после нормировки они по-прежнему пропущены, менять `STRIKE_FRAC` в `motion/envelope.py` с 0.35 вниз шагом 0.05 и прогонять снова, пока не сойдётся.

Известные числа пробы для сверки: у v1 медиана движения 0.00443 и максимум 0.02862, у v2 — 0.00142 и 0.01399, у v3 — 0.00739 и 0.04884. Мёртвых остановок проба насчитала 11 из 14 у v1 и 27 из 28 у v2.

- [ ] **Шаг 3: Зафиксировать порог, если он менялся**

Если `STRIKE_FRAC` изменён — дописать в его комментарий, на каком видео и по какому кадру он настроен. Значение без объяснения через месяц никому не поможет.

- [ ] **Шаг 4: Прогнать набор ещё раз**

Run: `python -m pytest -q`
Expected: PASS — смена порога не должна ломать тесты 1–6

- [ ] **Шаг 5: Коммит замеров и видео**

Видео идут в гит целиком — решение заказчика, цена названа в п. 12 проектного решения.

```bash
git add train/ && git commit -m "train: три тренировочных видео и замер по ним"
```

---

## Задача 9: Разбор, README и отчёт о состоянии

**Files:**
- Modify: `train/reports/2026-08-05/report.md` (дописать разбор)
- Create: `motion/README.md`
- Create: `docs/status/2026-08-05-training-review.md`
- Modify: `README.md`

- [ ] **Шаг 1: Прочитать кадры и дописать разбор**

Открыть все `train/reports/2026-08-05/frames/*.png` и дописать в `report.md` четыре раздела. Числа берутся из таблиц выше, а не придумываются.

1. **Владение оружием.** Хват и перехваты, стойка, откуда начинается взмах, чем он останавливается. Опираться на `stop` из таблицы и на кадры полос: третий кадр каждой полосы — это момент остановки.
2. **Годность к прогону номера.** Таблица сверки уже сгенерирована; дописать, что именно делать с каждым «нет».
3. **Ошибки по кадрам.** На каждую — ссылка на файл полосы и номер кадра в ней.
4. **Как снять следующий заход.** Заблокировать экспозицию и фокус; камера на уровне груди, а не на земле; не менять дистанцию посреди дубля; фон темнее палки; в кадре весь рост с запасом на замах; хлопок в ладоши в начале дубля как метка; возню с камерой оставлять по краям.

Обязательно сказать три вещи, которые известны заранее и не должны выглядеть открытием:
- **ни одного контакта во всём материале** — `stop` мерит, как ты сам гасишь палку, а не как её гасит препятствие, и это разная моторика;
- **палка не копьё** — масса и баланс другие, абсолютные скорости не перенесутся, переносятся тайминг, паузы и порядок включения корпуса;
- **v3 почти целиком медленное владение**, ударов там нет, и главный вопрос заказа по нему не отвечается — но это и была задача съёмки.

- [ ] **Шаг 2: Написать `motion/README.md`**

```markdown
# Анализатор движений

Замер тренировки по видео: время, ритм, торможение, переходы между ударами.
Проектное решение и объяснение метода — в
[docs/superpowers/specs/2026-08-05-motion-analyzer-design.md](../docs/superpowers/specs/2026-08-05-motion-analyzer-design.md).

## Запуск

    python motion/analyze.py                       всё новое в train/
    python motion/analyze.py --only train/a.mp4    одно видео
    python motion/analyze.py --no-pose             без слоя позы
    python motion/analyze.py --force               пересчитать поверх отчёта

Отчёт кладётся в `train/reports/<дата>/`: `report.md`, `measurements.json` и
`frames/`. Заход, у которого отчёт уже есть, не пересчитывается.

## Что означают числа

| поле | смысл |
|---|---|
| `windup` | от 10% до пика — длина замаха |
| `stop` | от пика до 10% — чем ты останавливаешь палку |
| `gap_before` | пауза до предыдущего удара |
| `dead_stop_before` | дно паузы упало до уровня покоя, то есть ты встал в стойку |
| `longest_action` | самое длинное непрерывное действие |
| `longest_stillness` | самая длинная неподвижность |
| `hip_lead` | бёдра опередили кисти, с. Минус — сила идёт не из корпуса |

Три поля, без которых числам верить нельзя, и отчёт называет их всегда:
`trim.reason` (что срезано), `scale_source` и `size_fix` (какая нормировка),
`pose.why` (был ли слой позы и почему нет).

## Слой позы

Необязателен. Без него анализатор отдаёт время, ритм и торможение, но не углы
тела. Нужен `mediapipe` (в `requirements.txt`) и файл модели, которого в пакете
нет:

    motion/models/pose_landmarker_full.task

Скачивается из официального хранилища моделей MediaPipe:
`https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task`
(около 9 МБ). Папка `motion/models/` в репозиторий не попадает.

Если суставы нашлись меньше чем на 60% кадров, выводы о теле подавляются, а
покрытие называется в отчёте. Несколько удачных кадров — не основание для
вывода обо всём прогоне.

## Чего здесь нет намеренно

**Модели фона.** Она проваливается на этом материале трижды: медиана по времени
оказывается самим исполнителем, когда он стоит на месте; автоэкспозиция
телефона красит кадр целиком; эрозия назначает палкой торс. Разница соседних
кадров ни одного из этих провалов не имеет. Замер, который это показал, — в
п. 2 проектного решения.

**Звука как источника тайминга.** Палка на этих скоростях не свистит: верхняя
полоса стоит на −60 dB и подскакивает только когда трогают камеру. Звук
используется ровно для одного — отрезать возню с камерой по краям.
```

- [ ] **Шаг 3: Дописать раздел в корневой `README.md`**

Найти оглавление разделов и добавить рядом с описанием тренажёра:

```markdown
### Анализатор движений

`motion/` — замер тренировки по видео: удары, замах, торможение, переходы,
мёртвые остановки. Запуск одной командой:

    python motion/analyze.py

Отчёты по заходам лежат в `train/reports/<дата>/`. Как это работает и почему
именно так — [motion/README.md](motion/README.md) и
[проектное решение](docs/superpowers/specs/2026-08-05-motion-analyzer-design.md).
```

- [ ] **Шаг 4: Написать отчёт о состоянии**

Создать `docs/status/2026-08-05-training-review.md` в стиле остальных файлов этой папки: что заказано, что проба сломала до проектирования, какие числа получились на трёх видео, что из требований номера есть и чего нет, что осталось открытым. Ссылка на `train/reports/2026-08-05/report.md` за подробностями.

- [ ] **Шаг 5: Прогнать набор последний раз**

Run: `python -m pytest -q`
Expected: PASS, ни одного упавшего

- [ ] **Шаг 6: Коммит**

```bash
git add motion/README.md README.md docs/status/2026-08-05-training-review.md train/reports/ && git commit -m "motion: разбор первого захода, README и отчёт"
```

---

## Самопроверка плана

**Покрытие проектного решения.** Каждый раздел документа отражён:

| раздел решения | задача |
|---|---|
| п. 2 четыре починки | задача 2, тесты 1–4 |
| п. 4 определения порогов | задача 2 (`FLOOR_PCT`, `STRIKE_FRAC`, `SMOOTH_S`), задача 3 (`HANDLING_MIN_S`, `DEAD_STOP_FACTOR`, `TRIM_DB`, `TRIM_EDGE_S`) |
| п. 5 одиннадцать файлов | задачи 1–7 |
| п. 6 поток данных | задача 7, `session.measure` |
| п. 7 поля на удар и на прогон | задача 3 (`Strike`), задача 7 (словарь) |
| п. 7 сверка с номером | задача 4 |
| п. 8 обработка ошибок | задача 1 (короткое видео, нет дорожки), задача 6 (покрытие позой), задача 7 (ударов не найдено) |
| п. 9 папка захода | задача 5 и 7 |
| п. 10 восемь тестов приёмки | 1–4 задача 2, 5–6 задача 3, 7 задача 4, 8 задача 6 |
| п. 11 как снять следующий заход | задача 9 шаг 1 |
| п. 13 что известно заранее | задача 9 шаг 1 |
| п. 14 порядок работ | порядок задач |

**Согласованность имён.** `Envelope.floor`/`strike_level`/`scale_source`/`size_fix`/`level_for` — задачи 2, 3, 7. `Strike.t_peak`/`windup`/`stop`/`gap_before`/`floor_before`/`dead_stop_before` — задачи 3, 5, 7. `Trim.start`/`end`/`reason` — задачи 3, 7. `PoseTrack.body_frac`/`coverage`/`trustworthy`/`hip_speed`/`wrist_speed`/`stance`/`grip` — задачи 6, 7. `Finding.what`/`verdict`/`detail` — задачи 4, 7. `video.probe`/`gray_frames`/`band_envelope`/`still_rgb`/`Clip`/`VideoError` — задачи 1, 3, 5, 6, 7. `requirements.from_scenario` — задачи 4, 7.

**Что план сознательно оставляет открытым.** `STRIKE_FRAC` настраивается в задаче 8 по критерию «найденные всплески совпадают с обзорным листом». Это не заглушка: значение 0.35 работает, критерий проверки назван, и в задаче 8 есть шаг зафиксировать причину, если он изменится.
