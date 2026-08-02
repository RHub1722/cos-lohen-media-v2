"""Генератор самодостаточной репетиционной страницы.

Данные вшиваются в HTML при генерации: из file:// браузер не даст подгрузить
внешний JSON. Дорожку пользователь выбирает сам через файловый диалог, чтобы
страницу можно было переслать без 17 мегабайт звука.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from src.models import Timeline  # noqa: E402
from src.movements import load_movements, resolve_times  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/rehearsal_template.html"

# Границы сцен не задаются отдельно: они выводятся из якорей video.state,
# которые уже стоят в сценарии для видеорендерера. Один источник на две
# подсистемы — сцены на странице не могут разойтись с картинкой.
SCENE_NAMES = {
    "interrogation": "Допрос",
    "combat": "Бой",
    "ice": "Лёд",
}


def build_scenes(raw_events: list[dict], total: float) -> list[dict]:
    starts = sorted(
        (e["t"], e["video"]["state"])
        for e in raw_events
        if e.get("video", {}).get("cue") == "state"
    )
    scenes = []
    for i, (t, state) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else total
        scenes.append({"key": state, "name": SCENE_NAMES.get(state, state),
                       "t": t, "end": end})
    return scenes


def build_payload(tl: Timeline, movements, raw: dict) -> dict:
    by_id = {e["id"]: e for e in raw["events"]}
    lines = [
        {"t": e.t, "id": e.id, "text": by_id[e.id].get("text", e.id)}
        for e in tl.by_stem("voices")
    ]
    return {
        "total": tl.total_duration,
        "scenes": build_scenes(raw["events"], tl.total_duration),
        "movements": [
            {"id": m.id, "t": m.t, "name": m.name, "what": m.what,
             "speed": m.speed, "power": m.power, "duration": m.duration,
             "hold": m.hold, "trigger": m.trigger_event}
            for m in movements
        ],
        "lines": sorted(lines, key=lambda x: x["t"]),
    }


def main() -> int:
    scenario = ROOT / "scenario/timeline.json"
    tl = Timeline.load(scenario)
    with open(scenario, encoding="utf-8") as fh:
        raw = json.load(fh)
    movements = resolve_times(load_movements(ROOT / "scenario/movements.json"), tl)
    payload = build_payload(tl, movements, raw)

    html = TEMPLATE.read_text(encoding="utf-8")
    marker = "/*__DATA__*/"
    if marker not in html:
        raise SystemExit(f"в шаблоне нет маркера {marker}")
    html = html.replace(marker, json.dumps(payload, ensure_ascii=False))

    out = ROOT / "output/rehearsal.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Готово: {out}")
    print(f"  сцен: {len(payload['scenes'])}, движений: {len(payload['movements'])}, "
          f"реплик: {len(payload['lines'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
