"""Генератор тренажёра номера: один самодостаточный HTML рядом с видео.

    python src/render_training.py [--video final_v2.mp4] [--out output/training.html]

Данные вшиваются в страницу при генерации: из `file://` браузер не даст
подгрузить внешний JSON, а страница обязана открываться двойным щелчком, без
сервера и без интернета.

Видео подключается относительным путём и лежит рядом. Так папку из двух файлов
можно скопировать на телефон целиком, и ничего не сломается.
"""

from __future__ import annotations

import argparse
import json
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


def build_payload(video: str) -> dict:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="final_v2.mp4",
                    help="имя файла номера рядом со страницей")
    ap.add_argument("--out", default=str(ROOT / "output/training.html"))
    args = ap.parse_args()

    payload = build_payload(args.video)
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
