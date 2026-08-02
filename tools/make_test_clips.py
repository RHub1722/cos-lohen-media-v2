"""Синтетические клипы, чтобы проверить компоновщик без единого купленного файла.

    python tools/make_test_clips.py          создать
    python tools/make_test_clips.py --clean  убрать

Ничего не скачивается: фон собирается из lavfi, слэш с альфа-каналом рисуется
здесь же и кодируется в ProRes 4444. Клипы намеренно узнаваемые — цветные
полосы и фрактал. Если на кадре-образце видно их, значит нижний слой
действительно подменился; если процедурный фон, значит материал не доехал.

После проверки клипы надо убрать: `--check` должен честно показывать, чего в
проекте нет.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "video"
W, H, FPS = 1920, 1080, 30

BASES = {
    "interrogation": "life=size=160x90:mold=10:r=8:ratio=0.1:"
                     "death_color=#203040:life_color=#8090b0,scale=1920:1080,boxblur=6",
    "combat": "testsrc2=size=1920x1080:rate=30",
    "ice": "mandelbrot=size=1920x1080:rate=30",
}

FX = [
    ("slash_01.mov", 8, 0.09, -0.6),
    ("slash_02.mov", 9, 0.12, 0.5),
    ("impact_big.mov", 11, 0.22, -0.2),
    ("impact_white.mov", 4, 0.60, 0.0),
    ("slash_03.mov", 7, 0.08, 0.9),
]


def clean() -> int:
    for name in BASES:
        (OUT / "base" / f"{name}.mp4").unlink(missing_ok=True)
    for name, *_ in FX:
        (OUT / "fx" / name).unlink(missing_ok=True)
    print("тестовые клипы убраны")
    return 0


def draw_slash(tmp: Path, frames: int, thickness: float, tilt: float) -> None:
    """Белая полоса, проходящая кадр насквозь, на прозрачном фоне."""
    x = np.linspace(-1.0, 1.0, W, dtype=np.float32)[None, :]
    y = np.linspace(-1.0, 1.0, H, dtype=np.float32)[:, None]
    proj = x * float(np.cos(tilt)) + y * float(np.sin(tilt))
    for i in range(frames):
        p = i / max(1, frames - 1)
        band = np.exp(-(((proj - (-1.6 + 3.2 * p)) / thickness) ** 2))
        fade = float(np.sin(np.pi * min(1.0, p * 1.15)))
        alpha = np.clip(band * fade, 0.0, 1.0)
        rgb = np.stack([
            np.full_like(alpha, 1.0),
            np.clip(0.55 + 0.45 * band, 0.0, 1.0),
            np.clip(0.25 + 0.50 * band, 0.0, 1.0),
        ], axis=2)
        rgba = np.concatenate([rgb, alpha[:, :, None]], axis=2)
        Image.fromarray((rgba * 255).astype(np.uint8), mode="RGBA").save(
            tmp / f"{i:04d}.png")


def main() -> int:
    if "--clean" in sys.argv:
        return clean()

    (OUT / "base").mkdir(parents=True, exist_ok=True)
    (OUT / "fx").mkdir(parents=True, exist_ok=True)

    for name, source in BASES.items():
        dst = OUT / "base" / f"{name}.mp4"
        subprocess.run([
            # Длину задаёт -t: дописывать :d= к строке фильтров нельзя,
            # параметр приклеится к последнему фильтру, а не к источнику.
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", source,
            "-t", "10", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
            str(dst),
        ], check=True)
        print(f"фон:     {dst.name}")

    tmp = Path(tempfile.mkdtemp(prefix="lohen-fx-"))
    try:
        for name, frames, thickness, tilt in FX:
            for old in tmp.glob("*.png"):
                old.unlink()
            draw_slash(tmp, frames, thickness, tilt)
            dst = OUT / "fx" / name
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
                "-i", str(tmp / "%04d.png"),
                "-c:v", "prores_ks", "-profile:v", "4444",
                "-pix_fmt", "yuva444p10le", str(dst),
            ], check=True)
            print(f"эффект:  {dst.name}, {frames} кадров")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nПроверить:  python src/render_video.py --stills")
    print("Убрать:     python tools/make_test_clips.py --clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
