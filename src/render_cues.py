"""Дорожки голосовых подсказок и печатный лист ориентиров.

    python src/render_cues.py                    # все три якоря
    python src/render_cues.py --chain 0.31       # свой замер цепочки
    python src/render_cues.py --anchor laugh     # только один якорь

Что получается:

    output/rehearsal_cues_v2.wav    номер + голос поверх, для репетиции дома
    output/stage_cues_laugh.wav     в наушник, ловить первый смех
    output/stage_cues_picture.wav   в наушник, ловить появление картинки
    output/stage_cues_titles.wav    в наушник, ловить смену титров
    output/stage_cues_*_sync.wav    то же плюс номер тихим фоном, под замер
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

from src.cues import (ANCHORS, CHAIN, Anchor, Cue,  # noqa: E402
                      CueError, all_cues, first_cues, lengths_of,
                      resolve_overlaps, shift, track_plan)
from src.counting import risers  # noqa: E402
from src.measure import peak_db  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.risers import build_risers, shift_rows  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

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

# Пик слоя ризов в сценической дорожке. Ставится замером, как подложка и
# щелчок: у синтезированного слоя свой уровень, предсказать его нельзя.
#
# Минус шесть, а не минус два, как у дорожки ризов из сборщика счёта: там риз
# единственное содержимое файла, здесь под ним живёт щелчок на -15, и разница
# в девять децибел между ними должна остаться той же, что была у слов.
RISER_PEAK_DB = -6.0

# Номер тихим фоном в сверочной копии. Она не для тренировки: две копии
# одного звука с расхождением слышны как хлопок, и это самый точный слуховой
# признак времени, какой есть у человека. По ней ловится и промах пуска, и
# задержка наушника — разом и без диктофона.
#
# Число взято у дорожки ризов, где та же копия делается с 17 августа.
GHOST_DB = -24.0

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

    Шум идёт до конца номера, а не до последнего слова, и файлы из-за этого
    выросли: 58.89, 59.55 и 54.55 секунды против прежних сорока с небольшим —
    у каждого якоря своё, это ровно 60 минус его сдвиг. Так и надо. Раньше
    дорожка обрывалась сразу за «готовь» на 45.98 — это экономило треть
    мегабайта и ничего больше. Теперь
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
           click: bool = False, ghost: Path | None = None,
           ghost_at: float = 0.0,
           riser_rows: list[dict] | None = None) -> None:
    """Собирает дорожку: слова через adelay, при наличии — поверх номера.

    channels=1 для сценической: она едет в один наушник, второе ухо обязано
    слышать зал. Моно и вдвое меньше файл на телефоне.

    floor=True тоже только для сценической: подложка нужна там, где дорожка
    идёт по Bluetooth и подолгу молчит. У репетиционной под словами играет
    номер, тишины нет вовсе, и подложка была бы мусором в файле.

    click=True тоже только для сценической: дома по проводу канал не рвётся,
    и подтверждать нечего.

    ghost — номер тихим фоном, для сверочной копии. От `bed` отличается двумя
    вещами: уровнем и тем, что под словами он не проваливается. Его не слушают
    — его сравнивают: две копии одного звука, разошедшиеся во времени, слышны
    как хлопок, и это самый точный слуховой признак времени, какой есть у
    человека. ghost_at — с какой секунды НОМЕРА начинается файл; у сверочной
    копии он тот же, что у дорожки, которую она проверяет.

    riser_rows вместо слов: сценическая дорожка несёт не слова, а нарастающие
    шумы, каждый с вершиной ровно в свой контакт. Слово даёт точку — «сейчас»,
    — а риз даёт разгон, по которому едешь. Слова остаются в репетиционной
    дорожке, где они и осмысленны.
    """
    if not cues and riser_rows is None:
        raise SystemExit("ни одной подсказки — нечего собирать")

    # Длины слов нужны только провалу номера под ними, то есть только
    # репетиционной дорожке. Считать их для сценической значило бы шесть
    # лишних вызовов ffprobe за прогон ради числа, которое никто не спросит.
    lengths = (lengths_of(assets, [c.word for c in cues], ffprobe_duration)
               if bed is not None else {})

    with tempfile.TemporaryDirectory(prefix="cues_") as tmp:
        work = Path(tmp)
        inputs: list[str] = []
        parts: list[str] = []
        labels: list[str] = []
        count = 0

        def add_input(*args: str) -> int:
            """Добавляет вход и возвращает его номер.

            Номера считаются здесь, а не арифметикой на каждом месте. Родов
            входа пять, и выражение вида base + len(cues) + (1 if floor else 0)
            ошибается МОЛЧА: сборка не падает, а вместо щелчка звучит слово.
            """
            nonlocal count
            inputs.extend(args)
            count += 1
            return count - 1

        bed_i = add_input("-i", str(bed)) if bed is not None else None

        if riser_rows is not None:
            layer = build_risers(work, riser_rows, total)
            idx = add_input("-i", str(layer))
            gain = RISER_PEAK_DB - peak_db(layer)
            parts.append(f"[{idx}:a]volume={gain:.2f}dB[cue]")
            labels.append("[cue]")
        else:
            for i, cue in enumerate(cues):
                idx = add_input("-i",
                                str(assets / f"cues/cue_{cue.word}.wav"))
                ms = int(round(cue.t * 1000.0))
                parts.append(f"[{idx}:a]adelay={ms}|{ms},"
                             f"volume={CUE_GAIN_DB}dB[c{i}]")
                labels.append(f"[c{i}]")

        if bed_i is not None:
            expr = duck_expression(cues, lengths)
            parts.append(f"[{bed_i}:a]volume='{expr}':eval=frame[bed]")
            labels.insert(0, "[bed]")

        if floor:
            path, gain = floor_track(work, total)
            idx = add_input("-i", str(path))
            parts.append(f"[{idx}:a]volume={gain:.2f}dB[floor]")
            labels.append("[floor]")

        if click:
            tick, tick_gain = click_track(work)
            idx = add_input("-i", str(tick))
            ms = int(round(CLICK_AT * 1000.0))
            parts.append(f"[{idx}:a]adelay={ms}|{ms},"
                         f"volume={tick_gain:.2f}dB[click]")
            labels.append("[click]")

        if ghost is not None:
            idx = add_input("-ss", f"{ghost_at:.4f}", "-i", str(ghost))
            # Свод в моно руками, а не средствами amix: дорожка едет в один
            # наушник, и половина номера, оставшаяся в другом канале, была бы
            # просто потеряна.
            parts.append(f"[{idx}:a]pan=mono|c0=0.5*c0+0.5*c1,"
                         f"volume={GHOST_DB}dB[ghost]")
            labels.append("[ghost]")

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


def sheet(kept: list[Cue], dropped: list[Cue], rows: list[dict],
          plan: list[tuple[Anchor, float]], chain: float, strikes) -> str:
    """Печатный лист. Пишется здесь, а не в шаблоне: он весь из чисел.

    План дорожек приходит СНАРУЖИ, тот самый, по которому они собраны. Считать
    его здесь заново нельзя: при `--anchor laugh --start-at 0.95` дорожка
    ложится на 0.95, а пересчёт напечатал бы 1.11 — и помощник прочёл бы с
    распечатки число, которого в файле нет.
    """
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
        "## Дорожки: чем ловить старт",
        "",
        "Play жмёт помощник за кулисами, а не исполнитель. Чем он поймает",
        "начало номера — вопрос к площадке, поэтому по умолчанию собираются",
        "все три, а выбор делается на месте и ДО выхода.",
        "",
        "| файл | ловить | чем | в номере | сдвиг |",
        "|---|---|---|---|---|",
    ]
    for anchor, start_at in plan:
        lines.append(f"| `stage_cues_{anchor.key}.wav` | {anchor.catch} | "
                     f"{anchor.sense} | {anchor.t:.2f} | {start_at:.2f} |")

    if len(plan) < len(ANCHORS):
        lines += [
            "",
            f"**В этот прогон собрана {len(plan)} дорожка из {len(ANCHORS)}.**",
            "Остальные не пересобирались. Если файлы от прошлого прогона лежат",
            "рядом, этот лист их НЕ описывает — пересобери всё без `--anchor`.",
        ]

    ручной = any(abs(s - a.start_at(chain)) > 1e-9 for a, s in plan)
    lines += [
        "",
        "Сдвиг задан вручную через `--start-at`, из якоря с цепочкой он не"
        " выводится." if ручной else
        f"Сдвиг = время якоря + реакция (ухо 0.16, глаз 0.20) + цепочка "
        f"{chain:.2f}.",
        "",
        "В дорожке не слова, а РИЗЫ: нарастающий шум, вершина которого",
        "приходится ровно в контакт. Слово давало точку — «сейчас», — и при",
        "промахе старта точка врала. Риз даёт разгон: слышишь, как набирает,",
        "и въезжаешь в вершину. Сместился он на десятую — ты всё равно едешь",
        "по нему, а не ловишь мгновение.",
        "",
        f"Ризов {len(rows)} против шести слов: они стоят на КАЖДОМ контакте,",
        "включая вторые попадания вспышек 2 и 3, которым слова не досталось",
        "из-за наложения. Исключён только встречный удар вспышки 4 — у него",
        "замаха нет намеренно, и объявлять подготовку, которой не существует,",
        "значит врать о движении. Слова остались в репетиционной дорожке.",
        "",
        "**Рабочее окно старта — ±0.2 с.** При опоздании на 0.2 с у «пошёл»",
        "остаётся 0.18 с опережения: подсказка сжимается, но помогает. При",
        "0.38 с слово ложится ровно в контакт и начинает вредить.",
        "",
        "В начале каждой дорожки стоит щелчок. Услышал — канал жив и часы",
        "пошли. Не услышал — Bluetooth оборвался, и подсказок не будет вовсе.",
        "",
        "У каждой есть двойник `stage_cues_*_sync.wav` — то же самое, но под",
        "словами тихо идёт номер. На выход он не берётся: он для замера, см.",
        "ниже. На сцене в ухе должны быть только подсказки.",
        "",
        "## Ризы: откуда разгон и куда вершина",
        "",
        "Времена в номере, до сдвига. Начало каждого подрезано предыдущим",
        "контактом: риз, накрывший прошлый удар, перестаёт означать «сейчас",
        "будет следующий», и потому длина у них разная.",
        "",
        "| разгон с | вершина = контакт | длина | действие |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['start']:.2f} | **{row['peak']:.2f}** | "
                     f"{row['peak'] - row['start']:.2f} с | {row['strike']} |")

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
        "### На слух, сверочной копией — быстро и без приборов",
        "",
        "У каждой дорожки есть двойник `_sync`: то же самое, но под словами",
        "тихо идёт сам номер. Слушать его не надо — надо сравнивать.",
        "",
        "1. Включи номер в зале или на колонках.",
        "2. Помощник жмёт play на `_sync` в тот же момент, что и на выходе.",
        "3. Слушай в наушник. Совпало — цепочка верна. Разошлось — слышно",
        "   ХЛОПКОМ: два одинаковых звука с зазором. Это самый точный",
        "   слуховой признак времени, какой есть у человека.",
        "4. Подбирай `--chain`, пока хлопок не схлопнется в один звук.",
        "",
        "**Дорожка отстаёт от зала — цепочка занижена, увеличивай.**",
        "Обгоняет — уменьшай.",
        "",
        "### С диктофоном — если нужно число, а не подгонка",
        "",
        "1. Включи номер, телефон помощника — в руке.",
        "2. Жми play на якоре своей дорожки.",
        "3. Пиши на диктофон второго устройства сразу и зал, и наушник",
        "   (наушник поднеси к микрофону).",
        "4. В записи найди якорь и ЩЕЛЧОК в начале дорожки. Разница минус",
        "   время якоря минус реакция и есть цепочка.",
        "5. Пересобери с ней: `python src/render_cues.py --chain ЧИСЛО`.",
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

    rows = risers(strikes)
    made: list[Path] = []
    for anchor, start_at in plan:
        moved = shift_rows(rows, int(round(start_at * 1000.0)))
        path = out / f"stage_cues_{anchor.key}.wav"
        print(f"\n{anchor.key}: ловить {anchor.catch} ({anchor.sense}), "
              f"сдвиг {start_at:.2f} с, {len(moved)} ризов")
        for row in moved:
            print(f"  файл {row['start']:6.2f} → {row['peak']:6.2f}   "
                  f"номер {row['peak'] + start_at:6.2f}  {row['strike']}")
        render([], path, tl.total_duration - start_at, assets, None,
               channels=1, floor=True, click=True, riser_rows=moved)
        made.append(path)

        # Сверочная копия того же самого: под словами тихо идёт номер. Играешь
        # её вместе с залом — совпало, значит цепочка замерена верно; разошлось,
        # слышно хлопком, и величина хлопка и есть поправка.
        check = out / f"stage_cues_{anchor.key}_sync.wav"
        render([], check, tl.total_duration - start_at, assets, None,
               channels=1, floor=True, click=True, riser_rows=moved,
               ghost=master, ghost_at=start_at)
        made.append(check)

    print("\nв телефон помощнику:")
    for path in publish(made):
        print(f"  {path.name}  {path.stat().st_size / 1e6:.2f} МБ")
    print(f"  лежат в {CUES_DIR}")

    text = sheet(kept, dropped, rows, plan, args.chain, strikes)
    (out / "cue_sheet.md").write_text(text, encoding="utf-8")

    for path in [out / "rehearsal_cues_v2.wav"] + made:
        print(f"\n{path}  {ffprobe_duration(path):.3f} с, "
              f"{path.stat().st_size / 1e6:.1f} МБ")
    print(f"{out / 'cue_sheet.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
