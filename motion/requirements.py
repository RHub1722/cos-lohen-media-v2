"""ЕДИНСТВЕННЫЙ модуль, знающий о номере.

Заказчик выбрал не разделять пакет и номер, и цена решения названа: в другом
проекте анализатор придётся разбирать. Чтобы цена осталась низкой, всё знание
живёт здесь. Остальные восемь модулей слова burst_3 не содержат.

Требования собираются из scenario/ каждый раз заново. Файла с копией
длительностей нет и не будет: в проекте правило — ни один таймкод не
дублируется, а копия разошлась бы с timeline.json молча.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Хореография пишет запрет прямым текстом: «после — медленный обход, разворот
# к новой стороне, НЕ стойка». Ищем эту фразу, а не догадываемся.
NO_STANCE = "НЕ стойка"

# Финальная неподвижность записана в hold текстом, а не числом. Держать её
# нужно 4.8 с — это остаток дорожки после ice_final_impact.
STILLNESS_FALLBACK = 4.8


def from_scenario(root: Path | None = None) -> dict:
    """Требования номера как обычный словарь.

    Боевые действия — те, у которых в strikes.json есть разбор по долям: у них
    номер требует конкретной длительности и конкретного числа попаданий.
    """
    base = root or ROOT
    movements = json.loads((base / "scenario" / "movements.json")
                           .read_text(encoding="utf-8"))["movements"]
    strikes = json.loads((base / "scenario" / "strikes.json")
                         .read_text(encoding="utf-8"))["strikes"]

    contacts: dict[str, int] = {}
    for strike in strikes:
        move = str(strike.get("movement", ""))
        contacts[move] = sum(1 for b in strike.get("beats", [])
                             if b.get("role") == "contact")

    actions = []
    for move in movements:
        move_id = str(move["id"])
        if move_id not in contacts:
            continue
        hold = str(move.get("hold", ""))
        actions.append({
            "id": move_id,
            "name": str(move.get("name", move_id)),
            "duration": float(move.get("duration", 0.0)),
            "contacts": int(contacts[move_id]),
            "hold": hold,
            "no_stance": NO_STANCE in hold,
        })

    stillness = STILLNESS_FALLBACK
    for move in movements:
        if move.get("id") != "final_pose":
            continue
        for token in str(move.get("hold", "")).replace(",", " ").split():
            try:
                value = float(token)
            except ValueError:
                continue
            if 1.0 <= value <= 30.0:
                stillness = value
                break
    return {"actions": actions, "longest_stillness": stillness}
