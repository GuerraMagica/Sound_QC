import json
import os
from pathlib import Path
import time

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from audio_qc.synthetic import write_wav, defect_signals
from audio_qc.programme import load_group_settings


def test_gui_group_settings_snapshot_is_independent(window, tmp_path):
    path = tmp_path / "groups.yaml"
    path.write_text("schema_version: 1\nnaming:\n  enabled: true\n  layout: stereo\n  suffixes:\n    L: ['-LEFT']\n    R: ['-RIGHT']\n")
    assert window.load_groups(path)
    args = window.scan_arguments(tmp_path / "out")
    saved = Path(args[args.index("--groups")+1])
    before = load_group_settings(saved)
    path.write_text("invalid changed yaml")
    window._group_settings["naming"]["layout"] = "5.1"
    assert load_group_settings(saved) == before
    assert before["naming"]["layout"] == "stereo"
    assert saved.stat().st_mode & 0o222 == 0
    path.write_text("schema_version: 1\nwrong: true")
    assert not window.load_groups(path)
    assert "Invalid programme groups" in window.status.text()


@pytest.mark.integration
def test_gui_real_group_scan_and_validation_display(window, tmp_path):
    source = tmp_path / "sources"
    for ch in ("L", "R"):
        write_wav(source / f"Mix_{ch}.wav", defect_signals()["zero_dropout"], bext=True, time_reference=172800000)
    write_wav(source / "Missing_L.wav", defect_signals()["zero_dropout"], bext=True)
    window.source.setText(str(source))
    window.reset_groups()
    deadline = time.monotonic()+10
    while not window._preview.is_idle and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert window._preview.is_idle
    assert "Mix (stereo" in window.group_preview.text()
    assert "L ← Mix_L.wav" in window.group_preview.text()
    window.defects.setChecked(True)
    window.snippets.setChecked(True)
    window.run_button.click()
    deadline = time.monotonic()+30
    while not window.run_button.isEnabled() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert window.process.state() == QProcess.NotRunning, window.log.toPlainText()
    assert window.open_button.isEnabled(), window.log.toPlainText()
    report = json.loads(window.report_path.with_suffix(".json").read_text())
    valid = next(g for g in report["programme_groups"] if g["name"] == "Mix")
    assert valid["validation_status"] == "VALID"
    assert {e["event_type"] for e in valid["issues"]} == {"POSSIBLE DROPOUT", "DIGITAL SIGNAL LOSS"}
    assert len(valid["issues"]) == 2
    assert valid["issues"][0]["channels"] == ["L", "R"]
    assert "Mix: VALID" in window.group_preview.text()
    assert "Missing: INCOMPLETE" in window.group_preview.text()
    assert "Missing logical channels: R" in window.group_preview.text()
