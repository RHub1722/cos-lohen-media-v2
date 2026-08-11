"""Генерация тренировочных клипов через Atlas Cloud.

Обвязка поверх tools/atlas_gen.py: загрузка файла, отправка задания, опрос,
скачивание, обеззвучивание и журнал берутся оттуда как есть. Своего кода
общения с сервисом здесь нет — имена полей запроса живут в одном месте, и
трогать проверенный путь генерации видеофона ради тренировочных клипов не надо.

Отличий от него три, и все три существенные:

    референсы идут из assets/sheets/panels/, а не из assets/screenshots/;
    результат ложится в assets/train_clips/, а НЕ в assets/video/ — это не
        часть номера, и попасть в монтаж оно не должно;
    слота нет вовсе: клип никто не рендерит, его смотрят глазами.

    $env:ATLASCLOUD_API_KEY="..."
    python tools/atlas_train.py --all --dry-run
    python tools/atlas_train.py --only take_the_hit
    python tools/atlas_train.py --all
    python tools/atlas_train.py --refetch <prediction_id> --as burst_3
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402
from src.train_clips import Clip, ClipError, attempt_name, load  # noqa: E402
from src.footage import BaseShot  # noqa: E402
from tools.atlas_gen import (AtlasError, MODEL, TOKENS_PER_SECOND,  # noqa: E402
                             download, estimate, full_prompt, key, ledger_rows,
                             note, submit, upload, wait)

ROOT = Path(__file__).resolve().parents[1]
# Вне assets/video/ намеренно: тренировочный клип не должен даже случайно
# оказаться в монтаже номера.
OUT = ROOT / "assets" / "train_clips"
# Префикс в столбце shot журнала: журнал один на проект, а строки должны быть
# различимы — фон номера и тренировка это разные траты.
TAG = "train:"


def shots() -> list:
    tl = Timeline.load(ROOT / "scenario/timeline.json")
    moves = resolve_times(load_movements(ROOT / "scenario/movements.json"), tl)
    peaks = peak_offsets(ROOT / "assets",
                         sorted({e.asset for e in tl.events if e.stem == "sfx"}))
    return resolve_strikes(load_strikes(ROOT / "scenario/strikes.json"), tl,
                           peaks, [m.id for m in moves])


def as_shot(clip: Clip) -> BaseShot:
    """Клип в том виде, в каком его понимает submit() из atlas_gen."""
    return BaseShot(anchor=TAG + clip.id, clip="%s.mp4" % clip.id,
                    prompt=clip.prompt, negative=clip.negative,
                    duration=clip.duration, resolution=clip.resolution)


def attempt_path(cid: str, number: int) -> Path:
    # Имя складывает src.train_clips: по нему же страница тренажёра находит
    # принятую попытку, и разойтись эти два места не должны.
    return OUT / attempt_name(cid, number)


def attempts(cid: str) -> list[int]:
    found = []
    for path in OUT.glob("%s_a*.mp4" % cid):
        tail = path.stem.removeprefix("%s_a" % cid)
        if tail.isdigit():
            found.append(int(tail))
    return sorted(found)


def attempt_number(cid: str) -> int:
    """Номер следующей попытки — по журналу и по уже скачанным файлам.

    Та же защита, что в atlas_gen: удали журнал, и номер вернулся бы к единице,
    а новая генерация легла бы в файл существующей попытки.
    """
    counted = sum(1 for r in ledger_rows() if r["shot"] == TAG + cid)
    return max([counted, *attempts(cid)]) + 1


def generate(clip: Clip, stamp: str) -> None:
    shot = as_shot(clip)
    number = attempt_number(clip.id)
    cost = estimate(shot, clip.resolution)
    target = attempt_path(clip.id, number)
    print("[%s] попытка %d, %d с %s, замедление %.1fx, ожидаемо $%.2f"
          % (clip.id, number, clip.duration, clip.resolution, clip.slow, cost),
          flush=True)

    row = {"timestamp": stamp, "shot": shot.anchor, "model": MODEL,
           "resolution": clip.resolution, "duration": clip.duration,
           "attempt": number, "cost_estimate_usd": "%.4f" % cost,
           "total_tokens": "", "status": "", "prediction_id": "",
           "file": target.name,
           "notes": "тренировочный клип, %s, доли %.2f-%.2f"
                    % (clip.strike, clip.first, clip.last)}
    try:
        # Порядок важен: промпт адресует картинки словом «image N», и номера в
        # нём посчитаны из этого же порядка — внешность, потом позы.
        refs = [upload(p) for p in clip.refs]
        job = submit(shot, refs, clip.resolution)
        row["prediction_id"] = job
        url, tokens = wait(job)
        download(url, target)
    except (AtlasError, subprocess.CalledProcessError) as error:
        row["status"] = "failed"
        row["notes"] = str(error).replace("\n", " ")[:300]
        note(row)
        raise
    row["status"] = "ok"
    row["total_tokens"] = tokens
    note(row)
    print("[%s] готово: %s, токенов %d, prediction %s"
          % (clip.id, target.relative_to(ROOT), tokens, job), flush=True)


def refetch(prediction_id: str, cid: str, known: dict) -> int:
    if cid not in known:
        raise AtlasError("--as: нет такого клипа: %s. Есть: %s"
                         % (cid, ", ".join(known)))
    url, _ = wait(prediction_id)
    number = attempt_number(cid)
    target = attempt_path(cid, number)
    download(url, target)
    note({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "shot": TAG + cid,
          "attempt": number, "cost_estimate_usd": "0.0000", "status": "refetch",
          "prediction_id": prediction_id, "file": target.name,
          "notes": "повторное скачивание готового результата, оплаты нет"})
    print("[%s] попытка %d: %s" % (cid, number, target.relative_to(ROOT)))
    return 0


def show(clips: list[Clip]) -> None:
    """Что уйдёт на сервер. Печатается целиком: платить за догадку не хочется."""
    for clip in clips:
        shot = as_shot(clip)
        print("=" * 78)
        print("%s — %s" % (clip.id, clip.title))
        print("  удар %s, доли %.2f → %.2f, движение %.2f с"
              % (clip.strike, clip.first, clip.last, clip.real))
        print("  модель      %s" % MODEL)
        print("  длина       %d с  (замедление %.1fx)" % (clip.duration, clip.slow))
        print("  разрешение  %s   пропорции 16:9   звук выключен, знака нет"
              % clip.resolution)
        print("  ожидаемо    $%.2f" % estimate(shot, clip.resolution))
        print("  референсов  %d = внешность %d + позы %d"
              % (len(clip.refs), len(clip.faces), len(clip.panels)))
        for i, p in enumerate(clip.refs, 1):
            role = "внешность" if i <= len(clip.faces) else "поза"
            print("    image %d  %-34s %s" % (i, p.name, role))
        print("  --- промпт целиком, вместе с запретами ---")
        for line in full_prompt(shot).splitlines():
            print("  " + line if line else "")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Генерация тренировочных клипов через Atlas Cloud")
    ap.add_argument("--only", nargs="+", metavar="ID", help="только эти клипы")
    ap.add_argument("--all", action="store_true", help="все клипы списка")
    ap.add_argument("--resolution", default=None, help="переопределить разрешение")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать, что уйдёт на сервер, и не отправлять")
    ap.add_argument("--refetch", metavar="PREDICTION_ID",
                    help="забрать готовый результат по идентификатору")
    ap.add_argument("--as", dest="cid", metavar="ID",
                    help="какому клипу принадлежит результат --refetch")
    args = ap.parse_args()

    if sum(map(bool, [args.only or args.all, args.refetch])) != 1:
        ap.error("выбери одно: --only ID [ID...] | --all | "
                 "--refetch PREDICTION_ID --as ID")
    if args.refetch and not args.cid:
        ap.error("--refetch требует --as ID")

    try:
        clips = load(shots())
    except ClipError as error:
        print(error, file=sys.stderr)
        return 1
    known = {c.id: c for c in clips}

    if args.resolution:
        clips = [Clip(**{**c.__dict__, "resolution": args.resolution})
                 for c in clips]
        known = {c.id: c for c in clips}

    if args.refetch:
        try:
            key()
            return refetch(args.refetch, args.cid, known)
        except (AtlasError, subprocess.CalledProcessError) as error:
            print(error, file=sys.stderr)
            return 1

    if args.only:
        unknown = sorted(set(args.only) - set(known))
        if unknown:
            ap.error("нет таких клипов: %s. Есть: %s"
                     % (", ".join(unknown), ", ".join(known)))
    chosen = [c for c in clips if args.all or c.id in args.only]

    total = sum(estimate(as_shot(c), c.resolution) for c in chosen)
    seconds = sum(c.duration for c in chosen)
    print("клипов: %d, секунд генерации: %d, ожидаемая стоимость $%.2f"
          % (len(chosen), seconds, total))
    unmeasured = sorted({c.resolution for c in chosen} - set(TOKENS_PER_SECOND))
    if unmeasured:
        print("ВНИМАНИЕ: расход на %s никто не мерил, сумма выше неполная. "
              "Известны: %s." % (", ".join(unmeasured), ", ".join(TOKENS_PER_SECOND)))
    print("результат ляжет в %s\n" % OUT.relative_to(ROOT))

    if args.dry_run:
        show(chosen)
        return 0

    try:
        key()
    except AtlasError as error:
        print(error, file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    for clip in chosen:
        try:
            generate(clip, stamp)
        except (AtlasError, subprocess.CalledProcessError) as error:
            print("[%s] ОШИБКА: %s" % (clip.id, error), file=sys.stderr)
            return 1
    print("\nжурнал: docs/atlas-ledger.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
