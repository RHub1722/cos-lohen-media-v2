"""Процедурный видеофон для LED-экрана.

    python src/render_video.py                 полный рендер + мукс со звуком
    python src/render_video.py --stills        только кадры-образцы, без видео
    python src/render_video.py --width 3840 --height 1080     другой экран

Кадры не рисуются в PNG и не собираются потом: сырой RGB уходит в FFmpeg через
трубу. Отклонение от плана намеренное — полторы тысячи PNG в 1080p это гигабайт
промежуточных файлов и втрое дольше при том же результате. Посмотреть картинку
глазами всё равно нужно, для этого есть `--stills`.

Ничего не анимируется «по секундомеру»: все три состояния и все одиннадцать
якорей приходят из `scenario/timeline.json` через `video_plan`. Сдвинулась
реплика — картинка едет за ней после перерендера, руками ничего не правится.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Консоль Windows по умолчанию в cp1252 и падает на кириллице в выводе.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.footage import FootageSource, load_shots, missing, resolve  # noqa: E402
from src.measure import measure_duration  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.video_plan import VideoPlan, build_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# --- Предохранитель ----------------------------------------------------------
# Исполнитель стоит перед экраном, передний свет организаторы не подтвердили.
# Яркий фон за спиной превращает костюм в силуэт, а костюм — главный критерий
# судей. Центральная полоса гасится всегда: во всех трёх состояниях и поверх
# любой вспышки, включая белую. Исключений нет ни одного, иначе они найдутся
# ровно в тот кадр, где исполнитель стоит неподвижно.
SAFE_STRIP = 0.40   # доля ширины кадра
SAFE_FLOOR = 0.30   # во сколько раз гасим; план требует не выше 0.35
SAFE_RAMP = 0.14    # плавный подъём ЗА пределами полосы, а не внутри неё

# --- Палитра -----------------------------------------------------------------
BLUE = np.array([0.30, 0.56, 1.00], dtype=np.float32)    # допросная
RED = np.array([1.00, 0.17, 0.09], dtype=np.float32)     # бой, тёмная масса
EMBER = np.array([1.00, 0.62, 0.30], dtype=np.float32)   # бой, ядра следов
ICE = np.array([0.66, 0.86, 1.00], dtype=np.float32)     # лёд

CRACK_SEED = 4700
GRAIN_SEED = 20260802


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def safety_row(
    width: int,
    strip: float = SAFE_STRIP,
    floor: float = SAFE_FLOOR,
    ramp: float = SAFE_RAMP,
) -> np.ndarray:
    """Множитель яркости по горизонтали: центр тёмный, края нетронуты.

    Плавный подъём вынесен ЗА пределы полосы намеренно. Если размазать его
    внутрь, заявленные сорок процентов ширины окажутся тёмными только в самой
    середине, а по краям полосы фон снова начнёт выедать силуэт — то есть
    предохранитель будет отчитываться о работе, не работая.
    """
    x = np.abs(np.linspace(-1.0, 1.0, width, dtype=np.float32))
    t = np.clip((x - strip) / ramp, 0.0, 1.0)
    return (floor + (1.0 - floor) * (t * t * (3.0 - 2.0 * t))).astype(np.float32)


class Canvas:
    """Всё, что не зависит от времени, считается один раз при запуске.

    Полторы тысячи кадров умножают любую забытую здесь операцию на полторы
    тысячи, поэтому в кадре остаётся только то, что реально меняется.
    """

    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        rng = np.random.default_rng(GRAIN_SEED)

        self.X = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
        self.Y = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
        ar = width / height
        self.R = (
            np.sqrt((self.X * ar) ** 2 + self.Y**2) / float(np.hypot(ar, 1.0))
        ).astype(np.float32)

        self.safe = safety_row(width)[None, :]

        # Статичный дизер. Тёмные синие градиенты на восьми битах полосят, а на
        # большом экране полосы видно из любой точки зала. Шум один и тот же во
        # всех кадрах: так он не мерцает и почти ничего не стоит кодеку.
        self.dither = (
            (rng.random((height, width, 1), dtype=np.float32) - 0.5) / 255.0
        ).astype(np.float32)

        self.dust = self._specks(rng, 0.99880, 1.6)
        self.dust_far = self._specks(rng, 0.99940, 2.6)
        # Угли крупные и редкие: мелкая крошка с десятого метра зала
        # превращается в ровную дымку и не читается вообще.
        self.embers = self._specks(rng, 0.999955, max(4.0, width / 240.0))

        self.base_interrogation = self._interrogation_base()
        self.door = self._door_fields()
        self.proj = self._projections()
        self.crack, self.crack_birth, self.bloom, self.bloom_birth = self._cracks()
        self.base_ice = self._ice_base()

    # -- статичные слои -------------------------------------------------------

    def _specks(self, rng, cut: float, sigma: float) -> np.ndarray:
        field = (rng.random((self.h, self.w), dtype=np.float32) > cut).astype(np.float32)
        blurred = gaussian_filter(field, sigma=sigma)
        peak = float(blurred.max())
        return (blurred / peak).astype(np.float32) if peak > 0 else blurred

    def _interrogation_base(self) -> np.ndarray:
        """Допросная: одна лампа сверху, два пятна на боковых стенах, чёрный пол.

        Середина кадра тёмная ещё до предохранителя — так и должно быть в
        допросной, и заодно предохранителю в этом состоянии почти нечего гасить.
        """
        x, y = self.X, self.Y
        lamp = 0.17 * np.exp(-((y + 1.0) ** 2) / 0.05)
        walls = (
            0.52
            * np.exp(-((np.abs(x) - 0.74) ** 2) / 0.075)
            * np.exp(-((y + 0.40) ** 2) / 0.80)
        )
        base = 0.026 + lamp + walls
        base = base * (1.0 - 0.55 * smoothstep(0.55, 1.05, self.R))
        return base.astype(np.float32)

    def _door_fields(self) -> dict[str, np.ndarray | float]:
        """Геометрия дверного проёма. Считается один раз: дверь не двигается.

        Проём стоит слева от центра намеренно. В середине кадра его съел бы
        предохранитель, а сбоку получается то, что и нужно по сцене: свет и
        враги приходят к нему со стороны, а сам он остаётся в тени.
        """
        x0, y0 = -0.62, 0.10
        dx = (self.X - x0) * (self.w / self.h)
        dy = self.Y - y0
        return {
            "x0": x0,
            "y0": y0,
            "r": np.sqrt(dx**2 + dy**2).astype(np.float32),
            # Угол от проёма. Нужен, чтобы свет расходился конусом, а не шаром.
            "ang": np.arctan2(dy, np.maximum(dx, 1e-4)).astype(np.float32),
            "inside": (self.X > x0 - 0.02).astype(np.float32),
        }

    def _projections(self) -> list[np.ndarray]:
        """Три фиксированных направления следов движения.

        Направление меняется не плавно, а рывком на каждом попадании: удар
        разворачивает поле. Плавный поворот пришлось бы пересчитывать каждый
        кадр, а рывок — это три заранее посчитанных массива.
        """
        out = []
        for angle in (-0.62, 0.51, -0.22):
            p = self.X * float(np.cos(angle)) + self.Y * float(np.sin(angle))
            out.append(np.ascontiguousarray(p, dtype=np.float32))
        return out

    def _cracks(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Трещины расходятся от нижнего центра — от точки удара копья в пол.

        Точка удара приходится на затемнённую полосу, и это правильно: лёд
        рождается за спиной исполнителя и уходит из тени в свет.
        """
        w, h = self.w, self.h
        img = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(img)
        origin = (w * 0.5, h * 0.995)
        span = float(np.hypot(w, h))
        rng = np.random.default_rng(CRACK_SEED)
        segments: list[tuple[float, float, float, float, float, float]] = []

        def grow(x, y, angle, dist, width, depth):
            for _ in range(int(rng.integers(6, 13))):
                step = span * float(rng.uniform(0.035, 0.075))
                angle += float(rng.normal(0.0, 0.16))
                nx = x + float(np.cos(angle)) * step
                ny = y + float(np.sin(angle)) * step
                segments.append((x, y, nx, ny, dist, width))
                x, y, dist = nx, ny, dist + step
                if dist > span * 1.05:
                    return
                width *= 0.88
                if depth < 2 and rng.random() < 0.32:
                    branch = angle + float(rng.choice([-1.0, 1.0])) * float(
                        rng.uniform(0.40, 0.95)
                    )
                    grow(x, y, branch, dist, width * 0.62, depth + 1)

        # Углы в экранных координатах: y растёт вниз, поэтому «вверх» это
        # промежуток от 180 до 360 градусов. Веер идёт от почти горизонтали
        # влево через вертикаль до почти горизонтали вправо.
        for angle in np.linspace(np.pi * 1.06, np.pi * 1.94, 13):
            grow(origin[0], origin[1], float(angle), 0.0, max(2.0, w / 380.0), 0)

        # Дальние сегменты рисуются первыми. На пересечениях пиксель должен
        # запомнить ближнюю к удару трещину, иначе ветка проявится раньше
        # ствола, из которого выросла.
        for x0, y0, x1, y1, dist, width in sorted(segments, key=lambda s: -s[4]):
            value = 1 + int(254 * min(dist / (span * 1.05), 1.0))
            draw.line((x0, y0, x1, y1), fill=value, width=max(1, int(round(width))))

        raw = np.asarray(img, dtype=np.float32)
        mask = (raw > 0).astype(np.float32)
        # Незанятым пикселям ставим 2.0: они не проявятся никогда, потому что
        # рост доходит только до 1.15.
        birth = np.where(raw > 0, (raw - 1.0) / 254.0, 2.0).astype(np.float32)

        sigma = max(3.0, w / 260.0)
        bloom = gaussian_filter(mask, sigma=sigma)
        peak = float(bloom.max())
        if peak > 0:
            bloom = bloom / peak
        # Средний возраст трещин в окрестности. Позволяет проявлять свечение
        # синхронно с самими трещинами, не размывая маску заново каждый кадр.
        near = gaussian_filter(mask * np.minimum(birth, 1.0), sigma=sigma)
        norm = gaussian_filter(mask, sigma=sigma)
        bloom_birth = np.where(norm > 1e-6, near / np.maximum(norm, 1e-6), 2.0)

        return (
            mask,
            birth,
            bloom.astype(np.float32),
            bloom_birth.astype(np.float32),
        )

    def _ice_base(self) -> np.ndarray:
        """Замёрзшая комната. Тёмная: весь белый цвет живёт в трещинах.

        Тринадцать секунд ровного белого поля за спиной неподвижного человека —
        это гарантированный силуэт, и предохранителя одного тут мало. Поэтому
        фон ледяного блока темнее боевого, а «льдисто-белое» набирается
        свечением трещин, которое расходится по краям кадра.
        """
        y = self.Y
        base = 0.038 + 0.055 * np.exp(-((y + 0.85) ** 2) / 0.9)
        base = base * (1.0 - 0.45 * smoothstep(0.60, 1.10, self.R))
        return base.astype(np.float32)

    # -- состояния ------------------------------------------------------------

    def interrogation(self, t: float, local: float) -> np.ndarray:
        # Комната дышит очень медленно: без этого кадр читается как фотография
        # и зал перестаёт на него смотреть уже к пятой секунде.
        breath = 1.0 + 0.055 * float(np.sin(2.0 * np.pi * local / 7.3))
        luma = self.base_interrogation * np.float32(breath)

        drift = int(local * 9.0) % self.h
        far = int(local * 3.5) % self.h
        dust = np.roll(self.dust, drift, axis=0) + 0.55 * np.roll(self.dust_far, far, axis=0)
        # Пыль видна только там, где есть свет: в темноте ей нечего отражать.
        luma = luma + dust * self.base_interrogation * 2.6

        return luma[:, :, None] * BLUE[None, None, :]

    def combat(self, t: float, local: float, flashes_passed: int) -> np.ndarray:
        """Между вспышками — ровный жар, вся сила отдана четырём попаданиям.

        Тот же принцип, по которому нарезана хореография: действие идёт
        вспышками, а не потоком. Яркий непрерывный узор соревновался бы с
        исполнителем все двадцать пять секунд и выел бы костюм — а костюм
        судят. Но и в чёрный уходить нельзя: под самую громкую музыку номера
        погасший экран читается как поломка, и бой оказался бы тусклее допроса.
        Фон держится примерно на уровне ледяного блока, попадания дают ×7.
        """
        pulse = 0.5 + 0.5 * float(np.sin(2.0 * np.pi * local / 3.1))

        # Тонкие частые следы: с десятого метра это фактура, а не рисунок.
        # Радиус подмешан в фазу, чтобы полосы выгибались. Ровная косая
        # штриховка на весь экран читается как обои, а не как движение.
        proj = self.proj[flashes_passed % len(self.proj)]
        wave = np.sin(proj * 24.0 + self.R * 6.0 + local * 8.5)
        np.maximum(wave, 0.0, out=wave)
        wave *= wave
        wave *= wave
        # Уровень выше, чем кажется нужным на глаз в цифрах: густой красный при
        # том же значении перцептивно темнее синего почти вдвое (по Rec.709
        # 0.34 против 0.54). Без поправки бой выходил темнее допроса — то есть
        # ровно наоборот тому, что должно происходить в номере.
        luma = 0.125 + 0.065 * pulse + 0.32 * wave

        # Жар снизу, как от пола, и медленно поднимающиеся угли.
        sparks = np.roll(self.embers, -int(local * 95.0) % self.h, axis=0)
        luma = luma + (0.27 + 0.10 * pulse) * np.exp(-((self.Y - 1.0) ** 2) / 0.55)
        luma = luma + sparks * 0.45

        luma = luma * (1.0 - 0.45 * smoothstep(0.55, 1.10, self.R))

        # Угли считаются горячими наравне со следами: в чистом красном они
        # выглядят россыпью точек, а не искрами.
        hot = np.clip(wave * 1.4 + sparks * 2.2, 0.0, 1.0)[:, :, None]
        colour = RED[None, None, :] * (1.0 - hot) + EMBER[None, None, :] * hot
        return luma[:, :, None] * colour

    def breach(self, local: float) -> np.ndarray:
        """Пролом двери: тёмная комната, проём, свет из него, входящие силуэты.

        Единственный кадр номера, который обязан не создавать настроение, а
        сообщать факт: в комнату вломились. Поэтому здесь узнаваемая форма —
        подсвеченный проём и тёмные фигуры в нём, — а не фактура. С десятого
        метра в тёмном зале это читается как вторжение именно потому, что силуэт
        человека в светящейся двери опознаётся мгновенно, без деталей.

        Работает, когда на месте `base/breach.mp4` файла нет. Снятый или
        сгенерированный клип его заменит, но зависимости от чужого сервиса,
        оплаты и гео-блока здесь нет.
        """
        door = self.door
        x0 = float(door["x0"])
        r, ang, inside = door["r"], door["ang"], door["inside"]

        # 1. Створка. Первые 0.35 с проём раскрывается от щели до полной ширины.
        opening = smoothstep(0.0, 0.35, np.float32(local))
        half = 0.035 + 0.115 * float(opening)
        frame_x = 1.0 - smoothstep(half * 0.75, half, np.abs(self.X - x0))
        frame_y = (1.0 - smoothstep(0.50, 0.60, np.abs(self.Y - 0.10) / 0.72))
        doorway = frame_x * frame_y

        # 2. Удар. Два кадра резкой засветки по контуру — это выбитая створка.
        kick = float(np.exp(-local / 0.09)) if local < 0.5 else 0.0

        # 3. Свет из коридора. Конус вправо, растёт и упирается в дальнюю стену.
        reach = 0.35 + 1.9 * smoothstep(0.05, 1.1, np.float32(local))
        cone = np.exp(-((ang / 0.62) ** 2)) * inside
        spill = cone * np.exp(-r / reach) * (0.55 + 0.45 * float(opening))

        luma = 0.030 + doorway * (1.05 + 2.2 * kick) + spill * 0.85
        luma = luma + kick * 0.30 * frame_y

        # 4. Пыль в луче: без неё свет выглядит нарисованной заливкой.
        dust = np.roll(self.dust, int(local * 26.0) % self.h, axis=0)
        luma = luma + dust * spill * 3.0

        # 5. Входящие. Уходят от проёма недалеко: силуэт читается, пока он на
        # просвет. Отойдя в тёмную часть кадра, фигура превращается в пятно.
        # Размеры и шаг у всех трёх разные — три одинаковые фигуры на равном
        # расстоянии читаются как узор, а не как люди.
        blocked = np.zeros_like(luma)
        for born, reach_i, size, lift in (
            (0.55, 0.30, 1.00, 0.00),
            (0.95, 0.17, 0.88, 0.04),
            (1.40, 0.42, 0.94, -0.03),
        ):
            if local < born:
                continue
            walk = smoothstep(0.0, 1.4, np.float32(local - born))
            scale = size * (0.62 + 0.42 * float(walk))
            cx = x0 - 0.02 + reach_i * float(walk)
            blocked = np.maximum(blocked, self._figure(cx, 0.20 + lift, scale))
        luma = luma * (1.0 - 0.94 * blocked)

        luma = luma * (1.0 - 0.35 * smoothstep(0.75, 1.25, self.R))

        # Свет из коридора тёплый, комната остаётся холодной: контраст двух
        # источников сам рисует границу между «здесь» и «оттуда».
        warm = np.array([1.00, 0.74, 0.45], dtype=np.float32)
        heat = np.clip((doorway + spill) * 1.5, 0.0, 1.0)[:, :, None]
        colour = RED[None, None, :] * (1.0 - heat) + warm[None, None, :] * heat
        return luma[:, :, None] * colour

    def _figure(self, cx: float, cy: float, scale: float) -> np.ndarray:
        """Силуэт человека: голова, корпус, две ноги.

        Ног и ширины корпуса не избежать. Одна вытянутая капля с головой сверху
        читается как кегля, а не как человек: узнаваемость силуэта держится на
        пропорции плеч к росту и на разрыве между ногами, а не на деталях,
        которых с десятого метра всё равно не видно.
        """
        ar = self.w / self.h
        bx = (self.X - cx) * ar

        def blob(ox: float, oy: float, hw: float, hh: float) -> np.ndarray:
            return 1.0 - smoothstep(0.82, 1.0, np.sqrt(
                ((bx - ox * scale) / (hw * scale)) ** 2
                + ((self.Y - cy - oy * scale) / (hh * scale)) ** 2))

        # Голова заходит на корпус намеренно: при зазоре между ними силуэт
        # читается как две отдельные фигуры, а не как человек с шеей. Плечи
        # вынесены отдельным широким блоком — один эллипс на весь корпус даёт
        # колокол, широкий по центру, а у человека шире всего именно плечи.
        parts = (
            blob(0.000, -0.470, 0.052, 0.070),   # голова
            blob(0.000, -0.330, 0.116, 0.080),   # плечи
            blob(0.000, -0.170, 0.088, 0.230),   # корпус
            blob(-0.046, 0.240, 0.040, 0.230),   # левая нога
            blob(0.048, 0.240, 0.040, 0.230),    # правая нога
        )
        out = parts[0]
        for part in parts[1:]:
            out = np.maximum(out, part)
        return out.astype(np.float32)

    def ice(self, t: float, local: float) -> np.ndarray:
        # Рост быстрый в первую секунду и почти останавливается к третьей:
        # разряд бьёт мгновенно, дальше лёд только доползает.
        growth = 1.15 * (1.0 - float(np.exp(-local / 0.72)))

        alpha = np.clip((growth - self.crack_birth) * 20.0, 0.0, 1.0) * self.crack
        glow = np.clip((growth - self.bloom_birth) * 8.0, 0.0, 1.0) * self.bloom

        # Свет продолжает медленно идти по трещинам наружу от точки удара.
        # Без этого ледяной кадр застывает уже на 48.75 и якорю freeze нечего
        # останавливать: последние одиннадцать секунд номера превратились бы в
        # одну фотографию, а остановка движения — это его смысловая точка.
        shimmer = 1.0 + 0.17 * np.sin(local * 1.05 - self.crack_birth * 7.0)
        breath = 1.0 + 0.10 * float(np.sin(local * 0.62))

        luma = self.base_ice + alpha * (0.78 * shimmer) + glow * (0.46 * breath)

        # Иней ползёт от нижнего края вместе с трещинами.
        frost_edge = -1.0 + 2.2 * min(growth, 1.0)
        frost = smoothstep(frost_edge + 0.5, frost_edge - 0.35, self.Y)
        luma = luma + frost * 0.055

        # Первые полсекунды — сам разряд.
        burst = float(np.exp(-local / 0.20)) if local < 1.2 else 0.0
        if burst > 0.002:
            luma = luma + burst * (0.35 + 0.9 * self.bloom)

        return luma[:, :, None] * ICE[None, None, :]


# --- сборка кадра ------------------------------------------------------------


def animation_time(plan: VideoPlan, t: float) -> float:
    """Время для анимации. Отличается от реального в двух местах номера.

    На 42.8 он получает удар и не реагирует — картинка в этот момент тоже
    перестаёт двигаться, чтобы зал смотрел на него, а не на фон. На 55.2
    движение останавливается насовсем: последние секунды исполнитель держит
    позу, и единственное, что должно шевелиться в зале, — ничего.
    """
    t_anim = t
    for cue in plan.cues:
        if cue.kind == "freeze" and cue.t <= t:
            t_anim = min(t_anim, cue.t)
        elif cue.kind == "whiteflash" and cue.t <= t < cue.end:
            t_anim = min(t_anim, cue.t)
    return t_anim


def render_frame(canvas: Canvas, plan: VideoPlan, t: float, fps: int,
                 source=None) -> np.ndarray:
    # Замирает только рисование состояния. Якоря живут по настоящему времени:
    # если считать их фазу по замороженному, белая вспышка залипнет на первом
    # своём кадре и вместо двух кадров света даст почти секунду белого поля.
    t_anim = animation_time(plan, t)
    seg = plan.segment_at(t)
    local = t_anim - seg.start
    flash_order = {
        c.source: i for i, c in enumerate(c for c in plan.cues if c.kind == "flash")
    }

    # Нижний слой: снятый материал, если он на это место положен. Клипа нет —
    # работает процедурный фон, и номер всё равно собирается целиком. Так клипы
    # можно докладывать по одному, каждый раз получая готовый файл, а не ждать
    # полного комплекта.
    rgb = source.base(t) if source is not None else None
    if rgb is None and source is not None:
        # Место может требовать не палитру состояния, а свой генератор. Пролом
        # двери — именно такое место: единственный кадр, который обязан
        # объяснять, и единственный, которого на стоке почти не бывает.
        kind, local_shot = source.procedural_at(t)
        if kind == "breach":
            rgb = canvas.breach(local_shot)
    if rgb is None:
        if seg.state == "interrogation":
            rgb = canvas.interrogation(t_anim, local)
        elif seg.state == "combat":
            passed = sum(1 for c in plan.cues if c.kind == "flash" and c.t <= t)
            rgb = canvas.combat(t_anim, local, passed)
        else:
            rgb = canvas.ice(t_anim, local)

    # Рисованные эффекты ложатся до якорей, а не после: сжатие кадра, спад
    # цвета и белая вспышка должны действовать и на них тоже, иначе слэш
    # окажется единственным, что живёт своей жизнью.
    if source is not None:
        rgb = source.overlay(t, rgb)

    for cue in plan.cues:
        phase = cue.phase(t)
        if phase is None:
            continue
        if (cue.kind == "flash" and source is not None
                and source.has_fx(cue.source)):
            # На этом ударе уже лежит рисованный слэш. Процедурная вспышка
            # поверх него читается как двойной удар и как ошибка сборки.
            continue

        if cue.kind == "tighten":
            # Кадр закрывается к центру вместе с тиканьем перед выстрелом.
            # Множители выкручены сильнее, чем сама intensity: якорь задаёт,
            # насколько сжимать, а насколько это заметно — дело рендерера, и
            # незаметное сжатие не стоит шести секунд экранного времени.
            k = cue.intensity * phase
            rgb = rgb * (1.0 - 1.6 * k * smoothstep(0.10, 0.85, canvas.R))[:, :, None]
            rgb = rgb * (1.0 - 0.45 * k)

        elif cue.kind == "drain":
            # Цвет уходит из боя перед ледяным блоком.
            k = cue.intensity * phase
            grey = rgb.mean(axis=2, keepdims=True)
            rgb = (rgb * (1.0 - k) + grey * k) * (1.0 - 0.35 * k)

        elif cue.kind == "flash":
            # Попадание видно как форма, а не как скачок яркости: полоса света
            # проходит кадр насквозь под углом этого удара, а от центра
            # расходится ударная волна. Угол у каждой из четырёх вспышек свой —
            # четыре одинаковые засветки зал перестал бы различать уже на
            # второй.
            env = float(np.exp(-phase * 4.5))
            level = cue.intensity * env
            proj = canvas.proj[flash_order[cue.source] % len(canvas.proj)]
            slash = np.exp(-(((proj - (-1.25 + 2.5 * phase)) / 0.20) ** 2))
            ring = np.exp(-(((canvas.R - 0.05 - 1.7 * phase) / 0.13) ** 2))
            hit = level * (1.25 * slash + 0.75 * ring)
            rgb = rgb + hit[:, :, None] * EMBER[None, None, :]
            rgb = rgb + level * 0.10

        elif cue.kind == "whiteflash":
            # Два белых кадра, потом провал: цвет и яркость возвращаются к концу
            # якоря. Это ровно та пауза, в которую он поворачивает голову назад.
            white_frames = 2.0 / (cue.end - cue.t) / fps
            if phase < white_frames:
                rgb = rgb * 0.15 + cue.intensity * 0.95
            else:
                p = (phase - white_frames) / max(1e-6, 1.0 - white_frames)
                stun = cue.intensity * (1.0 - smoothstep(0.45, 1.0, np.float32(p)))
                grey = rgb.mean(axis=2, keepdims=True)
                rgb = (rgb * (1.0 - stun) + grey * stun) * (1.0 - 0.55 * stun)

        elif cue.kind == "freeze":
            # Затухание короткое намеренно. Последний удар должен вспыхнуть и
            # погаснуть, а не гореть: за ним идут почти пять секунд, которые
            # исполнитель стоит неподвижно в финальной позе, и это худшее место
            # во всём номере, чтобы держать за его спиной свет.
            env = float(np.exp(-(t - cue.t) / 0.22))
            if env > 0.004:
                rgb = rgb + (cue.intensity * env * (0.18 + 0.75 * canvas.bloom))[
                    :, :, None
                ] * ICE[None, None, :]

    # Предохранитель применяется последним и без условий: ни одно состояние и
    # ни один якорь не может его обойти.
    rgb = rgb * canvas.safe[:, :, None]
    return rgb


def to_bytes(canvas: Canvas, rgb: np.ndarray) -> np.ndarray:
    out = np.clip(rgb + canvas.dither, 0.0, 1.0) * 255.0 + 0.5
    return out.astype(np.uint8)


# --- запуск ------------------------------------------------------------------


def still_times(plan: VideoPlan) -> list[tuple[float, str]]:
    """Моменты, которые надо посмотреть глазами перед полным рендером."""
    marks: list[tuple[float, str]] = []
    for seg in plan.segments:
        marks.append((seg.start + 0.05, f"{seg.state}-начало"))
        marks.append(((seg.start + seg.end) / 2.0, f"{seg.state}-середина"))
    for cue in plan.cues:
        marks.append((cue.t + 0.04, f"{cue.kind}-{cue.source}"))
        marks.append(((cue.t + cue.end) / 2.0, f"{cue.kind}-{cue.source}-середина"))
        if cue.end - cue.t > 1.0:
            marks.append((cue.end - 0.05, f"{cue.kind}-{cue.source}-конец"))
    marks.append((plan.total - 0.04, "последний-кадр"))
    return sorted(set(marks))


def write_stills(canvas: Canvas, plan: VideoPlan, fps: int, out_dir: Path,
                 source=None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = still_times(plan)
    thumbs = []
    for t, label in shots:
        frame = to_bytes(canvas, render_frame(canvas, plan, t, fps, source))
        image = Image.fromarray(frame, mode="RGB")
        image.save(out_dir / f"{t:06.2f}-{label}.png")
        thumbs.append((image.resize((384, int(384 * canvas.h / canvas.w))), f"{t:.2f} {label}"))

    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    tw, th = thumbs[0][0].size
    sheet = Image.new("RGB", (cols * tw, rows * (th + 18)), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    for i, (thumb, label) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        sheet.paste(thumb, (x, y))
        draw.text((x + 4, y + th + 3), label, fill=(190, 190, 200))
    sheet.save(out_dir / "contact.png")
    return len(shots)


def render(args, plan: VideoPlan, source=None) -> Path:
    canvas = Canvas(args.width, args.height)
    total = plan.total if args.limit is None else min(args.limit, plan.total)
    frames = int(round(total * args.fps))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{args.width}x{args.height}", "-r", str(args.fps), "-i", "-",
    ]
    if not args.no_audio:
        cmd += ["-i", args.audio, "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "320k"]
    cmd += [
        "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
        "-pix_fmt", "yuv420p",
        # Явная разметка цвета: видеопроцессор экрана иначе угадывает сам, и
        # тёмно-синий допрос может уехать в другой оттенок на чужом железе.
        # Именно через -x264-params: обычные -color_primaries и -color_trc
        # этой сборкой ffmpeg для libx264 молча игнорируются, в файле остаётся
        # unknown, и проверить это можно только ffprobe после сборки.
        "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709",
        "-movflags", "+faststart", "-shortest", str(out),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            frame = to_bytes(canvas, render_frame(canvas, plan, i / args.fps,
                                                  args.fps, source))
            proc.stdin.write(frame.tobytes())
            if i % (args.fps * 5) == 0:
                print(f"  {i / args.fps:5.1f} с / {total:.1f}", flush=True)
        proc.stdin.close()
    except BrokenPipeError:
        proc.stdin = None
    code = proc.wait()
    if code != 0:
        raise SystemExit(f"ffmpeg вернул {code}")
    return out


def colour_tags(path: str) -> dict[str, str]:
    """Как цвет размечен в готовом файле.

    Читается из результата, а не берётся с переданных флагов: обычные
    -color_primaries и -color_trc эта сборка ffmpeg для libx264 молча
    игнорирует, файл выходит с unknown, и заметить это можно только прочитав
    его обратно. Экран с неразмеченным цветом угадывает сам.
    """
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_primaries,color_transfer,color_space",
        "-of", "default=nw=1", path,
    ], capture_output=True, text=True)
    tags = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            tags[key.strip()] = value.strip()
    return tags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(ROOT / "scenario" / "timeline.json"))
    ap.add_argument("--audio", default=str(ROOT / "output" / "master_v2.wav"))
    ap.add_argument("--out", default=str(ROOT / "output" / "final_v2.mp4"))
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="slow")
    ap.add_argument("--limit", type=float, default=None, help="отрендерить только N секунд")
    ap.add_argument("--stills", action="store_true", help="только кадры-образцы")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--shots", default=str(ROOT / "scenario" / "shots.json"))
    ap.add_argument("--assets", default=str(ROOT / "assets" / "video"))
    ap.add_argument("--no-footage", action="store_true",
                    help="игнорировать снятый материал, рисовать процедурно")
    ap.add_argument("--check", action="store_true",
                    help="показать, какого материала не хватает, и выйти")
    args = ap.parse_args()

    with open(args.scenario, encoding="utf-8") as fh:
        raw = json.load(fh)
    tl = Timeline.load(args.scenario)
    plan = build_plan(raw["events"], tl.total_duration)

    print(f"Сценарий: {args.scenario}")
    print(f"Состояний: {len(plan.segments)}, якорей: {len(plan.cues)}, "
          f"длительность {plan.total:.3f} с")
    for seg in plan.segments:
        print(f"  {seg.start:6.2f}-{seg.end:6.2f}  {seg.state}")

    bases, fx, assets = [], [], Path(args.assets)
    shots_path = Path(args.shots)
    if not args.no_footage and shots_path.exists():
        bases, fx = resolve(*load_shots(shots_path), plan)
        gaps = missing(bases, assets) + missing(fx, assets)
        have = len(bases) + len(fx) - len(gaps)
        print(f"Материал:  {have} из {len(bases) + len(fx)} на месте"
              f"{'' if not gaps else f', не хватает {len(gaps)}'}")
        for shot in bases + fx:
            mark = "есть" if (assets / shot.clip).exists() else "НЕТ "
            print(f"  {shot.t:6.2f}  [{mark}] {shot.clip}")
        if gaps:
            print("  Недостающие места рисуются процедурно — файл соберётся всё равно.")

    if args.check:
        return 0

    source = None
    if bases or fx:
        source = FootageSource(bases, fx, assets, args.width, args.height,
                               args.fps, seek=args.stills)

    if args.stills:
        canvas = Canvas(args.width, args.height)
        out_dir = ROOT / "output" / "stills"
        count = write_stills(canvas, plan, args.fps, out_dir, source)
        print(f"Готово: {count} кадров в {out_dir}, сводка в contact.png")
        return 0

    if not args.no_audio and not Path(args.audio).exists():
        raise SystemExit(f"нет звука: {args.audio} — сначала `python src/build.py`")

    print(f"Рендер {args.width}x{args.height} @ {args.fps}, "
          f"{int(round(plan.total * args.fps))} кадров")
    try:
        out = render(args, plan, source)
    finally:
        if source is not None:
            source.close()

    # Проверка длительности встроена в рендер, а не оставлена отдельным шагом:
    # разъехавшаяся на кадр картинка не видна глазом, но на сдаче это брак.
    duration = measure_duration(str(out))
    target = plan.total if args.limit is None else min(args.limit, plan.total)
    tags = colour_tags(str(out))
    print(f"Готово: {out}")
    print(f"Длительность: {duration:.3f} с (цель {target:.3f})")
    print(f"Размер:       {out.stat().st_size / 1e6:.1f} МБ")
    print(f"Цвет:         {', '.join(f'{k}={v}' for k, v in sorted(tags.items()))}")
    if any(v in ("unknown", "") for v in tags.values()):
        print("  ВНИМАНИЕ: цвет размечен не полностью, экран будет угадывать сам.")
    if abs(duration - target) > 1.0 / args.fps:
        print("  ВНИМАНИЕ: длительность разошлась с целевой больше чем на кадр.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
