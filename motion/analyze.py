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

    videos = sorted(args.only) if args.only else sorted(
        p for p in TRAIN.glob("*.mp4") if p.is_file())
    if not videos:
        print(f"в {TRAIN} нет ни одного mp4", file=sys.stderr)
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
        print(f"замер {path.name} ...", flush=True)
        try:
            sessions.append(session.measure(
                path, out_frames=out_dir / "frames",
                pose_on=not args.no_pose))
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
