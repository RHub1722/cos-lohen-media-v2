"""Приёмка чужой фонограммы: попадает ли она в картинку и годится ли по уровню.

    python tools/check_fx_sync.py --audio "output/Project Anime Video.mp4"
    python tools/check_fx_sync.py --audio output/project_anime_fx.wav --chart output/fx.png

Задача возникает, когда звук номера правят вне проекта — в монтажке, руками — и
надо понять, что оттуда вернулось: тот же ли это материал, не уехал ли он
целиком и попадают ли удары в кадр.

ЧТО МЕРИТСЯ

1. Общий сдвиг. Корреляция с нашим мастером по пятисекундным окнам. Окна, где
   чужая фонограмма совпадает с нашей, дают сдвиг честно; окна, где её
   переделали, дают низкое совпадение — и их сдвигу верить нельзя.

2. Сколько от нас осталось. В каждом окне подбирается усиление, с которым наш
   мастер лучше всего вычитается. Доля остатка близко к 100% означает, что в
   этом куске от нас практически ничего.

3. Опорные удары. Девять моментов, подтверждённых ДВУМЯ независимыми
   источниками: скачком в картинке и нашим sfx, сведённым к картинке покадровым
   замером (точка 2026-08-04). Для каждого ищется самая сильная атака в окне
   +-200 мс.

ЧЕГО ЭТОТ ЗАМЕР НЕ УМЕЕТ. Судить об одном ударе. Инструмент проверен на нашем
мастере, у которого правильный ответ известен, и там он ошибается в среднем на
52 мс — полтора кадра. Значит расхождение меньше 50 мс не значит ничего, а
сравнивать имеет смысл РАЗБРОС по всем девяти, а не отдельные числа.

Полоса 2-10 кГц выбрана не на глаз: из четырёх кандидатов (низ, середина, верх,
широкая) она дала на нашем мастере наименьшую ошибку. Низ, вопреки ожиданию,
оказался худшим — 86 мс: у ударов длинный низкочастотный хвост, и его начало
размыто.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / 'output' / 'master_ru_lo_v41.wav'
SR, HOP, WIN = 48000, 256, 2048
FPS = 30
FRAME_MS = 1000.0 / FPS
BAND = (2000, 10000)
INSTRUMENT_ERROR_MS = 52.3     # собственная ошибка замера, проверена на мастере

# Момент в кадре, что там происходит, наше событие звука.
BEATS = [
    (22.30, 'дверь вынесли', 'door_breach'),
    (29.17, 'удар 1, контакт', 'burst1_impact'),
    (33.43, 'удар 2, замах', 'burst2_whoosh'),
    (36.53, 'удар 2, добивание', 'burst2_impact_b'),
    (39.90, 'удар 3, контакт', 'burst3_impact_b'),
    (40.90, 'удар 3, добивание', 'burst3_impact_c'),
    (42.83, 'попадание по Лоэну', 'hit_on_lohen'),
    (47.03, 'ледяной взрыв', 'ice_burst'),
    (55.23, 'финальный удар', 'ice_final_impact'),
]


def mono(path: Path) -> np.ndarray:
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float32)


def band_onset(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Прирост энергии в полосе 2-10 кГц — признак атаки."""
    m = (len(x) - WIN) // HOP
    w = np.hanning(WIN).astype(np.float32)
    fr = np.lib.stride_tricks.as_strided(
        x, shape=(m, WIN), strides=(x.strides[0] * HOP, x.strides[0])) * w
    spec = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    freq = np.fft.rfftfreq(WIN, 1 / SR)
    e = 10 * np.log10(spec[:, (freq >= BAND[0]) & (freq < BAND[1])].sum(1) + 1e-12)
    return np.r_[0.0, np.maximum(np.diff(e), 0)], HOP / SR


def beat_offsets(curve: np.ndarray, dt: float, half: float = 0.20) -> np.ndarray:
    out = []
    for t, _, _ in BEATS:
        i0, i1 = int((t - half) / dt), int((t + half) / dt) + 1
        seg = curve[max(0, i0):i1]
        out.append(((int(np.argmax(seg)) + max(0, i0)) * dt - t) * 1000)
    return np.array(out)


def windows(fx: np.ndarray, ms: np.ndarray) -> None:
    n = min(len(fx), len(ms))
    lag = int(0.05 * SR)
    print('окно      совпадение   сдвиг    от нас осталось')
    for s in range(0, 60, 5):
        i0, i1 = s * SR, min((s + 5) * SR, n)
        a = fx[i0:i1] - fx[i0:i1].mean()
        b = ms[i0:i1] - ms[i0:i1].mean()
        bb = ms[max(0, i0 - lag): i1 + lag]
        bb = bb - bb.mean()
        c = np.correlate(a.astype(np.float64), bb.astype(np.float64), 'valid')
        k = int(np.argmax(np.abs(c))) - (i0 - max(0, i0 - lag))
        corr = float(np.abs(c).max() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        g = float(a @ b / (b @ b + 1e-12))
        r = a - g * b
        share = np.sqrt((r ** 2).mean()) / (np.sqrt((a ** 2).mean()) + 1e-12)
        verdict = 'наше' if corr > 0.7 else ('переделано' if corr < 0.55 else 'смешано')
        print('%2d-%2d с    %6.3f    %+6.1f мс   остаток %3.0f%%   %s'
              % (s, s + 5, corr, 1000 * k / SR, 100 * share, verdict))


def quality(path: Path) -> None:
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '2',
                          '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    st = np.frombuffer(raw, np.float32).reshape(-1, 2)
    print('длительность %.6f с (наш мастер 60.000000)' % (len(st) / SR))
    for ch, nm in ((0, 'левый '), (1, 'правый')):
        x = np.abs(st[:, ch])
        at = x >= x.max() * 0.9995
        best = cur = 0
        for v in at:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        print('%s пик %+.3f dBFS, на потолке %d отсчётов, плато %d'
              % (nm, 20 * np.log10(x.max() + 1e-12), int(at.sum()), best))
    out = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
         '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
        capture_output=True, text=True).stderr
    try:
        b = json.loads(out[out.rindex('{'):out.rindex('}') + 1])
        print('громкость %s LUFS, разброс %s, истинный пик %s dBTP'
              % (b['input_i'], b['input_lra'], b['input_tp']))
    except ValueError:
        print('громкость прочитать не удалось')


def chart(fx: np.ndarray, ms: np.ndarray, dst: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from scipy.ndimage import maximum_filter1d, uniform_filter1d

    def env(x, msec=4):
        k = int(SR * msec / 1000) | 1
        return uniform_filter1d(maximum_filter1d(np.abs(x), k), k)

    a, b = env(fx), env(ms)
    half = 0.45
    fig, axes = plt.subplots(3, 3, figsize=(15, 9))
    fig.suptitle('Опорные удары: проверяемая фонограмма (сплошная) против нашего '
                 'мастера (пунктир).\nКрасная черта — событие в картинке, полоса — один кадр',
                 fontsize=13)
    for ax, (t, what, _) in zip(axes.ravel(), BEATS):
        i0, i1 = int((t - half) * SR), int((t + half) * SR)
        tt = (np.arange(i1 - i0) / SR - half) * 1000
        ax.plot(tt, a[i0:i1], lw=0.9, color='#2a6fd6')
        ax.plot(tt, b[i0:i1], lw=0.9, color='#c04040', ls='--', alpha=0.75)
        ax.axvline(0, color='#d02020', lw=1.4)
        ax.axvspan(-FRAME_MS, FRAME_MS, color='#d02020', alpha=0.10)
        ax.set_title('%.2f с — %s' % (t, what), fontsize=10)
        ax.set_xlim(-half * 1000, half * 1000)
        ax.set_yticks([])
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.25)
    for ax in axes[-1]:
        ax.set_xlabel('мс от события в кадре', fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(dst, dpi=110)
    print('раскадровка ударов: %s' % dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True, help='файл со звуком: wav или видео')
    ap.add_argument('--master', default=str(MASTER))
    ap.add_argument('--chart', default='')
    args = ap.parse_args()
    src, mst = Path(args.audio), Path(args.master)
    if not src.exists() or not mst.exists():
        print('нет файла: %s' % (src if not src.exists() else mst), file=sys.stderr)
        return 1

    fx, ms = mono(src), mono(mst)
    print('=== 1. совпадение с нашим мастером по окнам')
    windows(fx, ms)

    print('\n=== 2. опорные удары (собственная ошибка замера %.0f мс)' % INSTRUMENT_ERROR_MS)
    c_fx, dt = band_onset(fx)
    c_ms, _ = band_onset(ms)
    o_fx, o_ms = beat_offsets(c_fx, dt), beat_offsets(c_ms, dt)
    print(' кадр    что происходит          проверяемая   наш мастер')
    for (t, what, _), a, b in zip(BEATS, o_fx, o_ms):
        mark = 'ок' if abs(a) <= FRAME_MS else ('~' if abs(a) <= 2 * FRAME_MS else '!')
        print('%6.2f   %-22s %+6.0f мс %-2s  %+6.0f мс' % (t, what, a, mark, b))
    for nm, v in (('проверяемая', o_fx), ('наш мастер ', o_ms)):
        print('%s  среднее %+6.1f мс, РАЗБРОС %5.1f мс, в двух кадрах %d из 9'
              % (nm, v.mean(), v.std(), int((np.abs(v) <= 2 * FRAME_MS).sum())))

    print('\n=== 3. годность по уровню')
    quality(src)

    if args.chart:
        chart(fx, ms, Path(args.chart))
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
