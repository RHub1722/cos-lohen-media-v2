"""Прогон насквозь на синтетике: от файла до report.md."""

import json

from motion import report, session
from tests import motion_clips


def test_session_measures_a_synthetic_clip(tmp_path):
    path = motion_clips.two_sweeps(tmp_path / "d.mp4", fps=30, dead=True)
    data = session.measure(path, pose_on=False)
    assert data["strikes"] == 2
    assert data["transitions"] == 1
    assert data["dead_stops"] == 1
    assert data["scale_source"] in {"поза", "разброс", "нет"}
    assert data["trim"]["reason"]
    assert data["pose"]["used"] is False
    assert data["pose"]["why"]


def test_report_writes_both_files_and_names_its_limits(tmp_path):
    path = motion_clips.two_sweeps(tmp_path / "d.mp4", fps=30, dead=True)
    data = session.measure(path, pose_on=False)
    out = report.write([data], tmp_path / "out")
    text = out.read_text(encoding="utf-8")
    assert (tmp_path / "out" / "measurements.json").exists()
    saved = json.loads((tmp_path / "out" / "measurements.json")
                       .read_text(encoding="utf-8"))
    assert saved[0]["strikes"] == 2
    # Три вещи, без которых числам верить нельзя.
    assert "нормировк" in text.lower()
    assert "обрезк" in text.lower()
    assert "поза" in text.lower()


def test_report_says_so_when_no_strikes_were_found(tmp_path):
    path = motion_clips.still(tmp_path / "s.mp4", fps=30, total=120)
    data = session.measure(path, pose_on=False)
    assert data["strikes"] == 0
    out = report.write([data], tmp_path / "out")
    text = out.read_text(encoding="utf-8")
    assert "ударов не найдено" in text.lower()
