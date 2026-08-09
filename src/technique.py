"""Данные книжки: приёмы, навыки исполнителя, паузы, реквизит.

Своих таймкодов здесь нет и быть не может. Времена приходят из
scenario/strikes.json, а этот файл только называет то, что там уже стоит:
какой приём в каком ударе, какой навык в какой паузе.

Ровно поэтому все ссылки проверяются при загрузке. Удар, у которого не назван
ни один приём; навык, поставленный в паузу, которой нет; пауза, накрывающая
долю удара — всё это ошибки, которые иначе доехали бы до страницы и молча
разошлись бы с боем. Этот проект уже платил расхождением movements.json и
strikes.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class TechniqueError(Exception):
    """Книжка ссылается в пустоту или спорит с разбором боя."""


@dataclass(frozen=True)
class Video:
    title: str
    url: str
    watch: str
    slow: float
    why: str


@dataclass(frozen=True)
class Technique:
    id: str
    name: str
    glyph: str
    meaning: str
    what: str
    body: str
    grip: str
    mistake: str
    drill: str
    videos: tuple[Video, ...] = ()


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    seen: str
    how: str
    where: str
    fix: str


@dataclass(frozen=True)
class Pause:
    id: str
    start: float
    end: float
    after: str
    before: str
    now: str
    put: str
    why: str
    # Какие доли удара окно закрывает собой. Пусто — значит не закрывает
    # ни одной, и это проверяется.
    replaces: tuple[str, ...] = ()

    @property
    def length(self) -> float:
        return round(self.end - self.start, 3)


@dataclass(frozen=True)
class Book:
    techniques: tuple[Technique, ...]
    skills: tuple[Skill, ...]
    pauses: tuple[Pause, ...]
    strikes: dict
    finale: dict
    prop: dict
    spins: dict = field(default_factory=dict)
    stage: dict = field(default_factory=dict)
    problem: dict = field(default_factory=dict)
    hips: dict = field(default_factory=dict)

    def technique(self, tid: str) -> Technique:
        for t in self.techniques:
            if t.id == tid:
                return t
        raise TechniqueError(f"нет приёма {tid!r}")

    def skill(self, sid: str) -> Skill:
        for s in self.skills:
            if s.id == sid:
                return s
        raise TechniqueError(f"нет навыка {sid!r}")


def _videos(raw, owner: str) -> tuple[Video, ...]:
    out = []
    for v in raw or []:
        for key in ("title", "url", "watch", "slow", "why"):
            if key not in v:
                raise TechniqueError(
                    f"{owner}: у ссылки нет поля {key!r}. Ссылка без указания, "
                    "какой кусок смотреть и во сколько раз замедлить, бесполезна: "
                    "туториалы идут по разделениям, а в номере на удар 0.26 с"
                )
        out.append(Video(title=str(v["title"]), url=str(v["url"]),
                         watch=str(v["watch"]), slow=float(v["slow"]),
                         why=str(v["why"])))
    return tuple(out)


def load(path: str | Path) -> Book:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    techniques = []
    for t in raw.get("techniques", []):
        for key in ("id", "name", "what", "body", "grip", "mistake", "drill"):
            if not str(t.get(key, "")).strip():
                raise TechniqueError(f"приём без поля {key!r}: {t.get('id', t)}")
        techniques.append(Technique(
            id=str(t["id"]), name=str(t["name"]), glyph=str(t.get("glyph", "")),
            meaning=str(t.get("meaning", "")), what=str(t["what"]),
            body=str(t["body"]), grip=str(t["grip"]), mistake=str(t["mistake"]),
            drill=str(t["drill"]), videos=_videos(t.get("videos"), t["id"])))
    if not techniques:
        raise TechniqueError("в книжке нет ни одного приёма")

    skills_raw = raw.get("skills", {})
    skills = tuple(Skill(id=str(s["id"]), name=str(s["name"]), seen=str(s["seen"]),
                         how=str(s["how"]), where=str(s["where"]), fix=str(s["fix"]))
                   for s in skills_raw.get("items", []))

    pauses = tuple(Pause(id=str(p["id"]), start=float(p["from"]), end=float(p["to"]),
                         after=str(p["after"]), before=str(p["before"]),
                         now=str(p["now"]), put=str(p["put"]), why=str(p["why"]),
                         replaces=tuple(str(x) for x in p.get("replaces", [])))
                   for p in raw.get("pauses", {}).get("windows", []))

    def section(key: str) -> dict:
        """Раздел со списком ссылок. Ссылки разбираются в Video здесь же:
        иначе половина книжки получала бы объекты, а половина сырые словари, и
        вёрстка спотыкалась бы об это на каждом разделе."""
        block = dict(raw.get(key, {}))
        block["videos"] = _videos(block.get("videos"), key)
        return block

    book = Book(techniques=tuple(techniques), skills=skills, pauses=pauses,
                strikes=dict(raw.get("strikes", {})),
                finale=dict(raw.get("finale", {})),
                prop=dict(raw.get("prop", {})),
                spins=section("spins"),
                stage=section("stage"),
                problem=dict(skills_raw.get("problem", {})),
                hips=dict(skills_raw.get("hips", {})))

    ids = {t.id for t in techniques}
    for strike_id, entry in book.strikes.items():
        unknown = [u for u in entry.get("uses", []) if u not in ids]
        if unknown:
            raise TechniqueError(f"{strike_id}: неизвестные приёмы {unknown}")
    known_skills = {s.id for s in skills}
    for pause in pauses:
        if pause.put not in known_skills:
            raise TechniqueError(
                f"{pause.id}: в паузу поставлен навык {pause.put!r}, которого нет")
        if pause.end <= pause.start:
            raise TechniqueError(f"{pause.id}: окно {pause.start}–{pause.end} пустое")
    if book.finale and book.finale.get("skill") not in known_skills:
        raise TechniqueError(
            f"концовка: навык {book.finale.get('skill')!r} не описан")
    return book


def check_against_strikes(book: Book, strikes) -> None:
    """Книжка и разбор боя обязаны говорить об одном и том же.

    Проверяется не «похоже ли», а три конкретные вещи: каждому удару назван
    приём, каждый названный удар существует, и ни одна пауза не накрывает долю.
    Последнее важнее всего: перекрут поверх контакта сотрёт остановку, которой
    удар и читается с зала.
    """
    have = {s.id for s in strikes}
    named = set(book.strikes)
    missing = sorted(have - named)
    if missing:
        raise TechniqueError(
            f"у ударов не назван ни один приём: {missing}. Книжка существует "
            "ровно ради этого")
    extra = sorted(named - have)
    if extra:
        raise TechniqueError(f"книжка называет удары, которых нет в бою: {extra}")
    for strike in strikes:
        entry = book.strikes[strike.id]
        if not entry.get("uses") and not str(entry.get("how", "")).strip():
            raise TechniqueError(
                f"{strike.id}: ни приёмов, ни объяснения почему их нет")

    beats = [(s.id, b.role, b.heard) for s in strikes for b in s.beats]
    windows = [(p.id, p.start, p.end, set(p.replaces)) for p in book.pauses]
    if book.finale:
        windows.append(("концовка", float(book.finale["from"]),
                        float(book.finale["to"]),
                        set(book.finale.get("replaces", []))))

    for name, start, end, replaces in windows:
        covered = [(f"{sid}/{role}", role, t) for sid, role, t in beats
                   if start < t < end]
        # Контакт и взмах трогать нельзя ни при каких объявлениях: удар
        # читается остановкой, а вращение поверх неё её сотрёт.
        hard = [f"{key} на {t:.2f}" for key, role, t in covered
                if role in ("contact", "swing")]
        if hard:
            raise TechniqueError(
                f"{name}: окно {start:.2f}–{end:.2f} накрывает {hard}. Вращение "
                "поверх контакта сотрёт остановку, которой удар читается с зала")
        # Замах и держание закрыть можно — но только объявив это прямо. Иначе
        # доля тихо исчезает из номера, и заметить это можно лишь на репетиции.
        silent = [f"{key} на {t:.2f}" for key, role, t in covered
                  if key not in replaces]
        if silent:
            raise TechniqueError(
                f"{name}: окно {start:.2f}–{end:.2f} закрывает доли {silent}, и "
                "это нигде не объявлено. Если перекрут их заменяет — впиши их в "
                "поле replaces; если нет — двигай окно")
        gone = replaces - {key for key, _, _ in covered}
        if gone:
            raise TechniqueError(
                f"{name}: в replaces записаны доли {sorted(gone)}, которых в окне "
                f"{start:.2f}–{end:.2f} нет. Похоже, доля уехала в сценарии")
