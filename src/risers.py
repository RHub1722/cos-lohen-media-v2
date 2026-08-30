"""Синтез ризов: нарастающий шум, вершина которого приходится ровно в контакт.

Отделено от сборщиков намеренно. Риз понадобился обоим — и дорожке счёта, где
он появился, и дорожке подсказок, где он занял место слов, — а держать синтез
внутри одного из них значило бы, что второй тянет к себе чужой сборщик целиком
ради двадцати строк.

Когда риза стоит на КАЖДОМ контакте, а не на действии, — в `counting.risers`,
там же и объяснение, почему начало подрезается предыдущим контактом. Здесь
только как он звучит.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Уровень слоя ризов внутри дорожки счёта: столько, чтобы не задавить номер,
# под который он кладётся. Там, где номера в файле нет, уровень ставится
# замером по пику, и это число не участвует.
RISER_DB = -9.0


def shift_rows(rows: list[dict], lag_ms: int) -> list[dict]:
    """Ризы, сдвинутые РАНЬШЕ на заданное число миллисекунд.

    Двумя способами и по двум разным поводам.

    Задержка наушника, пока она не замерена: ризы уезжают на сто или двести
    миллисекунд, длина файла остаётся 60.000 с, потому что устройства пускают
    одновременно и файл обязан совпадать с видео.

    Сдвиг якоря: файл начинается там, где помощник нажал play, и длина у него
    своя — шестьдесят минус сдвиг. Длину задаёт вызывающий, здесь только
    содержимое.
    """
    lag = lag_ms / 1000.0
    out = []
    for row in rows:
        start = row["start"] - lag
        if start < 0.0:
            # SystemExit, а не доменная ошибка: так было в сборщике счёта, и
            # перенос обязан быть переносом. Вопрос о доменных исключениях в
            # библиотечных модулях записан в docs/tech-debt.md, запись 3, и
            # решается разом для всего проекта, а не походя в одной функции.
            raise SystemExit(
                "сдвиг на %d мс выносит риз %s за начало файла"
                % (lag_ms, row["strike"]))
        out.append(dict(row, start=round(start, 4),
                        peak=round(row["peak"] - lag, 4)))
    return out


def build_risers(work: Path, rows: list[dict], total: float) -> Path:
    """Нарастающие шумы: чирп плюс розовый шум под общей огибающей.

    Синтез целиком на FFmpeg: библиотек для звука в проекте нет. Огибающая
    степенная, а не линейная — линейная слышится как ровная полка и вершину
    не обозначает.
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
    parts.append("[m]apad,atrim=0:%.4f,asetpts=N/SR/TB[out]" % total)
    out = work / "risers.wav"
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-y"] + inputs
        + ["-filter_complex", ";".join(parts), "-map", "[out]",
           "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)],
        capture_output=True, text=True)
    if done.returncode:
        raise SystemExit("ffmpeg ризы: %s" % done.stderr[-1500:])
    return out
