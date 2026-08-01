"""Перенос сырых генераций из */archive/ в рабочие имена.

Приводит всё к единому формату проекта: 48 кГц, стерео, 24 бита. Исходники в
archive/ не трогаются — при неудачной генерации всегда видно, из чего получился
рабочий файл.

    python src/import_assets.py [--dry-run]
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

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SAMPLE_RATE = 48000


def convert(src: Path, dst: Path, start: float = 0.0, dur: float | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += [
        "-i", str(src),
        "-af", f"aresample={SAMPLE_RATE}:resampler=soxr:precision=28",
        "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s24le",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"конвертация {src.name} упала:\n{result.stderr[-2000:]}")


def duration(path: Path) -> float:
    out = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], capture_output=True, text=True).stdout.strip()
    return float(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = json.loads((ASSETS / "asset-manifest.json").read_text(encoding="utf-8"))
    missing: list[str] = []
    done = 0

    def target(spec) -> tuple[str, float, float | None]:
        """Значение map — имя файла или объект с окном вырезки."""
        if isinstance(spec, str):
            return spec, 0.0, None
        return spec["file"], float(spec.get("start", 0.0)), spec.get("duration")

    for group, mapping in manifest["map"].items():
        print(f"\n{group}/")
        items = sorted(mapping.items(), key=lambda kv: target(kv[1])[0])
        for raw_name, spec in items:
            final_name, start, dur = target(spec)
            src = ASSETS / group / "archive" / raw_name
            dst = ASSETS / group / final_name
            if not src.is_file():
                missing.append(f"{group}/archive/{raw_name}")
                print(f"  ОТСУТСТВУЕТ  {final_name:28} <- {raw_name}")
                continue
            if args.dry_run:
                window = "" if dur is None else f"  [{start:.1f}..{start + dur:.1f}]"
                print(f"  {final_name:28} <- {raw_name}{window}")
                continue
            convert(src, dst, start, dur)
            done += 1
            window = "" if dur is None else f"  (окно с {start:.1f} с)"
            print(f"  {final_name:28} {duration(dst):6.3f} с{window}")

    print()
    if missing:
        print(f"Не найдено исходников: {len(missing)}")
        for item in missing:
            print(f"  - {item}")
        return 1
    print(f"Перенесено файлов: {done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
