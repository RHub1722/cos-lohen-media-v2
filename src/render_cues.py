"""Дорожки голосовых подсказок и печатный лист ориентиров.

    python src/render_cues.py                    # все три якоря
    python src/render_cues.py --chain 0.31       # свой замер цепочки
    python src/render_cues.py --anchor laugh     # только один якорь

Что получается:

    output/rehearsal_cues_v2.wav    номер + голос поверх, для репетиции дома
    output/stage_cues_laugh.wav     в наушник, ловить первый смех
    output/stage_cues_picture.wav   в наушник, ловить появление картинки
    output/stage_cues_titles.wav    в наушник, ловить смену титров
    output/cue_sheet.md             печатный лист: что слышно и за сколько

Три дорожки, потому что play жмёт помощник за кулисами, а не исполнитель, и
чем он поймает старт — вопрос к площадке, а не к расчёту. Различаются только
сдвигом: слова и отбор считаются ДО него и потому общие.

Почему сценическая дорожка не содержит слова в точку контакта — в docstring
`src/cues.py`. Коротко: старт нажимается рукой, и слово в точку при промахе
вредит.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.cues import (ANCHORS, Cue, CueError, all_cues,  # noqa: E402
                      first_cues, lengths_of, resolve_overlaps, shift,
                      track_plan)
from src.measure import peak_db  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Задержка ЦЕПОЧКИ: нажатие кнопки плюс радиоканал до наушника. Свойство
# железа, одно на все три якоря, и потому отдельное от них.
#
# Заглушка: нажатие около 0.05 плюс Bluetooth, который по кодеку даёт
# 0.15-0.30 (SBC 0.15-0.25, AAC 0.15-0.20, aptX 0.08-0.15). Настоящее число
# даёт один замер, порядок в листе ориентиров.
CHAIN = 0.25

# Подложка под тишиной. Перенесено из src/render_count.py, где то же сделано
# для дорожки ризов: «наушники на тишине уходят в энергосбережение — первый
# риз пришёл бы обрезанным или не пришёл бы вовсе». Здесь между шестью словами
# паузы по 4-10 секунд, то есть болезнь та же.
#
# Оговорка оттуда переносится вместе с решением: это страховка, а не
# доказанное лечение, и проверяется только на его наушнике.
FLOOR_DB = -60.0

# Амплитуда генератора до приведения. Уровень ставится ЗАМЕРОМ, а не верой в
# этот параметр: цветной фильтр anoisesrc меняет пик непредсказуемо, и -60
# «на глаз» может оказаться и -48, и -72.
FLOOR_AMPLITUDE = 0.35

# Щелчок в начале дорожки. Помощник нажал — исполнитель услышал и знает, что
# канал жив и часы пошли. Обрыв Bluetooth на дальности в дорожке не лечится,
# но его можно сделать заметным сразу, а не на первом пропущенном слове.
#
# Не в нуле: первые ~0.2 с съедает пробуждение канала. На 0.30 щелчок звучит
# ПОСЛЕ пробуждения и тем доказывает, что оно случилось.
CLICK_AT = 0.30
CLICK_HZ = 1000
CLICK_LEN = 0.015
CLICK_DB = -12.0

# Та же папка, что у ризов: она целиком копируется в телефон, и держать две
# было бы приглашением взять на площадку не ту. Префикс разный намеренно — в
# одной папке должно быть видно, что это разные инструменты, а не варианты
# одного. Константы продублированы, а не импортированы: тянуть сборщик счёта
# в сборщик слов ради двух строк дороже, чем повторить их.
CUES_DIR = ROOT / "output" / "cues"
CUES_BITRATE = "128k"

# Провал номера под подсказкой в репетиционной дорожке. Глубоко: там важно
# слово, а не микс, и это единственный файл, который зал никогда не услышит.
DUCK_DB = 14.0
DUCK_ATTACK = 0.15
DUCK_RELEASE = 0.25

# Насколько подсказка громче номера. Это репетиция, голос главный.
CUE_GAIN_DB = 3.0


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True).stdout.strip()
    if not out:
        raise SystemExit(f"не читается длительность {path}")
    return float(out)


def duck_expression(cues: list[Cue], lengths: dict[str, float]) -> str:
    """Трапеция на каждую подсказку, наложения берутся по максимуму.

    Та же форма, что у провала музыки под ударами в `filtergraph`, но короче:
    там полка 0.30 с под транзиент, здесь полка равна длине слова. Складывать
    провалы нельзя — два подряд ушли бы в тишину.
    """
    if not cues:
        return ""
    depth = 1.0 - 10.0 ** (-DUCK_DB / 20.0)
    terms = []
    for cue in cues:
        a = max(0.0, cue.t - DUCK_ATTACK)
        b = cue.t + lengths[cue.word] + DUCK_RELEASE
        env = (f"max(0\\,min(1\\,min((t-{a:.4f})/{DUCK_ATTACK:.4f}\\,"
               f"({b:.4f}-t)/{DUCK_RELEASE:.4f})))")
        terms.append(f"{depth:.6f}*{env}")
    deepest = terms[0]
    for term in terms[1:]:
        deepest = f"max({deepest}\\,{term})"
    return f"1-({deepest})"


def floor_track(work: Path, total: float) -> tuple[Path, float]:
    """Розовый шум подо всей дорожкой и усиление до FLOOR_DB.

    Возвращает файл и то, на сколько его поднять. Отдельным файлом, а не
    фильтром на лету, потому что уровень выставляется замером пика, а
    замерить можно только записанное.

    Шум идёт до конца номера, а не до последнего слова, и файл из-за этого
    вырос с 45 до 59 секунд. Так и надо. Раньше дорожка обрывалась сразу за
    «готовь» на 45.98 — это экономило треть мегабайта и ничего больше. Теперь
    конец файла совпадает с концом номера, и у помощника появляется признак,
    которого не было: дорожка кончилась вместе с выступлением, значит она шла
    в ногу с ним.
    """
    path = work / "floor.wav"
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"anoisesrc=d={total:.4f}:c=pink:r=48000:a={FLOOR_AMPLITUDE}",
         "-ac", "1", "-c:a", "pcm_s24le", str(path)],
        capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"ffmpeg подложка: {done.stderr[-1500:]}")
    return path, FLOOR_DB - peak_db(path)


def click_track(work: Path) -> tuple[Path, float]:
    """Щелчок подтверждения и усиление до CLICK_DB.

    Уровень ставится ЗАМЕРОМ, как у подложки, и по той же причине, только
    здесь она злее: генератор `sine` в ffmpeg выдаёт не полную шкалу, а
    восьмую её часть — голый тон меряется на -18.1 dBFS. Написанное в
    константе `volume=-12dB` считалось бы от этих -18, и щелчок выходил на
    -33 dBFS, то есть на 27 dB тише слов: тихий тик вместо подтверждения.
    Константа обязана значить то, что в ней написано.

    Фейды по 2 мс: без них у щелчка появятся собственные щелчки на обрыве
    синуса, и он выйдет грязнее того, что обозначает. Пик они не трогают —
    он в середине пятнадцатимиллисекундного тона.

    В готовом файле щелчок меряется на -15, а не на -12: три децибела съедает
    раскладка моно в стерео внутри `amix`. Гнаться за ними незачем — важно
    отношение, а оно верное: щелчок на 9 dB тише слов и на 61 dB громче
    подложки. Слышен, но не бьёт по уху.
    """
    path = work / "click.wav"
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={CLICK_HZ}:duration={CLICK_LEN}"
               f":sample_rate=48000",
         "-af", f"afade=t=in:d=0.002,"
                f"afade=t=out:st={CLICK_LEN - 0.002:.4f}:d=0.002",
         "-ac", "1", "-c:a", "pcm_s24le", str(path)],
        capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"ffmpeg щелчок: {done.stderr[-1500:]}")
    return path, CLICK_DB - peak_db(path)


def render(cues: list[Cue], out: Path, total: float, assets: Path,
           bed: Path | None, channels: int = 2, floor: bool = False,
           click: bool = False) -> None:
    """Собирает дорожку: слова через adelay, при наличии — поверх номера.

    channels=1 для сценической: она едет в один наушник, второе ухо обязано
    слышать зал. Моно и вдвое меньше файл на телефоне.

    floor=True тоже только для сценической: подложка нужна там, где дорожка
    идёт по Bluetooth и подолгу молчит. У репетиционной под словами играет
    номер, тишины нет вовсе, и подложка была бы мусором в файле.

    click=True тоже только для сценической: дома по проводу канал не рвётся,
    и подтверждать нечего.
    """
    if not cues:
        raise SystemExit("ни одной подсказки — нечего собирать")

    lengths = lengths_of(assets, [c.word for c in cues], ffprobe_duration)

    with tempfile.TemporaryDirectory(prefix="cues_") as tmp:
        work = Path(tmp)
        inputs: list[str] = []
        if bed is not None:
            inputs += ["-i", str(bed)]
        for cue in cues:
            inputs += ["-i", str(assets / f"cues/cue_{cue.word}.wav")]

        base = 1 if bed is not None else 0
        parts = []
        labels = []
        for i, cue in enumerate(cues):
            ms = int(round(cue.t * 1000.0))
            parts.append(f"[{base + i}:a]adelay={ms}|{ms},"
                         f"volume={CUE_GAIN_DB}dB[c{i}]")
            labels.append(f"[c{i}]")

        if bed is not None:
            expr = duck_expression(cues, lengths)
            parts.append(f"[0:a]volume='{expr}':eval=frame[bed]")
            labels.insert(0, "[bed]")

        if floor:
            path, gain = floor_track(work, total)
            inputs += ["-i", str(path)]
            parts.append(f"[{base + len(cues)}:a]volume={gain:.2f}dB[floor]")
            labels.append("[floor]")

        if click:
            tick, tick_gain = click_track(work)
            inputs += ["-i", str(tick)]
            idx = base + len(cues) + (1 if floor else 0)
            ms = int(round(CLICK_AT * 1000.0))
            parts.append(f"[{idx}:a]adelay={ms}|{ms},"
                         f"volume={tick_gain:.2f}dB[click]")
            labels.append("[click]")

        n = len(labels)
        parts.append("".join(labels) + f"amix=inputs={n}:normalize=0:"
                     f"dropout_transition=0[mix]")
        # Обрезка по длине номера обязательна: adelay продлевает поток, и
        # последнее слово вытянуло бы файл за 60 с.
        parts.append(f"[mix]atrim=0:{total:.4f},asetpts=N/SR/TB[out]")

        cmd = (["ffmpeg", "-v", "error", "-y"] + inputs
               + ["-filter_complex", ";".join(parts), "-map", "[out]"]
               + ["-ar", "48000", "-ac", str(channels),
                  "-c:a", "pcm_s24le", str(out)])
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode:
            raise SystemExit(f"ffmpeg: {done.stderr[-1500:]}")


def sheet(kept: list[Cue], dropped: list[Cue], first: list[Cue],
          chain: float, strikes) -> str:
    """Печатный лист. Пишется здесь, а не в шаблоне: он весь из чисел."""
    contacts = {}
    for strike in strikes:
        earliest = min((b.heard for b in strike.beats if b.role == "contact"),
                       default=None)
        if earliest is not None:
            contacts[strike.id] = earliest

    lines = [
        "# Лист ориентиров: когда наносить удары",
        "",
        "Сгенерирован `python src/render_cues.py`. Времена — из долей",
        "`scenario/strikes.json`, то есть из того же источника, что тренажёр.",
        "Руками здесь править нечего: сдвинется удар в сценарии — уедет и лист.",
        "",
        "## Главное правило",
        "",
        "На удар реагировать нельзя. Реакция на звук 0.15–0.20 с, взмах копьём",
        "от покоя 0.3–0.6 с: к моменту контакта движение уже должно идти.",
        "Поэтому ориентир всегда стоит на подготовке, а не на попадании.",
        "",
        "## Три дорожки: чем ловить старт",
        "",
        "Play жмёт помощник за кулисами, а не исполнитель. Чем он поймает",
        "начало номера — вопрос к площадке, поэтому собраны все три, а выбор",
        "делается на месте и ДО выхода.",
        "",
        "| файл | ловить | чем | в номере | сдвиг |",
        "|---|---|---|---|---|",
    ]
    for anchor, start_at in track_plan(None, chain):
        lines.append(f"| `stage_cues_{anchor.key}.wav` | {anchor.catch} | "
                     f"{anchor.sense} | {anchor.t:.2f} | {start_at:.2f} |")

    lines += [
        "",
        f"Сдвиг = время якоря + реакция (ухо 0.16, глаз 0.20) + цепочка "
        f"{chain:.2f}.",
        "",
        "Слова в точку контакта нет ни в одной намеренно: старт нажимается",
        "рукой, и слово в точку при промахе вредит. Контакт несёт сам номер.",
        "",
        "**Рабочее окно старта — ±0.2 с.** При опоздании на 0.2 с у «пошёл»",
        "остаётся 0.18 с опережения: подсказка сжимается, но помогает. При",
        "0.38 с слово ложится ровно в контакт и начинает вредить.",
        "",
        "В начале каждой дорожки стоит щелчок. Услышал — канал жив и часы",
        "пошли. Не услышал — Bluetooth оборвался, и подсказок не будет вовсе.",
        "",
        "## Слова и опережение",
        "",
        "| слово | в номере | действие | до первого контакта |",
        "|---|---|---|---|",
    ]
    for cue in first:
        c = contacts.get(cue.strike)
        gap = f"{c - cue.t:.2f} с" if c is not None else "—"
        lines.append(f"| **{cue.text}** | {cue.t:.2f} | {cue.strike} | {gap} |")

    lines += [
        "",
        "## Репетиционная дорожка: все доли, какие влезли",
        "",
        "`output/rehearsal_cues_v2.wav` — номер плюс голос поверх. Только для",
        "репетиции: старта на сцене здесь нет, промаха нет, слова стоят точно.",
        "",
        "| время | слово | роль | действие |",
        "|---|---|---|---|",
    ]
    for cue in kept:
        lines.append(f"| {cue.t:.2f} | **{cue.text}** | {cue.role} | "
                     f"{cue.strike} |")

    if dropped:
        lines += [
            "",
            "### Что снято и почему",
            "",
            "Доли идут плотнее, чем произносятся слова: у первой вспышки четыре",
            "доли укладываются в 1.47 с, а четыре слова занимают 1.8 с. Снятое",
            "перечислено, чтобы не ждать слова, которого не будет. При наложении",
            "остаётся более важная роль, и подготовка важнее контакта: контакт",
            "слышен сам — в этот момент играет удар, — а подготовку не слышит",
            "никто, кроме подсказки.",
            "",
            "| время | слово | роль | действие |",
            "|---|---|---|---|",
        ]
        for cue in dropped:
            lines.append(f"| {cue.t:.2f} | {cue.text} | {cue.role} | "
                         f"{cue.strike} |")

    lines += [
        "",
        "## Как замерить задержку цепочки",
        "",
        "Замер ОДИН на все три дорожки: мерится цепочка — нажатие плюс",
        "радиоканал, — а она от якоря не зависит. В этом весь смысл того, что",
        "якорь и цепочка считаются врозь.",
        "",
        "1. Включи номер в зале или на колонках, телефон помощника — в руке.",
        "2. Возьми любую из трёх дорожек и жми play на её якоре.",
        "3. Пиши на диктофон второго устройства сразу и зал, и наушник",
        "   (наушник поднеси к микрофону).",
        "4. В записи найди якорь и ЩЕЛЧОК в начале дорожки. Разница минус",
        "   время якоря минус реакция и есть цепочка.",
        "5. Пересобери с ней: `python src/render_cues.py --chain ЧИСЛО`.",
        "",
        "Готовый инструмент для того же замера уже есть у дорожки ризов:",
        "`output/cues/lohen_cues_riser_sync.m4a` кладёт номер тихим фоном, и",
        "расхождение двух копий одного звука слышно как хлопок. Ею ловятся и",
        "промах пуска, и задержка наушника разом.",
        "",
        f"Сейчас цепочка стоит на заглушке {chain:.2f} с.",
        "",
        "Задержка меняется при переподключении наушника: кодек",
        "перевыбирается, и число становится другим. Мерить надо перед самым",
        "выходом и после этого наушник не трогать.",
        "",
        "## Чего эти дорожки не заменяют",
        "",
        "Прогон под запись. Все подготовительные точки в `strikes.json`",
        "поставлены по книжным 0.3–0.6 с на взмах. Твои числа могут отличаться",
        "вдвое, и тогда сдвигать надо доли, а не подсказки: подсказки",
        "пересчитаются сами.",
        "",
    ]
    return "\n".join(lines)


def publish(made: list[Path]) -> list[Path]:
    """m4a в папку телефона. Несжатых там быть не должно: три файла по 8 МБ
    в телефоне ни к чему, а разницы в наушнике на 128k нет.
    """
    CUES_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for src in made:
        key = src.stem.replace("stage_cues_", "")
        dst = CUES_DIR / f"lohen_words_{key}.m4a"
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-c:a", "aac", "-b:a", CUES_BITRATE, "-ac", "1", str(dst)],
            capture_output=True, text=True)
        if done.returncode:
            raise SystemExit(f"ffmpeg m4a: {done.stderr[-1500:]}")
        out.append(dst)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", default=str(ROOT / "scenario" / "timeline.json"))
    ap.add_argument("--strikes", default=str(ROOT / "scenario" / "strikes.json"))
    ap.add_argument("--movements", default=str(ROOT / "scenario" / "movements.json"))
    ap.add_argument("--assets", default=str(ROOT / "assets"))
    # Фонограмма номера, а не наш мастер: с 8 августа звучит ручное сведение из
    # монтажки. Под репетиционную дорожку кладётся то, подо что выступают, —
    # иначе подсказки лягут поверх звука, которого на площадке не будет.
    ap.add_argument("--master", default=str(ROOT / "output" / "master_ru_fx.wav"))
    ap.add_argument("--out", default=str(ROOT / "output"))
    ap.add_argument("--anchor", choices=sorted(ANCHORS), default=None,
                    help="чем ловить старт; без него собираются все три")
    ap.add_argument("--chain", type=float, default=CHAIN,
                    help="задержка цепочки: нажатие плюс радиоканал")
    ap.add_argument("--start-at", type=float, default=None,
                    help="прямое переопределение суммы, в обход якоря и цепочки")
    args = ap.parse_args()

    # План дорожек считается ДО первого рендера. Иначе неверная пара аргументов
    # обнаружится через минуту сборки репетиционной дорожки, а не сразу. И
    # CueError ловится здесь: пользователю нужно сообщение, а не трассировка.
    try:
        plan = track_plan(args.anchor, args.chain, args.start_at)
    except CueError as err:
        raise SystemExit(str(err))

    tl = Timeline.load(args.scenario)
    assets = Path(args.assets)
    # Только эффекты: у долей опорами стоят удары и взмахи, а замер пика на
    # шестнадцатисекундной музыкальной подложке ничего не значит и стоит времени.
    peaks = peak_offsets(assets, sorted({e.asset for e in tl.events
                                         if e.stem == "sfx"}))
    moves = [m.id for m in resolve_times(load_movements(args.movements), tl)]
    strikes = resolve_strikes(load_strikes(args.strikes), tl, peaks, moves)

    every = all_cues(strikes)
    lengths = lengths_of(assets, [c.word for c in every], ffprobe_duration)
    kept, dropped = resolve_overlaps(every, lengths)
    first = first_cues(strikes)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"действий {len(strikes)}, долей {len(every)}, "
          f"подсказок в репетиционной {len(kept)}, снято {len(dropped)}")
    for cue in kept:
        print(f"  {cue.t:6.2f}  {cue.text:9} {cue.role:8} {cue.strike}")
    if dropped:
        print("снято из-за наложения:")
        for cue in dropped:
            print(f"  {cue.t:6.2f}  {cue.text:9} {cue.role:8} {cue.strike}")

    master = Path(args.master)
    if not master.exists():
        raise SystemExit(f"нет мастера {master}. Сначала python src/build.py")
    render(kept, out / "rehearsal_cues_v2.wav", tl.total_duration, assets,
           master)

    made: list[Path] = []
    for anchor, start_at in plan:
        stage = shift(first, start_at)
        path = out / f"stage_cues_{anchor.key}.wav"
        print(f"\n{anchor.key}: ловить {anchor.catch} ({anchor.sense}), "
              f"сдвиг {start_at:.2f} с, {len(stage)} слов")
        for cue in stage:
            print(f"  файл {cue.t:6.2f}  номер {cue.t + start_at:6.2f}  "
                  f"{cue.text:9} {cue.strike}")
        render(stage, path, tl.total_duration - start_at, assets, None,
               channels=1, floor=True, click=True)
        made.append(path)

    print("\nв телефон помощнику:")
    for path in publish(made):
        print(f"  {path.name}  {path.stat().st_size / 1e6:.2f} МБ")
    print(f"  лежат в {CUES_DIR}")

    text = sheet(kept, dropped, first, args.chain, strikes)
    (out / "cue_sheet.md").write_text(text, encoding="utf-8")

    for path in [out / "rehearsal_cues_v2.wav"] + made:
        print(f"\n{path}  {ffprobe_duration(path):.3f} с, "
              f"{path.stat().st_size / 1e6:.1f} МБ")
    print(f"{out / 'cue_sheet.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
