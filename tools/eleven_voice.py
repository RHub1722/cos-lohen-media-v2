"""Озвучка реплик через ElevenLabs напрямую по HTTP.

Не через MCP. У MCP-обёртки входные файлы ограничены папкой предыдущего проекта
(`Resource path ... is outside of allowed directory C:\\Cosplay\\audio-project\\
assets\\voices`), из-за чего преобразование голоса, изоляция и клонирование были
недоступны вообще. У самого API такого ограничения нет.

Реплики и бюджеты берутся из src/voice_lines.py — того же места, что у Seed
Audio и у листа записи. Подача задаётся полем `tags`: у v3 разметка в квадратных
скобках это указание, а не текст. Проверено замером — одиночный тег вслух не
читается, длина результата не меняется.

Ключ берётся только из ELEVENLABS_API_KEY и никуда не печатается.

    $env:ELEVENLABS_API_KEY="..."
    python tools/eleven_voice.py --all --voice myvoicefordublo
    python tools/eleven_voice.py --only lohen_security --voice lo_v41 --speed 0.85
    python tools/eleven_voice.py --preview --voice myvoicefordublo
    python tools/eleven_voice.py --list-voices
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Timeline  # noqa: E402
from src.voice_lines import (MARGIN, Line, LineError, budgets,  # noqa: E402
                            check_events, effective_budget, load_lines, sheet)

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.elevenlabs.io/v1"

# Голоса аккаунта под понятными именами. Шесть Лоэнов и клон завёл не этот
# проект — в манифесте записаны только два, остальные нашлись в аккаунте, когда
# появился прямой доступ к API. Замер на одной фразе против образца из трейлера:
#   lo_v2  177 Гц,  8.7 полутона  — тот, которым озвучено всё до сих пор
#   lo_v41 140 Гц, 10.1 полутона  — ближе всех к образцу (142 Гц, 10.9)
#   myvoicefordublo 175 Гц, 9.2   — клон, сделанный вручную
VOICES = {
    "lo_v1": "E4UXLQYGPYWw6BP7Ni8i",
    "lo_v2": "5L1KqcuIYxrRg4k4opVX",
    "lo_v3": "ZVs7VoQ67WUTef6Lna37",
    "lo_v41": "W3tYSqeNCLEtvVfN69Yb",
    "lo_v42": "IeGAb0ePVBJDyqCrlchc",
    "lo_v43": "uDSaWrHTB652th5qIHNu",
    "myvoicefordublo": "U4nbY8fg0Ls2nrMzolqn",
    "christian": "pIsMvEB8LP1GR5k3OcQj",
    "dominic": "yhf80q1381zd2JJQ4tM7",
    "james": "EkK5I93UQWFDigLMpZcX",
    # Голоса из публичной библиотеки, подобранные под канон персонажа. Лоэн —
    # официальный персонаж Genshin Impact (5 звёзд, Крио, копьё, релиз
    # 09.06.2026), английский голос Nick Wolfhard. Тэглайн тизера «don't let his
    # smile fool you»: молодой светлый голос со скрытой жестокостью, а не бас.
    # Замер эталона это подтверждает — 142 Гц медианы для мужского голоса высоко.
    #
    # Отбор шёл по подтверждённому русскому языку в метках голоса, и пул тонкий:
    # из ~20 голосов с сильным описанием злодея русский нашёлся у пяти-шести.
    # Сильные по характеру Viktor, Seth, Zayn, Blackwood отброшены именно из-за
    # отсутствия русского.
    "edward": "zYcjlYFOd3taleS0gkk3",
    "callum_lib": "fs2OqxduwXgp9foh2xjK",
    "alexander": "DS6EUI0539yrd2EB0eig",
}

MODEL = "eleven_v3"
# Из двух моделей преобразования голоса русский держит только эта — проверено
# через /models по флагу can_do_voice_conversion и списку языков.
STS_MODEL = "eleven_multilingual_sts_v2"
# Списывается по времени, а не по знакам: 1000 кредитов за минуту записи.
CREDITS_PER_MINUTE_STS = 1000
# mp3, а не pcm: исходники всех прежних реплик тоже mp3, а к 48 кГц и 24 битам
# приводит src/import_assets.py. Второй путь приведения породил бы вторую
# правду о том, как ассет попадает в мастер.
OUTPUT_FORMAT = "mp3_44100_192"

# Замерено на пробах: 28 кредитов за две генерации по 26 знаков.
CREDITS_PER_CHAR = 0.54

OUT = ROOT / "assets" / "voices" / "archive" / "eleven"
# Выровненные по громкости копии записей. Производные — значит в archive, рядом
# с оригиналами в my/ им не место: их легко принять за сами дубли.
NORM = ROOT / "assets" / "voices" / "archive" / "norm"
LEDGER = ROOT / "docs" / "eleven-voice-ledger.csv"
LEDGER_HEADER = ["timestamp", "event", "voice", "model", "chars",
                 "credits_estimate", "stability", "similarity", "speed",
                 "seconds", "budget", "fits", "peak_db", "file", "notes"]


class VoiceError(RuntimeError):
    pass


def key() -> str:
    value = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not value:
        raise VoiceError(
            "нет переменной окружения ELEVENLABS_API_KEY.\n"
            '  PowerShell:  $env:ELEVENLABS_API_KEY="..."'
        )
    return value


def headers() -> dict[str, str]:
    return {"xi-api-key": key(), "Content-Type": "application/json"}


def resolve_voice(name: str) -> tuple[str, str]:
    """Имя или сырой id. Возвращает (понятное имя, id)."""
    if name in VOICES:
        return name, VOICES[name]
    for label, vid in VOICES.items():
        if vid == name:
            return label, vid
    # Незнакомый id пропускаем: голоса в аккаунте добавляются и без этого файла.
    if len(name) >= 20 and name.isalnum():
        return name[:8], name
    raise VoiceError(
        f"неизвестный голос {name!r}. Известные: {', '.join(sorted(VOICES))}\n"
        "  либо передай сырой voice_id, либо посмотри --list-voices")


def list_voices() -> None:
    response = requests.get(f"{API}/voices", headers={"xi-api-key": key()},
                            timeout=60)
    if response.status_code >= 400:
        raise VoiceError(f"/voices ({response.status_code}): "
                         f"{response.text[:300]}")
    known = {vid: label for label, vid in VOICES.items()}
    for item in response.json().get("voices", []):
        vid = item.get("voice_id", "")
        label = known.get(vid, "")
        print(f"  {item.get('name', ''):<40} {item.get('category', ''):<13} "
              f"{vid}  {label}")


def synth(line: Line, voice_id: str, stability: float, similarity: float,
          speed: float, style: float = 0.0) -> bytes:
    settings = {"stability": stability, "similarity_boost": similarity,
                "speed": speed}
    # style только когда его просили: у v3 этого рычага нет, и посылать его
    # нулём в каждый запрос значит однажды получить отказ на пустом месте.
    if style:
        settings["style"] = style
    response = requests.post(
        f"{API}/text-to-speech/{voice_id}",
        params={"output_format": OUTPUT_FORMAT}, headers=headers(),
        json={"text": line.tagged, "model_id": MODEL,
              "voice_settings": settings}, timeout=300)
    if response.status_code >= 400:
        raise VoiceError(f"{line.event}: отказ ({response.status_code}): "
                         f"{response.text[:400]}")
    if not response.content:
        raise VoiceError(f"{line.event}: пустой ответ")
    return response.content


def convert(take: Path, voice_id: str, remove_noise: bool = False,
            stability: float | None = None,
            similarity: float | None = None) -> bytes:
    """Преобразование голоса: тембр от целевого голоса, игра от записи.

    Модель `eleven_multilingual_sts_v2` — единственная из двух, которая держит
    русский; английская версия его не понимает. Тайминг сохраняется ровно:
    длина результата равна длине записи, растянуть или сжать нельзя.

    voice_settings до сих пор сюда не посылались вовсе, то есть весь материал
    сделан на умолчаниях сервера. Посылаются они только когда заданы: пустые
    значения сервер трактует не как «оставь по умолчанию», а как ноль.
    """
    form = {"model_id": STS_MODEL,
            "remove_background_noise": str(remove_noise).lower()}
    settings = {}
    if stability is not None:
        settings["stability"] = stability
    if similarity is not None:
        settings["similarity_boost"] = similarity
    if settings:
        form["voice_settings"] = json.dumps(settings)
    with open(take, "rb") as fh:
        response = requests.post(
            f"{API}/speech-to-speech/{voice_id}",
            params={"output_format": OUTPUT_FORMAT},
            headers={"xi-api-key": key()},
            files={"audio": (take.name, fh, "audio/wav")},
            data=form,
            timeout=600)
    if response.status_code >= 400:
        raise VoiceError(f"{take.name}: преобразование отклонено "
                         f"({response.status_code}): {response.text[:400]}")
    if not response.content:
        raise VoiceError(f"{take.name}: пустой ответ")
    return response.content


def loudness(path: Path) -> tuple[float, float]:
    """Интегральная громкость и истинный пик — то, чем слышится уровень.

    volumedetect для этого не годится: он меряет пик, а пик у речи гуляет от
    одного согласного. Дубли, записанные в разные заходы, разошлись по
    громкости на 13.5 dB, и увидеть это можно только по LUFS.
    """
    info = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af",
         "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace").stderr
    blob = json.loads(info[info.rindex("{"):info.rindex("}") + 1])
    return float(blob["input_i"]), float(blob["input_tp"])


def normalized_copy(take: Path, target: float, by_peak: bool,
                    peak_ceiling: float = -1.0) -> tuple[Path, float]:
    """Копия записи, поднятая одним гейном. Ни сжатия, ни лимитера.

    Игра остаётся ровно той же, меняется только уровень — иначе это была бы
    правка записи, а не подготовка входа.

    По пику или по громкости — разница не косметическая. У тихих дублей
    гребень между пиком и громкостью доходит до 24 dB: «Шесть гнёзд» лежит на
    −30 LUFS при пике −6.0, и поднять её до −20 LUFS значило бы загнать пик на
    +4 dBFS. Потолок это срежет, и цель по громкости всё равно не возьмётся.
    Значит для входа модели честнее пик: он даёт максимум сигнала без риска
    перегруза и не трогает разницу в подаче между репликами.
    """
    NORM.mkdir(parents=True, exist_ok=True)
    current, peak = loudness(take)
    gain = (target - peak) if by_peak else (target - current)
    if peak + gain > peak_ceiling:
        gain = peak_ceiling - peak
    kind = "pk" if by_peak else "lufs"
    out = NORM / f"{take.stem}__{target:g}{kind}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(take),
         "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(out)],
        check=True)
    return out, gain


def measure(path: Path) -> tuple[float, float]:
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


def next_attempt(event: str, voice: str) -> Path:
    """Попытки не затираются: каждая стоит кредитов, и сравнивать дубли можно
    только когда они все на месте."""
    OUT.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        path = OUT / f"{event}__{voice}_a{n}.mp3"
        if not path.exists():
            return path
    raise VoiceError(f"{event}: сто попыток — дальше меняется не спенд, а подход")


def ledger_append(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    if not fresh:
        with open(LEDGER, encoding="utf-8") as fh:
            if csv.DictReader(fh).fieldnames != LEDGER_HEADER:
                raise VoiceError(f"{LEDGER} другого формата — столбцы разъедутся")
    with open(LEDGER, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_HEADER)
        if fresh:
            writer.writeheader()
        writer.writerow(row)


def generate(line: Line, budget: float, voice: str, voice_id: str,
             stability: float, similarity: float, speed: float, style: float,
             note: str) -> tuple[Path, float, bool]:
    use_speed = line.speed if line.speed is not None else speed
    chars = len(line.tagged)
    audio = synth(line, voice_id, stability, similarity, use_speed, style)
    target = next_attempt(line.event, voice)
    target.write_bytes(audio)
    dur, peak = measure(target)
    fits = dur <= budget

    # Разметка длиннее самой реплики, поэтому прочитанный вслух тег виден в
    # длине сразу: без него на реплику из 20 знаков уходит около полутора секунд.
    leak = dur > (len(line.line) / 6.0) + 1.5
    verdict = "влезает" if fits else f"НЕ ВЛЕЗАЕТ в {budget:.2f}"
    print(f"  {line.event:<17} {dur:>5.2f} с / {budget:>5.2f}  пик {peak:>5.1f} dB"
          f"  темп {use_speed:.2f}  {verdict}"
          + ("   ВОЗМОЖНО ПРОЧЁЛ ТЕГ" if leak else ""))

    ledger_append({
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": line.event, "voice": voice, "model": MODEL, "chars": chars,
        "credits_estimate": round(chars * CREDITS_PER_CHAR),
        "stability": stability, "similarity": similarity, "speed": use_speed,
        "seconds": f"{dur:.3f}", "budget": f"{budget:.2f}",
        "fits": "да" if fits else "нет", "peak_db": f"{peak:.1f}",
        "file": target.name,
        "notes": (note + (" ТЕГ?" if leak else "")).strip(),
    })
    return target, dur, fits


def preview(tl: Timeline, picked: dict[str, Path], out: Path) -> Path:
    """Все реплики на своих таймкодах поверх тишины длиной в номер.

    Склейка подряд показала бы только тембр. На настоящих таймкодах слышно
    другое: попадают ли реплики в свои окна и как речь дышит внутри номера.
    """
    by_id = {e.id: e for e in tl.events}
    inputs, filters, labels = [], [], []
    for i, (event, path) in enumerate(sorted(
            picked.items(), key=lambda kv: by_id[kv[0]].t)):
        inputs += ["-i", str(path)]
        ms = int(round(by_id[event].t * 1000))
        filters.append(f"[{i}:a]aformat=sample_rates=48000:"
                       f"channel_layouts=stereo,adelay={ms}|{ms}[d{i}]")
        labels.append(f"[d{i}]")
    if not labels:
        raise VoiceError("нечего складывать в превью")
    graph = ";".join(filters) + ";" + "".join(labels) + \
        f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mix]"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                    "-filter_complex", graph, "-map", "[mix]",
                    "-t", str(tl.total_duration), "-ar", "48000", "-ac", "2",
                    str(out)], check=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", metavar="EVENT")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--voice", default="myvoicefordublo",
                        help="имя из VOICES или сырой voice_id")
    parser.add_argument("--stability", type=float, default=0.5,
                        help="0.0 творчески, 0.5 естественно, 1.0 устойчиво. "
                             "Замер: 0.0 сужает размах высоты, а не расширяет")
    parser.add_argument("--similarity", type=float, default=0.75)
    parser.add_argument("--speed", type=float, default=0.9,
                        help="общий темп; реплики со своим speed его не берут")
    parser.add_argument("--style", type=float, default=0.0,
                        help="только для моделей v2, у v3 рычага нет")
    parser.add_argument("--preview", action="store_true",
                        help="собрать превью из последних попыток этого голоса")
    parser.add_argument("--sheet", action="store_true",
                        help="лист записи голосом; ориентиры по темпу берутся "
                             "из готовых генераций выбранного голоса")
    parser.add_argument("--list-voices", action="store_true")
    parser.add_argument("--take", action="append", metavar="EVENT=ФАЙЛ",
                        help="преобразовать записанный дубль вместо генерации; "
                             "путь относительно assets/voices/my")
    parser.add_argument("--label", default="",
                        help="метка для файлов преобразования, чтобы они не "
                             "смешались с синтезом того же голоса")
    parser.add_argument("--remove-noise", action="store_true",
                        help="снять фон с записи перед преобразованием")
    parser.add_argument("--normalize-in", type=float, metavar="LUFS",
                        help="привести запись к этой громкости перед "
                             "преобразованием. Гейн линейный, игра не "
                             "меняется. Дубли разошлись на 13.5 dB, и модель "
                             "получала то нормальный вход, то очень тихий")
    parser.add_argument("--normalize-peak", type=float, metavar="DBFS",
                        help="то же, но целью служит пик, а не громкость. Для "
                             "тихих дублей единственный работающий вариант: "
                             "цель по громкости упрётся в потолок раньше, чем "
                             "будет взята")
    parser.add_argument("--sts-settings", action="store_true",
                        help="послать stability и similarity в преобразование. "
                             "Без этого флага идут умолчания сервера — так "
                             "сделан весь материал до сих пор")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if args.list_voices:
        list_voices()
        return 0

    lines = load_lines()
    tl = Timeline.load(ROOT / "scenario" / "timeline.json")
    room = budgets(tl)
    check_events(lines, tl)
    voice, voice_id = resolve_voice(args.voice)

    if args.take:
        by_id = {line.event: line for line in lines}
        label = args.label or f"{voice}sts"
        total_seconds = 0.0
        for pair in args.take:
            if "=" not in pair:
                raise VoiceError(f"--take ждёт EVENT=ФАЙЛ, получено {pair!r}")
            event, name = pair.split("=", 1)
            if event not in by_id:
                raise VoiceError(f"нет реплики {event!r} в voices_ru.json")
            take = ROOT / "assets" / "voices" / "my" / name
            if not take.exists():
                raise VoiceError(f"нет записи {take}")
            source_sec, source_peak = measure(take)
            total_seconds += source_sec
            gain = 0.0
            if args.normalize_in is not None and args.normalize_peak is not None:
                raise VoiceError("--normalize-in и --normalize-peak вместе не "
                                 "работают: цель уровня одна")
            if args.normalize_peak is not None:
                take, gain = normalized_copy(take, args.normalize_peak, True)
            elif args.normalize_in is not None:
                take, gain = normalized_copy(take, args.normalize_in, False)
            audio = convert(
                take, voice_id, args.remove_noise,
                stability=args.stability if args.sts_settings else None,
                similarity=args.similarity if args.sts_settings else None)
            target = next_attempt(event, label)
            target.write_bytes(audio)
            out_sec, out_peak = measure(target)
            budget = effective_budget(by_id[event], room)
            fits = out_sec <= budget
            # Тайминг обязан сохраниться. Расхождение больше 0.15 с означает,
            # что модель повела себя не так, как заявлено, и на это надо
            # смотреть, а не списывать на округление.
            drift = out_sec - source_sec
            print(f"  {event:<17} запись {source_sec:>5.2f} с (пик "
                  f"{source_peak:>5.1f}"
                  + (f", вход {gain:+.1f} dB" if gain else "")
                  + f") -> {out_sec:>5.2f} с (пик "
                  f"{out_peak:>5.1f})  бюджет {budget:>5.2f}  "
                  + ("влезает" if fits else
                     f"ПЕРЕБОР {out_sec - budget:.2f} с")
                  + (f"   ТАЙМИНГ УЕХАЛ на {drift:+.2f} с"
                     if abs(drift) > 0.15 else ""))
            ledger_append({
                "timestamp": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": event, "voice": f"{label}<-{voice}", "model": STS_MODEL,
                "chars": 0,
                "credits_estimate": round(source_sec / 60 * CREDITS_PER_MINUTE_STS),
                # Пусто означает «умолчания сервера», а не «ноль»: до появления
                # --sts-settings настройки в преобразование не уходили вовсе.
                "stability": args.stability if args.sts_settings else "",
                "similarity": args.similarity if args.sts_settings else "",
                "speed": "",
                "seconds": f"{out_sec:.3f}", "budget": f"{budget:.2f}",
                "fits": "да" if fits else "нет", "peak_db": f"{out_peak:.1f}",
                "file": target.name,
                "notes": (f"из {name}"
                          + (f"; вход {args.normalize_peak:g} dBFS по пику "
                             f"({gain:+.1f} dB)"
                             if args.normalize_peak is not None else "")
                          + (f"; вход {args.normalize_in:g} LUFS "
                             f"({gain:+.1f} dB)"
                             if args.normalize_in is not None else "")
                          + (f"; {args.note}" if args.note else "")),
            })
        print(f"\nсписано примерно "
              f"{round(total_seconds / 60 * CREDITS_PER_MINUTE_STS)} кредитов "
              f"за {total_seconds:.1f} с записи")
        print(f"журнал: {LEDGER.relative_to(ROOT)}")
        return 0

    if args.sheet:
        # Ориентир по темпу — длина уже сделанной генерации: в неё реплика
        # заведомо влезала, и держать в голове её проще, чем лимит.
        refs = {}
        for line in lines:
            found = sorted(OUT.glob(f"{line.event}__{voice}_a*.mp3"),
                           key=lambda p: int(p.stem.rsplit("_a", 1)[1]))
            if found:
                refs[line.event] = measure(found[-1])[0]
        out = sheet(lines, room, tl, refs=refs)
        print(f"лист: {out.relative_to(ROOT)}   ориентиров из голоса {voice}: "
              f"{len(refs)} из {len(lines)}\n")
        print("%-17s %7s %9s  %s" % ("реплика", "цель", "ориентир", "текст"))
        for line in sorted(lines, key=lambda ln: effective_budget(ln, room)):
            ref = refs.get(line.event)
            hard = effective_budget(line, room)
            print("%-17s %6.2fс %8s  «%s»"
                  % (line.event, hard - MARGIN,
                     f"{ref:.2f}с" if ref else "-", line.line))
        return 0

    if args.only:
        known = {line.event for line in lines}
        unknown = [n for n in args.only if n not in known]
        if unknown:
            raise VoiceError(f"нет таких реплик: {unknown}")
        lines = [line for line in lines if line.event in args.only]
    elif not (args.all or args.preview):
        parser.error("нужен --only, --all, --preview, --sheet или --list-voices")

    if args.preview and not (args.all or args.only):
        picked = {}
        for line in lines:
            # По номеру, а не по имени: строковая сортировка поставила бы a10
            # перед a2 и молча взяла в превью не последний дубль.
            found = sorted(OUT.glob(f"{line.event}__{voice}_a*.mp3"),
                           key=lambda p: int(p.stem.rsplit("_a", 1)[1]))
            if found:
                picked[line.event] = found[-1]
        if not picked:
            raise VoiceError(f"нет готовых попыток голосом {voice}")
        out = preview(tl, picked, ROOT / "output" / f"voices_ru_{voice}.wav")
        print(f"превью: {out.relative_to(ROOT)} из {len(picked)} реплик")
        return 0

    chars = sum(len(line.tagged) for line in lines)
    print(f"голос {voice} ({voice_id}), модель {MODEL}, реплик {len(lines)}")
    print(f"знаков {chars}, оценка {round(chars * CREDITS_PER_CHAR)} кредитов\n")

    made: dict[str, Path] = {}
    bad: list[str] = []
    for line in lines:
        target, _, fits = generate(line, effective_budget(line, room),
                                   voice, voice_id,
                                   args.stability, args.similarity, args.speed,
                                   args.style, args.note)
        made[line.event] = target
        if not fits:
            bad.append(line.event)

    print(f"\nжурнал: {LEDGER.relative_to(ROOT)}")
    if bad:
        print(f"не влезли в своё окно: {', '.join(bad)} — этим репликам нужен "
              "текст короче или темп выше")
    if args.preview:
        out = preview(tl, made, ROOT / "output" / f"voices_ru_{voice}.wav")
        print(f"превью: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (VoiceError, LineError) as failure:
        print(f"ОШИБКА: {failure}", file=sys.stderr)
        sys.exit(1)
