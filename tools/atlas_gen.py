"""Генерация кадров видеофона через Atlas Cloud.

Читает тот же scenario/shots.json, что и рендер: промпт живёт рядом со своим
якорем, и второго списка кадров в проекте нет.

Ключ берётся только из переменной окружения ATLASCLOUD_API_KEY и никуда не
печатается — ни в журнал, ни в сообщение об ошибке.

Имена полей запроса взяты из docs/atlas-api.md, снятых со схемы модели. Не
угадывать: у модели, например, вообще нет поля запретов, а пропорции называются
ratio, и обе очевидные догадки были бы неверными.

    $env:ATLASCLOUD_API_KEY="..."
    python tools/atlas_gen.py --only interrogation combat --resolution 480p
    python tools/atlas_gen.py --all
"""

from __future__ import annotations

import argparse
import csv
import os
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

# Оценка, а не факт: списывает Atlas в токенах, и настоящее число приезжает в
# ответе полем total_tokens. Нужна, чтобы знать сумму до отправки.
RATE_PER_SECOND = {"480p": 0.056, "720p": 0.061,
                   "720p-SR": 0.061, "1080p-SR": 0.075, "1440p-SR": 0.090}

LEDGER = ROOT / "docs" / "atlas-ledger.csv"
LEDGER_HEADER = ["timestamp", "shot", "model", "resolution", "duration",
                 "attempt", "cost_estimate_usd", "total_tokens", "status",
                 "file", "notes"]

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
    url = payload.get("url") or payload.get("data", {}).get("url")
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


def wait(job: str, timeout: float = 900.0) -> tuple[str, int]:
    """Опрашивает задание и возвращает ссылку на результат и списанные токены."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
    """Скачивает и обеззвучивает при переносе на место.

    Звук снимается локально, а не только флагом generate_audio: флаг выставлен
    правильно, но полагаться на один барьер там, где дорожка поехала бы в монтаж
    под готовый мастер, не стоит.
    """
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


def note(row: dict) -> None:
    fresh = not LEDGER.exists()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        if fresh:
            writer.writeheader()
        writer.writerow(row)


def attempt_number(anchor: str) -> int:
    if not LEDGER.exists():
        return 1
    with open(LEDGER, encoding="utf-8") as fh:
        return sum(1 for r in csv.DictReader(fh) if r["shot"] == anchor) + 1


def estimate(shot: BaseShot, resolution: str) -> float:
    return RATE_PER_SECOND.get(resolution, 0.061) * shot.duration


def generate(shot: BaseShot, resolution: str, stamp: str) -> None:
    attempt = attempt_number(shot.anchor)
    cost = estimate(shot, resolution)
    target = ROOT / "assets" / "video" / shot.clip
    print(f"[{shot.anchor}] попытка {attempt}, {shot.duration:g} с "
          f"{resolution}, ожидаемо ${cost:.2f}")

    row = {"timestamp": stamp, "shot": shot.anchor, "model": MODEL,
           "resolution": resolution, "duration": shot.duration,
           "attempt": attempt, "cost_estimate_usd": f"{cost:.4f}",
           "total_tokens": "", "status": "", "file": shot.clip, "notes": ""}
    try:
        refs = [upload(ROOT / "assets" / "screenshots" / r) for r in shot.refs]
        url, tokens = wait(submit(shot, refs, resolution))
        download(url, target)
    except (AtlasError, subprocess.CalledProcessError) as error:
        row["status"] = "failed"
        row["notes"] = str(error).replace("\n", " ")[:300]
        note(row)
        raise
    row["status"] = "ok"
    row["total_tokens"] = tokens
    note(row)
    print(f"[{shot.anchor}] готово: {target.relative_to(ROOT)}, "
          f"токенов {tokens}")


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
    args = ap.parse_args()

    if not args.only and not args.all:
        ap.error("укажи --only ЯКОРЬ [ЯКОРЬ...] или --all")

    bases, _ = load_shots(args.shots)
    if args.only:
        unknown = set(args.only) - {b.anchor for b in bases}
        if unknown:
            ap.error(f"нет таких якорей: {', '.join(sorted(unknown))}. "
                     f"Есть: {', '.join(b.anchor for b in bases)}")
    chosen = [b for b in bases if args.all or b.anchor in args.only]

    total = sum(estimate(b, args.resolution or b.resolution) for b in chosen)
    print(f"кадров: {len(chosen)}, ожидаемая стоимость ${total:.2f}\n")

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
