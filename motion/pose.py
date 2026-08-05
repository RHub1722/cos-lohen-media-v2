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

from motion.video import Clip, rgb_stream

MODEL = Path(__file__).resolve().parent / "models" / "pose_landmarker_full.task"
MIN_COVERAGE = 0.60
EVERY = 2               # каждый второй кадр: 30 замеров в секунду хватает
POSE_WIDTH = 640        # позе этого достаточно, а читается втрое быстрее

# Точки MediaPipe Pose, на которых держатся все замеры тела.
L_SHOULDER, R_SHOULDER = 11, 12
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_ANKLE, R_ANKLE = 27, 28

# Рост от плеч до стоп — примерно 0.8 полного роста. Делим на него, чтобы
# body_frac читался как доля роста человека, а не доля отрезка плечи-стопы.
SHOULDER_TO_ANKLE = 0.8


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
    if np.size(hip_speed) == 0 or np.size(wrist_speed) == 0:
        return 0.0
    return float((int(np.argmax(wrist_speed)) - int(np.argmax(hip_speed))) / fps)


def hip_lead_over_strikes(track: "PoseTrack", strikes) -> float | None:
    """Медиана опережения бёдер по ударам — внутри удара, а не по всему клипу.

    Глобальный argmax даёт бессмыслицу: максимум скорости бёдер и максимум
    скорости кистей могут лежать в разных секундах, и «опережение» выходит
    в тринадцать секунд. Первая версия так и отчиталась. Смысл метрика имеет
    только внутри одного действия, от начала замаха до пика.
    """
    if not strikes or np.size(track.times) < 3:
        return None
    steps = np.diff(track.times)
    step = float(np.median(steps)) if steps.size else 0.0
    if step <= 0.0:
        return None
    leads: list[float] = []
    for hit in strikes:
        window = ((track.times >= hit.t_peak - hit.windup)
                  & (track.times <= hit.t_peak + 0.10))
        if int(window.sum()) < 3:
            continue
        leads.append(hip_lead(track.hip_speed[window],
                              track.wrist_speed[window], 1.0 / step))
    return float(np.median(leads)) if leads else None


def _angle(ax, ay, bx, by) -> np.ndarray:
    return np.degrees(np.arctan2(by - ay, bx - ax))


def _empty(times: np.ndarray) -> PoseTrack:
    """Трек без единого найденного сустава. Семь массивов, потом покрытие."""
    return PoseTrack(times, *(np.zeros(0) for _ in range(7)), 0.0)


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

    stamps: list[float] = []
    rows: list[list[float] | None] = []
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        for index, (t, rgb) in enumerate(rgb_stream(clip, width=POSE_WIDTH)):
            if index % every:
                continue
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, int(t * 1000))
            stamps.append(t)
            if not result.pose_landmarks:
                rows.append(None)
                continue
            lm = result.pose_landmarks[0]
            rows.append([lm[i].x for i in range(33)]
                        + [lm[i].y for i in range(33)])

    times = np.array(stamps, dtype=np.float64)
    found = [r for r in rows if r is not None]
    coverage = len(found) / max(len(rows), 1)
    if not found:
        return _empty(times)

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
    shoulder_w = np.maximum(
        np.hypot(x[:, L_SHOULDER] - x[:, R_SHOULDER],
                 y[:, L_SHOULDER] - y[:, R_SHOULDER]), 1e-6)

    top = np.minimum(y[:, L_SHOULDER], y[:, R_SHOULDER])
    bottom = np.maximum(y[:, L_ANKLE], y[:, R_ANKLE])
    body_frac = np.clip(np.abs(bottom - top) / SHOULDER_TO_ANKLE, 0.05, 1.0)

    wrist_mid_x = (x[:, L_WRIST] + x[:, R_WRIST]) / 2.0
    wrist_mid_y = (y[:, L_WRIST] + y[:, R_WRIST]) / 2.0
    wrist_speed = np.abs(np.gradient(np.hypot(wrist_mid_x, wrist_mid_y)))
    hip_speed = np.abs(np.gradient(np.unwrap(np.radians(hip))))

    return PoseTrack(
        times=times,
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
