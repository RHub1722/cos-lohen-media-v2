"""Генератор тренажёра номера: один самодостаточный HTML рядом с видео.

    python src/render_training.py            # output/training.html, мастер-видео
    python src/render_training.py --site     # site/index.html, сжатое видео

Данные вшиваются в страницу при генерации: из `file://` браузер не даст
подгрузить внешний JSON, а страница обязана открываться двойным щелчком, без
сервера и без интернета.

Видео подключается относительным путём и лежит рядом. Так папку из двух файлов
можно скопировать на планшет целиком, и ничего не сломается.

`--site` собирает версионируемую копию в `site/`: ту же страницу и сжатое до
960×540 видео на четыре с половиной мегабайта вместо тридцати. Это единственное
место, где производный файл попадает в репозиторий, и попадает намеренно — иначе
страницу нельзя открыть с гита на планшете. Мастер `output/final_v2.mp4` при
этом не трогается: он остаётся файлом сдачи.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.footage import load_shots, resolve  # noqa: E402
from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402
from src.peaks import peak_offsets  # noqa: E402
from src.render_rehearsal import build_scenes  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402
from src.video_plan import build_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/training_template.html"
MARKER = "/*__DATA__*/"

# Версионируемая копия для планшета: открывается прямо с гита, поэтому вес имеет
# значение. 960×540 хватает, чтобы видеть, где вспышка и что на экране, а по
# мобильной связи это четыре с половиной мегабайта вместо тридцати одного.
SITE_DIR = ROOT / "site"
SITE_VIDEO = "lohen-60s.mp4"
SITE_SCALE = "960:540"
SITE_CRF = "24"
MASTER_VIDEO = ROOT / "output/final_v2.mp4"

# Запасной адрес видео для опубликованной копии. Нужен ровно одному случаю:
# страницу открыли через прокси вроде raw.githack, который отдаёт mp4 с типом
# application/octet-stream, и Safari на планшете такой файл проигрывать
# отказывается. jsDelivr отдаёт video/mp4, но HTML у него уходит как text/plain,
# то есть заменить прокси целиком он не может — только выручить видео.
# Срабатывает только после ошибки загрузки: когда файл лежит рядом и читается,
# в сеть страница не ходит вовсе.
SITE_VIDEO_FALLBACK = (
    "https://cdn.jsdelivr.net/gh/RHub1722/cos-lohen-media-v2@master/site/"
    + SITE_VIDEO
)

# Ключ с описанием кадра по-русски: он адресован человеку, и рядом с ним в
# shots.json лежат такие же русские «почему так». Схему кадра он не трогает —
# load_shots читает только известные ему поля.
SCREEN_KEY = "на экране"


def build_shots(raw_shots: dict, plan) -> list[dict]:
    """Окна кадров видеофона с человеческим описанием того, что видно."""
    bases, fx = load_shots(ROOT / "scenario/shots.json")
    placed, _ = resolve(bases, fx, plan)
    screens = {str(item["anchor"]): str(item.get(SCREEN_KEY, ""))
               for item in raw_shots.get("base", [])}
    return [{"anchor": shot.anchor, "t": shot.t, "end": shot.end,
             "screen": screens.get(shot.anchor, "")}
            for shot in placed]


def build_payload(video: str, video_fallback: str = "") -> dict:
    scenario = ROOT / "scenario/timeline.json"
    tl = Timeline.load(scenario)
    with open(scenario, encoding="utf-8") as fh:
        raw = json.load(fh)
    with open(ROOT / "scenario/shots.json", encoding="utf-8") as fh:
        raw_shots = json.load(fh)

    movements = resolve_times(load_movements(ROOT / "scenario/movements.json"), tl)
    peaks = peak_offsets(
        ROOT / "assets",
        sorted({e.asset for e in tl.events if e.stem == "sfx"}),
    )
    strikes = resolve_strikes(
        load_strikes(ROOT / "scenario/strikes.json"), tl, peaks,
        [m.id for m in movements],
    )
    plan = build_plan(raw["events"], tl.total_duration)

    by_id = {e["id"]: e for e in raw["events"]}
    lines = sorted(
        ({"t": e.t, "id": e.id, "text": by_id[e.id].get("text", e.id)}
         for e in tl.by_stem("voices")),
        key=lambda x: x["t"],
    )

    hits = sorted(
        ({"t": beat.heard, "label": f"{strike.title}: {beat.what[:40]}"}
         for strike in strikes for beat in strike.beats if beat.role == "contact"),
        key=lambda x: x["t"],
    )

    return {
        "total": tl.total_duration,
        "video": video,
        "video_fallback": video_fallback,
        "scenes": build_scenes(raw["events"], tl.total_duration),
        "movements": [
            {"id": m.id, "t": m.t, "name": m.name, "what": m.what,
             "speed": m.speed, "power": m.power, "duration": m.duration,
             "hold": m.hold, "trigger": m.trigger_event}
            for m in movements
        ],
        "lines": lines,
        "shots": build_shots(raw_shots, plan),
        "strikes": [
            {
                "id": s.id, "movement": s.movement, "title": s.title,
                "family": s.family, "why": s.why, "reference": s.reference,
                "floor": s.floor, "drill": list(s.drill),
                "mistakes": list(s.mistakes),
                "loop": [s.loop_from, s.loop_to],
                "beats": [
                    {"role": b.role, "trigger": b.trigger, "t": b.t,
                     "heard": b.heard, "what": b.what, "screen": b.screen,
                     "pose": b.pose}
                    for b in s.beats
                ],
            }
            for s in strikes
        ],
        "hits": hits,
    }


def render(payload: dict) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in html:
        raise SystemExit(f"в шаблоне нет маркера {MARKER}")
    # Закрывающий тег внутри данных оборвал бы <script> прямо посреди JSON.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return html.replace(MARKER, data)


def pack_video(force: bool = False) -> Path:
    """Сжатая копия видео рядом с версионируемой страницей.

    Перекодируется, только если её нет или она старше мастера: иначе каждая
    сборка страницы гоняла бы минуту видео впустую. Зато при новой сборке звука
    копия сама перестанет быть свежей, и следующий `--site` её обновит — молча
    разойтись с номером она не может.
    """
    target = SITE_DIR / SITE_VIDEO
    if not MASTER_VIDEO.exists():
        raise SystemExit(
            f"нет {MASTER_VIDEO.relative_to(ROOT)} — сначала python src/render_video.py"
        )
    fresh = (target.exists()
             and target.stat().st_mtime >= MASTER_VIDEO.stat().st_mtime)
    if fresh and not force:
        return target

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(MASTER_VIDEO),
        "-vf", f"scale={SITE_SCALE}",
        "-c:v", "libx264", "-crf", SITE_CRF, "-preset", "veryslow",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        # Без faststart браузер на планшете ждёт весь файл, прежде чем начать.
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k", str(target),
    ], capture_output=True, text=True)
    if result.returncode != 0 or not target.exists():
        raise SystemExit(f"FFmpeg не собрал {target.name}:\n{result.stderr[-600:]}")
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="final_v2.mp4",
                    help="имя файла номера рядом со страницей")
    ap.add_argument("--out", default=str(ROOT / "output/training.html"))
    ap.add_argument("--site", action="store_true",
                    help="собрать версионируемую копию в site/ со сжатым видео")
    ap.add_argument("--force-video", action="store_true",
                    help="перекодировать видео для site/ даже если оно свежее")
    ap.add_argument("--video-fallback", default="",
                    help="куда идти за видео, если файл рядом не читается")
    args = ap.parse_args()

    if args.site:
        args.out = str(SITE_DIR / "index.html")
        args.video = SITE_VIDEO
        args.video_fallback = args.video_fallback or SITE_VIDEO_FALLBACK
        packed = pack_video(force=args.force_video)
        print(f"Видео для сайта: {packed.relative_to(ROOT)} "
              f"({packed.stat().st_size / 1024 / 1024:.1f} МБ, {SITE_SCALE}, crf {SITE_CRF})")

    payload = build_payload(args.video, args.video_fallback)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload), encoding="utf-8")

    beats = sum(len(s["beats"]) for s in payload["strikes"])
    print(f"Готово: {out}  ({out.stat().st_size / 1024:.0f} КБ)")
    print(f"  движений: {len(payload['movements'])}, ударов: "
          f"{len(payload['strikes'])}, долей: {beats}, "
          f"контактов: {len(payload['hits'])}")
    print(f"  кадров экрана: {len(payload['shots'])}, "
          f"реплик: {len(payload['lines'])}")
    video = out.parent / payload["video"]
    print(f"  видео рядом: {payload['video']} — "
          + ("на месте" if video.exists() else "НЕ НАЙДЕНО, страница попросит выбрать файл"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
