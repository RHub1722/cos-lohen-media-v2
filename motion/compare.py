"""Сверка замеров с требованиями. О номере не знает ничего.

Требования приходят словарём, и слова burst_3 здесь нет: этот модуль одинаково
работает для любого номера с любым оружием.
"""

from __future__ import annotations

from dataclasses import dataclass

CLOSE = 0.85    # 85% требуемой длительности — «близко», а не «нет»


@dataclass(frozen=True)
class Finding:
    what: str
    verdict: str        # "есть" | "близко" | "нет" | "нечего проверять"
    detail: str


def compare(measured: dict, reqs: dict) -> list[Finding]:
    """Что из требований номера в этом заходе есть, а чего нет."""
    out: list[Finding] = []

    longest = float(measured.get("longest_action", 0.0))
    for action in reqs.get("actions", []):
        need = float(action["duration"])
        if longest >= need:
            verdict = "есть"
        elif longest >= need * CLOSE:
            verdict = "близко"
        else:
            verdict = "нет"
        contacts = int(action.get("contacts", 0))
        tail = f", попаданий нужно {contacts}" if contacts > 1 else ""
        out.append(Finding(
            what=f"{action['name']} {need:g} с",
            verdict=verdict,
            detail=(f"самое длинное непрерывное действие захода "
                    f"{longest:.2f} с против {need:g} с{tail}")))

    need_still = float(reqs.get("longest_stillness", 0.0))
    still = float(measured.get("longest_stillness", 0.0))
    out.append(Finding(
        what=f"неподвижность {need_still:g} с",
        verdict="есть" if still >= need_still else "нет",
        detail=f"самая длинная неподвижность захода {still:.2f} с"))

    transitions = int(measured.get("transitions", 0))
    dead = int(measured.get("dead_stops", 0))
    named = [a["name"] for a in reqs.get("actions", []) if a.get("no_stance")]
    if transitions == 0:
        verdict, detail = "нечего проверять", "переходов в заходе нет"
    elif dead == 0:
        verdict = "есть"
        detail = f"мёртвых остановок нет, переходов {transitions}"
    else:
        verdict = "нет"
        detail = (f"мёртвых остановок {dead} из {transitions}. "
                  f"Хореография запрещает стойку после: {', '.join(named)}"
                  if named else
                  f"мёртвых остановок {dead} из {transitions}")
    out.append(Finding(what="переходы без стойки", verdict=verdict,
                       detail=detail))
    return out
