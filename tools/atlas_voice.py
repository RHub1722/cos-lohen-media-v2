"""Озвучка реплик через Seed Audio 1.0 на Atlas Cloud.

Зачем отдельно от ElevenLabs: у Seed Audio поле `text` — не текст на прочтение,
а описание сцены с репликой внутри. Их собственный пример:

    "A phone vibrates first, then a calm male voice says: Welcome to Seed Audio."

То есть подача задаётся словами — режиссёрской ремаркой, — а не числовыми
ручками. Четыре пробы в ElevenLabs показали, что ручками нужного не добиться:
темп, высота, размах высоты и динамика уже совпадали с образцом из трейлера в
пределах 10 %, а на слух подача всё равно оставалась мёртвой.

Ремарка живёт в scenario/voices_ru.json рядом со своей репликой. Второго списка
реплик в проекте нет, как нет второго списка кадров.

Ключ берётся только из ATLASCLOUD_API_KEY и никуда не печатается — ни в журнал,
ни в текст ошибки.

Имена полей сняты со схемы модели, см. docs/atlas-api-audio.md. Не угадывать:
поля называются speech_rate/pitch_rate/loudness_rate и принимают целые в
диапазонах -50..100 и -12..12, а не множители, и обе очевидные догадки были бы
неверными.

    $env:ATLASCLOUD_API_KEY="..."
    python tools/atlas_voice.py --only lohen_security
    python tools/atlas_voice.py --only lohen_security --reference trailer_a
    python tools/atlas_voice.py --all
    python tools/atlas_voice.py --refetch <prediction_id> --as lohen_security
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Timeline  # noqa: E402
from src.voice_lines import (Line, LineError, budgets,  # noqa: E402
                            check_events, load_lines, sheet)

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.atlascloud.ai/api/v1/model"
MODEL = "bytedance/seed-audio-1.0"

# $0.015 за 1000 знаков — со страницы модели. Единственное число здесь, которое
# не снято с живого ответа: настоящее списание приезжает полем total_tokens, и
# после первых генераций эту оценку надо сверить с дашбордом, как это уже
# пришлось сделать с видео (там прежняя таблица врала вдвое и вниз).
USD_PER_1K_CHARS = 0.015

# 48 кГц и wav — формат проекта. Модель умеет до 48000, поэтому промежуточного
# перекодирования не будет вовсе: чем меньше пересжатий до мастера, тем лучше.
FORMAT = "wav"
SAMPLE_RATE = 48000

OUT = ROOT / "assets" / "voices" / "archive" / "atlas"
REFS = ROOT / "assets" / "voices" / "archive" / "refs"
LEDGER = ROOT / "docs" / "atlas-audio-ledger.csv"
LEDGER_HEADER = ["timestamp", "event", "chars", "cost_estimate_usd",
                 "total_tokens", "status", "prediction_id", "reference",
                 "file", "notes"]

# Оба слова: схема перечисляет completed, их пример пишет "completed, succeeded
# or failed". Проверять только одно — значит опрашивать готовый результат до
# таймаута. Ровно та же оговорка, что у видео.
DONE = ("completed", "succeeded")


class VoiceError(RuntimeError):
    pass


def key() -> str:
    value = os.environ.get("ATLASCLOUD_API_KEY", "").strip()
    if not value:
        raise VoiceError(
            "нет переменной окружения ATLASCLOUD_API_KEY.\n"
            '  PowerShell:  $env:ATLASCLOUD_API_KEY="..."\n'
            "  bash:        export ATLASCLOUD_API_KEY=..."
        )
    return value


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {key()}"}


def upload(path: Path) -> str:
    """Заливает образец голоса и возвращает временную ссылку.

    Имя поля в ответе — download_url, а не url: проверено живым ответом на
    видеомодели, в их питоновском примере стоит неверное.
    """
    if not path.exists():
        raise VoiceError(f"нет образца {path}")
    with open(path, "rb") as fh:
        response = requests.post(f"{API}/uploadMedia", headers=headers(),
                                 files={"file": fh}, timeout=120)
    if response.status_code >= 400:
        raise VoiceError(f"загрузка {path.name} отклонена "
                         f"({response.status_code}): {response.text[:400]}")
    data = response.json().get("data") or {}
    url = data.get("download_url") or data.get("url")
    if not url:
        raise VoiceError(f"в ответе на загрузку {path.name} нет ссылки: "
                         f"{response.text[:400]}")
    return url


def submit(prompt: str, reference_url: str = "", speech_rate: int = 0,
           pitch_rate: int = 0, loudness_rate: int = 0) -> str:
    body = {
        "model": MODEL,
        "text": prompt,
        "format": FORMAT,
        "sample_rate": SAMPLE_RATE,
        "pitch_rate": pitch_rate,
        "speech_rate": speech_rate,
        "loudness_rate": loudness_rate,
    }
    if reference_url:
        # Каждый элемент несёт ровно один источник — так написано в схеме,
        # поэтому пустые ключи не отправляем вовсе.
        body["references"] = [{"audio_url": reference_url}]

    response = requests.post(f"{API}/generateAudio", headers=headers(),
                             json=body, timeout=120)
    if response.status_code >= 400:
        raise VoiceError(f"задание отклонено ({response.status_code}): "
                         f"{response.text[:600]}")
    payload = response.json()
    job = payload.get("data", {}).get("id") or payload.get("id")
    if not job:
        raise VoiceError(f"в ответе нет id задания: {response.text[:400]}")
    return job


def wait(job: str, timeout: float = 600.0, beat: float = 20.0) -> tuple[str, int]:
    started = time.monotonic()
    deadline = started + timeout
    spoken = 0.0
    while time.monotonic() < deadline:
        waited = time.monotonic() - started
        if waited - spoken >= beat:
            spoken = waited
            print(f"    ждём {job}: {waited:.0f} с", flush=True)
        response = requests.get(f"{API}/prediction/{job}", headers=headers(),
                                timeout=60)
        if response.status_code >= 400:
            raise VoiceError(f"опрос {job} ({response.status_code}): "
                             f"{response.text[:400]}")
        payload = response.json()
        data = payload.get("data", payload)
        status = str(data.get("status", "")).lower()
        if status in DONE:
            outputs = data.get("outputs") or []
            if not outputs:
                raise VoiceError(f"задание {job} готово, но outputs пуст: "
                                 f"{str(payload)[:400]}")
            return outputs[0], int(data.get("total_tokens") or 0)
        if status in ("failed", "timeout"):
            raise VoiceError(f"задание {job} — {status}: {str(payload)[:600]}")
        time.sleep(2.0)
    raise VoiceError(f"задание {job} не завершилось за {timeout:.0f} с")


def download(url: str, target: Path) -> None:
    """Скачивает попытку. Существующую не перезаписывает: она стоит денег, а
    достать её обратно можно только по prediction_id."""
    if target.exists():
        raise VoiceError(f"попытка {target.name} уже скачана, не перезаписываю")
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=600) as response:
        if response.status_code >= 400:
            raise VoiceError(f"скачивание ({response.status_code}): {url}")
        with open(target, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 16):
                fh.write(chunk)


def measure(path: Path) -> tuple[float, float]:
    """Длительность и пик. Нужны сразу: реплика, не влезающая в своё окно,
    бесполезна, каким бы удачным ни вышел дубль."""
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip() or 0.0)
    info = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True,
        encoding="utf-8", errors="replace").stderr
    peak = 0.0
    for token in info.split("max_volume:")[1:]:
        peak = float(token.split("dB")[0].strip())
    return dur, peak


def next_attempt(event: str) -> Path:
    """Следующий свободный номер попытки. Затирать нельзя — то же правило, что
    у кадров видео."""
    OUT.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        path = OUT / f"{event}_a{n}.{FORMAT}"
        if not path.exists():
            return path
    raise VoiceError(f"{event}: сто попыток — дальше меняется не спенд, а подход")


def ledger_append(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    if not fresh:
        with open(LEDGER, encoding="utf-8") as fh:
            if csv.DictReader(fh).fieldnames != LEDGER_HEADER:
                raise VoiceError(
                    f"{LEDGER} другого формата — столбцы разъедутся молча, а "
                    "первым потеряется prediction_id")
    with open(LEDGER, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        if fresh:
            writer.writeheader()
        writer.writerow(row)


def generate(line: Line, budget: float, reference: Path | None,
             speech_rate: int, pitch_rate: int, loudness_rate: int,
             note: str = "") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chars = len(line.prompt)
    cost = chars / 1000.0 * USD_PER_1K_CHARS
    ref_url = upload(reference) if reference else ""
    print(f"  {line.event}: {chars} знаков, ~${cost:.4f}"
          + (f", образец {reference.name}" if reference else ", без образца"))
    print(f"    промпт: {line.prompt}")

    job = ""
    try:
        job = submit(line.prompt, ref_url, speech_rate, pitch_rate,
                     loudness_rate)
        url, tokens = wait(job)
        target = next_attempt(line.event)
        download(url, target)
    except Exception as failure:
        ledger_append({"timestamp": stamp, "event": line.event,
                       "chars": chars,
                       "cost_estimate_usd": f"{cost:.4f}",
                       "total_tokens": "", "status": "error",
                       "prediction_id": job,
                       "reference": reference.name if reference else "",
                       "file": "", "notes": str(failure)[:200]})
        raise

    dur, peak = measure(target)
    verdict = "влезает" if dur <= budget else f"НЕ ВЛЕЗАЕТ в {budget:.2f}"
    print(f"    {target.name}: {dur:.3f} с, пик {peak:.1f} dB, "
          f"бюджет {budget:.2f} с — {verdict}")
    ledger_append({"timestamp": stamp, "event": line.event,
                   "chars": line.chars, "cost_estimate_usd": f"{cost:.4f}",
                   "total_tokens": tokens, "status": "ok",
                   "prediction_id": job,
                   "reference": reference.name if reference else "",
                   "file": target.name,
                   "notes": f"{dur:.3f}s peak {peak:.1f}dB; {note}".strip()})
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", metavar="EVENT",
                        help="озвучить только эти реплики")
    parser.add_argument("--all", action="store_true",
                        help="озвучить все реплики из voices_ru.json")
    parser.add_argument("--reference", metavar="FILE",
                        help=f"образец голоса из {REFS.relative_to(ROOT)} "
                             "без расширения")
    parser.add_argument("--speech-rate", type=int, default=0,
                        help="темп, -50..100, по умолчанию 0")
    parser.add_argument("--pitch-rate", type=int, default=0,
                        help="высота, -12..12, по умолчанию 0")
    parser.add_argument("--loudness-rate", type=int, default=0,
                        help="громкость, -50..100, по умолчанию 0")
    parser.add_argument("--note", default="", help="пометка в журнал")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать промпты и оценку, ничего не отправлять")
    parser.add_argument("--sheet", action="store_true",
                        help="напечатать лист для записи голосом и выйти")
    args = parser.parse_args()

    lines = load_lines()
    tl = Timeline.load(ROOT / "scenario" / "timeline.json")
    room = budgets(tl)

    if args.sheet:
        out = sheet(lines, room, tl)
        print(f"лист: {out.relative_to(ROOT)}")
        for line in lines:
            print(f"  {line.event:<17} {room[line.event]:>5.2f} с  «{line.line}»")
        return 0

    check_events(lines, tl)

    if args.only:
        known = {line.event for line in lines}
        unknown = [name for name in args.only if name not in known]
        if unknown:
            raise VoiceError(f"нет таких реплик в voices_ru.json: {unknown}")
        lines = [line for line in lines if line.event in args.only]
    elif not args.all:
        parser.error("нужен --only или --all")

    reference = None
    if args.reference:
        for suffix in (".wav", ".mp3", ".m4a"):
            candidate = REFS / f"{args.reference}{suffix}"
            if candidate.exists():
                reference = candidate
                break
        if reference is None:
            raise VoiceError(f"нет образца {args.reference} в {REFS}")

    total = sum(len(line.prompt) for line in lines) / 1000.0 * USD_PER_1K_CHARS
    print(f"реплик: {len(lines)}, оценка ${total:.4f}")
    if args.dry_run:
        for line in lines:
            budget = room.get(line.event)
            print(f"  {line.event}: бюджет "
                  + (f"{budget:.2f} с" if budget else "нет в сценарии"))
            print(f"    {line.prompt}")
        return 0

    for line in lines:
        budget = room.get(line.event)
        if budget is None:
            raise VoiceError(
                f"{line.event}: такого события нет в timeline.json — реплику "
                "некуда ставить")
        generate(line, budget, reference, args.speech_rate, args.pitch_rate,
                 args.loudness_rate, args.note)
    print(f"журнал: {LEDGER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (VoiceError, LineError) as failure:
        print(f"ОШИБКА: {failure}", file=sys.stderr)
        sys.exit(1)
