"""Завести фонограмму из монтажки: привести уровень и переложить во все копии.

    python tools/adopt_audio.py --audio "output/Project Anime Video.wav" --suffix fx

Звук номера правится вне проекта, руками, и возвращается готовым файлом. Этот
инструмент не пересобирает ничего: картинка в роликах уже посчитана, и она
копируется потоком как есть. Меняется только звуковая дорожка.

ЧТО ДЕЛАЕТСЯ С ЗВУКОМ. Ровно одно: линейный гейн, чтобы истинный пик встал на
−2.0 dBTP. Ни компрессии, ни ограничителя, ни эквалайзера — микс из монтажки
остаётся тем, каким его сделали, просто с восстановленным запасом. Гейн один на
весь файл, поэтому баланс внутри номера не меняется ни на децибел.

ПОЧЕМУ ЗАПАС ОБЯЗАТЕЛЕН. Файл из монтажки приходит упёртым в полную шкалу.
Пока он лежит файлом, это ничем не грозит, но любое воспроизведение с
пересчётом частоты — а это почти любой плеер и любой пульт — даёт пики выше
шкалы и хрип на ударах. Наша цель −2.0 dBTP взята из спеки сдачи.

ЧТО ПРОВЕРЯЕТСЯ ДО. Длительность ровно 60.000000 с и отсутствие сдвига
относительно нашего мастера. Сдвиг ищется по окнам, где чужая фонограмма
совпадает с нашей: в переделанных кусках корреляция низкая и её сдвигу верить
нельзя. Подробный разбор попадания в картинку — отдельный инструмент,
tools/check_fx_sync.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'output'
MASTER = OUT / 'master_ru_lo_v41.wav'
SR = 48000
DURATION = 60.0
TARGET_TP = -2.0
AUDIO_BITRATE = '320k'

# Копия -> что в ней. Имя готового файла получает суффикс перед расширением.
COPIES = [
    ('final_ru_lo_v41.mp4', 'организаторам: полоса, без титров и знака'),
    ('final_ru_nostrip.mp4', 'без полосы, без титров и знака'),
    ('final_ru_lo_v41_titles_logo.mp4', 'полоса + титры + знак'),
    ('final_ru_nostrip_titles_logo.mp4', 'без полосы + титры + знак'),
]


def mono(path: Path) -> np.ndarray:
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def loudness(path: Path) -> tuple[float, float, float]:
    out = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
                          '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
                         capture_output=True, text=True).stderr
    b = json.loads(out[out.rindex('{'):out.rindex('}') + 1])
    return float(b['input_i']), float(b['input_lra']), float(b['input_tp'])


def duration(path: Path) -> float:
    return float(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', str(path)], capture_output=True, text=True, check=True).stdout)


def check_shift(src: Path) -> float:
    """Сдвиг относительно нашего мастера по окнам, где фонограммы совпадают."""
    a, m = mono(src), mono(MASTER)
    n = min(len(a), len(m))
    lag = int(0.05 * SR)
    shifts = []
    for s in range(5, 55, 5):                      # края не берём: там упор в границу
        i0, i1 = s * SR, min((s + 5) * SR, n)
        x = a[i0:i1] - a[i0:i1].mean()
        y = m[i0:i1] - m[i0:i1].mean()
        yy = m[i0 - lag: i1 + lag]
        yy = yy - yy.mean()
        c = np.correlate(x, yy, 'valid')
        corr = float(np.abs(c).max() / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-12))
        if corr > 0.7:                             # только там, где это наша же фонограмма
            shifts.append((int(np.argmax(np.abs(c))) - lag) / SR * 1000)
    if not shifts:
        print('  сдвиг проверить не на чем: с нашим мастером не совпадает нигде')
        return 0.0
    print('  окон для проверки сдвига: %d, сдвиг %s мс'
          % (len(shifts), ', '.join('%+.2f' % v for v in shifts)))
    return float(np.mean(shifts))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True)
    ap.add_argument('--suffix', default='fx')
    args = ap.parse_args()
    src = Path(args.audio)
    if not src.exists():
        print('нет файла: %s' % src, file=sys.stderr)
        return 1

    print('=== проверка исходной фонограммы')
    d = duration(src)
    print('  длительность %.6f с (нужно %.6f)' % (d, DURATION))
    if abs(d - DURATION) > 0.001:
        print('  ВНИМАНИЕ: длина не совпадает, ролик перестанет быть ровно минутным')
    shift = check_shift(src)
    if abs(shift) > 5:
        print('  ВНИМАНИЕ: средний сдвиг %+.1f мс — фонограмма уехала' % shift)

    i, lra, tp = loudness(src)
    gain = TARGET_TP - tp
    print('  громкость %.2f LUFS, разброс %.2f, истинный пик %+.2f dBTP' % (i, lra, tp))
    print('  гейн для запаса: %+.2f dB -> громкость станет %.2f LUFS' % (gain, i + gain))

    dst = OUT / ('master_ru_%s.wav' % args.suffix)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(src),
                    '-af', 'volume=%.4fdB' % gain,
                    '-c:a', 'pcm_s24le', '-ar', str(SR), str(dst)], check=True)
    i2, lra2, tp2 = loudness(dst)
    print('\n=== мастер %s' % dst.name)
    print('  %.2f LUFS, разброс %.2f, истинный пик %+.2f dBTP, длительность %.6f с'
          % (i2, lra2, tp2, duration(dst)))
    if tp2 > TARGET_TP + 0.15:
        print('  ВНИМАНИЕ: запас не получен, истинный пик выше цели')

    print('\n=== копии (картинка копируется потоком, не пересчитывается)')
    for name, what in COPIES:
        v = OUT / name
        if not v.exists():
            print('  %-38s пропуск: нет файла' % name)
            continue
        o = OUT / ('%s_%s%s' % (v.stem, args.suffix, v.suffix))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(v), '-i', str(dst),
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                        '-c:a', 'aac', '-b:a', AUDIO_BITRATE, '-shortest', str(o)],
                       check=True)
        print('  %-38s %.6f с   %s' % (o.name, duration(o), what))
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
