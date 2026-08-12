"""Генератор тренажёра номера: один самодостаточный HTML рядом с видео.

    python src/render_training.py            # output/training.html, ролик номера
    python src/render_training.py --site     # site/index.html, сжатое видео

Данные вшиваются в страницу при генерации: из `file://` браузер не даст
подгрузить внешний JSON, а страница обязана открываться двойным щелчком, без
сервера и без интернета.

Видео подключается относительным путём и лежит рядом. Так папку из двух файлов
можно скопировать на планшет целиком, и ничего не сломается.

`--site` собирает версионируемую копию в `site/`: ту же страницу и сжатое до
960×540 видео на четыре с половиной мегабайта вместо тридцати. Это единственное
место, где производный файл попадает в репозиторий, и попадает намеренно — иначе
страницу нельзя открыть с гита на планшете. Ролик номера в `output/` при этом не
трогается: он остаётся файлом сдачи.

ЗВУК ВИДЕО СВЕРЯЕТСЯ С ФОНОГРАММОЙ НОМЕРА. Тренажёр учит попадать в звук, и
играть он обязан тот звук, под который выступают. Один раз это уже разошлось
молча: номер сменил фонограмму на ручную из монтажки, а страница месяц играла
августовскую сборку с английским голосом. Теперь сверка идёт при сборке, см.
src/soundcheck.py.
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
from src.soundcheck import SoundcheckError, check  # noqa: E402
from src.strikes import load_strikes, resolve_strikes  # noqa: E402
from src.train_clips import caveat as clips_caveat  # noqa: E402
from src.train_clips import load as load_clips  # noqa: E402
from src.video_plan import build_plan  # noqa: E402
from src.voice_lines import load_lines  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/training_template.html"
MARKER = "/*__DATA__*/"

# Ролик номера, по которому его разучивают, и фонограмма, которая в нём звучит.
#
# Взята отправленная организаторам копия — та, что и пойдёт на экран: без
# тёмной полосы, с титрами и знаком. Разучивать надо под то, что будет на
# площадке, а не под удобный вариант. Если файл у организаторов заменят на
# сценическую копию с полосой, пересобрать с `--video final_ru_lo_v41_fx.mp4`.
NUMBER_VIDEO = "final_ru_nostrip_titles_logo_fx.mp4"
SOUNDTRACK = ROOT / "output/master_ru_fx.wav"

# Версионируемая копия для планшета: открывается прямо с гита, поэтому вес имеет
# значение. 960×540 хватает, чтобы видеть, где вспышка и что на экране, а по
# мобильной связи это четыре с половиной мегабайта вместо тридцати одного.
SITE_DIR = ROOT / "site"
SITE_VIDEO = "lohen-60s.mp4"
SITE_SCALE = "960:540"
SITE_CRF = "24"
MASTER_VIDEO = ROOT / "output" / NUMBER_VIDEO

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

# Тренировочные клипы: по одному на удар, сгенерированы по панелям листов
# движений, см. scenario/train_clips.json и docs/status/2026-08-10-train-clips.md.
#
# Сырьё лежит в assets/train_clips/ и в гит не идёт: там же лежат отклонённые
# попытки, и каждая забирается обратно без повторной оплаты по prediction_id из
# журнала. На страницу кладётся ОТБОР — по одному файлу на клип, тот, который
# признан годным. Какой именно, сказано в сценарии клипов, а не выведено из
# имени: рядом лежат spear_down_a1 с копьём вверх ногами и burst_4_a1 с наездом
# камеры, и отличаются они одной цифрой.
#
# Перекодировать нечего: с сервера они приходят H.264 / yuv420p / 864x496 и
# играют в любом браузере. Ремультиплексируем только ради +faststart, чтобы на
# мобильной связи плеер начинал играть, не дожидаясь всего файла.
CLIPS_SRC = ROOT / "assets/train_clips"
CLIPS_SUB = "clips"
CLIP_POSTER_WIDTH = "432"
CLIP_POSTER_QUALITY = "80"
CLIPS_FALLBACK = (
    "https://cdn.jsdelivr.net/gh/RHub1722/cos-lohen-media-v2@master/site/"
    + CLIPS_SUB + "/"
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


def build_lines(tl: Timeline, raw_events: list[dict]) -> list[dict]:
    """Реплики так, как их слышно: по-русски.

    Поле `text` в timeline.json — английский текст первой версии номера, и он
    там остался не по недосмотру: по нему собраны титры. Но звучит номер с 6
    августа по-русски, и тренажёр, показывающий английскую строку под русскую
    реплику, врёт исполнителю в самом простом месте.

    Второго списка реплик заводить нельзя — русский текст живёт там же, где
    живут указания на запись, в scenario/voices_ru.json, и читается тем же
    src/voice_lines.py.

    Смех и вздохи своей реплики не имеют: у них в сценарии стоит ремарка вроде
    «(смех, голоднее)», уже по-русски. Для них подстановка из сценария законна,
    для остальных — нет, и это проверяется, а не подразумевается.
    """
    ru = {line.event: line.line for line in load_lines()}
    by_id = {e["id"]: e for e in raw_events}
    missing = [e.id for e in tl.by_stem("voices")
               if e.id not in ru
               and not str(by_id[e.id].get("text", "")).startswith("(")]
    if missing:
        raise SystemExit(
            f"нет русского текста для реплик: {missing}. Они есть в "
            "scenario/timeline.json, но их нет в scenario/voices_ru.json — "
            "тренажёр показал бы английскую строку под русскую реплику"
        )
    return sorted(
        ({"t": e.t, "id": e.id,
          "text": ru.get(e.id) or str(by_id[e.id].get("text", e.id))}
         for e in tl.by_stem("voices")),
        key=lambda x: x["t"],
    )


def shown_file(cid: str, accepted: str) -> Path:
    """Файл клипа, с которого можно снять мерку: принятая попытка или её
    опубликованная копия.

    В свежем клоне assets/train_clips/ пустая — папка не версионируется, — а
    копия в site/ лежит в гите. Поток в них один и тот же: при публикации клип
    только перекладывается, без перекодирования.
    """
    src = CLIPS_SRC / accepted
    if src.exists():
        return src
    published = SITE_DIR / CLIPS_SUB / ("%s.mp4" % cid)
    if published.exists():
        return published
    raise SystemExit(
        "нет ни %s, ни опубликованной копии %s. Забрать без повторной оплаты "
        "можно по prediction_id из docs/atlas-ledger.csv:\n"
        "    python tools/atlas_train.py --refetch <prediction_id> --as %s"
        % (src.relative_to(ROOT), published.relative_to(ROOT), cid))


def build_clips(strikes) -> list[dict]:
    """Тренировочные клипы для страницы, вместе с тем, чего они не показывают.

    Панели входа и официальный арт в гит не идут, а страница собирается и из
    свежего клона, — поэтому `require_refs=False`: сюда картинки входа не нужны
    вовсе, нужен только отбор попыток и темп из долей.
    """
    clips = load_clips(strikes, require_refs=False)
    by_id = {s.id: s for s in strikes}
    out = []
    for clip in clips:
        beats = [by_id[clip.strike].beats[n - 1] for n in clip.beats]
        # Размер кадра снимается с файла, а не написан руками: перегенерируем
        # клип в другом разрешении — и вёрстка соврала бы. По нему браузер знает
        # высоту плеера до всякой загрузки, иначе при preload="none" семь
        # карточек прыгают, когда догружаются постеры.
        width, height = frame_size(shown_file(clip.id, clip.accepted))
        out.append({
            "id": clip.id,
            "strike": clip.strike,
            "title": clip.title,
            "file": "%s/%s.mp4" % (CLIPS_SUB, clip.id),
            "poster": "%s/%s.webp" % (CLIPS_SUB, clip.id),
            "accepted": clip.accepted,
            "attempt": clip.attempt,
            "w": width,
            "h": height,
            "duration": clip.duration,
            "real": clip.real,
            "slow": round(clip.slow, 1),
            "watch": clip.watch,
            "missing": list(clip.missing),
            # `at` — где эта доля стоит внутри клипа. По паре (heard, at) пульт
            # сопоставляет время кусочно, а не одной прямой.
            "beats": [{"role": b.role, "heard": b.heard, "what": b.what,
                       "at": at}
                      for b, at in zip(beats, clip.marks)],
        })
    return out


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

    lines = build_lines(tl, raw["events"])

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
        "clips": build_clips(strikes),
        "clips_caveat": clips_caveat(),
        "clips_fallback": CLIPS_FALLBACK,
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


def frame_size(video: Path) -> tuple[int, int]:
    """Размер кадра файла, который реально ляжет на страницу."""
    run = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(video),
    ], capture_output=True, text=True)
    parts = run.stdout.strip().split("x")
    if run.returncode != 0 or len(parts) != 2:
        raise SystemExit("FFprobe не прочитал размер кадра %s:\n%s"
                         % (video.name, run.stderr[-300:]))
    return int(parts[0]), int(parts[1])


def pack_clips(clips: list[dict], target: Path, force: bool = False) -> int:
    """Отобранные клипы и постеры рядом со страницей. Возвращает вес отбора.

    Копия, а не ссылка на assets/train_clips/: там рядом лежат отклонённые
    попытки, и папка не версионируется. На страницу уезжает ровно то, что
    признано годным, под именем без номера попытки — номер уже записан в
    сценарии клипов и показан на карточке.

    Источника может не быть вовсе: в свежем клоне assets/train_clips/ пустая, а
    опубликованная копия лежит в гите. Это не ошибка — ошибка, когда нет ни
    того, ни другого, и тогда сказано, чем это лечится.
    """
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for clip in clips:
        src = CLIPS_SRC / clip["accepted"]
        dst = target / Path(clip["file"]).name
        poster = target / Path(clip["poster"]).name
        if not src.exists():
            # Источника нет, а копия лежит: свежий клон. Тогда публиковать нечего
            # — уже опубликовано, и постер рядом с ней.
            if dst.exists() and poster.exists():
                total += dst.stat().st_size + poster.stat().st_size
                continue
            shown_file(clip["id"], clip["accepted"])  # скажет, чем это лечится
        fresh = dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime
        if not fresh or force:
            # -c copy: перекодировать нечего, поток уже H.264/yuv420p. Ремукс
            # нужен ради faststart, иначе плеер на планшете ждёт весь файл.
            # -an: звуковой дорожки у клипов нет, и появиться она не должна —
            # репетируют под фонограмму номера, а не под тишину клипа.
            run = subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-i", str(src),
                "-c", "copy", "-an", "-movflags", "+faststart", str(dst),
            ], capture_output=True, text=True)
            if run.returncode != 0 or not dst.exists():
                raise SystemExit("FFmpeg не переложил %s:\n%s"
                                 % (src.name, run.stderr[-500:]))
        stale = poster.exists() and poster.stat().st_mtime >= dst.stat().st_mtime
        if not stale or force:
            # Кадр с середины клипа: на первом кадре он ещё в замахе, а карточке
            # нужен узнаваемый силуэт. Постер обязателен из-за preload="none" —
            # без него на странице семь чёрных прямоугольников.
            run = subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % (clip["duration"] / 2),
                "-i", str(dst), "-frames:v", "1",
                "-vf", "scale=%s:-2:flags=lanczos" % CLIP_POSTER_WIDTH,
                "-c:v", "libwebp", "-quality", CLIP_POSTER_QUALITY, str(poster),
            ], capture_output=True, text=True)
            if run.returncode != 0 or not poster.exists():
                raise SystemExit("FFmpeg не снял постер %s:\n%s"
                                 % (poster.name, run.stderr[-500:]))
        total += dst.stat().st_size + poster.stat().st_size
    return total


def verify_soundtrack(video: Path) -> None:
    """Видео рядом со страницей обязано играть фонограмму номера.

    Не находится файл — не беда: страница умеет попросить выбрать его руками, и
    сверять тогда нечего. Находится, но играет чужой звук — беда, и молчать о
    ней нельзя: разучивать номер под звук, которого на площадке не будет,
    дороже, чем не собрать страницу.
    """
    if not video.exists():
        print(f"  видео рядом: {video.name} — НЕ НАЙДЕНО, страница попросит "
              "выбрать файл; звук сверить не с чем")
        return
    if not SOUNDTRACK.exists():
        raise SystemExit(
            f"нет {SOUNDTRACK.relative_to(ROOT)} — не с чем сверять звук "
            "страницы. Фонограмма номера собирается tools/adopt_audio.py"
        )
    try:
        windows = check(video, SOUNDTRACK)
    except SoundcheckError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"  видео рядом: {video.name} — на месте")
    print(f"  звук сверен с {SOUNDTRACK.name}: худшее окно "
          f"{min(c for _, c in windows):.3f} из {len(windows)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=NUMBER_VIDEO,
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

    # Клипы кладутся рядом со страницей — той же папкой, что и ролик номера.
    # Тогда и локальная сборка в output/, и версионируемая в site/ открываются
    # одинаково, и раздел не бывает пустым только на одной из них.
    weight = pack_clips(payload["clips"], out.parent / CLIPS_SUB,
                        force=args.force_video)

    # Сверка до записи: страница, которая играет чужой звук, не должна лечь на
    # диск даже на минуту — её успеют скопировать на планшет.
    verify_soundtrack(out.parent / payload["video"])
    out.write_text(render(payload), encoding="utf-8")

    beats = sum(len(s["beats"]) for s in payload["strikes"])
    print(f"Готово: {out}  ({out.stat().st_size / 1024:.0f} КБ)")
    print(f"  движений: {len(payload['movements'])}, ударов: "
          f"{len(payload['strikes'])}, долей: {beats}, "
          f"контактов: {len(payload['hits'])}")
    print(f"  кадров экрана: {len(payload['shots'])}, "
          f"реплик: {len(payload['lines'])}")
    print(f"  тренировочных клипов: {len(payload['clips'])} в "
          f"{(out.parent / CLIPS_SUB).relative_to(ROOT)} "
          f"({weight / 1024 / 1024:.1f} МБ с постерами)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
