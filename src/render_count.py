"""Три дорожки подсказок плюс печатный лист ориентиров.

    python src/render_count.py --cut               # нарезать числительные
    python src/render_count.py                     # собрать все три дорожки
    python src/render_count.py --site --video      # копии для страницы и ролики
    python src/render_count.py --only riser        # одну дорожку по ключу

Третий инструмент рядом с двумя от 5 августа, и задача у него другая. Слово
подсказки стоит на доле и говорит, ЧТО делать. Цифра счёта идёт равномерно и
говорит, ГДЕ ты. Совместить их в одном файле нельзя: на шаге 0.5 с между двумя
цифрами слову «готовь» негде поместиться.

Дорожек три, и выбирать между ними исполнителю: счёт в правое ухо, счёт в оба
уха, и только нарастающий шум без счёта вовсе. Чем они отличаются и почему —
в TRACKS. Отдельные ролики нужны не странице (та переключает дорожки поверх
одного видео), а телефону: положить в галерею и гонять без сайта и без сети.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.counting import (STEP, WORDS, assign, collisions,  # noqa: E402
                          repeated_digits, risers)
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.strikes import ROLE_NAMES, load_strikes, resolve_strikes  # noqa: E402

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

# Фонограмма номера, а не наш мастер: с 8 августа звучит ручное сведение из
# монтажки. Кладём то, подо что выступают.
SOUNDTRACK = ROOT / "output/master_ru_fx.wav"
SHEET = ROOT / "output/count_sheet.md"
TOTAL = 60.0

# Сжатая копия для страницы: m4a на 96k. Второго видео не собирается — страница
# играет то же видео с выключенным звуком и переключает эти дорожки.
SITE_BITRATE = "96k"

# Насколько уходит вниз номер под НЕПРЕРЫВНЫМ счётом. Девять, а не четырнадцать
# как в репетиционной дорожке: глубже — и пропадает сам звук удара, по которому
# проверяется попадание, то есть дорожка отменяет собственную задачу.
DUCK_DB = 9.0
RISER_DB = -9.0

PAN_RIGHT = "pan=stereo|c0=0*c0|c1=c0"
PAN_BOTH = "pan=stereo|c0=c0|c1=c0"

# Три дорожки, между которыми переключается страница. Различаются тремя вещами:
# идёт ли счёт, куда уходят подсказки и приглушается ли номер.
#
# У варианта «только риз» номер приглушается НЕ постоянно, а провалом под самим
# ризом, и это не прихоть. Постоянные 9 dB существовали ради непрерывного счёта:
# без них негде было бы услышать сто двадцать цифр. Риз звучит шесть раз по 1.2
# секунды, и ронять под него весь номер на минуту значит портить то, подо что
# выступают. Совсем без провала тоже нельзя: номер стоит на -2.00 dBTP, и сумма
# с ризом упёрлась в потолок — замерено, 0.00 dBTP.
#
# Провал отпускает ровно НА контакте, а не после: риз кончается в удар, и
# приглушить сам удар значило бы убрать тот звук, под который надо попасть.
# Сам риз идёт громче — на 6 dB вместо 9, — и этого хватает, потому что он
# сидит выше самой занятой полосы номера: в окнах ризов у фонограммы 63%
# энергии ниже 200 Гц, а центр спектра риза 2.8 кГц.
#
# У стереоварианта подсказки получают -3 dB: моно, разложенное в оба канала,
# звучит на те же три децибела громче, чем оно же в одном ухе.
TRACKS = (
    {"key": "right", "name": "счёт в правое ухо", "count": True,
     "pan": PAN_RIGHT, "duck": DUCK_DB, "cue_db": 0.0,
     "hint": "левое ухо слышит номер чистым: вынул правый наушник — и ты на сцене"},
    {"key": "stereo", "name": "счёт в оба уха", "count": True,
     "pan": PAN_BOTH, "duck": DUCK_DB, "cue_db": -3.0,
     "hint": "счёт по центру, номер тише на 9 dB"},
    {"key": "riser", "name": "только риз, без счёта", "count": False,
     "pan": PAN_BOTH, "duck": "risers", "cue_db": 3.0,
     "hint": "номер цел, провал только под ризом и отпускает в удар"},
)


def track_path(key: str) -> Path:
    return ROOT / "output" / ("count_%s.wav" % key)


def site_path(key: str) -> Path:
    return ROOT / "site" / ("count_%s.m4a" % key)


def video_path(key: str) -> Path:
    return ROOT / "output" / ("count_%s.mp4" % key)


# Картинка для отдельного видео берётся из сжатой копии страницы и КОПИРУЕТСЯ
# потоком: пересчитывать её незачем, а 960x540 хватает, чтобы видеть, где
# вспышка. Так файл выходит около пяти мегабайт вместо тридцати одного.
SITE_VIDEO = ROOT / "site/lohen-60s.mp4"


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


def build_cycle(work: Path) -> Path:
    """Один цикл счёта длиной ровно CYCLE*STEP секунд.

    Цикл собирается отдельно и потом зацикливается: 60 с делятся на 5.000 с
    ровно 12 раз, поэтому склейка попадает точно в границу, а входов у FFmpeg
    остаётся десять вместо ста двадцати.
    """
    parts, labels, inputs = [], [], []
    for i in range(len(WORDS)):
        inputs += ["-i", str(OUT_DIR / ("count_%02d.wav" % (i + 1)))]
        ms = int(round(i * STEP * 1000))
        parts.append("[%d:a]adelay=%d[c%d]" % (i, ms, i))
        labels.append("[c%d]" % i)
    parts.append("".join(labels) + "amix=inputs=%d:normalize=0:"
                 "dropout_transition=0[m]" % len(labels))
    parts.append("[m]apad,atrim=0:%.4f,asetpts=N/SR/TB[out]"
                 % (len(WORDS) * STEP))
    out = work / "cycle.wav"
    run(["ffmpeg", "-v", "error", "-y"] + inputs
        + ["-filter_complex", ";".join(parts), "-map", "[out]",
           "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)])
    return out


def build_count(work: Path) -> Path:
    """Счёт на весь номер: цикл, повторённый нужное число раз."""
    cycle = build_cycle(work)
    times = int(round(TOTAL / (len(WORDS) * STEP)))
    if abs(times * len(WORDS) * STEP - TOTAL) > 1e-6:
        raise SystemExit(
            "цикл %.3f с не укладывается в %.3f с целое число раз — "
            "склейка попадёт внутрь цифры" % (len(WORDS) * STEP, TOTAL))
    out = work / "count.wav"
    run(["ffmpeg", "-v", "error", "-y", "-stream_loop", str(times - 1),
         "-i", str(cycle), "-t", "%.4f" % TOTAL,
         "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)])
    return out


def build_risers(work: Path, rows: list[dict]) -> Path:
    """Шесть нарастающих шумов: чирп плюс розовый шум под общей огибающей.

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
    parts.append("[m]apad,atrim=0:%.4f,asetpts=N/SR/TB[out]" % TOTAL)
    out = work / "risers.wav"
    run(["ffmpeg", "-v", "error", "-y"] + inputs
        + ["-filter_complex", ";".join(parts), "-map", "[out]",
           "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(out)])
    return out


# Провал номера ПОД РИЗОМ, для дорожки без счёта. Форма та же, что у провала
# музыки под ударами в src/filtergraph.py, но отпускает он не после события, а
# ровно НА нём: риз кончается в контакт, и приглушить сам контакт значило бы
# убрать тот звук, под который надо попасть.
RISER_DUCK_DB = 8.0
RISER_DUCK_IN = 0.30
RISER_DUCK_OUT = 0.10


def riser_duck(rows: list[dict]) -> str:
    """Выражение для volume: единица везде, провал на время каждого риза.

    Провалы берутся по максимуму, а не складываются: два подряд ушли бы в
    тишину. Здесь ризы не пересекаются, но правило то же, что у слов.
    """
    depth = 1.0 - 10.0 ** (-RISER_DUCK_DB / 20.0)
    terms = []
    for row in rows:
        a = row["start"]
        b = row["peak"] + 0.05
        env = (r"max(0\,min(1\,min((t-%.4f)/%.4f\,(%.4f-t)/%.4f)))"
               % (a, RISER_DUCK_IN, b, RISER_DUCK_OUT))
        terms.append("%.6f*%s" % (depth, env))
    deepest = terms[0]
    for term in terms[1:]:
        deepest = r"max(%s\,%s)" % (deepest, term)
    return "1-(%s)" % deepest


def build_track(work: Path, rows: list[dict], spec: dict,
                cue_db: float = 0.0) -> Path:
    """Свести одну дорожку по её описанию из TRACKS.

    Ограничителя нет намеренно. С ним левый канал варианта «в правое ухо»
    перестал бы совпадать с приглушённым номером бит в бит, а это единственная
    проверка, которая доказывает, что в левое ухо не попала ни одна подсказка.
    Запас проверяется замером, и если его не хватит, вниз идёт один линейный
    гейн на подсказки — так же, как сделан запас у мастера 8 августа.
    """
    risers_wav = build_risers(work, rows)
    out = track_path(spec["key"])
    out.parent.mkdir(parents=True, exist_ok=True)
    gain = spec["cue_db"] + cue_db

    inputs = ["-i", str(SOUNDTRACK)]
    cue_src = "[1:a]"
    if spec["count"]:
        inputs += ["-i", str(build_count(work)), "-i", str(risers_wav)]
        cue_src = ("[1:a][2:a]amix=inputs=2:normalize=0:"
                   "dropout_transition=0,")
    else:
        inputs += ["-i", str(risers_wav)]
        cue_src = "[1:a]"

    if spec["duck"] == "risers":
        bed = "[0:a]volume='%s':eval=frame,atrim=0:%.4f[bed]" % (
            riser_duck(rows), TOTAL)
    else:
        bed = "[0:a]volume=-%.1fdB,atrim=0:%.4f[bed]" % (spec["duck"], TOTAL)
    parts = [bed]
    parts.append("%svolume=%.2fdB,%s[cue]" % (cue_src, gain, spec["pan"]))
    parts.append("[bed][cue]amix=inputs=2:normalize=0:dropout_transition=0,"
                 "atrim=0:%.4f,asetpts=N/SR/TB[out]" % TOTAL)

    run(["ffmpeg", "-v", "error", "-y"] + inputs
        + ["-filter_complex", ";".join(parts), "-map", "[out]",
           "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(out)])
    return out


def publish(keys) -> list[Path]:
    """Сжатые копии для страницы."""
    out = []
    for key in keys:
        src, dst = track_path(key), site_path(key)
        if not src.exists():
            raise SystemExit("нет %s: сначала python src/render_count.py" % src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-c:a", "aac", "-b:a", SITE_BITRATE, str(dst)])
        print("  %s  %.2f МБ" % (dst.name, dst.stat().st_size / 1e6))
        out.append(dst)
    return out


def build_video(key: str) -> Path:
    """Отдельный ролик: картинка копируется потоком, меняется только звук.

    Нужен не странице — та переключает дорожки поверх одного видео, — а
    телефону: положить в галерею и гонять без сайта и без сети.
    """
    if not SITE_VIDEO.exists():
        raise SystemExit("нет %s: python src/render_training.py --site"
                         % SITE_VIDEO)
    src, out = track_path(key), video_path(key)
    if not src.exists():
        raise SystemExit("нет %s: сначала python src/render_count.py" % src)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(SITE_VIDEO), "-i", str(src),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-shortest", str(out)])
    print("  %s  %.1f МБ" % (out.name, out.stat().st_size / 1e6))
    return out


def sheet(strikes) -> str:
    """Печатный лист. Пишется здесь, а не в шаблоне: он весь из чисел."""
    rows = assign(strikes)
    # Лист читает человек, а не программа, поэтому в нём стоит название приёма,
    # а не ключ вроде burst_1. Берётся часть до двоеточия: полное название
    # («Вспышка 3: полный оборот, два попадания, низкий выпад») в столбец
    # таблицы не влезает.
    names = {s.id: s.title.split(":")[0].strip() for s in strikes}
    lines = [
        "# Лист счёта: какой удар на какой цифре",
        "",
        "Собран `python src/render_count.py`. Времена — из долей",
        "`scenario/strikes.json`, то есть из того же источника, что тренажёр.",
        "Руками здесь править нечего: сдвинется удар в сценарии — уедет и лист.",
        "",
        "## Как этим пользоваться",
        "",
        "Счёт идёт два раза в секунду и не замолкает. Цикл из десяти цифр",
        "длится ровно пять секунд, поэтому **«один» приходится на каждой",
        "круглой пятёрке** таймера: 0, 5, 10 и так далее. Потерялся — дождись",
        "«один» и посмотри на таймер.",
        "",
        "Счёт говорит, ГДЕ ты. Точный момент удара говорит нарастающий шум:",
        "его вершина стоит ровно в контакт. Цифра — координата, риз — попадание.",
        "",
        "Всё это звучит только в правом ухе. Левое слышит номер чистым.",
        "",
        "## Восемь ударов",
        "",
        "| время | приём | цифра | промах |",
        "|---|---|---|---|",
    ]
    for row in rows:
        if row["role"] == "contact":
            lines.append("| %.2f | %s | **«%s»** | %+.3f с |"
                         % (row["t"], names[row["strike"]], row["word"],
                            row["miss"]))

    repeats = repeated_digits(strikes)
    if repeats:
        lines += [
            "",
            "### Одна цифра на два удара",
            "",
            "Это не ошибка: удары стоят в разных цикла́х, между ними целых пять",
            "секунд, и у каждого свой риз. Но знать стоит.",
            "",
        ]
        for word, times in sorted(repeats.items()):
            lines.append("- **«%s»** — это и %s"
                         % (word, ", и ".join("%.2f" % t for t in times)))

    hits = collisions(strikes)
    lines += [
        "",
        "## Доли, которые делят одну цифру",
        "",
        "Цена темпа два раза в секунду. Самые тесные доли номера стоят в 0.21 с",
        "друг от друга, а шаг счёта 0.5 с — значит счёт их не различает.",
        "Перечислены все, чтобы не ждать цифру, которой не будет.",
        "",
        "| цифра | доли |",
        "|---|---|",
    ]
    for word, beats in hits:
        what = ", ".join("%.2f %s, %s" % (b["t"], names[b["strike"]],
                                          ROLE_NAMES.get(b["role"], b["role"]))
                         for b in beats)
        lines.append("| «%s» | %s |" % (word, what))

    lines += [
        "",
        "## Все двадцать шесть долей",
        "",
        "| время | приём | роль | цифра | промах |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| %.2f | %s | %s | «%s» | %+.3f с |"
                     % (row["t"], names[row["strike"]],
                        ROLE_NAMES.get(row["role"], row["role"]),
                        row["word"], row["miss"]))

    lines += [
        "",
        "## Чего этот лист не заменяет",
        "",
        "Прогон под запись. Подготовительные доли в `strikes.json` поставлены",
        "по книжным 0.3–0.6 с на взмах. Твои числа могут отличаться вдвое, и",
        "тогда сдвигать надо доли: цифры и ризы пересчитаются сами.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cut", action="store_true",
                    help="заново нарезать числительные из заказа")
    ap.add_argument("--cue-db", type=float, default=0.0,
                    help="общий гейн на слой подсказок поверх того, что "
                         "задан у дорожки, если не хватило запаса по пикам")
    ap.add_argument("--site", action="store_true",
                    help="сжать копии для страницы тренажёра")
    ap.add_argument("--video", action="store_true",
                    help="собрать отдельные ролики: картинка копируется, "
                         "меняется только звук")
    ap.add_argument("--only", default="",
                    help="собрать одну дорожку по ключу: %s"
                         % ", ".join(t["key"] for t in TRACKS))
    args = ap.parse_args()
    if args.cut:
        cut_numerals()
        return 0

    specs = [t for t in TRACKS if not args.only or t["key"] == args.only]
    if not specs:
        raise SystemExit("нет дорожки с ключом %r, есть %s"
                         % (args.only, [t["key"] for t in TRACKS]))

    tl = Timeline.load(ROOT / "scenario/timeline.json")
    assets = ROOT / "assets"
    peaks = peak_offsets(assets, sorted({e.asset for e in tl.events
                                         if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(
        load_movements(ROOT / "scenario/movements.json"), tl)]
    strikes = resolve_strikes(
        load_strikes(ROOT / "scenario/strikes.json"), tl, peaks, moves)

    if not SOUNDTRACK.exists():
        raise SystemExit("нет фонограммы %s" % SOUNDTRACK)
    if not (OUT_DIR / "count_01.wav").exists():
        raise SystemExit("числительные не нарезаны: "
                         "python src/render_count.py --cut")

    rows = risers(strikes)
    work = ROOT / "output" / "count_work"
    work.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        out = build_track(work, rows, spec, args.cue_db)
        print("%-22s %s  пик %.2f dBTP  (%s)"
              % (spec["name"], out.name, peak_db(out), spec["hint"]))
    print("ризы:")
    for row in rows:
        print("  %-13s %.2f → %.2f" % (row["strike"], row["start"],
                                       row["peak"]))

    SHEET.write_text(sheet(strikes), encoding="utf-8")
    print("%s" % SHEET)
    for word, beats in collisions(strikes):
        print("  делят «%s»: %s" % (word, ", ".join(
            "%.2f %s" % (b["t"], b["role"]) for b in beats)))

    keys = [t["key"] for t in specs]
    if args.site:
        print("для страницы:")
        publish(keys)
    if args.video:
        print("ролики:")
        for key in keys:
            build_video(key)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
