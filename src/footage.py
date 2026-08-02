"""Видеоматериал поверх того же таймлайна.

База и эффекты привязаны к событиям звука по `anchor`, своих таймкодов у них
нет — тот же принцип, что у движений исполнителя в `movements.py`. Сдвинулась
реплика, и материал едет за ней.

Клипа на месте нет — на его месте работает процедурный фон из `render_video`.
Поэтому номер собирается целиком на любом наборе материала, хоть на пустой
папке, и клипы можно докладывать по одному, каждый раз получая готовый файл.
Но это касается только отсутствующих файлов: если файл есть и не читается, это
ошибка, и она обязана быть громкой — молчаливый откат на процедурный фон в
такой ситуации выглядит как «материал не подошёл» и стоит часа поисков.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

# Ключ по зелёному для материала без альфа-канала. Порог мягкий: жёсткий даёт
# рваный контур на рисованных эффектах, у которых края и так полупрозрачные.
GREEN_STRENGTH = 2.6

GRADES = {
    "none": (1.00, 1.00, 1.00),
    "cold": (0.62, 0.82, 1.15),   # допросная
    "hot": (1.20, 0.72, 0.55),    # бой
    "ice": (0.82, 0.95, 1.15),    # лёд
}


class FootageError(Exception):
    """Список кадров не соответствует схеме, или файл есть, но не читается."""


@dataclass(frozen=True)
class BaseShot:
    """Кусок фона. Длится до следующей базы или до конца номера."""

    anchor: str
    clip: str
    start_at: float = 0.0
    speed: float = 1.0
    grade: str = "none"
    gain: float = 1.0
    t: float = -1.0
    end: float = -1.0


@dataclass(frozen=True)
class FxShot:
    """Рисованный эффект поверх фона: слэш, импакт, спидлайны."""

    anchor: str
    clip: str
    scale: float = 1.0
    x: float = 0.0          # −1 левый край, 0 центр, +1 правый
    y: float = 0.0
    opacity: float = 1.0
    key: str = "alpha"      # alpha | green
    lead: float = 0.0       # насколько раньше якоря начать
    t: float = -1.0


def _need(raw: dict, *keys: str) -> None:
    for key in keys:
        if key not in raw:
            raise FootageError(f"кадр без обязательного поля {key!r}: {raw}")


def load_shots(path: str | Path) -> tuple[list[BaseShot], list[FxShot]]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    bases = []
    for item in raw.get("base", []):
        _need(item, "anchor", "clip")
        grade = str(item.get("grade", "none"))
        if grade not in GRADES:
            raise FootageError(
                f"{item['anchor']}: неизвестная цветокоррекция {grade!r}, "
                f"допустимы {tuple(GRADES)}"
            )
        speed = float(item.get("speed", 1.0))
        if speed <= 0:
            raise FootageError(f"{item['anchor']}: speed={speed} должен быть больше нуля")
        bases.append(BaseShot(
            anchor=str(item["anchor"]), clip=str(item["clip"]),
            start_at=float(item.get("start_at", 0.0)), speed=speed,
            grade=grade, gain=float(item.get("gain", 1.0)),
        ))

    fx = []
    for item in raw.get("fx", []):
        _need(item, "anchor", "clip")
        key = str(item.get("key", "alpha"))
        if key not in ("alpha", "green", "add"):
            raise FootageError(
                f"{item['anchor']}: key={key!r}, допустимы alpha, green и add"
            )
        scale = float(item.get("scale", 1.0))
        if scale <= 0:
            raise FootageError(f"{item['anchor']}: scale={scale} должен быть больше нуля")
        fx.append(FxShot(
            anchor=str(item["anchor"]), clip=str(item["clip"]), scale=scale,
            x=float(item.get("x", 0.0)), y=float(item.get("y", 0.0)),
            opacity=float(item.get("opacity", 1.0)),
            key=key, lead=float(item.get("lead", 0.0)),
        ))
    return bases, fx


def resolve(bases: list[BaseShot], fx: list[FxShot], plan) -> tuple[list[BaseShot], list[FxShot]]:
    """Проставляет времена из якорей и режет базы по границам друг друга."""
    # База обычно вешается на имя состояния, эффект — на идентификатор события.
    # Разрешены оба: иногда фон надо сменить не на смене палитры, а на ударе.
    known = {seg.state: seg.start for seg in plan.segments}
    known.update({cue.source: cue.t for cue in plan.cues})

    def at(anchor: str, what: str) -> float:
        if anchor not in known:
            raise FootageError(
                f"{what} ссылается на якорь {anchor!r}, которого нет в сценарии. "
                f"Есть: {', '.join(sorted(known))}"
            )
        return known[anchor]

    placed = sorted(
        (replace(b, t=at(b.anchor, f"база {b.clip}")) for b in bases),
        key=lambda b: b.t,
    )
    out_bases = []
    for i, base in enumerate(placed):
        end = placed[i + 1].t if i + 1 < len(placed) else plan.total
        out_bases.append(replace(base, end=end))

    out_fx = sorted(
        (replace(f, t=max(0.0, at(f.anchor, f"эффект {f.clip}") - f.lead)) for f in fx),
        key=lambda f: f.t,
    )
    return out_bases, out_fx


def missing(shots, assets: Path) -> list[str]:
    return [s.clip for s in shots if not (Path(assets) / s.clip).exists()]


@lru_cache(maxsize=64)
def clip_duration(path: str) -> float:
    """Длина клипа. Нужна, чтобы короткий материал заворачивался по кругу.

    Без этого база короче своего куска молча кончается на середине блока, и
    дальше кадр откатывается на процедурный фон — выглядит как «клип не
    подошёл», а на деле просто десятисекундный файл под двадцатипятисекундный
    блок.
    """
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise FootageError(f"не удалось прочитать длину клипа {path}: {result.stderr[-400:]}")


class ClipReader:
    """Читает клип кадрами заданного размера через трубу FFmpeg.

    Приведение к размеру делает сам FFmpeg: так материал любого разрешения и
    любых пропорций доходит до компоновщика уже готовым, и в Python не остаётся
    ни одной ветки «а если клип вертикальный».

    fill=True  — заполнить кадр целиком, лишнее обрезать. Для фона.
    fill=False — вписать целиком, поля оставить прозрачными. Для эффектов:
                 у слэша важны его собственные пропорции, обрезать его нельзя.
    """

    def __init__(self, path: Path, width: int, height: int, fps: int,
                 start_at: float = 0.0, speed: float = 1.0,
                 alpha: bool = False, loop: bool = False, fill: bool = True) -> None:
        self.path, self.w, self.h = path, width, height
        self.channels = 4 if alpha else 3
        pix = "rgba" if alpha else "rgb24"

        if fill:
            chain = [f"scale={width}:{height}:force_original_aspect_ratio=increase",
                     f"crop={width}:{height}"]
        else:
            # pad всегда только увеличивает, поэтому сначала вписываем, потом
            # добиваем до точного размера. Обратный порядок ffmpeg отвергает.
            chain = [f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                     f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0"]
        if speed != 1.0:
            chain.append(f"setpts=PTS/{speed:g}")
        chain.append(f"fps={fps}")

        cmd = ["ffmpeg", "-v", "error", "-nostdin"]
        if loop:
            cmd += ["-stream_loop", "-1"]
        if start_at > 0:
            cmd += ["-ss", f"{start_at:.3f}"]
        cmd += ["-i", str(path), "-vf", ",".join(chain),
                "-f", "rawvideo", "-pix_fmt", pix, "-"]

        self.cmd = cmd
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        self.frame_bytes = width * height * self.channels
        self.frames_read = 0

    def read(self) -> np.ndarray | None:
        raw = self.proc.stdout.read(self.frame_bytes)
        if raw is None or len(raw) < self.frame_bytes:
            if self.frames_read == 0 and self.proc.wait() != 0:
                raise FootageError(
                    f"FFmpeg не смог прочитать {self.path.name} "
                    f"(код {self.proc.returncode}). Команда:\n  "
                    + " ".join(self.cmd)
                )
            return None
        self.frames_read += 1
        array = np.frombuffer(raw, dtype=np.uint8).reshape(self.h, self.w, self.channels)
        return array.astype(np.float32) / 255.0

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc.wait()


def green_alpha(rgb: np.ndarray) -> np.ndarray:
    """Прозрачность по зелёному для материала без альфа-канала."""
    green = rgb[:, :, 1]
    other = np.maximum(rgb[:, :, 0], rgb[:, :, 2])
    keyed = np.clip((green - other) * GREEN_STRENGTH, 0.0, 1.0)
    return (1.0 - keyed).astype(np.float32)


def despill(rgb: np.ndarray) -> np.ndarray:
    """Убирает зелёный ореол по краям выключенного фона."""
    out = rgb.copy()
    limit = np.maximum(out[:, :, 0], out[:, :, 2])
    np.minimum(out[:, :, 1], limit, out=out[:, :, 1])
    return out


def paste(base: np.ndarray, patch: np.ndarray, alpha: np.ndarray,
          ox: int, oy: int, blend: str = "over") -> np.ndarray:
    """Кладёт кусок на кадр со смещением, обрезая всё, что вышло за край.

    Смещение и масштаб считаются здесь, а не фильтрами FFmpeg, потому что pad
    не принимает отрицательных отступов: увеличенный слэш, сдвинутый влево,
    через фильтры выразить нельзя, а numpy режет края без всяких условий.

    blend="add" — сложение вместо перекрытия. Так кладут световые эффекты,
    снятые на чёрном: чёрное не добавляет ничего и исчезает само, а мягкие
    края свечения остаются мягкими. Ключевать такой материал по яркости
    бессмысленно — потеряется как раз полупрозрачный ореол, ради которого его
    и берут.
    """
    fh, fw = base.shape[:2]
    ph, pw = patch.shape[:2]
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(fw, ox + pw), min(fh, oy + ph)
    if x0 >= x1 or y0 >= y1:
        return base
    sx, sy = x0 - ox, y0 - oy
    a = alpha[sy:sy + (y1 - y0), sx:sx + (x1 - x0)][:, :, None]
    c = patch[sy:sy + (y1 - y0), sx:sx + (x1 - x0)]
    if blend == "add":
        base[y0:y1, x0:x1] = base[y0:y1, x0:x1] + c * a
    else:
        base[y0:y1, x0:x1] = base[y0:y1, x0:x1] * (1.0 - a) + c * a
    return base


class FootageSource:
    """Отдаёт кадр фона и накладывает рисованные эффекты по списку кадров.

    Два режима. Потоковый — для рендера подряд: читатель живёт ровно столько,
    сколько длится его кадр, и файл проходит через трубу один раз. Режим
    перемотки — для кадров-образцов, где времена идут вразнобой; там на каждый
    запрос поднимается отдельный FFmpeg ровно на один кадр.
    """

    def __init__(self, bases: list[BaseShot], fx: list[FxShot], assets: Path,
                 width: int, height: int, fps: int, seek: bool = False) -> None:
        self.bases, self.fx = bases, fx
        self.assets, self.w, self.h, self.fps = Path(assets), width, height, fps
        self.seek = seek
        self._base_index = -1
        self._base_reader: ClipReader | None = None
        self._fx_readers: dict[int, ClipReader] = {}
        self._fx_started: set[int] = set()

    # -- фон ------------------------------------------------------------------

    def base(self, t: float) -> np.ndarray | None:
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
            frame = self._one_frame(path, self._wrapped_offset(path, shot, t), shot.speed)
        else:
            if index != self._base_index:
                self._close_base()
                self._base_index = index
                self._base_reader = ClipReader(
                    path, self.w, self.h, self.fps,
                    start_at=shot.start_at, speed=shot.speed, loop=True,
                )
            frame = self._base_reader.read() if self._base_reader else None
        if frame is None:
            return None
        tint = np.array(GRADES[shot.grade], dtype=np.float32) * shot.gain
        return frame[:, :, :3] * tint[None, None, :]

    def _wrapped_offset(self, path: Path, shot: BaseShot, t: float) -> float:
        """Смещение внутри клипа, завёрнутое по его длине.

        В потоковом режиме то же самое делает -stream_loop, в режиме перемотки
        приходится считать руками — иначе кадр-образец за концом короткого
        клипа молча вернёт процедурный фон.
        """
        elapsed = (t - shot.t) * shot.speed
        length = clip_duration(str(path))
        usable = max(0.05, length - shot.start_at)
        return shot.start_at + (elapsed % usable)

    def _one_frame(self, path: Path, offset: float, speed: float) -> np.ndarray | None:
        reader = ClipReader(path, self.w, self.h, self.fps,
                            start_at=max(0.0, offset), speed=speed)
        try:
            return reader.read()
        finally:
            reader.close()

    def _close_base(self) -> None:
        if self._base_reader is not None:
            self._base_reader.close()
            self._base_reader = None

    # -- эффекты --------------------------------------------------------------

    def has_fx(self, anchor: str) -> bool:
        """Есть ли для якоря готовый эффект.

        Нужно вызывающему, чтобы не рисовать процедурную вспышку поверх
        рисованного слэша: два удара в один кадр читаются как ошибка сборки.
        """
        return any(f.anchor == anchor and (self.assets / f.clip).exists()
                   for f in self.fx)

    def _fx_size(self, shot: FxShot) -> tuple[int, int, int, int]:
        inner_w = max(2, int(round(self.w * shot.scale)))
        inner_h = max(2, int(round(self.h * shot.scale)))
        ox = int(round((self.w - inner_w) / 2 + shot.x * self.w / 2))
        oy = int(round((self.h - inner_h) / 2 + shot.y * self.h / 2))
        return inner_w, inner_h, ox, oy

    def overlay(self, t: float, rgb: np.ndarray) -> np.ndarray:
        for i, shot in enumerate(self.fx):
            if t < shot.t:
                continue
            path = self.assets / shot.clip
            if not path.exists():
                continue
            inner_w, inner_h, ox, oy = self._fx_size(shot)

            if self.seek:
                offset = t - shot.t
                if offset > clip_duration(str(path)):
                    continue
                reader = ClipReader(path, inner_w, inner_h, self.fps,
                                    start_at=offset, alpha=(shot.key == "alpha"),
                                    fill=False)
                try:
                    frame = reader.read()
                finally:
                    reader.close()
            else:
                if i not in self._fx_started:
                    self._fx_started.add(i)
                    self._fx_readers[i] = ClipReader(
                        path, inner_w, inner_h, self.fps,
                        alpha=(shot.key == "alpha"), fill=False,
                    )
                reader = self._fx_readers.get(i)
                if reader is None:
                    continue
                frame = reader.read()
                if frame is None:
                    reader.close()
                    self._fx_readers.pop(i, None)
                    continue
            if frame is None:
                continue

            if shot.key == "alpha":
                colour, alpha = frame[:, :, :3], frame[:, :, 3]
                blend = "over"
            elif shot.key == "green":
                colour, alpha = despill(frame[:, :, :3]), green_alpha(frame[:, :, :3])
                blend = "over"
            else:
                colour = frame[:, :, :3]
                alpha = np.ones(colour.shape[:2], dtype=np.float32)
                blend = "add"
            rgb = paste(rgb, colour, alpha * shot.opacity, ox, oy, blend)
        return rgb

    def close(self) -> None:
        self._close_base()
        for reader in self._fx_readers.values():
            reader.close()
        self._fx_readers.clear()
