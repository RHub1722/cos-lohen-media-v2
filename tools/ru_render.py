"""Русская версия номера: голосовой стем заменяется, остальное берётся готовым.

Ничего не трогает в assets/ и в scenario/. Русские реплики раскладываются в
теневую папку под теми же именами, что английские, и голосовой стем собирается
**тем же кодом**, что и обычная сборка — render_stem. Поэтому гейны, панорама,
задержки и длина стема получаются не «примерно как в проекте», а ровно как в
проекте.

Три остальных стема переиспользуются готовыми, и это законно: дакинг в
filtergraph применяется только к музыке и строится по таймкодам событий, а не по
длине ассетов. Русские реплики стоят на тех же таймкодах, значит провалы уже в
нужных местах. Смены языка sfx, музыка и эмбиенс не замечают вовсе.

Картинка не перерисовывается: она процедурная и от текста реплик не зависит.
Видеодорожка копируется из готового final_v2.mp4 без перекодирования.

    python tools/ru_render.py --voice lo_v41
    python tools/ru_render.py --voice myvoicefordublo --voice lo_v41
    python tools/ru_render.py --voice lo_v41 --audio-only
    python tools/ru_render.py --raw
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Timeline  # noqa: E402
from src.render_audio import normalize, render_stem, sum_stems  # noqa: E402
from src.voice_lines import LineError, load_lines  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ELEVEN = ASSETS / "voices" / "archive" / "eleven"
# Живые записи и решение, какой дубль из них взят. Записи не версионируются,
# решение — версионируется, поэтому источник и выбор лежат в разных местах.
RAW = ASSETS / "voices" / "my"
CHOSEN = ROOT / "scenario" / "takes_chosen.json"
OUT = ROOT / "output"
# Теневые ассеты живут в archive: он в .gitignore, и производные туда и должны
# уходить. В assets/voices/ рядом с оригиналами их класть нельзя — однажды
# кто-нибудь соберёт мастер с русскими репликами, не заметив этого.
SHADOW = ASSETS / "voices" / "archive" / "shadow"
# Смехи, подогнанные под соседнюю реплику по тону, яркости и уровню. Смех не
# переводится, поэтому остаётся английским синтезом — и звучит как другой
# человек рядом с живым голосом. Подгонка считается от конкретной сборки,
# значит при смене рецепта её надо пересчитывать.
LAUGHFIX = ASSETS / "voices" / "archive" / "laughfix"

# Стемы, которые не зависят от языка. Имена — как их пишет render_all.
REUSED = ("sfx_v2.wav", "music_v2.wav", "ambience_v2.wav")
VIDEO = OUT / "final_v2.mp4"


class RuError(RuntimeError):
    pass


def latest_attempt(event: str, labels: list[str]) -> tuple[Path, str]:
    """Последний дубль реплики по цепочке метка -> метка.

    Цепочка нужна, когда часть реплик пришла преобразованием живой записи, а
    часть синтезом: первая метка, у которой дубль есть, и побеждает. Порядок в
    цепочке — это и есть решение, что важнее.

    По номеру, а не по имени: строковая сортировка поставила бы a10 перед a2.
    """
    for label in labels:
        found = sorted(ELEVEN.glob(f"{event}__{label}_a*.mp3"),
                       key=lambda p: int(p.stem.rsplit("_a", 1)[1]))
        if found:
            return found[-1], label
    raise RuError(f"нет ни одной попытки {event} ни по одной из меток {labels}")


def chosen_take(event: str) -> Path:
    """Дубль живой записи, выбранный для реплики.

    Берётся поле in_use, а где решение исполнителя открыто — единственный
    кандидат с вердиктом ready. Если готовых кандидатов не один, выбор
    неоднозначен, и молча угадывать нельзя: тогда в ролик попал бы дубль,
    который никто не выбирал.

    Это тот же дубль, что стоит в версиях с преобразованием голоса. Значит
    сырая сборка отличается от них ровно одним — тембр не подменён.
    """
    chosen = json.loads(CHOSEN.read_text(encoding="utf-8"))["chosen"]
    if event not in chosen:
        raise RuError(f"в {CHOSEN.name} нет реплики {event}")
    entry = chosen[event]

    name = entry.get("in_use")
    if name is None:
        ready = [c["file"] for c in entry.get("candidates", [])
                 if c.get("verdict") == "ready"]
        if len(ready) != 1:
            raise RuError(
                f"{event}: решение открыто, готовых кандидатов {len(ready)} — "
                "нужен ровно один или поле in_use")
        name = ready[0]

    path = RAW / name
    if not path.exists():
        raise RuError(f"{event}: нет записи {path}")
    return path


def build_shadow(labels: list[str], tl: Timeline, raw: bool = False,
                 fix_laughs: bool = False) -> Path:
    """Папка ассетов, где голоса русские, а остальное на своих местах.

    Смехи копируются английскими: смех не переводится. Без них render_stem
    упал бы на отсутствующем файле, и упал бы уже после того, как всё
    остальное собрано.
    """
    root = SHADOW / "-".join(labels)
    voices = root / "voices"
    if voices.exists():
        shutil.rmtree(voices)
    voices.mkdir(parents=True)

    ru = {line.event for line in load_lines()}
    made, kept = 0, 0
    from_label: dict[str, int] = {}
    for event in tl.events:
        if not event.asset.startswith("voices/"):
            continue
        target = root / event.asset
        if event.id in ru:
            if raw:
                src, label = chosen_take(event.id), "живая запись"
            else:
                src, label = latest_attempt(event.id, labels)
            from_label[label] = from_label.get(label, 0) + 1
            # 48 кГц, стерео, 24 бита — то же приведение, что делает
            # src/import_assets.py для любого сгенерированного ассета.
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-i", str(src),
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(target),
            ], check=True)
            made += 1
        else:
            original = ASSETS / event.asset
            if fix_laughs and (LAUGHFIX / Path(event.asset).name).exists():
                original = LAUGHFIX / Path(event.asset).name
                from_label["смех подогнан"] = \
                    from_label.get("смех подогнан", 0) + 1
            if not original.exists():
                raise RuError(f"нет исходного ассета {original}")
            shutil.copyfile(original, target)
            kept += 1
    breakdown = ", ".join(f"{label}: {n}" for label, n in from_label.items())
    print(f"  теневые ассеты: {made} русских ({breakdown}), "
          f"{kept} оставлено английскими")
    return root


def mux(master: Path, out: Path) -> None:
    """Звук в готовую картинку. Видеопоток копируется как есть."""
    if not VIDEO.exists():
        raise RuError(
            f"нет {VIDEO.relative_to(ROOT)} — картинку сначала надо собрать:\n"
            "  python src/render_video.py")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(VIDEO), "-i", str(master),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "320k", "-shortest", str(out),
    ], check=True)


def probe(path: Path) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    dur, size = out.strip().split(",")[:2] if "," in out else (out.strip(), "0")
    return f"{float(dur):.3f} с, {int(size) / 1048576:.1f} МБ"


def render(chain: str, tl: Timeline, audio_only: bool, raw: bool = False,
           fix_laughs: bool = False) -> None:
    labels = [part.strip() for part in chain.split(",") if part.strip()]
    voice = labels[0] + ("_lf" if fix_laughs else "")
    print(f"\n{' -> '.join(labels)}" + ("  (смехи подогнаны)" if fix_laughs
                                        else ""))
    shadow = build_shadow(labels, tl, raw, fix_laughs)

    stem = OUT / f"voices_ru_{voice}_stem.wav"
    render_stem(tl, "voices", shadow, stem)

    missing = [name for name in REUSED if not (OUT / name).exists()]
    if missing:
        raise RuError(
            f"нет готовых стемов {missing} — сначала обычная сборка:\n"
            "  python src/build.py")

    premaster = OUT / f"premaster_ru_{voice}.wav"
    sum_stems([stem] + [OUT / name for name in REUSED], tl, premaster)

    master = OUT / f"master_ru_{voice}.wav"
    measured = normalize(premaster, tl, master)
    print(f"  премастер до нормализации: {float(measured['input_i']):.1f} LUFS, "
          f"пик {float(measured['input_tp']):.1f} dBTP")
    print(f"  мастер: {probe(master)}")

    if audio_only:
        return
    out = OUT / f"final_ru_{voice}.mp4"
    mux(master, out)
    print(f"  видео: {out.relative_to(ROOT)} — {probe(out)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", action="append",
                        help="метка голоса; можно передать несколько раз для "
                             "нескольких роликов. Через запятую — цепочка "
                             "приоритета внутри одного ролика, например "
                             "mysts,lo_v2: где есть преобразование живой "
                             "записи, берётся оно, остальное синтезом")
    parser.add_argument("--raw", action="store_true",
                        help="голос исполнителя как записан: выбранные дубли "
                             "из scenario/takes_chosen.json, без подмены "
                             "тембра и без правки уровней")
    parser.add_argument("--fix-laughs", action="store_true",
                        help="взять смехи из archive/laughfix: подогнанные по "
                             "тону, яркости и уровню под соседнюю реплику. "
                             "Имя ролика получает суффикс _lf")
    parser.add_argument("--audio-only", action="store_true",
                        help="не собирать видео, только мастер")
    args = parser.parse_args()
    if not args.voice and not args.raw:
        parser.error("нужен --voice или --raw")

    tl = Timeline.load(ROOT / "scenario" / "timeline.json")
    print(f"номер {tl.total_duration:.3f} с, цель {tl.target_lufs} LUFS / "
          f"{tl.target_tp} dBTP")
    if args.raw:
        render("raw", tl, args.audio_only, raw=True,
               fix_laughs=args.fix_laughs)
    for voice in args.voice or []:
        render(voice, tl, args.audio_only, fix_laughs=args.fix_laughs)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuError, LineError) as failure:
        print(f"ОШИБКА: {failure}", file=sys.stderr)
        sys.exit(1)
