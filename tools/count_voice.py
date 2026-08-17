"""Заказ счёта одной фразой и замер каждого числительного.

    $env:ELEVENLABS_API_KEY="..."
    python tools/count_voice.py --order          # заказать и замерить
    python tools/count_voice.py --measure FILE   # только замерить готовый файл

Гейт перед сборкой дорожки счёта: влезает ли числительное в шаг. Ответ даёт
замер, а не оценка.

ЗАМЕР СДЕЛАН, И ОН ПЕРЕСТАВИЛ ВОПРОС. В 0.333 с влезает только «три»,
остальным девяти нужно от 0.40 до 0.58 с. Собраны две пробы, и на слух выбран
шаг 0.5 с: сжатие речи падает с 1.665× до 1.110×, а цикл становится ровно
5.000 с, то есть «один» приходится на каждую круглую пятёрку таймера вместо
каждой десятки. Рабочий шаг живёт теперь в `src/counting.py`; STEP ниже
оставлен как условие того замера, а не как решение.

Счёт заказывается ОДНОЙ фразой, как до этого семь слов подсказок: десять
отдельных вызовов дали бы десять чуть разных тембров, и в ухе это читалось бы
как десять разных людей. Два цикла в одном заказе — чтобы увидеть ещё и
разброс между двумя произнесениями одного числительного.

Ключ берётся только из ELEVENLABS_API_KEY и никуда не печатается.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.elevenlabs.io/v1"

# Тот же голос, которым записаны «готовь» и «бей». Не голос Лоэна: подсказка
# обращена к исполнителю, а не к залу, и путать их нельзя.
VOICE = "cgSgspJ2msm6clMCkdW9"
MODEL = "eleven_multilingual_v2"
STABILITY = 0.85
OUTPUT_FORMAT = "mp3_44100_192"

# Заказано «один», а не «раз»: так сказал исполнитель. Два слога против одного,
# и на шаге 0.333 с это решающая разница — потому и меряем оба.
WORDS = ["один", "два", "три", "четыре", "пять", "шесть",
         "семь", "восемь", "девять", "десять"]
CYCLES = 2

# Шаг, ПОД КОТОРЫЙ шёл замер, а не принятый в дело. Принятый — 0.5 с, он в
# src/counting.py. Здесь оставлено 1/3, чтобы вывод скрипта воспроизводил ту
# самую проверку, из которой решение и выросло.
STEP = 1.0 / 3.0

OUT = ROOT / "assets" / "cues" / "archive"


class CountError(RuntimeError):
    pass


def key() -> str:
    value = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not value:
        raise CountError(
            "нет переменной окружения ELEVENLABS_API_KEY.\n"
            '  PowerShell:  $env:ELEVENLABS_API_KEY="..."')
    return value


def order(speed: float, attempt: int) -> Path:
    text = ", ".join(WORDS * CYCLES) + "."
    print("заказ: %d знаков, скорость %.2f, попытка %d"
          % (len(text), speed, attempt))
    response = requests.post(
        f"{API}/text-to-speech/{VOICE}",
        params={"output_format": OUTPUT_FORMAT},
        headers={"xi-api-key": key(), "accept": "audio/mpeg",
                 "content-type": "application/json"},
        json={"text": text, "model_id": MODEL,
              "voice_settings": {"stability": STABILITY, "speed": speed}},
        timeout=300)
    if response.status_code >= 400:
        # Тело ответа печатается обрезанным и ключа не содержит.
        raise CountError("отказ (%d): %s" % (response.status_code,
                                             response.text[:400]))
    if not response.content:
        raise CountError("пустой ответ")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("count_take%d_speed%03d.mp3" % (attempt, round(speed * 100)))
    path.write_bytes(response.content)
    print("записано: %s  %.1f КБ" % (path, len(response.content) / 1024))
    return path


def mono(path: Path, sr: int = 16000) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1",
         "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def segments(x: np.ndarray, sr: int = 16000, hop: int = 80,
             floor_db: float = 32.0, join: float = 0.100) -> list:
    """Слова как участки поверх порога, склеенные через короткие провалы.

    Порог берётся от пика самой записи, а не абсолютным числом: громкость
    заказа от вызова к вызову плавает, а форма — нет.

    Склейка 100 мс, а не 45: смычные внутри числительного дают паузу до 75 мс
    («че-тыре», «пя-ть», «шес-ть»), и на 45 мс запись распадалась на 30 кусков
    вместо 20. Между самими числительными провал от 220 мс, так что 100 мс
    сшивает слово, но не склеивает соседей.
    """
    n = len(x) // hop
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    live = db > (db.max() - floor_db)
    fps = sr / hop
    runs, start = [], None
    for i, on in enumerate(live):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(live)])
    merged = []
    for run in runs:
        if merged and (run[0] - merged[-1][1]) / fps < join:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(a / fps, b / fps) for a, b in merged]


def split_run(x: np.ndarray, a: float, b: float, parts: int,
              sr: int = 16000, hop: int = 80, min_word: float = 0.18) -> list:
    """Разрезать слитую речь на `parts` слов по самым глубоким провалам энергии.

    На скорости 1.2 числительные произносятся без пауз, и порог тишины их не
    разделяет. Но количество известно точно, поэтому задача сводится к поиску
    parts-1 границ: берётся самый тихий отсчёт, который стоит не ближе
    `min_word` к уже найденным границам и к краям, и так parts-1 раз.

    ПРОВЕРЕНО И НЕ РАБОТАЕТ. На записи со скоростью 1.2 разбор выдал «семь»
    длиной 0.635 с — при том, что то же слово на БОЛЕЕ МЕДЛЕННОЙ записи
    занимает 0.430 с. Это не размытая граница, это границы поставлены не туда:
    самый тихий отсчёт внутри слитного счёта приходится на смычный ВНУТРИ
    числительного не реже, чем на стык между ними.

    Оставлено как запись отрицательного результата. Пользоваться внутренними
    границами отсюда нельзя; надёжны только внешние края участка, по которым
    считается темп цикла.
    """
    n = len(x) // hop
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    fps = sr / hop
    lo, hi = int(a * fps), int(b * fps)
    cuts = []
    while len(cuts) < parts - 1:
        best, best_db = None, None
        for i in range(lo, hi):
            if i - lo < min_word * fps or hi - i < min_word * fps:
                continue
            if any(abs(i - c) < min_word * fps for c in cuts):
                continue
            if best_db is None or db[i] < best_db:
                best, best_db = i, db[i]
        if best is None:
            break
        cuts.append(best)
    edges = [lo] + sorted(cuts) + [hi]
    return [(edges[i] / fps, edges[i + 1] / fps) for i in range(len(edges) - 1)]


def measure_merged(path: Path) -> int:
    """Замер записи, в которой числительные слиты в непрерывный счёт."""
    x = mono(path)
    runs = segments(x)
    print("\nсплошных участков: %d" % len(runs))
    for i, (a, b) in enumerate(runs):
        print("  цикл %d: %6.3f–%6.3f  %.3f с на десять числительных, "
              "%.3f с на одно" % (i + 1, a, b, b - a, (b - a) / len(WORDS)))
    if not runs:
        return 1
    a, b = runs[-1]
    print("\nПоследний цикл — устоявшийся темп, его и разбираем.")
    print("цель 3.3333 с, получено %.3f с → правка темпа %.4f×"
          % (b - a, (b - a) / (len(WORDS) * STEP)))
    parts = split_run(x, a, b, len(WORDS))
    print("\nслово     начало от цикла   длина    отклонение от ровной сетки")
    for word, (s, e) in zip(WORDS, parts):
        ideal = WORDS.index(word) * (b - a) / len(WORDS)
        print("%-9s %6.3f с          %.3f с  %+.3f с"
              % (word, s - a, e - s, (s - a) - ideal))
    return 0


def measure(path: Path) -> int:
    x = mono(path)
    found = segments(x)
    want = len(WORDS) * CYCLES
    print("\nнайдено участков речи: %d, ожидалось %d" % (len(found), want))
    if len(found) != want:
        print("РАЗБОР НЕ СОШЁЛСЯ — числительные слились или распались.")
        for i, (a, b) in enumerate(found):
            print("  %2d  %6.3f–%6.3f  %.3f с" % (i + 1, a, b, b - a))
        return 1

    print("\nслово     цикл 1   цикл 2   разброс  влезает в %.3f с" % STEP)
    over = []
    for i, word in enumerate(WORDS):
        d1 = found[i][1] - found[i][0]
        d2 = found[i + len(WORDS)][1] - found[i + len(WORDS)][0]
        worst = max(d1, d2)
        ok = worst <= STEP
        if not ok:
            over.append((word, worst))
        print("%-9s %.3f с  %.3f с  %+.3f   %s"
              % (word, d1, d2, d2 - d1,
                 "да" if ok else "НЕТ, длиннее на %.3f" % (worst - STEP)))

    starts = [a for a, _ in found]
    gaps = np.diff(starts)
    print("\nшаг в самой записи: среднее %.3f с, от %.3f до %.3f"
          % (gaps.mean(), gaps.min(), gaps.max()))
    print("нужно %.3f с — запись %s"
          % (STEP, "быстрее нужного" if gaps.mean() < STEP else
             "медленнее нужного в %.2f раза" % (gaps.mean() / STEP)))

    if over:
        print("\nНЕ ВЛЕЗАЮТ: %s" % ", ".join(
            "%s (%.3f с)" % (w, d) for w, d in over))
        print("Сетку не трогаем. Варианты: перезаказ быстрее (--speed) или "
              "сжатие через atempo до %.3f с." % STEP)
    else:
        print("\nВсе десять влезают в шаг. Сетка собирается как есть.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--order", action="store_true")
    ap.add_argument("--measure")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--raz", action="store_true",
                    help="считать «раз» вместо «один» — один слог против двух")
    ap.add_argument("--merged", action="store_true",
                    help="запись без пауз между числительными: резать по энергии")
    args = ap.parse_args()

    if args.raz:
        WORDS[0] = "раз"
    look = measure_merged if args.merged else measure

    if args.order:
        return look(order(args.speed, args.attempt))
    if args.measure:
        return look(Path(args.measure))
    ap.error("нужен --order или --measure FILE")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except CountError as exc:
        print("ошибка: %s" % exc)
        raise SystemExit(2)
