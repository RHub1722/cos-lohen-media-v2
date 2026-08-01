"""Сборка стемов, суммы и нормализованного мастера через FFmpeg.

Порядок намеренно такой: каждый стем рендерится отдельным файлом, четыре стема
суммируются в предмастер, двухпроходный loudnorm даёт мастер. Так стемы и мастер
гарантированно согласованы, а не собраны разными путями.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from src.filtergraph import GraphInput, build_stem_graph, ffmpeg_input_args
from src.models import STEMS, Timeline

_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class RenderError(Exception):
    pass


def _run(cmd: list[str], what: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"{what} упал:\n{' '.join(cmd)}\n\n{result.stderr[-4000:]}")
    return result.stderr


def render_stem(tl: Timeline, stem: str, assets_root: Path, out_path: Path) -> list[str]:
    graph, inputs = build_stem_graph(tl, stem)
    resolved = [GraphInput(path=str(assets_root / i.path), loop=i.loop) for i in inputs]

    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    cmd += ffmpeg_input_args(resolved)
    cmd += [
        "-filter_complex", graph,
        "-map", "[out]",
        "-ar", str(tl.sample_rate), "-ac", "2", "-c:a", "pcm_s24le",
        str(out_path),
    ]
    _run(cmd, f"рендер стема {stem}")
    return cmd


def sum_stems(stem_paths: list[Path], tl: Timeline, out_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    for path in stem_paths:
        cmd += ["-i", str(path)]
    labels = "".join(f"[{i}:a]" for i in range(len(stem_paths)))
    graph = (
        f"{labels}amix=inputs={len(stem_paths)}:normalize=0:dropout_transition=0,"
        f"apad,atrim=0:{tl.total_duration:.6f},asetpts=PTS-STARTPTS[out]"
    )
    cmd += [
        "-filter_complex", graph, "-map", "[out]",
        "-ar", str(tl.sample_rate), "-ac", "2", "-c:a", "pcm_s24le",
        str(out_path),
    ]
    _run(cmd, "сумма стемов")


def _loudnorm_measure(path: Path, tl: Timeline) -> dict:
    stderr = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"loudnorm=I={tl.target_lufs}:TP={tl.target_tp}:LRA=11:print_format=json",
        "-f", "null", "-",
    ], "loudnorm, первый проход")
    match = _LOUDNORM_JSON.search(stderr)
    if not match:
        raise RenderError("loudnorm не вернул измерения на первом проходе")
    return json.loads(match.group(0))


def normalize(premaster: Path, tl: Timeline, out_path: Path) -> dict:
    m = _loudnorm_measure(premaster, tl)
    af = (
        f"loudnorm=I={tl.target_lufs}:TP={tl.target_tp}:LRA=11"
        f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}:linear=true:print_format=summary,"
        f"aresample={tl.sample_rate}:resampler=soxr:precision=28,"
        f"apad,atrim=0:{tl.total_duration:.6f},asetpts=PTS-STARTPTS"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", str(premaster), "-af", af,
        "-ar", str(tl.sample_rate), "-ac", "2", "-c:a", "pcm_s24le",
        str(out_path),
    ], "loudnorm, второй проход")
    return m


def to_mp3(wav_path: Path, mp3_path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", str(wav_path), "-c:a", "libmp3lame", "-b:a", "320k", str(mp3_path),
    ], "экспорт mp3")


def render_all(tl: Timeline, assets_root: Path, out_dir: Path, suffix: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    stem_paths: list[Path] = []
    commands: dict[str, list[str]] = {}
    for stem in STEMS:
        path = out_dir / f"{stem}_{suffix}.wav"
        commands[stem] = render_stem(tl, stem, assets_root, path)
        stem_paths.append(path)

    premaster = out_dir / f"premaster_{suffix}.wav"
    sum_stems(stem_paths, tl, premaster)

    master = out_dir / f"master_{suffix}.wav"
    measured = normalize(premaster, tl, master)
    to_mp3(master, out_dir / f"master_{suffix}.mp3")

    (out_dir / f"ffmpeg-commands-{suffix}.txt").write_text(
        "\n\n".join(f"# {stem}\n{' '.join(cmd)}" for stem, cmd in commands.items()),
        encoding="utf-8",
    )

    return {
        "master": master,
        "stems": stem_paths,
        "premaster_measured": measured,
        "commands": commands,
    }
