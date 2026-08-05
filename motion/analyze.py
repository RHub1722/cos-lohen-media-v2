"""Точка входа.

    python motion/analyze.py                       всё новое в train/
    python motion/analyze.py --only train/a.mp4    одно видео
    python motion/analyze.py --out <папка>         куда положить
    python motion/analyze.py --no-pose             без слоя позы

Заход, для которого отчёт уже есть, не пересчитывается: следующий раз — одна
команда без аргументов.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # Запуск как `python motion/analyze.py` кладёт в sys.path папку motion/,
    # а не корень, и `from motion import ...` не находится. Из pytest этого не
    # видно: там корень уже на пути (pytest.ini, pythonpath = .).
    sys.path.insert(0, str(ROOT))

from motion import pose, report, session, video  # noqa: E402

TRAIN = ROOT / "train"
SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def collect(root: Path) -> list[Path]:
    """Все видео в папке и подпапках, без дублей по содержимому.

    Папка отчётов пропускается: там лежат наши же кадры, а не материал.

    Дедупликация нужна по факту: один и тот же файл лежал сразу в двух папках
    заказчика (2action-meha и final), побайтово одинаковый. Считать его дважды
    значит дважды посчитать один заход в итогах.
    """
    seen: dict[str, Path] = {}
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if "reports" in path.relative_to(root).parts:
            continue
        # Хеш только по размеру и первому мегабайту: полный от 265 МБ читать
        # незачем, а совпадение размера и начала у разных дублей не встречается.
        with open(path, "rb") as fh:
            head = hashlib.md5(fh.read(1 << 20)).hexdigest()
        key = f"{path.stat().st_size}-{head}"
        if key in seen:
            print(f"  дубль, пропущен: {path.relative_to(root)} "
                  f"= {seen[key].relative_to(root)}")
            continue
        seen[key] = path
        out.append(path)
    return out


def label_for(path: Path, root: Path) -> str:
    """Короткое имя для заголовка: путь от train/ без расширения."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return path.stem
    return str(rel.with_suffix("")).replace("\\", "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Разбор тренировки по видео")
    parser.add_argument("--only", type=Path, action="append", default=None,
                        help="разобрать только эти файлы")
    parser.add_argument("--out", type=Path, default=None,
                        help="куда положить отчёт")
    parser.add_argument("--no-pose", action="store_true",
                        help="не использовать слой позы")
    parser.add_argument("--force", action="store_true",
                        help="пересчитать, даже если отчёт уже есть")
    args = parser.parse_args(argv)

    videos = sorted(args.only) if args.only else collect(TRAIN)
    if not videos:
        print(f"в {TRAIN} нет ни одного видео", file=sys.stderr)
        return 1

    out_dir = args.out or (TRAIN / "reports" / date.today().isoformat())
    if (out_dir / "report.md").exists() and not args.force:
        print(f"отчёт уже есть: {out_dir / 'report.md'}\n"
              f"пересчитать — добавить --force")
        return 0

    ok, why = pose.available()
    used = ok and not args.no_pose
    print(f"слой позы: {'есть' if used else 'нет'} — "
          f"{'слой отключён ключом --no-pose' if ok and not used else why}")

    sessions = []
    for path in videos:
        print(f"замер {label_for(path, TRAIN)} ...", flush=True)
        try:
            sessions.append(session.measure(
                path, out_frames=out_dir / "frames",
                pose_on=not args.no_pose,
                label=label_for(path, TRAIN)))
        except video.VideoError as exc:
            print(f"  пропущено: {exc}", file=sys.stderr)
    if not sessions:
        print("ни одно видео не прочиталось", file=sys.stderr)
        return 1

    path = report.write(sessions, out_dir)
    print(f"\nготово: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
