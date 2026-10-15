import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from audio_qc.timecode import RATES


def test_gui_reporting_controls_and_defaults(window):
    assert [window.frame_rate.itemText(i) for i in range(window.frame_rate.count())] == list(RATES)
    assert window.frame_rate.currentText() == "25"
    assert window.tc_source.currentText() == "AUTO"
    assert not window.manual_start.isEnabled()
    window.tc_source.setCurrentText("MANUAL")
    window.frame_rate.setCurrentText("29.97 DF")
    assert window.manual_start.isEnabled()
    assert window.manual_start.text() == "10:00:00;00"
    args = window.scan_arguments("/tmp/new-report")
    assert args[args.index("--frame-rate")+1] == "29.97 DF"
    assert args[args.index("--start-timecode")+1] == "10:00:00;00"


def test_gui_invalid_drop_frame_never_starts(window, wav):
    window.source.setText(str(wav))
    window.tc_source.setCurrentText("MANUAL")
    window.frame_rate.setCurrentText("29.97 DF")
    window.manual_start.setText("00:01:00;00")
    window.run_button.click()
    assert window.process.state() == QProcess.NotRunning
    assert "skips" in window.status.text()
    assert window.report_path is None


def test_gui_yaml_load_and_control_override(window, tmp_path):
    path = tmp_path/"custom.yaml"
    path.write_text('timecode:\n  frame_rate: "29.97 DF"\n  source: MANUAL\n  manual_start: "01:00:00;00"\n')
    window.load_yaml(path)
    assert window.frame_rate.currentText() == "29.97 DF"
    assert window.manual_start.text() == "01:00:00;00"
    window.tc_source.setCurrentText("FILE_RELATIVE")
    window.frame_rate.setCurrentText("24")
    args = window.scan_arguments(tmp_path/"output")
    assert args[args.index("--timecode-source")+1] == "FILE_RELATIVE"
    assert "--start-timecode" not in args


@pytest.mark.integration
def test_gui_runs_real_cli_with_selected_rate(window, wav):
    window.source.setText(str(wav))
    window.frame_rate.setCurrentText("29.97 DF")
    window.tc_source.setCurrentText("MANUAL")
    window.manual_start.setText("10:00:00;00")
    window.run_button.click()
    deadline = time.monotonic()+20
    while (not window.run_button.isEnabled()) and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert window.process.state() == QProcess.NotRunning, window.log.toPlainText()
    assert window.open_button.isEnabled(), window.log.toPlainText()
    assert window.report_path.is_file()
    report = json.loads(window.report_path.with_suffix(".json").read_text())
    assert report["timecode_reporting"]["frame_rate"]["label"] == "29.97 DF"
    assert report["files"][0]["timecode_reporting"]["file_start_timecode"] == "10:00:00;00"
    assert "HTML report:" in window.log.toPlainText()
