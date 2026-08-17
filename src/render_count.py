"""Дорожка счёта и ризов плюс печатный лист ориентиров.

    python src/render_count.py --cut     # заново нарезать числительные
    python src/render_count.py           # собрать дорожку и лист

Третий инструмент рядом с двумя от 5 августа, и задача у него другая. Слово
подсказки стоит на доле и говорит, ЧТО делать. Цифра счёта идёт равномерно и
говорит, ГДЕ ты. Совместить их в одном файле нельзя: на шаге 0.5 с между двумя
цифрами слову «готовь» негде поместиться.

Всё, что подсказка, идёт в ПРАВЫЙ канал. Левое ухо остаётся чистым монитором
номера: вынул правый наушник — слышишь выступление без единой подсказки. Это то
же разделение, на котором построена сценическая дорожка, — она моно и идёт в
один наушник, потому что второе ухо обязано слышать зал.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.counting import STEP, WORDS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Заказ ElevenLabs, голос cgSgspJ2msm6clMCkdW9, eleven_multilingual_v2,
# stability 0.85 — тот же, которым записаны «готовь» и «бей». Лежит вне гита:
# assets/cues/archive под .gitignore, как все исходники озвучки.
TAKE = ROOT / "assets/cues/archive/count_take1_speed100.mp3"
OUT_DIR = ROOT / "assets/cues"

# Границы первого цикла, замерены tools/count_voice.py по провалам тишины.
# Разброс между двумя произнесениями одного числительного не больше 0.030 с.
NUMERALS: tuple[tuple[float, float], ...] = (
    (0.030, 0.505),   # один
    (0.725, 1.130),   # два
    (1.490, 1.780),   # три
    (2.050, 2.605),   # четыре
    (2.980, 3.305),   # пять
    (3.615, 4.090),   # шесть
    (4.465, 4.895),   # семь
    (5.295, 5.835),   # восемь
    (6.160, 6.680),   # девять
    (7.085, 7.635),   # десять
)

# Запас перед атакой и скосы от щелчков — как у семи слов подсказок.
LEAD = 0.010
FADE = 0.006
PEAK_DB = -6.0

# Тишина между концом одного числительного и началом следующего. Без неё цифры
# стыкуются впритык и счёт слышится сплошной речью — ровно то, из-за чего
# отброшена запись на скорости 1.2. У слов подсказок та же константа зовётся
# MIN_GAP и равна 0.08; здесь шаг втрое короче, поэтому и зазор меньше.
GAP = 0.020


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit("ffmpeg: %s" % done.stderr[-1500:])
    return done.stderr


def peak_db(path: Path) -> float:
    """Пик файла в dBFS. Нужен, чтобы привести все десять к одному уровню.

    Приведение по ПИКУ, а не по громкости: числительные разной длины, и
    loudnorm сделал бы короткое «три» громче длинного «четыре», хотя в счёте
    они обязаны звучать одинаково.
    """
    err = run(["ffmpeg", "-v", "info", "-i", str(path),
               "-af", "volumedetect", "-f", "null", "-"])
    for line in err.splitlines():
        if "max_volume:" in line:
            return float(line.split("max_volume:")[1].split("dB")[0].strip())
    raise SystemExit("volumedetect не вернул пик для %s" % path)


def window(a: float, b: float) -> float:
    """Сколько звука реально вырезается под числительное.

    Не `b - a`: перед атакой берётся запас LEAD, и он проходит через atempo
    вместе со словом. Считать сжатие от `b - a`, а вырезать `b - a + LEAD` —
    это ошибка на десять миллисекунд, и она выталкивала «четыре» и «десять» за
    шаг сетки при внешне верном множителе.
    """
    return b - a + LEAD


def factor() -> float:
    """Один множитель на все десять.

    Свой на каждое слово дал бы счёт, у которого цифры произносятся с разной
    скоростью, и он читался бы как сбой темпа, а не как счёт.

    Целью взят шаг МИНУС зазор: числительное обязано не просто влезть в ячейку,
    а оставить тишину до следующего. Самое длинное — «четыре», 0.555 с, и с
    запасом перед атакой это 0.565 против цели 0.480.
    """
    return max(window(a, b) for a, b in NUMERALS) / (STEP - GAP)


def cut_numerals() -> list[Path]:
    if not TAKE.exists():
        raise SystemExit(
            "нет заказа %s. Он вне гита: заказать заново — "
            "python tools/count_voice.py --order" % TAKE)
    k = factor()
    print("самое длинное числительное %.3f с (с запасом %.3f), цель %.3f с "
          "→ сжатие %.3f× на все"
          % (max(b - a for a, b in NUMERALS),
             max(window(a, b) for a, b in NUMERALS), STEP - GAP, k))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Заказ разжимается ЦЕЛИКОМ и один раз. Резать прямо из mp3 нельзя: `-ss`
    # там попадает в границу кадра, а не в отсчёт, и на 44.1 кГц это до 26 мс
    # промаха — «четыре» вылезало за шаг сетки при внешне верном множителе.
    flat = OUT_DIR / "count_take.flat.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(TAKE),
         "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(flat)])

    out = []
    for i, ((a, b), word) in enumerate(zip(NUMERALS, WORDS), start=1):
        path = OUT_DIR / ("count_%02d.wav" % i)
        raw = path.with_suffix(".raw.wav")
        length = window(a, b) / k
        # Первый проход: вырезать, сжать, скосить щелчки. Подрезка по длине
        # обязательна: atempo отдаёт чуть больше запрошенного, и без неё длина
        # цифры зависела бы от версии FFmpeg.
        run(["ffmpeg", "-v", "error", "-y",
             "-ss", "%.4f" % max(0.0, a - LEAD), "-t", "%.4f" % window(a, b),
             "-i", str(flat),
             "-af", "atempo=%.5f,afade=t=in:d=%.3f,afade=t=out:st=%.4f:d=%.3f,"
                    "atrim=0:%.4f,asetpts=N/SR/TB"
                    % (k, FADE, max(0.0, length - FADE), FADE, length),
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(raw)])
        # Второй проход: один линейный гейн до общего пика. Замер, а не
        # угадывание: числительные приходят с разбросом громкости до 4 dB.
        gain = PEAK_DB - peak_db(raw)
        run(["ffmpeg", "-v", "error", "-y", "-i", str(raw),
             "-af", "volume=%.2fdB" % gain,
             "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(path)])
        raw.unlink()
        print("  %-9s %.3f с, гейн %+.2f dB → %s"
              % (word, length, gain, path.name))
        out.append(path)
    flat.unlink()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cut", action="store_true",
                    help="заново нарезать числительные из заказа")
    args = ap.parse_args()
    if args.cut:
        cut_numerals()
        return 0
    ap.error("сборка дорожки появится в следующей задаче")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
