"""Генерация кадров видеофона через Atlas Cloud.

Читает тот же scenario/shots.json, что и рендер: промпт живёт рядом со своим
якорем, и второго списка кадров в проекте нет.

Ключ берётся только из переменной окружения ATLASCLOUD_API_KEY и никуда не
печатается — ни в журнал, ни в сообщение об ошибке.

Имена полей запроса взяты из docs/atlas-api.md, снятых со схемы модели. Не
угадывать: у модели, например, вообще нет поля запретов, а пропорции называются
ratio, и обе очевидные догадки были бы неверными.

Каждая попытка ложится отдельным файлом в assets/video/attempts/, а в слот,
который читает рендер, уходит копия выбранной. Затирать попытку нельзя: она
стоит денег, а достать её обратно можно только по prediction_id — поэтому он и
пишется в журнал.

    $env:ATLASCLOUD_API_KEY="..."
    python tools/atlas_gen.py --only interrogation combat --resolution 480p
    python tools/atlas_gen.py --all
    python tools/atlas_gen.py --use combat=1
    python tools/atlas_gen.py --refetch <prediction_id> --as combat
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.footage import BaseShot, load_shots  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.atlascloud.ai/api/v1/model"
MODEL = "bytedance/seedance-2.0-mini/reference-to-video"

# Списывает Atlas в токенах, и настоящее число приезжает в ответе полем
# total_tokens. Оценка до отправки считается через токены, а не мимо них — так
# видно, откуда берётся сумма.
#
# Токены на секунду сняты с живых ответов, а не взяты из прайса:
#   480p   15 с → 151078,  7 с →  70726   ≈ 10090 токенов/с
#   720p    7 с → 152100,  6 с → 130500,  5 с → 108900  ≈ 21750 токенов/с
#
# То есть 720p дороже 480p в 2.16 раза, а не на девять процентов, как говорила
# прежняя таблица. Семь секунд на 720p стоят ровно столько же, сколько пятнадцать
# на 480p. Ошибка была вдвое и вниз — самая неприятная сторона.
TOKENS_PER_SECOND = {"480p": 10090, "720p": 21750}

# Цена токена. Снята с ответа задания, а не выведена из суммы: в объекте
# предсказания есть поле `price`, которого мы раньше не читали.
#
#   train:take_the_hit, 10 августа: total_tokens 50638, price "0.19850096"
#   0.19850096 / 50638 * 1e6 = 3.920 ровно
#
# Прежнее значение было 5.545 — выведено из первых четырёх генераций (443608
# токенов на $2.46), и в docs/atlas-api.md про него честно стояло «единственное
# число, не снятое с ответа, сверить с дашбордом». Сверилось: цена ниже на 30%,
# ровно та скидка, что стоит в каталоге. Оценка была завышена в 1.41 раза —
# в безопасную сторону, но неверно.
#
# Расход в токенах на секунду при этом мерили правильно: 5 с на 480p дали 50638
# против ожидаемых 50450, промах 0.4%.
USD_PER_MILLION_TOKENS = 3.920

# Разрешения выше 720p не проверялись ни разу. Ставить им множитель наугад
# значит печатать перед тратой цифру, которой никто не мерил, поэтому их тут нет:
# estimate() на них честно скажет, что не знает.
UNMEASURED = ("720p-SR", "1080p-SR", "1440p-SR")

VIDEO = ROOT / "assets" / "video"
# Попытки лежат отдельно от слотов, которые читает рендер. Слот один на кадр, а
# попыток на него бывает три, и раньше каждая новая затирала предыдущую.
ATTEMPTS = VIDEO / "attempts"

LEDGER = ROOT / "docs" / "atlas-ledger.csv"
LEDGER_HEADER = ["timestamp", "shot", "model", "resolution", "duration",
                 "attempt", "cost_estimate_usd", "total_tokens", "status",
                 # Результат живёт на стороне сервиса, и вернуть его можно только
                 # по идентификатору. Один раз его уже пришлось выписывать со
                 # скриншота дашборда, потому что в журнал он не попадал.
                 "prediction_id", "file", "notes"]

# Успехом считаются оба слова: схема перечисляет completed, а их же пример в
# cURL пишет "completed, succeeded or failed". Проверять только одно — значит
# опрашивать готовый результат до таймаута.
DONE = ("completed", "succeeded")


class AtlasError(RuntimeError):
    pass


def key() -> str:
    value = os.environ.get("ATLASCLOUD_API_KEY", "").strip()
    if not value:
        raise AtlasError(
            "нет переменной окружения ATLASCLOUD_API_KEY.\n"
            '  PowerShell:  $env:ATLASCLOUD_API_KEY="..."\n'
            "  bash:        export ATLASCLOUD_API_KEY=..."
        )
    return value


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {key()}"}


def upload(path: Path) -> str:
    """Заливает референс и возвращает временную ссылку на него."""
    if not path.exists():
        raise AtlasError(f"нет референса {path}")
    with open(path, "rb") as fh:
        response = requests.post(f"{API}/uploadMedia", headers=headers(),
                                 files={"file": fh}, timeout=120)
    if response.status_code >= 400:
        raise AtlasError(f"загрузка {path.name} отклонена "
                         f"({response.status_code}): {response.text[:400]}")
    payload = response.json()
    data = payload.get("data") or {}
    # Настоящее имя поля — download_url, проверено живым ответом. В питоновском
    # примере их документации стоит data.get("url"), и это неверно: ответ
    # выглядит как {"code":200,"data":{"type":"image","download_url":...}}.
    # Остальные варианты оставлены на случай, если схема поменяется.
    url = (data.get("download_url") or data.get("url")
           or payload.get("download_url") or payload.get("url"))
    if not url:
        raise AtlasError(f"в ответе на загрузку {path.name} нет ссылки: "
                         f"{response.text[:400]}")
    return url


def full_prompt(shot: BaseShot) -> str:
    """Промпт вместе с запретами.

    Отдельного поля запретов у модели нет — это единственный способ их передать.
    """
    if not shot.negative.strip():
        return shot.prompt
    return f"{shot.prompt}\n\nAvoid entirely: {shot.negative}."


def submit(shot: BaseShot, refs: list[str], resolution: str) -> str:
    body = {
        "model": MODEL,
        "prompt": full_prompt(shot),
        "duration": int(shot.duration),
        "resolution": resolution,
        # Не aspect_ratio. И не дефолтный adaptive: adaptive взял бы пропорции
        # первого референса, а у нас они от 1.07 до 2.20 — кадр обязан быть 16:9.
        "ratio": "16:9",
        "bitrate_mode": "standard",
        # По умолчанию true. Мастер-звук готов, дорожка от модели не нужна.
        "generate_audio": False,
        # По умолчанию уже false, но передаём явно: молчаливая смена дефолта на
        # стороне сервиса стоила бы водяного знака в готовом номере, а виден он
        # с любого места в зале.
        "watermark": False,
        "return_last_frame": False,
    }
    if refs:
        # Поле требует минимум один элемент, поэтому пустым его не отправляем.
        body["reference_images"] = refs

    response = requests.post(f"{API}/generateVideo", headers=headers(),
                             json=body, timeout=120)
    if response.status_code >= 400:
        raise AtlasError(f"задание отклонено ({response.status_code}): "
                         f"{response.text[:600]}")
    payload = response.json()
    # Идентификатор в конверте: {"code": 200, "data": {"id": ..., ...}}
    job = payload.get("data", {}).get("id") or payload.get("id")
    if not job:
        raise AtlasError(f"в ответе нет id задания: {response.text[:400]}")
    return job


def wait(job: str, timeout: float = 900.0, beat: float = 30.0) -> tuple[str, int]:
    """Опрашивает задание и возвращает ссылку на результат и списанные токены.

    Раз в `beat` секунд печатает, что ждём и сколько уже: генерация идёт минуты,
    а на восьми кадрах подряд молчащий скрипт неотличим от зависшего.
    """
    started = time.monotonic()
    deadline = started + timeout
    spoken = 0.0
    while time.monotonic() < deadline:
        waited = time.monotonic() - started
        if waited - spoken >= beat:
            spoken = waited
            print(f"    ждём {job}: {waited:.0f} с", flush=True)
        response = requests.get(f"{API}/prediction/{job}",
                                headers=headers(), timeout=60)
        if response.status_code >= 400:
            raise AtlasError(f"опрос {job} ({response.status_code}): "
                             f"{response.text[:400]}")
        payload = response.json()
        data = payload.get("data", payload)
        status = str(data.get("status", "")).lower()
        if status in DONE:
            outputs = data.get("outputs") or []
            if not outputs:
                raise AtlasError(f"задание {job} готово, но outputs пуст: "
                                 f"{str(payload)[:400]}")
            return outputs[0], int(data.get("total_tokens") or 0)
        if status in ("failed", "timeout"):
            raise AtlasError(f"задание {job} — {status}: {str(payload)[:600]}")
        time.sleep(2.0)
    raise AtlasError(f"задание {job} не завершилось за {timeout:.0f} с")


def download(url: str, target: Path) -> None:
    """Скачивает попытку и обеззвучивает её.

    Звук снимается локально, а не только флагом generate_audio: флаг выставлен
    правильно, но полагаться на один барьер там, где дорожка поехала бы в монтаж
    под готовый мастер, не стоит.
    """
    if target.exists():
        raise AtlasError(f"попытка {target.name} уже скачана, не перезаписываю")
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = target.with_suffix(".raw.mp4")
    with requests.get(url, stream=True, timeout=600) as response:
        if response.status_code >= 400:
            raise AtlasError(f"скачивание ({response.status_code}): {url}")
        with open(raw, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw),
                    "-an", "-c:v", "copy", str(target)], check=True)
    raw.unlink()


def place(attempt: Path, slot: Path) -> None:
    """Кладёт выбранную попытку в слот, который читает рендер.

    Копией, а не переносом: файл попытки обязан остаться на месте, ради этого
    вся раскладка и заведена.
    """
    slot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(attempt, slot)


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    with open(LEDGER, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # Дописывать строку нового формата в журнал старого нельзя: столбцы
        # разъедутся молча, и первым потеряется как раз prediction_id.
        if reader.fieldnames != LEDGER_HEADER:
            raise AtlasError(
                f"журнал {LEDGER.name} другого формата.\n"
                f"  в файле: {', '.join(reader.fieldnames or [])}\n"
                f"  нужно:   {', '.join(LEDGER_HEADER)}\n"
                "  допиши колонки или удали файл — это только журнал расходов."
            )
        return list(reader)


def note(row: dict) -> None:
    fresh = not LEDGER.exists()
    if not fresh:
        ledger_rows()  # только ради проверки формата, до открытия на запись
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        if fresh:
            writer.writeheader()
        writer.writerow(row)


def attempt_path(anchor: str, number: int) -> Path:
    return ATTEMPTS / f"{anchor}_a{number}.mp4"


def attempts(anchor: str) -> list[int]:
    """Номера уже скачанных попыток кадра."""
    found = []
    for path in ATTEMPTS.glob(f"{anchor}_a*.mp4"):
        tail = path.stem.removeprefix(f"{anchor}_a")
        if tail.isdigit():
            found.append(int(tail))
    return sorted(found)


def attempt_number(anchor: str) -> int:
    """Номер следующей попытки — по журналу и по уже скачанным файлам.

    Одного журнала мало: стоит его удалить или переписать, и номер вернулся бы к
    единице, а новая генерация легла бы в файл существующей попытки.
    """
    counted = sum(1 for r in ledger_rows() if r["shot"] == anchor)
    return max([counted, *attempts(anchor)]) + 1


def estimate(shot: BaseShot, resolution: str) -> float:
    """Ожидаемая стоимость кадра в долларах, или nan, если её никто не мерил.

    Ноль тут был бы хуже всего: он выглядит как «бесплатно» и суммируется в
    итоговую строку, не меняя её. nan виден и в строке, и в сумме.
    """
    rate = TOKENS_PER_SECOND.get(resolution)
    if rate is None:
        return float("nan")
    return rate * shot.duration * USD_PER_MILLION_TOKENS / 1_000_000.0


def generate(shot: BaseShot, resolution: str, stamp: str) -> None:
    attempt = attempt_number(shot.anchor)
    cost = estimate(shot, resolution)
    target = attempt_path(shot.anchor, attempt)
    print(f"[{shot.anchor}] попытка {attempt}, {shot.duration:g} с "
          f"{resolution}, ожидаемо ${cost:.2f}", flush=True)

    row = {"timestamp": stamp, "shot": shot.anchor, "model": MODEL,
           "resolution": resolution, "duration": shot.duration,
           "attempt": attempt, "cost_estimate_usd": f"{cost:.4f}",
           "total_tokens": "", "status": "", "prediction_id": "",
           "file": shot.clip, "notes": ""}
    try:
        refs = [upload(ROOT / "assets" / "screenshots" / r) for r in shot.refs]
        # Идентификатор запоминаем сразу после отправки, а не после ожидания:
        # упади скачивание, оплаченный результат остаётся на стороне сервиса, и
        # забрать его можно только по нему — --refetch.
        job = submit(shot, refs, resolution)
        row["prediction_id"] = job
        url, tokens = wait(job)
        download(url, target)
        place(target, VIDEO / shot.clip)
    except (AtlasError, subprocess.CalledProcessError) as error:
        row["status"] = "failed"
        row["notes"] = str(error).replace("\n", " ")[:300]
        note(row)
        raise
    row["status"] = "ok"
    row["total_tokens"] = tokens
    note(row)
    print(f"[{shot.anchor}] готово: {target.relative_to(ROOT)} -> {shot.clip}, "
          f"токенов {tokens}, prediction {job}", flush=True)


def use_attempts(pairs: list[str], slots: dict[str, BaseShot]) -> int:
    """Переключает слоты на уже скачанные попытки, без генерации."""
    for pair in pairs:
        anchor, _, raw = pair.partition("=")
        if not raw.isdigit():
            raise AtlasError(f"--use ждёт пары ЯКОРЬ=НОМЕР, получено {pair!r}")
        shot = slots.get(anchor)
        if shot is None:
            raise AtlasError(f"нет такого якоря: {anchor}. "
                             f"Есть: {', '.join(slots)}")
        source = attempt_path(anchor, int(raw))
        if not source.exists():
            have = attempts(anchor)
            raise AtlasError(
                f"нет попытки {raw} кадра {anchor}. "
                + (f"Есть: {', '.join(str(n) for n in have)}" if have else
                   f"Скачанных попыток этого кадра нет вовсе — "
                   f"в {ATTEMPTS.relative_to(ROOT)} для него ничего не лежит.")
            )
        place(source, VIDEO / shot.clip)
        print(f"[{anchor}] слот {shot.clip} <- {source.relative_to(ROOT)}")
    return 0


def refetch(prediction_id: str, anchor: str, slots: dict[str, BaseShot]) -> int:
    """Забирает готовый результат по идентификатору, не платя за него заново.

    В слот не кладёт. Старую версию достают, чтобы сравнить её с той, что в слоте
    уже отобрана, и молча заменить отобранное было бы той же потерей, от которой
    вся раскладка и заведена. Переключает слот --use, и он же печатается готовой
    строкой в конце.
    """
    if anchor not in slots:
        raise AtlasError(f"--as: нет такого якоря: {anchor}. "
                         f"Есть: {', '.join(slots)}")
    url, _ = wait(prediction_id)
    number = attempt_number(anchor)
    target = attempt_path(anchor, number)
    download(url, target)
    note({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "shot": anchor,
          "attempt": number, "cost_estimate_usd": "0.0000", "status": "refetch",
          "prediction_id": prediction_id,
          # Модель и разрешение не пишем: ответ prediction/{id} мы читаем только
          # ради ссылки, и выдумывать за него поля этой строки нельзя.
          "notes": "повторное скачивание готового результата, оплаты нет"})
    print(f"[{anchor}] попытка {number}: {target.relative_to(ROOT)}")
    print(f"  в слот {slots[anchor].clip}: --use {anchor}={number}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Генерация кадров видеофона через Atlas Cloud")
    ap.add_argument("--shots", default=str(ROOT / "scenario" / "shots.json"))
    ap.add_argument("--only", nargs="+", metavar="ЯКОРЬ",
                    help="сгенерировать только эти кадры")
    ap.add_argument("--all", action="store_true", help="все кадры списка")
    ap.add_argument("--resolution", default=None,
                    help="переопределить разрешение, например 480p для пробы")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать, что будет отправлено, и не отправлять")
    ap.add_argument("--use", nargs="+", metavar="ЯКОРЬ=N",
                    help="положить в слот уже скачанную попытку, без генерации")
    ap.add_argument("--refetch", metavar="PREDICTION_ID",
                    help="забрать готовый результат по идентификатору из журнала")
    ap.add_argument("--as", dest="anchor", metavar="ЯКОРЬ",
                    help="какому кадру принадлежит результат --refetch")
    args = ap.parse_args()

    if sum(map(bool, [args.only or args.all, args.use, args.refetch])) != 1:
        ap.error("выбери одно: --only ЯКОРЬ [ЯКОРЬ...] | --all | "
                 "--use ЯКОРЬ=N | --refetch PREDICTION_ID --as ЯКОРЬ")
    if args.refetch and not args.anchor:
        ap.error("--refetch требует --as ЯКОРЬ: без якоря непонятно, чьей "
                 "попыткой стал бы скачанный файл")

    bases, _ = load_shots(args.shots)
    slots = {b.anchor: b for b in bases}

    if args.use or args.refetch:
        try:
            if args.use:
                return use_attempts(args.use, slots)
            key()
            return refetch(args.refetch, args.anchor, slots)
        except (AtlasError, subprocess.CalledProcessError) as error:
            print(error, file=sys.stderr)
            return 1

    if args.only:
        unknown = set(args.only) - {b.anchor for b in bases}
        if unknown:
            ap.error(f"нет таких якорей: {', '.join(sorted(unknown))}. "
                     f"Есть: {', '.join(b.anchor for b in bases)}")
    chosen = [b for b in bases if args.all or b.anchor in args.only]

    total = sum(estimate(b, args.resolution or b.resolution) for b in chosen)
    print(f"кадров: {len(chosen)}, ожидаемая стоимость ${total:.2f}")
    unknown = sorted({args.resolution or b.resolution for b in chosen}
                     - set(TOKENS_PER_SECOND))
    if unknown:
        print(f"ВНИМАНИЕ: расход на {', '.join(unknown)} никто не мерил, "
              f"сумма выше неполная. Известны: "
              f"{', '.join(TOKENS_PER_SECOND)}.")
    print()

    if args.dry_run:
        for shot in chosen:
            resolution = args.resolution or shot.resolution
            print(f"--- {shot.anchor} | {shot.duration:g} с | {resolution} "
                  f"| ${estimate(shot, resolution):.2f} ---")
            print(f"референсы: {', '.join(shot.refs) or 'нет'}")
            print(f"{full_prompt(shot)}\n")
        return 0

    # Ключ проверяем один раз и до цикла. Иначе он падал бы внутри generate(),
    # тот записывал бы в журнал строку failed и съедал номер попытки — ошибка
    # конфигурации не должна выглядеть в журнале как неудачная генерация.
    try:
        key()
    except AtlasError as error:
        print(error, file=sys.stderr)
        return 1

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    for shot in chosen:
        try:
            generate(shot, args.resolution or shot.resolution, stamp)
        except (AtlasError, subprocess.CalledProcessError) as error:
            print(f"[{shot.anchor}] ОШИБКА: {error}", file=sys.stderr)
            return 1
    print(f"\nжурнал: {LEDGER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
