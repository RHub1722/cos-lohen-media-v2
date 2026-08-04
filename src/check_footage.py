"""Приёмка снятого материала: яркость по третям и движение по кадрам.

Мерить надо на том размере, на котором картинку увидит зал, — 1920×1080 и по
Rec.709. Средний RGB и превью в четверть размера врут по-разному: RGB завышает
сине-белый допрос, а превью съедает мелкую суету, ради которой замер движения и
затевался.

Третями, а не «центр против краёв». Усреднение тёмной левой трети с яркой правой
один раз уже отчиталось «в порядке» на кадре, где вся яркость стояла сбоку и
именно поэтому была безопасна.

Движение мерится отдельно, и раньше его не было вовсе. На это указала Галина,
посмотрев пробу: тусклый, но суетливый фон тянет взгляд не хуже яркого, и
исполнитель за ним проигрывает так же. Дисциплина по яркости у меня была с
первого дня, по динамике — ничем.

    python -m src.check_footage --shot interrogation
    python -m src.check_footage --all
    python -m src.check_footage --clip assets/video/attempts/combat_a2.mp4 --as combat
    python -m src.check_footage --shot ice --stills output/checks
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.footage import (ClipReader, FootageSource, GRADES,  # noqa: E402
                         load_shots, resolve)
from src.models import Timeline  # noqa: E402
from src.render_video import (SAFE_STRIP, Canvas, render_frame,  # noqa: E402
                              safety_row)
from src.video_plan import VideoPlan, build_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Rec.709. Не mean(RGB): у синего вес 0.07 против 0.33, и весь тёмно-синий трюм
# по среднему RGB выглядит на треть ярче, чем его увидит глаз.
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# Центральная полоса после предохранителя. Порог из спеки.
CENTRE_LIMIT = 0.12

# Движение в центральной полосе там, где исполнитель стоит неподвижно.
# Число снято с материала, который уже принят, а не назначено. Замер 4 августа
# через полный пайплайн, 1920×1080:
#
#   допрос (спокойный, обоими рецензентами назван лучшей частью пробы)
#       медиана 0.0016, 95-й 0.0053, максимум 0.0072
#   пролом (взрыв, принят пользователем)
#       медиана 0.0022, 95-й 0.0091, максимум 0.1063 на самом проломе
#
# Предел 0.012 — это 1.7 принятого максимума спокойного кадра, выше 95-го
# процентиля обоих клипов и в девять раз ниже взрыва. Он ловит фон, который
# заметно суетливее уже принятого, и не спорит ни с медленным наездом, ни с
# самим проломом — тот в спокойные окна не попадает.
#
# Медиану допроса занижают дубли кадров: исходник 24 fps, speed 0.87, на выходе
# 30 — часть соседних кадров совпадает буквально, и разница между ними ноль.
# Поэтому предел стоит от максимума и 95-го, а не от медианы.
QUIET_MOTION_LIMIT = 0.012

# Мусор по краям клипа. Обе стороны уже ловились руками: 1.7 с мёртвого люка
# перед взрывом и выбеленная вспышка с пиком на 0.25 с.
EDGE_WINDOW = 0.6

# Сколько центру позволено быть выше порога.
#
# Порог 0.12 стоит не против яркости самой по себе, а против того, чтобы глаз
# зала успел к фону приспособиться и потерять костюм. Приспособиться он успевает
# за время, а не за кадр, поэтому судить надо длительность.
#
# Что заставило это переписать: сам процедурный рендерер, принятый задолго до
# первой генерации, ДОБАВЛЯЕТ свет на каждом ударе — в render_frame на якоре
# flash кадр получает и полосу, и волну, и ровный подъём. Приёмка, которая
# запрещает то, что делает принятая часть проекта, мерит не то. Первые же три
# серии дали превышение по 2–5 кадров, и все три — на самом ударе, под который в
# звуке стоит импакт.
#
# Поэтому: короткая вспышка разрешена, свет — нет. Оба предела в секундах, и это
# не мелочь. Сначала вторым пределом стояла доля кадров куска, и она сразу дала
# ложное срабатывание: у кадра hit_on_lohen окно всего 1.8 с, три кадра выше
# порога — это 11% при позволенных 10%, притом что абсолютно там 0.10 с, то есть
# ничего. Доля на коротком окне меряет длину окна, а не яркость.
#
# Суммарный предел 0.35 с выведен из первого: одна вспышка длиной 0.20 с
# позволена, две подряд уже нет. В номере на каждый кадр по замыслу один удар.
#
# Оба условия проверялись на живых замерах:
#   burst1 0.13 с, burst2 0.07, burst3 0.17, hit_on_lohen 0.10, лёд 0.07 — прошли
#   отвергнутый первый пролом: центр выше порога почти все 6.2 с — провалился бы
#   мерцающий фон: двенадцать вспышек по 0.03 с дают 0.40 с — провалился бы
FLASH_BURST = 0.20
FLASH_TOTAL = 0.35


@dataclass(frozen=True)
class Sample:
    """Один кадр в цифрах.

    motion у первого кадра — nan, а не ноль. Ноль здесь означал бы «замерли», и
    самый спокойный кадр в отчёте оказался бы тем, который не измерен вовсе.
    """

    t: float
    left: float
    middle: float
    right: float
    centre: float
    motion: float
    motion_centre: float
    quiet: bool = False
    # Кадр внутри белой вспышки. Порог яркости к нему не применяется: вспышка
    # центральная и яркая намеренно, это удар в глаза на 42.8.
    flash: bool = False

    @property
    def middle_hotter(self) -> bool:
        """Середина ярче обеих крайних третей — то, чего быть не должно."""
        return self.middle > self.left and self.middle > self.right


def zones(width: int) -> dict[str, np.ndarray]:
    """Маски по горизонтали. «Центр» намеренно пересекается с «серединой»:
    середина — это треть кадра, а центр — ровно та полоса, которую гасит
    предохранитель, и порог 0.12 стоит именно на ней."""
    x = np.linspace(-1.0, 1.0, width, dtype=np.float32)
    third = 1.0 / 3.0
    return {
        "left": x < -third,
        "middle": (x >= -third) & (x < third),
        "right": x >= third,
        "centre": np.abs(x) < SAFE_STRIP,
    }


def scan(stream: Iterable[tuple[float, np.ndarray]], width: int,
         quiet: list[tuple[float, float]] | None = None,
         flashes: list[tuple[float, float]] | None = None) -> list[Sample]:
    masks = zones(width)
    windows = quiet or []
    bright = flashes or []
    prev: np.ndarray | None = None
    out: list[Sample] = []
    for t, rgb in stream:
        luma = rgb[:, :, :3] @ LUMA
        if prev is None or prev.shape != luma.shape:
            motion = motion_centre = float("nan")
        else:
            diff = np.abs(luma - prev)
            motion = float(diff.mean())
            motion_centre = float(diff[:, masks["centre"]].mean())
        prev = luma
        out.append(Sample(
            t=t,
            left=float(luma[:, masks["left"]].mean()),
            middle=float(luma[:, masks["middle"]].mean()),
            right=float(luma[:, masks["right"]].mean()),
            centre=float(luma[:, masks["centre"]].mean()),
            motion=motion,
            motion_centre=motion_centre,
            quiet=any(a <= t < b for a, b in windows),
            flash=any(a <= t < b for a, b in bright),
        ))
    return out


# --- источники кадров --------------------------------------------------------


def clip_stream(path: Path, width: int, height: int, fps: int,
                shot=None) -> Iterator[tuple[float, np.ndarray]]:
    """Кадры файла ровно так, как их получит рендер, плюс предохранитель.

    Предохранитель здесь приходится накладывать руками: в режиме `--shot` его
    накладывает сам render_frame, а тут никакого рендера нет. Без него замер
    отчитался бы о яркости, которой в зале не будет, — и первая же проба
    провалилась бы на пороге, который к ней не относится.
    """
    start_at = shot.start_at if shot else 0.0
    speed = shot.speed if shot else 1.0
    tint = (np.array(GRADES[shot.grade], dtype=np.float32) * shot.gain
            if shot else np.ones(3, dtype=np.float32))
    safe = safety_row(width)[None, :, None]

    reader = ClipReader(path, width, height, fps, start_at=start_at, speed=speed)
    try:
        i = 0
        while True:
            frame = reader.read()
            if frame is None:
                return
            yield i / fps, frame[:, :, :3] * tint[None, None, :] * safe
            i += 1
    finally:
        reader.close()


def pipeline_stream(canvas: Canvas, plan: VideoPlan, source, fps: int,
                    upto: float, verbose: bool = True
                    ) -> Iterator[tuple[float, np.ndarray]]:
    """Кадры через настоящий рендер: грейд, гейн, якоря, предохранитель.

    Идём всегда от нуля, даже если нужен кадр в конце номера. Потоковый читатель
    отдаёт следующий кадр на каждый вызов, и перемотаться к середине, не пройдя
    начало, он не может — а замерять на режиме перемотки нельзя вовсе: там
    каждый кадр читается отдельным процессом, и разница между соседними кадрами
    перестала бы быть разницей между соседними кадрами.
    """
    frames = int(round(upto * fps))
    for i in range(frames):
        t = i / fps
        if verbose and i and i % (fps * 5) == 0:
            print(f"    {t:5.1f} с / {upto:.1f}", flush=True)
        yield t, render_frame(canvas, plan, t, fps, source)


# --- окна, в которых зал смотрит на неподвижного исполнителя ------------------


def quiet_windows(plan: VideoPlan) -> list[tuple[float, float]]:
    """Где фон обязан быть спокойным.

    Два места, и оба взяты из таймлайна, а не назначены руками. Допрос — там
    зал впервые читает костюм, и смысл несёт текст. Заморозка до конца номера —
    там исполнитель держит финальную позу почти пять секунд, и это худшее место
    во всём номере, чтобы за его спиной что-то шевелилось.

    Везде остальное движение мерится и печатается, но не судится: пролом и
    попадания обязаны двигаться, и предел, запрещающий это, был бы предел,
    запрещающий номер.
    """
    windows = [(seg.start, seg.end) for seg in plan.segments
               if seg.state == "interrogation"]
    windows += [(cue.t, plan.total) for cue in plan.cues if cue.kind == "freeze"]
    return sorted(windows)


def flash_windows(plan: VideoPlan) -> list[tuple[float, float]]:
    """Где яркий центр — это замысел, а не провал приёмки.

    Одно место на весь номер: белая вспышка на 42.8. Она обязана быть яркой и
    обязана быть центральной — это удар, пришедший в глаза, и он единственное
    исключение из порога. Окно берётся из якоря, а не выписывается временем:
    приёмка, которая кричит на замысел, перестаёт работать целиком, а приёмка с
    руками вписанным таймкодом переживёт правку сценария и начнёт врать.
    """
    return sorted((cue.t, cue.end) for cue in plan.cues
                  if cue.kind == "whiteflash")


# --- отчёт -------------------------------------------------------------------


def frame_step(samples: list[Sample]) -> float:
    """Сколько секунд занимает один кадр замера.

    Берётся из самих отсчётов, а не из fps: замер может идти с любой частотой, и
    зашитая тридцатка превратила бы суммарный предел в предел на число кадров.
    """
    if len(samples) < 2:
        return 1.0 / 30.0
    return (samples[-1].t - samples[0].t) / (len(samples) - 1)


def longest_run(samples: list[Sample]) -> tuple[float, float]:
    """Самая долгая непрерывная засветка центра: длина в секундах и когда.

    Считается по времени кадров, а не по их числу: считать в кадрах значило бы
    привязать предел к частоте, с которой снят замер, и на 24 fps тот же самый
    свет проходил бы, а на 60 нет.
    """
    best = span = 0.0
    best_at = start = -1.0
    for i, s in enumerate(samples):
        if s.centre > CENTRE_LIMIT:
            if start < 0:
                start = s.t
            # Длина серии — до начала следующего кадра, иначе одиночный кадр
            # получает нулевую длину и никогда не переваливает ни за какой предел.
            nxt = samples[i + 1].t if i + 1 < len(samples) else s.t + (
                s.t - samples[i - 1].t if i else 0.033)
            span = nxt - start
            if span > best:
                best, best_at = span, start
        else:
            start = -1.0
    return best, best_at


def percentile(values: list[float], q: float) -> float:
    clean = [v for v in values if not np.isnan(v)]
    return float(np.percentile(clean, q)) if clean else float("nan")


def report(title: str, samples: list[Sample], step: float = 0.5,
           judge_motion: bool = True) -> list[str]:
    """Печатает таблицу и сводку, возвращает список нарушений."""
    print(f"\n=== {title} ===")
    if not samples:
        print("  ни одного кадра не прочитано")
        return [f"{title}: ни одного кадра"]

    print(f"  {'время':>6} {'левая':>7} {'середина':>9} {'правая':>7} "
          f"{'центр':>7} {'движ':>7} {'движ-ц':>7}")
    shown = -1.0
    for s in samples:
        if s.t - shown < step - 1e-6:
            continue
        shown = s.t
        mark = ""
        if s.flash:
            mark += " вспышка"
        elif s.centre > CENTRE_LIMIT:
            mark += " ЦЕНТР"
        if s.middle_hotter and not s.flash:
            mark += " серединаЯрче"
        if s is samples[0] and not np.isnan(s.motion):
            # Разница у первого кадра куска — это стык с предыдущим куском.
            # Пометить её «ДВИЖЕНИЕМ» значило бы противоречить сводке ниже, где
            # она из движения как раз исключена.
            mark += " склейка"
        elif judge_motion and s.quiet and s.motion_centre > QUIET_MOTION_LIMIT:
            mark += " ДВИЖЕНИЕ"
        print(f"  {s.t:6.2f} {s.left:7.3f} {s.middle:9.3f} {s.right:7.3f} "
              f"{s.centre:7.3f} {s.motion:7.4f} {s.motion_centre:7.4f}{mark}")

    # Кадры белой вспышки из суда по яркости исключены целиком: и порог, и
    # «середина ярче краёв» на ней срабатывают по замыслу, а не по ошибке.
    judged = [s for s in samples if not s.flash]
    flashes = [s for s in samples if s.flash]
    hot = [s for s in judged if s.centre > CENTRE_LIMIT]
    hotter = [s for s in judged if s.middle_hotter]
    worst = max(judged, key=lambda s: s.centre) if judged else samples[0]

    # Первый кадр окна: его «движение» — это разница с последним кадром
    # предыдущего кадра списка, то есть сама склейка, а не движение внутри
    # клипа. Считать её вместе с остальными нельзя: любой максимум движения
    # оказывался бы стыком, и настоящая суета внутри кадра под ним пряталась бы.
    cut = samples[0] if not np.isnan(samples[0].motion) else None
    inner = samples[1:] if cut is not None else samples
    if not inner:
        inner = samples
    centre_motion = [s.motion_centre for s in inner]
    quiet = [s for s in inner if s.quiet]

    print(f"\n  кадров {len(samples)}, {samples[0].t:.2f}–{samples[-1].t:.2f} с")
    if cut is not None:
        print(f"  склейка на входе: {cut.motion:.4f}, в полосе "
              f"{cut.motion_centre:.4f} (это стык, а не движение клипа)")
    burst, burst_at = longest_run(judged)
    total = len(hot) * frame_step(samples)
    if judged:
        print(f"  центр: максимум {worst.centre:.3f} на {worst.t:.2f} с, "
              f"порог {CENTRE_LIMIT:.2f}, выше порога {len(hot)} кадров")
        if hot:
            print(f"  выше порога: подряд {burst:.2f} с на {burst_at:.2f} с, "
                  f"всего {total:.2f} с (позволено {FLASH_BURST:.2f} с подряд "
                  f"и {FLASH_TOTAL:.2f} с суммарно)")
    else:
        print("  центр: судить нечего — все кадры внутри белой вспышки")
    if flashes:
        peak = max(flashes, key=lambda s: s.centre)
        print(f"  белая вспышка: {len(flashes)} кадров вне суда по яркости, "
              f"центр в пике {peak.centre:.3f} на {peak.t:.2f} с — "
              f"это замысел, удар в глаза")
    print(f"  середина ярче обеих крайних третей: {len(hotter)} "
          f"({100.0 * len(hotter) / len(samples):.0f}%)")
    print(f"  движение в полосе: медиана {percentile(centre_motion, 50):.4f}, "
          f"95-й {percentile(centre_motion, 95):.4f}, "
          f"максимум {percentile(centre_motion, 100):.4f}")

    problems: list[str] = []
    if burst > FLASH_BURST:
        problems.append(f"{title}: центр выше {CENTRE_LIMIT:.2f} подряд "
                        f"{burst:.2f} с на {burst_at:.2f} с — это уже не "
                        f"вспышка, а свет (позволено {FLASH_BURST:.2f} с)")
    if total > FLASH_TOTAL:
        problems.append(f"{title}: центр выше {CENTRE_LIMIT:.2f} суммарно "
                        f"{total:.2f} с, максимум {worst.centre:.3f} на "
                        f"{worst.t:.2f} с (позволено {FLASH_TOTAL:.2f} с)")
    if quiet and judge_motion:
        loud = [s for s in quiet if s.motion_centre > QUIET_MOTION_LIMIT]
        peak = max(quiet, key=lambda s: (s.motion_centre
                                         if not np.isnan(s.motion_centre) else -1))
        print(f"  спокойных кадров {len(quiet)}, движение в них: медиана "
              f"{percentile([s.motion_centre for s in quiet], 50):.4f}, "
              f"максимум {peak.motion_centre:.4f} на {peak.t:.2f} с, "
              f"порог {QUIET_MOTION_LIMIT:.4f}")
        if loud:
            problems.append(f"{title}: движение в полосе выше "
                            f"{QUIET_MOTION_LIMIT:.4f} в {len(loud)} спокойных "
                            f"кадрах, максимум {peak.motion_centre:.4f} "
                            f"на {peak.t:.2f} с")

    # Мусор по краям ищется только среди кадров, за которые отвечает модель.
    # Окно hit_on_lohen начинается ровно там, где стоит белая вспышка, и без
    # этого исключения приёмка требовала бы подрезать start_at у кадра, начало
    # которого сделано нами и нарочно.
    edge = [s for s in samples
            if s.t <= samples[0].t + EDGE_WINDOW and not s.flash]
    if edge:
        flash = max(edge, key=lambda s: s.middle)
        still = [s for s in edge[1:] if not np.isnan(s.motion) and s.motion < 0.002]
        if flash.middle > 0.30:
            problems.append(f"{title}: вспышка на входе, середина "
                            f"{flash.middle:.3f} на {flash.t:.2f} с — "
                            f"подрезать start_at")
        if len(still) >= len(edge) - 1 and len(edge) > 2:
            problems.append(f"{title}: мёртвый разгон, первые "
                            f"{EDGE_WINDOW:.1f} с почти без движения")
    return problems


def save_stills(samples: list[Sample], frames: dict[float, np.ndarray],
                out_dir: Path, tag: str) -> None:
    from PIL import Image
    out_dir.mkdir(parents=True, exist_ok=True)
    for t, rgb in frames.items():
        data = (np.clip(rgb[:, :, :3], 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        Image.fromarray(data, mode="RGB").save(out_dir / f"{tag}-{t:06.2f}.png")
    print(f"  кадры-образцы: {out_dir}")


def keep_worst(stream, keep: dict[float, np.ndarray], every: float
               ) -> Iterator[tuple[float, np.ndarray]]:
    """Пропускает поток дальше и попутно откладывает кадры для картинок."""
    last = -1e9
    for t, rgb in stream:
        if t - last >= every:
            last = t
            keep[round(t, 2)] = rgb.copy()
        yield t, rgb


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", default=str(ROOT / "scenario" / "timeline.json"))
    ap.add_argument("--shots", default=str(ROOT / "scenario" / "shots.json"))
    ap.add_argument("--assets", default=str(ROOT / "assets" / "video"))
    ap.add_argument("--shot", nargs="+", metavar="ЯКОРЬ",
                    help="проверить через полный пайплайн")
    ap.add_argument("--all", action="store_true",
                    help="все кадры, у которых лежит файл")
    ap.add_argument("--clip", help="проверить отдельный файл")
    ap.add_argument("--as", dest="anchor", metavar="ЯКОРЬ",
                    help="чьи start_at, speed, grade и gain применить к --clip")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--step", type=float, default=0.5, help="шаг таблицы")
    ap.add_argument("--stills", help="куда положить кадры-образцы")
    args = ap.parse_args()

    if sum(map(bool, [args.shot or args.all, args.clip])) != 1:
        ap.error("выбери одно: --shot ЯКОРЬ [...] | --all | --clip ФАЙЛ")

    bases, fx = load_shots(args.shots)
    slots = {b.anchor: b for b in bases}
    problems: list[str] = []
    keep: dict[float, np.ndarray] = {}

    if args.clip:
        path = Path(args.clip)
        if not path.exists():
            print(f"нет файла {path}", file=sys.stderr)
            return 1
        shot = None
        if args.anchor:
            if args.anchor not in slots:
                ap.error(f"нет якоря {args.anchor}. Есть: {', '.join(slots)}")
            shot = slots[args.anchor]
        stream = clip_stream(path, args.width, args.height, args.fps, shot)
        title = f"{path.name}" + (f" как {args.anchor}" if shot else " без трансформа")
        if args.stills:
            stream = keep_worst(stream, keep, 2.0)
        # Движение здесь не судим: у отдельного файла нет места в номере, а
        # значит нет и ответа на вопрос, стоит ли в это время исполнитель.
        problems += report(title, scan(stream, args.width), args.step,
                           judge_motion=False)
        if args.stills:
            save_stills([], keep, Path(args.stills), path.stem)
        return finish(problems)

    timeline = Timeline.load(args.scenario)
    with open(args.scenario, encoding="utf-8") as fh:
        import json
        raw = json.load(fh)
    plan = build_plan(raw["events"], timeline.total_duration)
    resolved, resolved_fx = resolve(bases, fx, plan)

    chosen = [s for s in resolved
              if args.all or s.anchor in set(args.shot or ())]
    if args.shot:
        unknown = set(args.shot) - {s.anchor for s in resolved}
        if unknown:
            ap.error(f"нет таких якорей: {', '.join(sorted(unknown))}. "
                     f"Есть: {', '.join(s.anchor for s in resolved)}")
    have = [s for s in chosen if (Path(args.assets) / s.clip).exists()]
    skipped = [s.anchor for s in chosen if s not in have]
    if skipped:
        print(f"файла нет, пропущены: {', '.join(skipped)}")
    if not have:
        print("нечего проверять: ни у одного выбранного кадра нет файла")
        return 1

    upto = max(s.end for s in have)
    print(f"через пайплайн до {upto:.1f} с, {args.width}×{args.height}, "
          f"{args.fps} fps")
    canvas = Canvas(args.width, args.height)
    source = FootageSource(resolved, resolved_fx, Path(args.assets),
                           args.width, args.height, args.fps)
    windows = quiet_windows(plan)
    flashes = flash_windows(plan)
    print("спокойные окна: "
          + ", ".join(f"{a:.1f}–{b:.1f}" for a, b in windows))
    print("вспышки вне суда по яркости: "
          + (", ".join(f"{a:.1f}–{b:.1f}" for a, b in flashes) or "нет"))

    stream = pipeline_stream(canvas, plan, source, args.fps, upto)
    if args.stills:
        stream = keep_worst(stream, keep, 2.0)
    samples = scan(stream, args.width, windows, flashes)

    for shot in have:
        inside = [s for s in samples if shot.t <= s.t < shot.end]
        problems += report(f"{shot.anchor} ({shot.t:.1f}–{shot.end:.1f}, "
                           f"{shot.clip})", inside, args.step)
    if args.stills:
        save_stills(samples, keep, Path(args.stills), "pipeline")
    return finish(problems)


def finish(problems: list[str]) -> int:
    print()
    if not problems:
        print("приёмка пройдена")
        return 0
    print(f"НАРУШЕНИЙ {len(problems)}:")
    for line in problems:
        print(f"  — {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
